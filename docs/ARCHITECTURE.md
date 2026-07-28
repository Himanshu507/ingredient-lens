# ARCHITECTURE.md

## Purpose of This Document

This is the map. It describes the system's major components, how data moves between them, why the system is layered the way it is, the repository structure, and the technology choices. Every other document in `/docs` zooms into one region of this map — when you need implementation-level detail, this document will point you to the right one.

---

## 1. System Overview

RIE is a pipeline system with one strict rule: **data flows in one direction, through named stages, and no stage is allowed to skip ahead or reach backward.** A parser never writes to the database. An API handler never parses XML. The AI layer never touches a raw government payload. This is not bureaucracy — it is what makes each stage independently testable, independently replaceable, and independently debuggable when something goes wrong at 2am.

```
┌─────────────────┐     ┌──────────────────┐
│     openFDA     │     │    DailyMed      │
│  (REST + bulk)  │     │  (ZIP → SPL XML) │
└────────┬────────┘     └────────┬─────────┘
         │                       │
         ▼                       ▼
┌──────────────────┐      ┌──────────────────┐
│  openFDA Adapter │      │ DailyMed Adapter │
│ (source-specific)│      │ (source-specific)│
└────────┬─────────┘      └────────┬─────────┘
         │                         │
         └───────────┬─────────────┘
                     ▼
            ┌────────────────────┐
            │   Validation Layer │   ← rejects malformed records early
            └──────────┬─────────┘
                       ▼
            ┌────────────────────┐
            │  Transformer / Map │   ← source schema → canonical schema
            └──────────┬─────────┘
                       ▼
            ┌──────────────────────┐
            │ Ingredient Normalizer│  ← string normalization, synonym lookup
            └──────────┬───────────┘
                       ▼
            ┌────────────────────┐
            │   Entity Resolver  │   ← cross-source deduplication, merge
            └──────────┬─────────┘
                       ▼
            ┌────────────────────┐
            │     PostgreSQL     │   ← canonical, versioned, source-attributed
            └──────────┬─────────┘
                       ▼
            ┌────────────────────┐
            │     Search API     │   ← Postgres FTS today, OpenSearch later
            └──────────┬─────────┘
                       ▼
            ┌─────────────────────┐
            │   AI Reasoning Layer│   ← retrieval-grounded, never raw-source
            └─────────────────────┘
```

Every box in this diagram is a real, separately-testable module. None of them import each other's internals — they communicate through the canonical model (see [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md)) and well-defined function signatures (see [`PIPELINE.md`](./PIPELINE.md)).

---

## 2. Architectural Decision: Adapter Pattern per Source

### The problem

openFDA and DailyMed have nothing in common. openFDA is a paginated JSON REST API with a documented rate limit. DailyMed is a bulk ZIP file containing nested ZIPs containing HL7 SPL XML documents. A future source (EFSA, Health Canada) will look different again. If ingestion logic is written ad hoc per source, every new source risks reinventing retry logic, logging conventions, and checkpointing — and every bug fix has to be manually ported across N copy-pasted pipelines.

### Alternatives considered

| Approach | Description | Verdict |
|---|---|---|
| One monolithic ingestion script per source, no shared interface | Fastest to write initially | Rejected — logic duplication, inconsistent error handling, unmaintainable past 2 sources |
| Plugin/adapter architecture with a shared interface contract | Every source implements `fetch()`, `parse()`, `validate()`, `transform()`, `save()` | **Selected** |
| Generic schema-mapping config (declarative YAML mapping, no code per source) | Maximizes reuse | Rejected for phase 1 — DailyMed's nested-ZIP-to-XML-to-XPath extraction is not expressible declaratively without building a mini DSL; premature abstraction for 2 sources |

### The chosen design

Every source adapter implements the same contract:

```
fetch()      → retrieves raw payloads from the source (network or filesystem)
parse()      → turns raw payloads into source-shaped intermediate objects
validate()   → rejects malformed/incomplete records before they pollute the model
transform()  → maps source-shaped objects into canonical model objects
save()       → persists canonical objects (idempotently) via the shared data layer
```

`fetch` and `parse` are the only stages that know the source's native format. From `validate` onward, every adapter is working with the same canonical types, so the validation, transformation, normalization, entity resolution, and persistence code is **written once and shared across all sources.** Adding source #3 means writing a new `fetch`/`parse` pair against the existing contract — it does not touch the database layer, the normalizer, or the entity resolver.

This is the single most important architectural decision in the system: **it is what keeps the canonical model from becoming source-specific over time.** See [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) for why raw source schemas must never leak past the `transform()` boundary.

---

## 3. Component Responsibilities

