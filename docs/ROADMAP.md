# ROADMAP.md

## Purpose of This Document

This is not a feature roadmap. It is a **brick-by-brick engineering roadmap**, following the philosophy in [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md) Section 1: every brick compiles, runs, is tested, is deployable, and is documented before the next brick starts. Each brick extends a working system — the project is runnable after every single brick in this list.

Each brick entry states: **Objective** (the one thing this brick delivers), **Builds on** (the prior brick it extends), **Done when** (the concrete, checkable completion criterion).

---

## Phase 1: Foundation

### Brick 1 — Repository

**Objective**: a working, empty-but-real repository — Docker, FastAPI skeleton, PostgreSQL, dependency management, linting, formatting, type-checking, and pre-commit hooks all wired together.

**Builds on**: nothing — this is the foundation.

**Done when**: `docker compose up` starts a Postgres instance and a FastAPI app that responds to a request, from a clean checkout, with no manual setup steps beyond documented prerequisites.

---

### Brick 2 — Database Schema (No Application Logic)

**Objective**: the core tables from [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) exist — `ingredients`/`ingredient_versions`, `products`/`product_versions`, `manufacturers`/`manufacturer_versions`, `warnings`, `recalls`, `aliases`, `references`, `sources`, `ingestion_logs` — with no API or ingestion logic touching them yet.

**Builds on**: Brick 1.

**Done when**: the schema exists as SQLAlchemy models with corresponding Alembic migrations; `alembic upgrade head` runs cleanly against a fresh database.

---

### Brick 3 — Database Access Layer and Migration Discipline

**Objective**: a tested repository-style data access layer over the Brick 2 schema — typed functions for creating/querying entity identity rows and version rows, implementing the versioning and soft-delete rules from [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md).

**Builds on**: Brick 2.

**Done when**: unit and integration tests (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)) cover creating a new entity, creating a new version, and retrieving current vs. historical state — against a real (test) Postgres instance.

---

### Brick 4 — First API Surface

**Objective**: `GET /` and `GET /health`. Nothing else.

**Builds on**: Brick 1 (the FastAPI skeleton), independent of Brick 2/3.

**Done when**: both endpoints are live, tested, and documented in the auto-generated OpenAPI schema.

---

## Phase 2: First Source, End to End

### Brick 5 — openFDA Adapter: Fetch and Parse Only

**Objective**: the openFDA `fetch()` and `parse()` steps (see [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md)) — pagination, streaming, retry/backoff — producing source-shaped intermediate objects. No canonical model, no database writes yet.

**Builds on**: Brick 1.

**Done when**: running the adapter against a live (or recorded, for CI) openFDA endpoint produces correctly parsed intermediate objects, with unit tests covering pagination and retry logic using a fake clock and fake HTTP client (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md) Section 7).

---

### Brick 6 — openFDA Adapter: Validate, Transform, Persist

**Objective**: complete the openFDA adapter — validation against a schema, transformation into canonical model objects (per [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md)), and idempotent persistence into the Brick 2/3 schema. No entity resolution yet — records are saved as new canonical entities directly.

**Builds on**: Brick 3, Brick 5.

