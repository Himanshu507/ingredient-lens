# PIPELINE.md

## Purpose of This Document

[`ARCHITECTURE.md`](./ARCHITECTURE.md) shows the pipeline as a map; this document is the operational specification — how the stages actually execute, what the data contract is between each pair of stages, how concurrency and batching work, and how a run is scheduled, triggered, and orchestrated end to end. If you are implementing or debugging the pipeline itself (not a specific source adapter, not the database schema), this is the document you need.

---

## 1. The Twelve Stages

Every ingestion run passes data through these stages, in this order. Every stage is independently unit-testable in isolation (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)), and every stage boundary is a typed data contract, not an implicit convention.

```
Fetcher → Downloader → Queue → Parser → Validator → Transformer
   → Normalizer → Entity Resolver → Deduplicator → Database → Search → AI
```

| Stage | Input | Output | Detailed in |
|---|---|---|---|
| Fetcher | Source query/endpoint config | Raw bytes/JSON responses | [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md), [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md) |
| Downloader | Bulk file reference | Streamed local bytes (never fully materialized) | [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) |
| Queue | Units of work from Fetcher/Downloader | Buffered, backpressure-controlled work items | Section 3, below |
| Parser | Raw bytes | Source-shaped intermediate objects | [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) (extractors), [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md) |
| Validator | Source-shaped objects | Valid objects (invalid → dead letter) | [`ERROR_HANDLING.md`](./ERROR_HANDLING.md) |
| Transformer | Valid source-shaped objects | Canonical model candidates | [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) |
| Normalizer | Canonical candidates (raw strings) | Canonical candidates (normalized strings) | [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) §3 |
| Entity Resolver | Normalized candidates | Candidates linked to canonical entity IDs (existing or new) | [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) |
| Deduplicator | Resolved candidates | Merged canonical writes (no redundant versions) | [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) §9, [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) §4 |
| Database | Canonical writes | Durable, versioned rows | [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) |
| Search | Canonical rows | Indexed, queryable text/structured search | [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) §9 |
| AI | User query + search/retrieval | Cited answer | [`AI_PIPELINE.md`](./AI_PIPELINE.md) |

The first ten stages are the **ingestion pipeline**, run on a schedule or triggered manually. Search and AI are **query-time** — they read from what ingestion has already durably written; they are never in the write path of ingestion. This is a hard boundary: the AI layer cannot cause a database write, and a slow or failing AI query cannot back up or block ingestion.

---

## 2. Data Contracts Between Stages

Each stage boundary is a defined type, not an ad hoc dict passed along:

- **Fetcher/Downloader → Queue**: a `RawPayload` (source, endpoint/file reference, byte content or stream handle, fetch timestamp).
- **Queue → Parser**: the same `RawPayload`, dequeued.
- **Parser → Validator**: a source-specific intermediate type (e.g., `OpenFDADrugLabelRecord`, `DailyMedSPLDocument`) — this is the last point in the pipeline where source-specific shape is allowed to exist.
- **Validator → Transformer**: the same intermediate type, but now guaranteed to satisfy that source's schema — invalid records do not reach the Transformer at all (see [`ERROR_HANDLING.md`](./ERROR_HANDLING.md) for where they go instead).
- **Transformer → Normalizer**: a canonical model candidate object (e.g., `IngredientCandidate`), per [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) — source-specific shape ends here, permanently.
- **Normalizer → Entity Resolver → Deduplicator → Database**: the same canonical candidate type, progressively enriched with a resolved entity ID, then finalized into a database write instruction (create new version / no-op / merge).

Because every boundary is typed, a stage can be tested by constructing its input type directly and asserting on its output type — no stage's test needs to run the stages before it (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)).

---

## 3. Why a Queue Exists Between Fetch and Parse

Fetching (network-bound, rate-limited) and parsing (CPU-bound) have fundamentally different performance characteristics. Without a queue between them, the pipeline is forced into lockstep: fetch one page, then parse it, then fetch the next — wasting the network-idle time during parsing and the CPU-idle time during fetching.

The queue decouples these:

- The Fetcher/Downloader produces `RawPayload` items as fast as the source and rate limits allow, pushing them onto the queue.
- The Parser (and downstream stages) consume from the queue independently, at whatever rate parsing/validation/transformation/database writes can sustain.
- **Backpressure is bounded**: the queue has a maximum size. If downstream stages fall behind, the Fetcher blocks on pushing new work rather than fetching unboundedly ahead — this is what keeps the "streaming, not loading" guarantee from [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) true even under stage-speed mismatches. A fast Fetcher and a slow Database stage does not result in the entire dataset queuing up in memory; it results in the Fetcher naturally throttling to match.

In phase 1, this queue is an in-process, bounded, in-memory construct (not a separate broker like Kafka/RabbitMQ) — a single ingestion run is a single process, and the queue's job is intra-process flow control, not distributed messaging. See [`ROADMAP.md`](./ROADMAP.md) for when a real message broker becomes justified (multi-worker, distributed ingestion at a scale phase 1 does not target).

