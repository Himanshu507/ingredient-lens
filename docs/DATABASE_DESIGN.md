# DATABASE_DESIGN.md

## Purpose of This Document

This document specifies how the canonical model defined in [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) is physically represented in PostgreSQL: table design, versioning, soft deletes, indexing, relationships, migration strategy, and the search and partitioning strategy. This is the layer that turns conceptual entities into durable, queryable, auditable storage.

---

## 1. Database Philosophy

Four non-negotiable rules govern every table in this system:

1. **Nothing is ever destructively overwritten.** An update to a canonical fact creates a new version; the prior version remains queryable. This is what makes the system auditable and what makes "what did we believe last Tuesday" an answerable question instead of a lost one.
2. **Every row is attributable.** Every canonical entity version carries a link to the `Source` record that produced it (see [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) Section 7). A row with no provenance is a bug, not an edge case.
3. **The schema is the contract, and it changes through migrations, not manual intervention.** No engineer runs `ALTER TABLE` by hand against a real environment. Every schema change is a reviewed, version-controlled migration (Section 6).
4. **Business logic does not live in the database.** No stored procedures encoding transformation or resolution logic, no triggers implementing entity-resolution rules. PostgreSQL is a durable store with strong consistency guarantees and good query capabilities — not an application runtime. This keeps logic testable in the application layer (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)) instead of hidden in the database where it's invisible to code review and hard to unit test.

---

## 2. Versioning Strategy

### The problem

Government sources correct themselves. A recall gets reclassified. A warning gets strengthened. If RIE simply updates a row in place, two things are lost: the fact that a change happened at all, and what the system believed before the change — both of which matter enormously for a *regulatory* intelligence product, where "what did the label say as of last month" is a legitimate and important question.

### The design: append-only version chains

Each canonical entity (`Ingredient`, `Product`, `Manufacturer`, `Warning`, `Recall`) is represented by two things:

- A stable **entity identity row** — holds the permanent canonical ID (e.g., `ING-000123`) and never changes.
- A sequence of **version rows** — each one a complete snapshot of that entity's fields at a point in time, linked to the entity identity, ordered by a version number and timestamp, and linked to the `Source` that produced it.

Querying "the current state of ingredient X" means fetching its identity row and joining to the latest version row (a `current_version_id` pointer on the identity row, updated when a new version is accepted, makes this a cheap indexed lookup rather than a `MAX(version)` scan on every read). Querying "the full history of ingredient X" means fetching all version rows for that identity, ordered by version.

### Why this design over the alternatives

| Approach | Description | Verdict |
|---|---|---|
| In-place update, no history | Simplest schema | Rejected — loses auditability entirely, unacceptable for a regulatory product |
| Separate `*_history` shadow tables populated by triggers | Current table stays simple; history is a side table | Rejected — pushes versioning logic into database triggers (violates Rule 4 above), and creates two sources of truth that can drift if a trigger is ever bypassed (bulk load, manual fix) |
| Single append-only version table per entity, identity row points to current version (chosen) | One clear model: identity is stable, versions are immutable facts | **Selected** — versioning logic lives in the application's save path (explicit, testable, reviewable), and "current" is just a pointer, not a separately maintained copy |

### What creates a new version