**Done when**: running the full adapter against real openFDA data populates the database with correct canonical records, re-running it produces zero duplicates (idempotency test, per [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 4), and an `ingestion_logs` entry is written per [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 9.

---

### Brick 7 — Checkpointing and Resumable Ingestion

**Objective**: add checkpoint writing and resume-on-restart to the openFDA adapter, per [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 5.

**Builds on**: Brick 6.

**Done when**: an integration test simulates a mid-run failure and asserts the next run resumes from the correct checkpoint with no data loss or duplication.

---

## Phase 3: Second Source, Proving the Adapter Pattern

### Brick 8 — DailyMed Adapter: Discovery, Streaming Extraction, XML Parsing

**Objective**: recursive ZIP traversal, automatic SPL XML discovery, streaming extraction (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Sections 2–4), and the first dedicated extractor (`IngredientExtractor`) with golden-file tests.

**Builds on**: Brick 1 (independent of the openFDA-specific code — this is the proof that the adapter pattern from [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 2 actually holds for a structurally unrelated source).

**Done when**: running the extraction pipeline against a real DailyMed bulk export correctly discovers and extracts only SPL XML files, ignoring images/PDFs, with bounded memory usage (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md) Section 7) verified under test.

---

### Brick 9 — DailyMed Adapter: Remaining Extractors Through Persistence

**Objective**: `WarningExtractor`, `ManufacturerExtractor`, `DosageExtractor`; validation, transformation into the same canonical model Brick 6 established, idempotent persistence, checkpointing at package granularity (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Section 8).

**Builds on**: Brick 6 (shares the persistence/transform/checkpoint infrastructure — proving it required zero changes to support a second source), Brick 8.

**Done when**: DailyMed data lands in the same canonical tables openFDA data lands in, both sources' data coexisting correctly, each attributed to its correct `Source`.

---

## Phase 4: Making the Data Trustworthy

### Brick 10 — Entity Resolution: Authoritative Identifier and Exact Match

**Objective**: Strategies 1 and 2 from [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) — CAS/UNII exact match and normalized-name/alias exact match. No fuzzy matching yet.

**Builds on**: Brick 6, Brick 9 (needs both sources producing candidates to be meaningful).

**Done when**: ingesting the same ingredient from both openFDA and DailyMed under an identical or CAS/UNII-linked name correctly merges into one canonical `Ingredient`, verified by an integration test.

---

### Brick 11 — Entity Resolution: Fuzzy Matching and Manual Review

**Objective**: Strategy 3 — trigram candidate generation, confidence scoring, the manual review queue (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) Sections 6–7).

**Builds on**: Brick 10.

**Done when**: "Vitamin C" (openFDA) and "Ascorbic Acid" (DailyMed) — no shared identifier, no exact name match — correctly route to auto-merge or manual review per confidence tier, and an approved manual review correctly writes back an alias so the same pair never re-queues.

---

### Brick 12 — Error Handling and Dead Letter Queue

**Objective**: the full DLQ, structured logging, retry/backoff generalized across both adapters, and the alerting conditions from [`ERROR_HANDLING.md`](./ERROR_HANDLING.md).

**Builds on**: Brick 6, Brick 9.

**Done when**: injected record-level and batch-level failures in both adapters correctly dead-letter without halting the run, and dead-lettered records are successfully reprocessed once a simulated root cause is fixed.

---

## Phase 5: Making the Data Queryable

### Brick 13 — Search API

**Objective**: `/ingredients`, `/products`, `/warnings`, `/recalls` endpoints backed by PostgreSQL full-text search (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) Section 9).

**Builds on**: Brick 4, Brick 11 (search needs resolved, deduplicated canonical data to be meaningful).

**Done when**: a keyword search for "Vitamin C" returns the single merged canonical ingredient and its associated products/warnings/recalls, with correct provenance attached to each result.

---

### Brick 14 — Observability Dashboard

**Objective**: the health views described in [`OBSERVABILITY.md`](./OBSERVABILITY.md) Section 5 — per-source health, trend views, entity resolution health — built from `ingestion_logs`, `ingestion_dead_letters`, and `entity_resolution_reviews`.

**Builds on**: Brick 12, Brick 13.

**Done when**: an operator can answer "is source X healthy, and what's the manual review backlog" without querying the database by hand.

---

## Phase 6: AI Reasoning Layer

### Brick 15 — Retrieval

**Objective**: query-time retrieval against the canonical model and search layer (see [`AI_PIPELINE.md`](./AI_PIPELINE.md) Section 3), returning ranked evidence with full provenance — no LLM call yet.

**Builds on**: Brick 13.

**Done when**: given a natural-language-ish query, retrieval returns relevant canonical records with correct provenance, tested against seeded data independent of any LLM.

---

### Brick 16 — Prompting, Citation, and Hallucination Guards

**Objective**: the full AI pipeline from [`AI_PIPELINE.md`](./AI_PIPELINE.md) — structured evidence injection, citation-constrained prompting, post-generation citation verification, and rejection/fallback on validation failure.

**Builds on**: Brick 15.

**Done when**: a query with strong evidence produces a correctly cited answer; a query with no relevant evidence produces an explicit "insufficient evidence" response rather than a fabricated one — both verified by automated tests on the citation-verification logic (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md) Section 7).