---

## 4. Concurrency Model

- **Across sources**: openFDA and DailyMed ingestion runs are fully independent processes/jobs and run concurrently without coordination — they write to disjoint parts of the canonical model at the transform stage and only converge at the entity-resolution stage, which is safe under concurrent writes because resolution decisions are made per-candidate against the current database state at write time (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) for the transactional guarantees this relies on).
- **Within a source**: parsing, validation, and transformation are parallelized across a bounded worker pool (CPU-bound stages benefit from this); fetching is paced by the source's rate limit (Section 3, [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md)) regardless of how much parsing capacity is available.
- **Database writes are the natural serialization point** for a given canonical entity — two concurrent workers both proposing an update to the same `Ingredient` resolve through the database's transactional isolation (an upsert keyed on the entity's natural/canonical key), not through application-level locking. See [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) Section 5.

---

## 5. Orchestration: How a Run Starts

Phase 1 orchestration is deliberately simple:

- **Scheduled runs**: a cron-triggered job (via the container's scheduler, or CI-scheduled workflow — see [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 7) invokes each source adapter's incremental ingestion entry point on a defined cadence (e.g., daily).
- **Manual runs**: an operator can trigger a full backfill or a re-run of a specific source/endpoint via a CLI entry point, which is the same code path the scheduler uses — there is exactly one way to start an ingestion run, invoked either by a human or a timer, never two divergent implementations.
- **Each run is independent and self-contained**: it acquires (or resumes) its own checkpoint (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 5), runs to completion or failure, and writes its outcome to `ingestion_logs` (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)).
- **A source's incremental and full-reconciliation runs do not overlap.** A simple run-level lock (checked against `ingestion_logs` for an in-progress run on the same source) prevents two runs from concurrently ingesting the same source and racing on checkpoint state.

A dedicated job queue/scheduler (Celery, Temporal) is deferred — see [`ROADMAP.md`](./ROADMAP.md) — until ingestion needs true distributed scheduling (multiple workers, dynamic retry orchestration across machines) that a cron trigger plus the in-process pipeline described above cannot satisfy.

---

## 6. Batching Within Stages

"Streaming, not loading" (per [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md)) does not mean "one record at a time end to end" — that would make database writes pathologically inefficient (one round trip per record). Instead:

- Records flow through Fetch → Parse → Validate → Transform individually (or in small pipeline-internal chunks matching the source's natural page/package size).
- Immediately before the Database stage, records are grouped into **fixed-size write batches** (a small, bounded constant — enough to amortize round-trip cost, small enough to keep a single batch's memory footprint negligible and keep a failed batch's blast radius small).
- A batch is written inside a single database transaction: either the whole batch's canonical writes (new versions, no-ops, dedup merges) commit together, or none do — this is what keeps a mid-batch failure from leaving some records at version N+1 and others at version N in a way that's inconsistent with what the checkpoint (Section 5) claims was processed.

---

## 7. End-to-End Failure Propagation

A failure at any stage is handled at the narrowest scope that correctly contains it, per the categorization in [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 8 and detailed in [`ERROR_HANDLING.md`](./ERROR_HANDLING.md):

- A single bad record fails at Validator → dead-lettered, batch continues.
- A batch-level database failure (e.g., constraint violation the Validator should have caught but didn't) fails that batch → logged, the run continues with the next batch, and the failure is surfaced loudly (this indicates a Validator gap, not just bad source data — see [`ERROR_HANDLING.md`](./ERROR_HANDLING.md) on the distinction).
- A Fetcher/Downloader failure that exhausts retries fails the **run** → checkpoint preserved, run marked `failed`, alerting fires (see [`OBSERVABILITY.md`](./OBSERVABILITY.md)).

No stage swallows an exception silently. Every failure, at every scope, produces a log entry with enough context to diagnose it without reproducing the run.

---

## 8. Why This Stage Count and Not Fewer

It's reasonable to ask whether Normalizer, Entity Resolver, and Deduplicator could be one "resolve" stage, or whether Validator and Transformer could be merged. They are kept separate because each has a genuinely distinct responsibility and a distinct failure mode:

- Merging Validator into Transformer risks a malformed record silently producing a garbage canonical object instead of being cleanly rejected before transformation is attempted.
- Merging Normalizer into Entity Resolver conflates a pure, deterministic, no-database-access operation (normalization) with a stateful, database-querying operation (resolution) — collapsing them would make normalization untestable in isolation and make resolution harder to reason about (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) Section 3's emphasis on this separation).
- Merging Entity Resolver into Deduplicator conflates "decide what this candidate matches" with "decide how to merge/write it" — two different concerns with two different testing strategies (resolution logic is tested against matching scenarios; deduplication logic is tested against write/version semantics).

Twelve stages is not a target to hit — it is what falls out of insisting that each stage have one responsibility and one clear failure mode, per the engineering principles in [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md).
