# INGESTION_STRATEGY.md

## Purpose of This Document

This document defines the ingestion patterns shared by **every** source adapter, regardless of whether the source is a REST API (openFDA) or a bulk file distribution (DailyMed). Source-specific detail belongs in [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md) and [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md); this document is what those two build on top of, and what every future source adapter must also build on top of.

The central engineering problem this document solves: **how do you reliably pull millions of records from a system you do not control, that will fail on you mid-run, without corrupting your data or losing your place?**

---

## 1. Core Principle: Streaming Over Loading

### The problem

openFDA's drug label dataset alone is millions of records. DailyMed's full SPL archive is tens of gigabytes of compressed XML. Loading either fully into memory before processing is not a performance optimization problem — it is a correctness problem: the process will be OOM-killed partway through a run, and you will not know which records were actually persisted before the crash.

### The rule

**Nothing in the ingestion path holds an entire dataset in memory at once.** Every stage — fetch, parse, validate, transform — operates on a stream of individual records or a bounded batch, never the whole dataset.

- HTTP responses from paginated APIs are consumed page by page, not accumulated into one giant list before processing starts.
- Bulk file downloads are streamed to disk in chunks, not buffered fully in memory before being written.
- JSON parsing of large files uses incremental/streaming parsing (e.g., ijson-style token streaming) rather than `json.load()`-ing an entire multi-gigabyte file.
- XML files are parsed with targeted, streaming access (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md)) rather than building a full DOM tree for documents that may be large.

This is what allows the same ingestion code to run correctly whether the source has ten thousand records or fifty million — the memory footprint is bounded by batch size, not dataset size.

---

## 2. Pagination Strategy

Most source APIs (openFDA included) paginate. The ingestion layer treats pagination as a first-class concern, not an afterthought:

- **Cursor/offset tracking is externalized.** The current pagination position is written to the checkpoint store (Section 5) after each page is successfully processed — not held only in a local loop variable that dies with the process.
- **Page size is tuned per source**, balancing request count (too small = excessive round trips) against response size and memory footprint (too large = defeats the point of pagination).
- **Pagination continues past transient failures.** A failed page fetch triggers the retry policy (Section 3) for that page specifically; it does not restart pagination from the beginning.
- **Total-count drift is tolerated.** Some APIs report an approximate or changing total record count as new data lands during a long-running ingestion. The ingestion loop terminates on "no more pages returned," not on "reached the originally reported total."

---

## 3. Retry and Backoff Strategy

Every network call in the ingestion path — not just the "main" fetch — is wrapped in a retry policy:

- **Exponential backoff with jitter** for transient failures (connection resets, timeouts, 5xx responses, rate-limit 429s). Jitter prevents a fleet of retrying workers from synchronizing into a thundering-herd retry against a source that is already struggling.
- **A bounded maximum retry count.** Infinite retry is indistinguishable from a hang; after the max is reached, the failure is surfaced to the error-handling and alerting path (see [`ERROR_HANDLING.md`](./ERROR_HANDLING.md)) rather than looping silently forever.
- **Retry is classified by failure type.** A 4xx (excluding 429) indicates a request problem (bad query, auth) and is *not* retried — retrying a malformed request just wastes time and can look like a stuck process. A 5xx or network-level failure *is* retried, since it indicates a transient server or connectivity issue.
- **Rate limits are respected proactively, not just reactively.** Where a source documents a rate limit (openFDA does), the fetcher paces requests under that limit rather than relying solely on 429 responses to slow down.

---

## 4. Idempotent Ingestion

### Why this matters

Ingestion runs will be re-executed — deliberately (re-running a failed job), accidentally (a scheduler double-fires), or as a matter of course (daily incremental syncs re-fetch overlapping data). If re-running an ingestion job can produce duplicate rows or corrupted state, the system is not production-safe.

### How idempotency is achieved

- **Every canonical record is keyed by a deterministic natural key derived from the source** (e.g., an openFDA `set_id` + version, or a DailyMed SPL document ID + effective date), never by an auto-incrementing "just insert it" ID at the ingestion boundary.
- **Writes are upserts, not blind inserts.** The persistence layer's `save()` step (see [`PIPELINE.md`](./PIPELINE.md)) checks for an existing record with the same natural key and source before deciding whether this is a new version, an unchanged duplicate, or truly new data.
- **Unchanged data is a no-op, not a new version.** If a re-fetched record is byte-for-byte (or field-for-field) identical to the current canonical version, no new row/version is written — this keeps the version history in [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) meaningful (a real change history) instead of noisy (a log of re-ingestion runs).
- **Running the full ingestion pipeline twice on the same input produces the same database state as running it once.** This is treated as a testable invariant (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)), not just a design aspiration.

---

## 5. Checkpointing and Resumable Ingestion

### The problem

