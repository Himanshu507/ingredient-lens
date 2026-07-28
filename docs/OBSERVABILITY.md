# OBSERVABILITY.md

## Purpose of This Document

Observability is what turns "the pipeline ran" into "we know exactly what the pipeline did, how fast, and whether it's healthy" — without reading source code or guessing. This document specifies logging, metrics, tracing, and the pipeline statistics that make RIE debuggable and operable in production, complementing the failure-specific monitoring/alerting already defined in [`ERROR_HANDLING.md`](./ERROR_HANDLING.md).

---

## 1. Observability Philosophy

- **If it isn't measured, assume it's broken.** A pipeline stage with no metrics is a pipeline stage nobody can prove is working correctly at scale, regardless of how confident the author is in the code.
- **Logs, metrics, and traces answer different questions** and are not substitutes for each other: logs answer "what exactly happened to this specific record/run," metrics answer "how is the system behaving in aggregate, over time," traces answer "where did the time go within a single run." All three are treated as required, not optional extras bolted on after the pipeline "works."
- **Observability data is itself a first-class output of the system**, versioned and structured with the same care as the canonical model — an `ingestion_logs` row is data, not an incidental side effect.

---

## 2. Logging

### Structure

All logs are structured (key-value / JSON), never bare interpolated strings — this is what makes logs queryable and aggregable rather than something a human has to grep and mentally parse.

### Required fields on every log entry

- `source` (openFDA, DailyMed, etc.)
- `run_id`
- `stage` (fetch, parse, validate, transform, normalize, resolve, dedupe, save — matching [`PIPELINE.md`](./PIPELINE.md) Section 1)
- `timestamp`
- `severity`
- A stage-appropriate identifier (record natural key, batch ID, or file/package identifier) wherever the log entry concerns a specific unit of work

### What gets logged, at what level

| Level | Examples |
|---|---|
| `DEBUG` | Per-record processing detail (enabled only in local/diagnostic runs, not production by default — volume would otherwise be unmanageable at millions of records) |
| `INFO` | Stage start/completion, batch completion, run start/completion, checkpoint writes |
| `WARN` | Record-level validation failures (dead-lettered but non-fatal), retry attempts |
| `ERROR` | Batch-level failures, retry exhaustion, run-level failures |
| `CRITICAL` | Systemic failures (source contract changed), anything triggering immediate alerting |

Logs are centrally aggregated (not left as scattered container stdout) so that "show me every log line for run X across all stages" is a single query, not a multi-container archaeology exercise.

---

## 3. Metrics

### Pipeline throughput and health metrics

Per source, per run, and aggregated over time (backing the dashboards described in Section 5):

- Records fetched / parsed / validated / transformed / saved, per unit time
- Validation failure rate and DLQ write rate (see [`ERROR_HANDLING.md`](./ERROR_HANDLING.md) Section 6)
- Run duration, and duration per stage — this is what turns "ingestion feels slow" into "the Transformer stage's p95 duration doubled since last week"
- Entity resolution outcomes: auto-merge count, manual-review-queued count, new-entity-created count, and their ratios (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)) — a shifting ratio here is often the earliest signal of a source's naming conventions changing
- Checkpoint lag: how far behind "real time" a source's watermark is, surfacing a source that's silently falling behind its expected cadence before it becomes a hard failure

### System-level metrics

- Database connection pool utilization, query latency percentiles
- Queue depth (see [`PIPELINE.md`](./PIPELINE.md) Section 3) — a sustained high queue depth indicates a downstream stage is the bottleneck, not the source itself
- API endpoint latency and error rate (standard request-level metrics)
- AI layer: retrieval latency, LLM call latency, citation-verification failure rate (see [`AI_PIPELINE.md`](./AI_PIPELINE.md) Section 7) — the last one specifically because a rising rate of rejected/regenerated answers is a direct signal of retrieval or prompt quality degrading

---

## 4. Tracing

- Each ingestion run carries a single `run_id` that is propagated through every stage, every log line, and every metric emission — this is the minimum viable tracing and is required from day one (it costs nothing extra to thread one ID through the pipeline that's already being built stage-by-stage per [`PIPELINE.md`](./PIPELINE.md)).
- For deeper cross-stage timing analysis, spans are recorded per stage per batch (start/end timestamps tagged with `run_id` and `stage`), enabling reconstruction of exactly how a given batch's time was spent across fetch/parse/validate/transform/save without needing a full distributed-tracing system for a single-process pipeline.
- Full distributed tracing (OpenTelemetry-style span propagation across services) is deferred until the system is genuinely distributed across multiple services/workers (see [`ROADMAP.md`](./ROADMAP.md)) — introducing it earlier would add operational overhead the current single-process pipeline doesn't need to pay for.

---

## 5. Pipeline Statistics and Dashboards

The `ingestion_logs` table (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)) is the durable source of truth for run-level statistics, and is the backing data for:

- **A per-source health view**: last successful run, current watermark, trailing 7/30-day success rate, trailing DLQ rate.
- **A trend view**: are validation failure rates, DLQ rates, and manual-review-queue growth trending up or holding steady over time — the kind of slow drift that a single run's logs would never surface but a trend view catches immediately.
- **An entity resolution health view**: manual review queue size and age (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) Section 7), auto-merge/manual-review/new-entity ratios over time.

These views are built directly from `ingestion_logs`, `ingestion_dead_letters`, and `entity_resolution_reviews` — no shadow analytics store duplicating this data is introduced in phase 1; the operational database already holds the ground truth these views need.

---

## 6. Performance Observability

- **Memory footprint** of streaming stages (Fetcher, Downloader, Parser — see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 1 and [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Section 4) is tracked, not assumed — a regression that reintroduces full-document buffering should show up as a memory metric spike, catching a correctness regression (not just a performance one) via an observability signal.
- **Database write latency and batch size tuning** (see [`PIPELINE.md`](./PIPELINE.md) Section 6) is monitored to validate that the chosen batch size is actually amortizing round-trip cost effectively, rather than being a value picked once and never revisited.

---

## 7. What Observability Is Not a Substitute For

Dashboards and metrics tell you something is wrong faster than a user complaint would — they do not replace the error-handling design in [`ERROR_HANDLING.md`](./ERROR_HANDLING.md) that determines *what happens* when something goes wrong, and they do not replace the testing strategy in [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md) that prevents the wrong thing from happening in the first place. Observability's job is narrowly "make the system's real behavior visible" — not "compensate for a system that wasn't built to fail safely."