| Component | Responsibility | Must NOT do |
|---|---|---|
| **Fetcher** | Retrieve raw bytes/JSON from a source (HTTP, file download) | Parse, validate, or interpret content |
| **Downloader** | Stream large files (ZIPs) to disk/temp storage without loading fully into memory | Hold entire archive in memory |
| **Queue** | Buffer units of work (records, files) between stages for backpressure and parallelism | Contain business logic |
| **Parser** | Convert raw bytes into structured, source-shaped objects | Know about the canonical model |
| **Validator** | Reject/flag malformed or incomplete records against a schema | Silently drop data without logging |
| **Transformer** | Map source-shaped objects → canonical model objects | Perform entity resolution or deduplication |
| **Normalizer** | Standardize strings, units, casing, whitespace, punctuation | Decide whether two ingredients are "the same" |
| **Entity Resolver** | Decide whether a new record refers to an existing canonical entity | Mutate the canonical schema itself |
| **Deduplicator** | Merge multiple source records into one canonical record with provenance preserved | Discard source provenance |
| **Database** | Durable, versioned, queryable storage | Contain transformation logic (no business logic in triggers/procs) |
| **Search** | Full-text and structured query surface over canonical data | Perform ingestion or writes |
| **AI Reasoning Layer** | Retrieve canonical evidence and generate cited explanations | Access raw source payloads or decide compliance outcomes |

Full detail on each stage's internal design lives in [`PIPELINE.md`](./PIPELINE.md), [`ERROR_HANDLING.md`](./ERROR_HANDLING.md), and the per-source ingestion documents.

---

## 4. Repository Structure

```
regulatory-intelligence-engine/
│
├── docs/                    # This documentation set. Source of truth for design decisions.
│
├── ingestion/                # Source adapters. One subpackage per source.
│   ├── openfda/               #   fetch/parse/validate/transform for openFDA
│   ├── dailymed/               #   fetch/parse/validate/transform for DailyMed
│   └── common/                 #   shared adapter interface, retry/backoff, checkpointing
│
├── normalization/            # Ingredient normalization, synonym resolution, unit standardization
│
├── resolution/                # Entity resolution and deduplication engine
│
├── database/                  # SQLAlchemy models, Alembic migrations, DB access layer
│   ├── models/
│   └── migrations/
│
├── api/                       # FastAPI application: search endpoints, health checks
│
├── ai/                        # Retrieval + prompt orchestration for the reasoning layer
│
├── scripts/                   # One-off / operational scripts (backfills, manual reconciliation)
│
├── tests/                     # Unit, integration, golden-file, and snapshot tests
│   ├── unit/
│   ├── integration/
│   └── golden/
│
├── docker/                    # Dockerfiles, docker-compose definitions
│
└── .github/                   # CI workflows
```

### Why this structure and not feature folders

The repository is organized **by engineering layer, not by feature.** A "feature folder" structure (e.g., `features/recalls/`, `features/warnings/`) looks appealing early but breaks down here because a single canonical `Recall` entity is populated by multiple sources, consumed by multiple API endpoints, and referenced by the AI layer — there is no single feature boundary that owns it. Organizing by layer (ingestion, normalization, resolution, database, api, ai) means:

- A new engineer looking for "how do we talk to openFDA" goes straight to `ingestion/openfda/` — no hunting across feature folders.
- The canonical model has exactly one home (`database/models/`), which reinforces the rule that no layer defines its own private version of `Ingredient` or `Product`.
- Each top-level directory maps 1:1 to a box in the architecture diagram in Section 1, so the repository structure and the system's mental model never drift apart.

### Directory-by-directory rationale

- **`ingestion/`** — isolates all source-specific, "the outside world is messy" code. Everything here is expected to change when a government API changes; nothing outside this directory should need to change in response.
- **`ingestion/common/`** — the adapter interface contract, shared retry/backoff/circuit-breaker logic, and the checkpointing mechanism (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md)). This is what prevents each new source from reimplementing resilience from scratch.
- **`normalization/`** — pure, source-agnostic transformation logic (string cleanup, unit conversion, synonym lookup). No network calls, no database access — this makes it trivially unit-testable.
- **`resolution/`** — the entity resolution and deduplication engine described in [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md). Kept separate from `normalization/` because resolution requires database reads (comparing against existing canonical entities) while normalization does not.
- **`database/`** — the only place that knows the physical schema. All other layers interact with it through repository-style functions, never raw SQL scattered across the codebase.
- **`api/`** — thin. It composes database/search queries into HTTP responses. Business logic does not live here.
- **`ai/`** — isolated because it is the only layer allowed to call an LLM provider. This makes "did we accidentally send raw data to a third-party API" a one-directory audit instead of a codebase-wide grep.
- **`tests/golden/`** — fixed input/output pairs for parsers (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)) — critical because government source formats change silently and golden files are what catch it.