A DailyMed full-archive ingestion or an openFDA full backfill can run for hours. A network blip, an out-of-memory kill, a deploy, or a source outage 80% of the way through should not mean starting over from record zero.

### The design

- Every ingestion run is assigned a **run ID** and persists its progress to an `ingestion_logs`-backed checkpoint store as it goes (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) for the table design).
- The checkpoint records, at minimum: the source, the run ID, the last successfully processed page/cursor/file, a count of records fetched/parsed/validated/saved so far, and a status (`running`, `completed`, `failed`, `partial`).
- **On restart, an adapter first checks for an incomplete run for its source** and, if found, resumes from the last checkpoint rather than starting from the beginning — re-processing only the batch that was in flight when the run was interrupted (which idempotency, Section 4, makes safe to redo).
- Checkpoints are written **after** a batch is durably persisted, not before — a checkpoint must never claim progress that didn't actually make it to the database. This ordering is what prevents "resume" from silently skipping unpersisted data.

---

## 6. Incremental Updates and Versioning

Full re-ingestion of a source on every run does not scale and is not necessary — most sources support fetching only what changed since the last successful run.

- **The ingestion layer tracks a per-source "last successful sync" watermark** (a timestamp or source-provided version marker) and, where the source API supports it, requests only records modified since that watermark.
- **Where a source does not support server-side filtering by date** (which affects some DailyMed distribution mechanisms — see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md)), the ingestion layer still avoids unnecessary write churn by relying on the idempotent upsert behavior in Section 4: the full dataset can be re-scanned, but only genuinely changed records result in a new version.
- **Nothing is ever overwritten in place.** Every accepted change creates a new version of the canonical record, preserving the prior version and the source/timestamp that produced it. This is a deliberate, non-negotiable design choice — see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) for the versioning schema and [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) for how provenance is attached to every version.

---

## 7. Validation on Ingest

Validation happens **as early as possible in the pipeline** — immediately after parsing, before transformation into the canonical model:

- Records are checked against an explicit schema (required fields present, correct types, sane value ranges) specific to that source's parsed shape.
- **Invalid records do not silently disappear and do not crash the run.** A malformed record is logged with enough detail to diagnose it (source, record identifier, the specific validation failure) and routed to a dead-letter path (see [`ERROR_HANDLING.md`](./ERROR_HANDLING.md)) while the rest of the batch continues processing.
- Validation failure rate is tracked as a per-run metric. A sudden spike (e.g., 40% of records failing validation when the historical baseline is under 1%) is a strong signal that the source has changed its schema upstream, and is alerted on rather than silently absorbed (see [`OBSERVABILITY.md`](./OBSERVABILITY.md)).

---

## 8. Failure Recovery

A failure in ingestion falls into one of three categories, each handled differently:

| Failure type | Example | Handling |
|---|---|---|
| **Transient, single-record** | One malformed record in an otherwise healthy batch | Log, dead-letter, continue the batch |
| **Transient, infrastructure** | Network blip, source 503, DB connection drop | Retry with backoff (Section 3); if exhausted, fail the run and checkpoint the last good state |
| **Systemic** | Source changed its schema/API contract entirely | Fail fast, alert loudly, do not attempt to "best-effort" ingest against a contract that no longer matches expectations |

The guiding principle: **prefer a loud, checkpointed failure over a quiet, partial success that looks like a complete success.** A run that silently ingested 60% of a dataset and reported "done" is a worse outcome than a run that clearly reports "failed at record 60,000 of 100,000, resumable from checkpoint X."

---

## 9. Ingestion Logs

Every run — successful, failed, or partial — writes a structured entry to the ingestion log (persisted in `ingestion_logs`, detailed in [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)) capturing:

- Source, run ID, start time, end time
- Records fetched, parsed, validated, transformed, saved, deduplicated, rejected
- Final status and, on failure, the checkpoint position for resumption
- A reference to any dead-lettered records produced during the run

This log is the primary tool for answering "what happened during last night's ingestion" without reading application logs line by line, and it is the data source for the pipeline health metrics described in [`OBSERVABILITY.md`](./OBSERVABILITY.md).

---

## 10. Deduplication at Ingestion Time vs. Entity Resolution

It is important to distinguish two different kinds of "duplicate" handled at different layers:

- **Ingestion-time deduplication** (this document): recognizing that a record fetched in this run is the same *source record* as one already ingested (same natural key), so it doesn't produce a redundant version. This is a mechanical, per-source concern.
- **Cross-source entity resolution** (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)): recognizing that "Vitamin C" from openFDA and "Ascorbic Acid" from DailyMed refer to the same real-world ingredient. This is a semantic, cross-source concern and happens downstream of ingestion, in the resolution layer.

Conflating these two is a common source of bugs — ingestion-time deduplication must never attempt semantic matching, and entity resolution must never be used as a substitute for proper idempotent upserts within a single source.