Per [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 4 and Section 6, a new version is only written when incoming data is genuinely different from the current version — an idempotent re-ingestion of unchanged data is a no-op, not a redundant version. This is what keeps version history meaningful (a real change log) rather than noisy (a log of every ingestion run that happened to touch this record).

---

## 3. Soft Deletes

Government sources occasionally retract records entirely (a mistakenly published recall, a withdrawn label). RIE never hard-deletes a canonical entity or version in response:

- A retraction is recorded as a new version with a `status` field set to `retracted` (or `superseded`, `withdrawn`, depending on entity type), not a row deletion.
- Application-level queries (API, search, AI retrieval) default to filtering out retracted/non-current records, but the data remains in the database and is queryable explicitly for audit purposes.
- **Hard deletes are reserved for genuinely erroneous data that should never have been written** (e.g., an ingestion bug that wrote malformed rows) — this is an operator-invoked, logged, exceptional action, not a normal part of the ingestion or update flow.

---

## 4. Core Tables (Conceptual Schema)

This section describes table responsibilities and key columns conceptually. Exact column types and constraints are implementation detail decided at build time against this specification, not enumerated here.

| Table | Purpose | Key columns (conceptual) |
|---|---|---|
| `ingredients` | Entity identity row for canonical ingredients | `id` (canonical, e.g. `ING-000123`), `current_version_id`, `created_at` |
| `ingredient_versions` | Immutable version history for ingredients | `id`, `ingredient_id` (FK), `version_number`, `name`, `normalized_name`, `status`, `source_id` (FK), `created_at` |
| `products` | Entity identity row for canonical products | `id`, `current_version_id`, `created_at` |
| `product_versions` | Immutable version history for products | `id`, `product_id` (FK), `version_number`, `name`, `dosage_form`, `manufacturer_id` (FK), `status`, `source_id` (FK), `created_at` |
| `product_ingredients` | Join table: product ↔ ingredient with relationship attributes | `product_version_id` (FK), `ingredient_id` (FK), `role` (active/inactive), `quantity`, `unit` |
| `manufacturers` / `manufacturer_versions` | Same identity/version pattern as ingredients | (mirrors `ingredients` pattern) |
| `warnings` | Warning records attached to a product version | `id`, `product_id` (FK), `category`, `text`, `status`, `source_id` (FK), `version_number` |
| `recalls` | Recall records | `id`, `product_id` (FK), `manufacturer_id` (FK), `reason`, `classification`, `status`, `source_id` (FK) |
| `aliases` | Alternate names resolving to a canonical entity | `id`, `entity_type`, `entity_id`, `alias_text`, `normalized_alias_text`, `confidence`, `source_id` (FK, nullable for curated dictionary entries) |
| `references` | External identifiers attached to a canonical entity | `id`, `entity_type`, `entity_id`, `reference_type` (enum), `reference_value`, `source_id` (FK) |
| `sources` | Provenance record for every ingested fact | `id`, `source_system`, `endpoint_or_document_type`, `ingestion_run_id`, `raw_payload_ref`, `ingested_at` |
| `ingestion_logs` | Per-run ingestion outcome, checkpointing, and audit trail (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 9) | `id`, `source`, `run_id`, `status`, `checkpoint_state` (JSONB), `records_fetched/validated/created/updated/rejected`, `started_at`, `completed_at` |
| `entity_resolution_reviews` | Queue of low-confidence match candidates awaiting manual review (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)) | `id`, `entity_type`, `candidate_a_id`, `candidate_b_id`, `confidence_score`, `status` (pending/approved/rejected), `reviewed_by`, `reviewed_at` |

`aliases` and `references` use a polymorphic `(entity_type, entity_id)` pair rather than separate join tables per entity type — this trades strict foreign-key enforcement (mitigated by application-layer validation and, where the database supports it, check constraints on `entity_type`) for avoiding a combinatorial explosion of near-identical join tables (`ingredient_aliases`, `manufacturer_aliases`, etc.) as more entity types are added.

---

## 5. Relationships and Referential Integrity

- Foreign keys are enforced at the database level wherever the relationship is to a non-polymorphic table (e.g., `product_versions.manufacturer_id → manufacturers.id`). This is a deliberate choice to let PostgreSQL, not application code, guarantee that a product version never references a manufacturer that doesn't exist.
- Version rows are immutable once written — no foreign key ever points *into the middle* of another entity's version history expecting it to change; relationships are always expressed against either the stable identity row or a specific version row, explicitly.
- `ON DELETE RESTRICT` (not `CASCADE`) is the default posture for foreign keys touching canonical entities — given the soft-delete philosophy (Section 3), an accidental cascading hard-delete propagating across the entity graph is exactly the failure mode this system is designed to prevent.

---

## 6. Migration Strategy

- **Alembic** manages all schema changes, generating versioned, reviewable migration scripts checked into source control alongside the SQLAlchemy models they correspond to.
- **Migrations are additive-first.** Adding a column, adding a table, adding an index — safe, backward-compatible changes — are the default pattern. Destructive changes (dropping a column, renaming a table) go through a deprecate-then-remove cycle: mark unused, confirm no code path reads it, remove in a later migration — never a same-PR "rename and hope nothing broke."
- **Every migration is forward-only in normal operation; rollback scripts exist but are a break-glass tool**, not a routine part of the deploy cycle — a schema rollback after data has already been written against the new schema risks data loss, so the default posture is "fix forward."
- **Migrations run automatically as part of deployment**, gated by CI passing against the migration (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)) — no manual `alembic upgrade head` against a production database as a routine action.

