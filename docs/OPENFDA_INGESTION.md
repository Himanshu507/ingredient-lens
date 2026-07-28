# OPENFDA_INGESTION.md

## Purpose of This Document

This document specifies exactly how RIE ingests data from openFDA. It assumes you have read [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) — this document does not repeat the general patterns (streaming, retry, idempotency, checkpointing) except where openFDA requires something specific. What follows is the source-specific application of that general strategy, plus the reasoning behind a decision that shapes everything downstream: **we do not use the `FDA/openfda` GitHub repository as part of this application.**

---

## 1. Decision: Official APIs and Bulk Datasets, Not the GitHub Repository

### What the FDA/openfda GitHub repository is

The `FDA/openfda` GitHub repository contains the actual ETL pipeline the FDA itself runs internally to harvest data from source systems (SPL, FAERS, recall enforcement systems, etc.) and produce the openFDA API and bulk downloads. It is a real, working data engineering pipeline — and it is genuinely useful to *read*.

### The decision

**We study the `FDA/openfda` repository to understand FDA's data model and ETL philosophy. We do not run it, fork it, or depend on it as part of RIE.** Instead, RIE consumes data exclusively through:

1. The **official openFDA REST APIs** (`api.fda.gov`) for incremental, query-driven access.
2. The **official openFDA bulk download datasets** (versioned JSON exports published by the FDA) for full/backfill ingestion.

### Why

| Consideration | Running `FDA/openfda` ourselves | Using official APIs/bulk data (chosen) |
|---|---|---|
| **Data freshness guarantee** | We would be responsible for keeping our fork's harvesting logic in sync with FDA's upstream source systems — systems we have no visibility into or contract with | The FDA operates and guarantees the freshness of its own public-facing API/bulk data; that's the actual contract we can rely on |
| **Maintenance burden** | We would inherit FDA's internal infrastructure dependencies (their job scheduler, their internal data stores, credentials we don't have) | Zero infrastructure dependency beyond an HTTP client and a file downloader |
| **Correctness surface** | Any bug in a stale fork silently produces wrong data with no upstream signal that something changed | The published API is the FDA's own validated output — errors there are the FDA's errors, not ours, and are visible to every other consumer too (so they get fixed) |
| **Legitimacy of output** | A modified/forked internal pipeline producing "FDA-like" data is not something we can credibly attribute back to the FDA | Data pulled directly from `api.fda.gov` is unambiguously and verifiably sourced from the FDA, which matters enormously for a *regulatory* intelligence product |
| **Engineering value of the repo** | — | Studied read-only, as a reference for how a mature org models SPL/FAERS/enforcement data and handles its own ETL — informs our canonical model and extractor design without coupling us to their infrastructure |

### Advantages of this decision

- No dependency on FDA-internal infrastructure we don't control and can't debug.
- Our ingestion contract is a public, documented, versioned API — changes are announced, not silent.
- Provenance is unambiguous: every record can be traced to a specific `api.fda.gov` endpoint and query, which matters for an intelligence platform whose entire value proposition is trustworthy sourcing.
- We can start ingesting today without needing to stand up or replicate FDA's internal pipeline infrastructure.

### Disadvantages, and how we mitigate them

- **We inherit whatever latency exists between FDA's internal systems updating and the public API/bulk data reflecting that update.** Mitigation: this is acceptable — RIE is a regulatory intelligence platform, not a real-time alerting system, and the openFDA API's publish cadence is well within what our use case needs.
- **We are constrained to whatever fields/structure the public API exposes** — we cannot patch or extend FDA's own extraction logic the way a fork of their repo theoretically could. Mitigation: the public API is comprehensive for our canonical model's needs (see [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md)); if a genuine gap emerges, we accept it as a documented known limitation rather than reaching into infrastructure we don't own.
- **We are subject to the public API's rate limits**, whereas an internal pipeline would not be. Mitigation: rate-limit-aware pacing (Section 3) and use of bulk downloads for large backfills instead of paginating the live API for millions of records.

---

## 2. Ingestion Modes

openFDA supports two ingestion modes, used for different purposes:

| Mode | Source | Used for |
|---|---|---|
| **REST API** (`api.fda.gov`) | Live, query-filterable, paginated JSON endpoint | Incremental syncs — "what changed since our last run" |
| **Bulk download** | Versioned, pre-exported JSON files (gzipped) covering an entire endpoint's dataset | Initial backfill and periodic full-reconciliation runs |

Using the API for a multi-million-record initial backfill would mean tens of thousands of paginated HTTP round trips against a rate-limited public service — slow, fragile, and unfriendly to a shared public resource. Bulk downloads exist specifically to avoid that. **The rule: full/backfill ingestion uses bulk downloads; incremental/delta ingestion uses the API.**

---

## 3. Pagination Strategy (API Mode)

- openFDA's REST API paginates via `skip`/`limit` query parameters, with a documented per-request maximum page size.
- The fetcher requests the maximum allowed page size to minimize round-trip count, then advances `skip` by that page size each iteration.
- The current `skip` offset for a given query/run is written to the checkpoint store after each page is successfully validated and persisted (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 5) — not just held in a loop variable.
- Pagination terminates when a page returns fewer records than the requested page size (the standard "last page" signal), not on a pre-fetched total count, since openFDA's reported total can shift slightly as new data is indexed during a long-running sync.
- Requests are paced to stay under openFDA's documented rate limit (requests per minute per API key). An API key is used specifically because it raises this limit relative to anonymous access — the fetcher paces to that documented ceiling proactively, and falls back to retry-with-backoff (Section 4) only for the unexpected case.