---

## 5. Technology Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python | Best-in-class ecosystem for data engineering, XML/JSON parsing, and AI tooling; team familiarity |
| API framework | FastAPI | Async-native (important for I/O-bound ingestion and API calls), automatic OpenAPI schema, Pydantic validation baked in |
| Database | PostgreSQL | Relational integrity for entity relationships, native full-text search for phase 1, JSONB for provenance/raw-payload archival, mature partitioning support for future scale |
| ORM | SQLAlchemy + Alembic | Explicit migrations (no magic auto-sync to production schema), mature, well-understood by most backend engineers |
| Search (phase 1) | PostgreSQL full-text search | Avoids operating a second stateful system before it's justified by scale or query needs |
| Search (future) | OpenSearch/Elasticsearch | Added only when relevance ranking or query volume outgrows Postgres FTS — see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) |
| Background jobs (future) | Celery or Temporal | Deferred until ingestion needs true distributed scheduling; phase 1 ingestion runs as scheduled batch jobs, not a job queue |
| AI orchestration | LangGraph / LangChain + Anthropic/OpenAI APIs | Retrieval-augmented generation orchestration; see [`AI_PIPELINE.md`](./AI_PIPELINE.md) |
| Containerization | Docker + Docker Compose | Reproducible local environment; one-command bring-up (`docker compose up`) |
| CI | GitHub Actions | Standard, no new infrastructure to operate |
| Testing | Pytest | Standard Python testing, good fixture support for golden-file and snapshot testing |

Every "future" entry above is deliberately deferred, not omitted by oversight — see [`ROADMAP.md`](./ROADMAP.md) for the trigger conditions that justify introducing each one.

---

## 6. Data Flow: Concrete Walkthrough

To make the diagram in Section 1 concrete, here is what happens when a new DailyMed SPL file is ingested end to end:

1. **Fetcher** downloads the DailyMed bulk ZIP (or an incremental delta) to local/temp storage — streamed, not buffered in memory.
2. **Downloader** recursively walks the ZIP-of-ZIPs structure, extracting only `.xml` files matching the SPL pattern, discarding images/PDFs (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md)).
3. **Parser** runs targeted XPath extraction against each XML — never a full-document parse — using dedicated extractors (`IngredientExtractor`, `WarningExtractor`, `ManufacturerExtractor`, `DosageExtractor`).
4. **Validator** checks each extracted record against the expected schema (required fields present, types correct); malformed records are logged and routed to a dead-letter path, not silently dropped (see [`ERROR_HANDLING.md`](./ERROR_HANDLING.md)).
5. **Transformer** maps the validated, source-shaped record into canonical `Ingredient`/`Product`/`Warning` objects, tagging each with its `Source` and a raw-payload reference for provenance.
6. **Normalizer** standardizes ingredient name strings (casing, whitespace, punctuation, unit format).
7. **Entity Resolver** checks whether this canonical entity already exists (by CAS number, exact synonym match, or fuzzy match above a confidence threshold) and either links to the existing entity or creates a new one, flagging low-confidence matches for manual review.
8. **Database** persists the record as a new version, never overwriting prior history.
9. **Search API** indexes/exposes the updated record.
10. **AI Reasoning Layer**, on a user query, retrieves from the canonical model (never from the original DailyMed XML) and generates an answer with citations back to the specific canonical records used.

The openFDA path (Section 1) joins this same pipeline from step 4 onward — this convergence is exactly what the adapter pattern in Section 2 is designed to produce.

---

## 7. Deployment Architecture (Phase 1)

Phase 1 deployment is intentionally simple — a single Docker Compose stack:

```
docker-compose.yml
  ├── postgres        (canonical data store)
  ├── api              (FastAPI app)
  └── ingestion-runner   (scheduled/manual ingestion jobs)
```

No orchestration platform, no message broker, no managed search cluster — these are explicitly deferred (see [`ROADMAP.md`](./ROADMAP.md)) until real scale or concurrency requirements justify their operational cost. Running `docker compose up` must always bring up a fully working system; this is treated as a hard invariant, not an aspiration.

---

## 8. What This Architecture Optimizes For, and What It Trades Away

**Optimizes for:** correctness and traceability of data (every canonical record can be traced back to the exact source payload and version that produced it), source isolation (a breaking change in one government API cannot silently corrupt another source's data), and incremental extensibility (new sources are additive, not invasive).

**Trades away:** raw ingestion throughput in phase 1 (no distributed job queue yet — see [`ROADMAP.md`](./ROADMAP.md)) and search sophistication in phase 1 (Postgres FTS, not a dedicated search engine). Both are explicit, reversible, documented trade-offs, not accidents.