---

### Brick 17 — Minimal Search/Ask UI

**Objective**: a small frontend — a search box and an ask-a-question box, nothing else — exercising Brick 13 and Brick 16.

**Builds on**: Brick 13, Brick 16.

**Done when**: a user can search canonical data and ask a question and see a cited answer, end to end, through a browser.

---

## Deferred Work and Trigger Conditions

Consolidated from the "future" notes scattered across other documents — listed here together so the roadmap is the single place that shows what's intentionally not yet built, and why:

| Deferred item | Trigger condition to build it | Documented in |
|---|---|---|
| Dedicated search engine (OpenSearch/Elasticsearch) | Postgres FTS query latency/relevance becomes insufficient at real query volume | [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) §9 |
| Table partitioning | `*_versions`/`ingestion_logs` growth measurably degrades query or maintenance performance | [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) §8 |
| Distributed job queue (Celery/Temporal) | Ingestion needs true multi-worker distributed scheduling beyond a single-process pipeline + cron trigger | [`PIPELINE.md`](./PIPELINE.md) §3, §5 |
| Message broker (Kafka/RabbitMQ) replacing the in-process queue | Same trigger as above — distributed, multi-process ingestion | [`PIPELINE.md`](./PIPELINE.md) §3 |
| Vector/semantic retrieval for the AI layer | Keyword retrieval's recall proves insufficient for natural-language query vocabulary mismatch | [`AI_PIPELINE.md`](./AI_PIPELINE.md) §3 |
| Full distributed tracing (OpenTelemetry span propagation) | The system becomes genuinely multi-service/multi-worker | [`OBSERVABILITY.md`](./OBSERVABILITY.md) §4 |
| S3-backed raw payload archival | Raw payload volume/retention needs outgrow ad hoc storage | [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) §10 |
| Package insert PDF storage/display | A real product requirement to show original PDFs to end users emerges | [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) §2 |

---

## Future Sources (Phase 7+)

Each additional source is, by design (see [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 2), one new adapter — not a change to the canonical model, database schema, entity resolution engine, search layer, or AI layer. In roughly increasing order of integration complexity relative to what Bricks 1–17 already establish:

1. **FDA SRS** (Substance Registration System) — additional authoritative ingredient identifiers, strengthening entity resolution's Strategy 1 (Section 4 of [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)).
2. **GRAS** (Generally Recognized As Safe) notices — new `Reference`/status data attached to existing `Ingredient` entities.
3. **21 CFR** — regulatory text, likely introducing a new canonical entity for citable regulatory provisions, feeding AI evidence retrieval.
4. **NIH / PubMed** — scientific literature references, another new `Reference` type and a candidate new canonical entity (`Publication`).
5. **EFSA, Health Canada, FSSAI** — international regulatory equivalents of openFDA/DailyMed, proving the adapter pattern generalizes across jurisdictions, and introducing jurisdiction as a first-class dimension of the canonical model (a deliberate, reviewed schema extension, not an ad hoc field).

## Future Capabilities (Phase 8+)

- **Knowledge graph** — relationship-centric querying across ingredients, products, warnings, and recalls beyond what relational joins comfortably express.
- **Compliance rules engine** — codified regulatory rules that consume canonical data as input; explicitly kept separate from the AI layer, since compliance determination is a rules/logic concern, not a generative one, per the non-goal stated in [`AI_PIPELINE.md`](./AI_PIPELINE.md) Section 1.
- **Multi-country support** — generalizing the jurisdiction concept introduced by Phase 7's international sources into a first-class query and modeling dimension throughout the system.

Every item in this roadmap builds on the previous one. Nothing here is started before the brick it depends on is genuinely done, per the Definition of Done in [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md) Section 8.