---

## 4. Streaming Strategy and Memory Safety

### Bulk downloads

openFDA bulk files are large, gzip-compressed JSON documents structured as `{ meta: {...}, results: [ ... millions of records ... ] }`. The naive approach — `json.load()` the whole decompressed file — is a memory-safety bug at this scale, not a style choice.

Instead:

1. The gzip stream is decompressed **incrementally**, chunk by chunk, never fully materialized on disk or in memory before processing starts.
2. The JSON is parsed with a **streaming/incremental JSON parser** that yields individual records from the `results` array as they're encountered in the byte stream, rather than building the full in-memory object graph first. This means peak memory usage is bounded by "one record plus buffer," not "entire multi-gigabyte file."
3. Each yielded record is pushed through validate → transform → save (Section 6) as an individual unit of work, batched only for the sake of efficient database writes (e.g., batched upserts of a few hundred records at a time) — batching for I/O efficiency is not the same as loading the whole dataset into memory, and the batch size is a small, bounded constant.

### API mode

Each page response (bounded by the page-size limit in Section 3) is naturally small and is processed and discarded before the next page is fetched — there is no accumulation across pages.

### Why this matters concretely

A dataset with 5 million drug label records at even 2KB/record averages ~10GB if fully materialized in memory. Streaming keeps the ingestion process's memory footprint roughly constant regardless of whether the dataset is 5,000 or 5,000,000 records — which is what makes "ingest millions of records" an operational non-event rather than a capacity-planning crisis.

---

## 5. Retry Strategy

Follows the general policy in [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 3, applied specifically to openFDA's behavior:

- **429 (rate limited)**: retried with exponential backoff; the backoff additionally respects a `Retry-After` header if openFDA provides one.
- **5xx**: retried with exponential backoff + jitter, bounded retry count.
- **4xx other than 429** (e.g., malformed query): not retried — this indicates a bug in our query construction, and is surfaced as an error immediately rather than retried into a longer, equally-doomed loop.
- **Bulk download interruption** (connection drop mid-download): the downloader supports resuming a partial download via HTTP range requests where the CDN serving the bulk file supports it; otherwise the partial file is discarded and the download restarted, gated by checkpoint state so the rest of the pipeline knows the file isn't yet valid to process.

---

## 6. Validation, Transformation, and Idempotent Save

- Each parsed openFDA record is validated against a schema specific to that endpoint (drug label, enforcement/recall, adverse event) before transformation — required fields, expected types, non-null identifiers.
- Validated records are transformed into canonical model objects (`Product`, `Ingredient`, `Recall`, `Warning` — see [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md)), tagged with `Source = openFDA`, the specific endpoint, and a reference to the raw record for provenance.
- The natural key used for idempotent upsert is the openFDA-provided unique identifier for that record type (e.g., `set_id` + version for drug labels, `recall_number` for enforcement records) — never a freshly generated ID at ingestion time. Re-running ingestion against the same data is guaranteed to produce zero duplicate rows (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 4).

---

## 7. Incremental Updates and Versioning

- Each openFDA endpoint has a stored **watermark**: the timestamp or version marker of the most recent successfully ingested record for that endpoint.
- Incremental (API-mode) runs query only for records modified since that watermark, where the endpoint supports a date-filterable field (most openFDA endpoints expose an effective/report date usable for this).
- A **periodic full-reconciliation run** (via bulk download, on a slower cadence — e.g., weekly) re-scans the entire dataset regardless of watermark, to catch any records that were retroactively corrected or backfilled by the FDA outside the incremental window. This is a deliberate trade-off: incremental syncs are cheap and frequent; full reconciliation is expensive but catches the class of update that a "since last watermark" query structurally cannot.
- Every accepted change produces a new version of the canonical record (never an in-place overwrite) — see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) for the versioning schema.

---

## 8. Deduplication

Two distinct deduplication concerns apply here, per the distinction drawn in [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 10:

- **Within openFDA**, the same underlying record can appear in both a bulk download and a subsequent incremental API sync. The natural-key-based idempotent upsert (Section 6) handles this mechanically — it's the same record, same key, no-op if unchanged.
- **Across sources** (e.g., the same ingredient described by both openFDA and DailyMed) is not handled here at all — that is the job of the entity resolution layer described in [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md), which operates on canonical records after both adapters have independently transformed and saved their data.

---

## 9. Checkpointing and Resumable Ingestion

Applies the general mechanism from [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 5, with openFDA-specific checkpoint content:

- **API mode**: checkpoint = `{ endpoint, query watermark, current skip offset, records processed so far }`.
- **Bulk mode**: checkpoint = `{ endpoint, bulk file version/URL, byte offset or record offset within the stream, records processed so far }`.

On restart, the adapter checks for an incomplete run for the given endpoint and mode, and resumes from the recorded offset rather than re-fetching from zero — critical for bulk downloads, where restarting a multi-hour ingestion of a multi-gigabyte file from scratch after a late-stage failure would be a significant, avoidable cost.

---

## 10. Ingestion Log Example

A completed openFDA drug-label incremental run produces an `ingestion_logs` entry structured per [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 9, e.g.:

```
source: openfda
endpoint: drug/label
mode: incremental
run_id: <uuid>
started_at / completed_at
records_fetched: 4,213
records_validated: 4,201
records_rejected: 12  (dead-lettered, with reasons)
records_created: 340
records_updated: 812
records_unchanged: 3,049
status: completed
watermark_advanced_to: 2026-07-27T00:00:00Z
```

This is the artifact an on-call engineer reads first when asked "did last night's openFDA sync work," without needing to grep raw logs.
