# ERROR_HANDLING.md

## Purpose of This Document

[`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) and [`PIPELINE.md`](./PIPELINE.md) both reference error handling as a cross-cutting concern; this document is its canonical specification. It covers retry and backoff mechanics, the dead letter queue, checkpointing's role in recovery, and the monitoring/alerting that turns a failure from a silent problem into a visible, actionable one.

The governing principle, stated once here and assumed everywhere else: **a loud, checkpointed failure is always preferable to a quiet, partial success that looks complete.**

---

## 1. Failure Taxonomy

Every failure in the system is classified into exactly one of these categories, because each demands a different response:

| Category | Example | Scope of impact | Response |
|---|---|---|---|
| **Record-level** | One malformed SPL document, one record failing schema validation | Single record | Log, dead-letter, continue |
| **Batch-level** | A database constraint violation across a write batch | One batch (bounded, small — see [`PIPELINE.md`](./PIPELINE.md) §6) | Log, dead-letter the batch, continue with next batch, alert if pattern repeats |
| **Transient infrastructure** | Network timeout, source 503, DB connection drop | The current operation | Retry with backoff (Section 2); escalate to run-level failure if retries exhausted |
| **Systemic** | Source changed its API contract or schema entirely | The entire run, and potentially all future runs until fixed | Fail fast, alert loudly, halt further automated retries for that source |

Misclassifying a systemic failure as transient (and retrying indefinitely against a source that has fundamentally changed) is treated as a bug — retry policies are bounded specifically to force this class of failure to surface rather than loop invisibly.

---

## 2. Retry and Backoff

- **Exponential backoff with jitter** is the default retry policy for any transient infrastructure failure: each retry waits roughly double the previous wait, with randomized jitter added to avoid synchronized retry storms across concurrent workers hitting the same source.
- **Bounded retry count.** Every retry policy has a maximum attempt count. Exhausting it converts a transient failure into a run-level failure (Section 1) rather than retrying forever.
- **Retry is failure-type-aware**, not blanket. 5xx and network errors retry; 4xx errors (other than 429) do not, since they indicate a request problem that repeating won't fix (see [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md) Section 5 for the concrete openFDA policy this generalizes).
- **Rate-limit responses (429) honor any provided `Retry-After` signal** before falling back to the standard backoff schedule — respecting the source's own guidance is preferred over guessing.

---

## 3. Dead Letter Queue (DLQ)

### Purpose

Record-level and batch-level failures must not silently vanish and must not halt the run. The DLQ is where they go instead.

### Design

- A rejected record (validation failure, transform failure, or a batch-level write failure) is written to a durable dead-letter store — a table (`ingestion_dead_letters`, alongside `ingestion_logs` in [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)) capturing: the source, run ID, the raw or partially-processed record, the stage at which it failed, the specific error, and a timestamp.
- **The DLQ is not a graveyard.** Dead-lettered records are reviewable, and — critically — re-processable once the underlying cause is fixed (a schema bug patched, a validator relaxed correctly, a transient source issue resolved). Re-processing a dead-lettered record goes through the exact same pipeline stages as live ingestion, not a special-cased recovery path, so it benefits from the same idempotency guarantees (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 4).
- **DLQ volume is a first-class metric** (see [`OBSERVABILITY.md`](./OBSERVABILITY.md)). A sudden spike is the earliest and clearest signal that something upstream changed — a source schema shift, a bug introduced in a recent deploy — and is alerted on, not just logged.

---

## 4. Checkpointing as a Recovery Mechanism

Checkpointing is specified in full in [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 5 and [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Section 8; this section covers its role specifically in failure recovery:

- On any run-level failure (retries exhausted, systemic failure detected), the run's last-written checkpoint remains intact — the failure path never clears or corrupts checkpoint state.
- The run is marked `failed` (or `partial`) in `ingestion_logs`, with the checkpoint position recorded as part of that log entry, so recovery doesn't depend on a separate lookup.
- **Recovery is always "resume from checkpoint," never "start over," unless a systemic failure specifically invalidates the checkpoint's assumptions** (e.g., a schema change means the checkpoint's pagination cursor or file-offset semantics may no longer be valid) — this exception is handled explicitly and manually, not silently assumed safe by default.

---

## 5. Logging

Every stage of the pipeline logs in a structured (not free-text) format, so logs are queryable and aggregable, not just human-readable line noise:

- **Every log entry includes**: source, run ID, stage, timestamp, and a severity level.
- **Record-level failures log the record's natural key** (or enough identifying context to find it in the DLQ) — never just "a record failed," always "record X failed, here's why."
- **Success is logged too, at a coarser granularity** — batch and stage completion, not every individual record — so that the absence of expected log volume is itself a detectable signal (see [`OBSERVABILITY.md`](./OBSERVABILITY.md)) rather than requiring someone to notice logs simply stopped.

---

## 6. Monitoring, Metrics, and Alerting

This section defines the error-handling-specific metrics; the full observability specification (tracing, performance, dashboards) lives in [`OBSERVABILITY.md`](./OBSERVABILITY.md).

### Metrics tracked per run and aggregated over time

- Retry count and retry-exhaustion count, by source and failure type
- DLQ write count, by source and failure stage
- Run outcome (`completed` / `failed` / `partial`) counts, by source
- Validation failure rate (Section 1 of [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md)) — tracked against a historical baseline specifically to catch upstream schema drift

### Alert conditions

| Condition | Signal |
|---|---|
| Any run reaches `failed` status | Systemic or exhausted-retry failure — needs prompt attention |
| Validation failure rate exceeds historical baseline by a wide margin | Likely upstream schema change |
| DLQ write volume spikes relative to baseline | Same as above, or a regression in a recent deploy |
| A source has no successful run within its expected cadence window | Silent failure of the scheduler/trigger itself, not just the ingestion logic |
| Entity resolution manual review queue (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)) grows past a threshold | Review throughput or matching thresholds need attention — not a pipeline failure, but an operational health signal handled through the same alerting path |

Alerting is intentionally conservative about noise: thresholds are set against observed baselines, not arbitrary round numbers, because an alert that fires constantly is an alert that gets ignored — and an ignored alert is equivalent to no alert at all.

---

## 7. What Error Handling Explicitly Does Not Do

- **Does not retry systemic failures automatically forever** — see Section 1; this would convert a visible problem into an invisible, resource-consuming one.
- **Does not silently drop data to "keep the pipeline green."** A dashboard showing 100% success with a shrinking dataset is a worse outcome than a dashboard showing a clearly flagged partial failure.
- **Does not attempt automatic schema-drift correction.** When a source's shape changes in a way the validator wasn't built for, the correct response is a loud failure and a human fix to the parser/validator/extractor — not a "best guess" auto-adaptation that risks quietly ingesting misinterpreted data.
