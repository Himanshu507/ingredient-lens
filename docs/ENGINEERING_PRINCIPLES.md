# ENGINEERING_PRINCIPLES.md

## Purpose of This Document

This document states the rules that govern every decision in this codebase — the ones that don't belong to any single layer, and that every other document in `/docs` implicitly assumes. When a design choice in another document seems to trade elegance for restraint, or completeness for narrowness, this is the document that explains why that trade was made on purpose.

---

## 1. Build Brick by Brick, Never Module by Module

### The rule

Every unit of work ("brick" — see [`ROADMAP.md`](./ROADMAP.md) for the concrete sequence) must, on its own:

- **Compile** — the codebase builds cleanly with the brick added.
- **Run** — the system starts and functions with the brick in place.
- **Be testable** — the brick has tests that exercise its actual behavior.
- **Be deployable** — `docker compose up` (or the production equivalent) works with the brick included.
- **Be documented** — the corresponding `/docs` file reflects the brick's design, not a stale pre-brick description.

A brick that fails any of these five is not finished, regardless of how much code was written for it.

### Why, not just what

The alternative — "module by module" — means building an entire layer (e.g., "the whole database schema," or "the whole AI system") in isolation before it's wired into anything working. This looks efficient (specialize, build the whole thing, move on) but it front-loads risk: you don't discover that your database schema doesn't fit your ingestion pipeline's actual needs until both are "done" and you try to connect them, at which point the rework touches two large, already-built systems instead of one small, recently-built one.

Building brick by brick means every step produces a **working, if narrow, system** — the project is never more than one brick away from a runnable state. This is what makes the project reviewable and correctable continuously, instead of only at large, expensive integration milestones. It is the same reasoning that underlies vertical-slice development and walking skeletons in the broader engineering literature, applied here concretely to a data pipeline: brick 1 is a running repo, not "the repo layer finished"; brick 5 is one working source adapter producing real canonical objects, not "the ingestion module, unconnected to anything."

### What this looks like in practice

See [`ROADMAP.md`](./ROADMAP.md) for the actual sequence. The shape is always: extend the previous working system by one small, coherent, testable capability — never "build three unconnected things in parallel and integrate them later."

---

## 2. SOLID, Applied to a Data Pipeline

- **Single Responsibility**: every stage in [`PIPELINE.md`](./PIPELINE.md) has exactly one job (fetch, parse, validate, transform...), and every extractor in [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) handles exactly one SPL section. A class or function that does two of these things is a signal to split it, not a convenient shortcut.
- **Open/Closed**: adding a new source (see [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 2) or a new SPL extractor (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Section 5) is additive — new adapter, new extractor — and does not require modifying the shared pipeline, the canonical model, or existing adapters.
- **Liskov Substitution**: every source adapter implementing the shared `fetch`/`parse`/`validate`/`transform`/`save` contract (see [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 2) is fully substitutable in the pipeline — the pipeline code that drives ingestion never branches on "if this is the openFDA adapter, do X."
- **Interface Segregation**: the adapter contract is deliberately narrow — five methods, not a sprawling interface exposing every possible hook a source *might* need. Extractors similarly expose a narrow "given parsed XML, return this one canonical fragment" interface, not a general-purpose document-querying API.
- **Dependency Inversion**: the database access layer, the search layer, and the AI layer all depend on the canonical model's abstractions (see [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md)), never on a specific source's concrete shape — this is the mechanism, not just the intent, behind "raw government schemas never leak into business logic."

---

## 3. Implementation Completeness

- **No partial features.** If a brick is started, it is finished to a working state before the next brick begins — no half-wired adapter, no API endpoint that returns mock data "for now."
- **No mock objects or stub implementations standing in for real logic** in anything other than test fixtures. A `TODO: implement retry logic` in production code is treated as an unfinished brick, not a deferred one.
- **No speculative fields, tables, or configuration options** added because they might be useful later — see YAGNI (Section 4). Every field in the canonical model exists because a real, current consumer needs it.

---

## 4. Scope Discipline

- **Build only what's asked.** Phase 1 is two sources (openFDA, DailyMed), a canonical model, entity resolution, a search API, and a narrowly-scoped AI layer — not authentication, not a general-purpose document store, not a multi-tenant SaaS platform, unless and until a specific brick in [`ROADMAP.md`](./ROADMAP.md) calls for it.
- **YAGNI is a discipline, not a slogan.** Multiple documents in this set explicitly note where an obvious-seeming addition (a dedicated search engine, a distributed job queue, vector retrieval, partitioning) is deferred with a stated trigger condition rather than built preemptively — see [`ROADMAP.md`](./ROADMAP.md) for the consolidated list. Deferring is a decision made with reasoning, not an oversight.
- **MVP first, iterate from evidence.** The entity resolution confidence thresholds (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) Section 6) are explicitly a starting point expected to be tuned from observed data, not a value we agonize over getting perfectly right before shipping.

---

## 5. Testability and Observability as Design Constraints, Not Afterthoughts

- Every stage boundary in [`PIPELINE.md`](./PIPELINE.md) is a typed contract specifically so it can be unit tested in isolation — testability is a reason the architecture looks the way it does, not a property checked after the fact.
- Every pipeline run produces structured logs and metrics by construction (see [`OBSERVABILITY.md`](./OBSERVABILITY.md)) — "how do we know this worked" is answered by the system itself, not by an engineer manually inspecting a database after the fact.

---

## 6. Idempotency and Reproducibility

- **Idempotency**: running any ingestion pipeline twice against the same input never duplicates data (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 4) — this is treated as a hard invariant, verified by automated tests (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md) Section 3), not just an aspiration.
- **Reproducibility**: the same input always produces the same canonical output. This is what makes golden-file and snapshot testing (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md) Sections 4–5) meaningful at all — a non-deterministic transform would make "does this match the golden output" an unanswerable question.

---

## 7. Professional Honesty in Engineering Claims

- Trade-offs are documented, not hidden — every architectural decision in this doc set that has real alternatives includes them and states why one was chosen (see, for example, [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 2's adapter-pattern comparison table, repeated in form throughout the other documents).
- Deferred work is labeled as deferred, with a stated trigger condition — not silently omitted and not implemented prematurely to look complete. "Not built yet, here's when it should be" is treated as a complete and honest engineering answer.
- Nothing in this system is described as "production-ready" until it satisfies the Definition of Done (Section 8).

---

## 8. Definition of Done

A brick, a feature, or a change is done only when it satisfies all of the following — not most of them:

- **Working**: it functions correctly for its intended use, verified by running it, not just by reading the code.
- **Tested**: it has unit and/or integration coverage appropriate to its layer (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)).
- **Documented**: the relevant `/docs` file reflects the change in the same pull request, not as a follow-up.
- **Logged**: it emits the structured logs and metrics appropriate to its stage (see [`OBSERVABILITY.md`](./OBSERVABILITY.md)).
- **Dockerized / deployable**: it works inside the standard `docker compose up` environment, not only on one engineer's machine.

If any of these is missing, the work is not finished — it is in progress, and is represented as such.