---

## 7. Indexing Strategy

| Index | On | Why |
|---|---|---|
| Unique index on entity identity `id` | `ingredients.id`, `products.id`, etc. | Primary lookup path for canonical entities |
| Index on `current_version_id` | identity tables | Fast "get current state" without scanning version history |
| Index on `(entity_id, version_number)` | all `*_versions` tables | Fast "get full history" and "get version N" queries |
| Index on `normalized_name` | `ingredient_versions`, `aliases` | Entity resolution's exact/near-match lookups (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)) run against normalized text, not display text |
| Composite index on `(entity_type, entity_id)` | `aliases`, `references` | Primary access pattern for the polymorphic tables |
| Index on `(reference_type, reference_value)` | `references` | Fast lookup by external identifier (e.g., "find the canonical ingredient for this CAS number") — this is the index that makes cross-source matching by authoritative ID fast |
| Index on `(source, status, started_at)` | `ingestion_logs` | Operational queries: "show me the last failed run for source X" |
| GIN index on normalized text columns | `ingredient_versions.normalized_name`, `warnings.text` | Backs PostgreSQL full-text search (Section 9) |

Indexes are added deliberately, tied to a known query pattern from the API, search, or resolution layer — not speculatively added to every column "in case it's needed later," per the YAGNI principle in [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md).

---

## 8. Partitioning (Future)

Not implemented in phase 1 — the initial dataset size does not justify the operational complexity. Documented here so the trigger condition and approach are decided in advance rather than improvised under pressure:

- **Trigger condition**: `*_versions` and `ingestion_logs` tables are the ones expected to grow unboundedly over time (every accepted change is a new row, forever). Partitioning is introduced when either table's size starts measurably degrading query performance or vacuum/maintenance times — not on a pre-set row-count guess.
- **Approach**: range partitioning by time (e.g., `created_at` for version tables, `started_at` for `ingestion_logs`) is the natural fit, since the dominant query patterns are either "current state" (served by the identity table's pointer, not affected by version-table partitioning) or "recent history" (naturally aligned with time-range partitions). This is a schema change executed as a planned migration (Section 6) when the trigger condition is met, not a day-one default.

---

## 9. Search Strategy

### Phase 1: PostgreSQL full-text search

- `tsvector` columns (generated/maintained via a stored generated column, not application-side triggers) on the primary searchable text fields — ingredient names, product names, warning text.
- GIN indexes back these `tsvector` columns for performant `@@` query matching.
- This is sufficient for phase 1's query needs: exact/fuzzy name lookup and keyword search across warnings and recalls, at a dataset size where a dedicated search cluster is not yet justified.

### Future: dedicated search engine (OpenSearch/Elasticsearch)

Introduced when either of two conditions is met: query volume/latency requirements exceed what Postgres FTS comfortably serves alongside transactional ingestion load, or relevance-ranking needs (typo tolerance, semantic/vector search feeding the AI retrieval layer — see [`AI_PIPELINE.md`](./AI_PIPELINE.md)) exceed what `tsvector` ranking provides. When introduced, it is a **read-side projection** of the canonical PostgreSQL data (kept in sync via a dedicated indexing pipeline), not a system that ingestion writes to directly — PostgreSQL remains the single source of truth; search infrastructure is always derived, never authoritative.

---

## 10. Why PostgreSQL and Not a Document Store

A document database (e.g., MongoDB) is a tempting fit for heterogeneous source JSON — but RIE's entire purpose is imposing relational structure and referential integrity on top of that heterogeneity (see [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) Section 1). The canonical model is fundamentally relational: products reference ingredients and manufacturers, warnings and recalls reference products, aliases and references resolve to entities. A document store would either duplicate related data across documents (creating consistency risk) or require application-level joins that PostgreSQL already does natively and efficiently. Raw, unstructured source payloads — where a document-store shape would actually be a good fit — are archived as opaque blobs referenced from `sources.raw_payload_ref` (in object storage, not the relational database itself — see [`ROADMAP.md`](./ROADMAP.md) for when S3-backed archival is introduced), keeping the relational database focused on the structured, resolved canonical model it's actually good at serving.
