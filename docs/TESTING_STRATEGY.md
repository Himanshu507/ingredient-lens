# TESTING_STRATEGY.md

## Purpose of This Document

This document specifies how every layer of RIE is tested. The pipeline architecture in [`PIPELINE.md`](./PIPELINE.md) was explicitly designed with typed, narrow stage boundaries so that each stage could be tested in isolation — this document is where that design pays off. A change to this system is not considered done until it is tested at the appropriate level(s) described here; "it worked when I ran it manually once" is not a substitute for any of what follows.

---

## 1. Testing Philosophy

- **Test at the lowest level that can catch the bug.** A normalization bug belongs in a unit test of the normalizer, not discovered via a full end-to-end ingestion run against live DailyMed data.
- **Government source formats change silently.** Unlike most external dependencies, there is no changelog notification when the FDA tweaks a field. Golden-file and snapshot tests (Sections 4–5) exist specifically to catch this class of drift automatically, not to catch logic bugs.
- **Never skip or disable a failing test to unblock a merge.** Per [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md), a failing test indicates a real defect or a genuinely outdated assumption — the fix is to address the cause, not to comment out the assertion.
- **Tests are documentation.** A well-named test for `EntityResolver` matching "Vitamin C" to "Ascorbic Acid" is often clearer than prose at explaining the expected behavior — this is treated as a real, valued property of the test suite, not incidental.

---

## 2. Unit Tests

**Scope**: a single function, class, or stage, in complete isolation — no network, no database, no filesystem beyond in-memory fixtures.

**Applies to**:
- Normalizer logic (string normalization rules) — see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) Section 3.
- Individual extractors (`IngredientExtractor`, `WarningExtractor`, etc.) — given a parsed XML fragment, assert on the extracted fields, independent of the full SPL document or the rest of the pipeline (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Section 5).
- Validators — given a well-formed and a malformed record, assert accept/reject behavior and the specific rejection reason.
- Transformers — given a source-shaped object, assert the resulting canonical object's fields.
- Entity resolution scoring — given two name strings, assert the computed confidence score falls in the expected tier (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) Section 6).
- Retry/backoff logic — given a sequence of simulated failures, assert the correct number of attempts and delay progression, without real network calls (a fake clock and a fake failing client are used, not `sleep()`).

**Standard**: unit tests are fast (the full unit suite should run in seconds, not minutes) and run on every commit, not just before merge.

---

## 3. Integration Tests

**Scope**: multiple stages composed together, against real (but test-scoped) infrastructure — a real PostgreSQL instance (via a disposable test database/container), not a mock of the database.

**Applies to**:
- Full adapter runs (`fetch` → `save`) against a **recorded/replayed** source response (see Section 6) rather than the live source — this keeps integration tests deterministic and independent of external service availability.
- The full resolution pipeline: ingest two records from different simulated sources that should resolve to the same canonical entity, and assert the database ends up with one merged `Ingredient` with both `Reference`s and `Alias`es attached (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) Section 9).
- Idempotent re-ingestion: run the same ingestion input twice and assert the resulting database state is identical after both runs (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 4) — this is treated as a required, automated test, not a manual spot-check.
- Checkpoint/resume behavior: simulate a mid-run failure (inject a failure partway through a batch), restart the run, and assert it resumes correctly with no data loss and no duplication (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 5).
- API endpoint tests: given seeded canonical data, assert the search/API layer returns correct results.

**Standard**: integration tests are slower than unit tests and run on every pull request via CI, using ephemeral, isolated test infrastructure (a fresh database per test run) — never against a shared or production-adjacent environment.

---

## 4. Parser Tests and Golden Files

### The problem golden files solve

Parsers and extractors are the layer most exposed to real-world format variation and silent upstream drift (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Section 9 on schema evolution). A hand-written synthetic test fixture risks testing what we *assume* the format looks like, not what it *actually* looks like.

### The approach

- A curated set of **real, representative source documents** — actual openFDA JSON responses and actual DailyMed SPL XML files, sanitized of anything sensitive if needed but otherwise unmodified — are checked into `tests/golden/` as fixed input files.
- For each golden input, the **expected parsed/extracted output** is captured and checked in alongside it.
- The test asserts that running the current parser/extractor against the golden input reproduces the golden output exactly.
- **Golden files are deliberately diverse**: documents with optional sections present and absent, documents with multiple ingredients, documents with unusual but valid structural variations (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) Section 9) — the set is expanded every time a real-world edge case is discovered in production, so the golden set grows to reflect actual encountered variation over time rather than staying static.

### Why this catches what unit tests alone miss

A hand-crafted unit test fixture encodes the author's *assumptions* about the format. A golden file encodes *reality* at the time it was captured. When the source changes its format, a well-designed golden-file test fails clearly — pointing at exactly which real document broke and how — rather than passing against an assumption that's now stale.

---

## 5. Snapshot Tests

**Scope**: canonical model output for a given input, captured as a snapshot and compared on subsequent runs.

- Distinct from golden-file tests: golden files test *parsing/extraction* (source format → intermediate object); snapshot tests test the *full transform* (intermediate object → canonical model candidate), capturing the shape of `IngredientCandidate`, `ProductCandidate`, etc. as serialized snapshots.
- When a snapshot test fails because a canonical field's derivation intentionally changed, the snapshot is explicitly reviewed and updated as part of that change's code review — a snapshot update is never an automated, unreviewed action, since an unreviewed snapshot update is equivalent to deleting the test's ability to catch regressions.

---

## 6. Regression Tests

- Every production incident (a bad merge in entity resolution, a parser mishandling a newly-observed document variant, a validator gap that let malformed data through) produces a regression test as part of its fix — the specific failing input becomes a new golden file, snapshot, or integration test case, so the same class of bug cannot silently reoccur.
- Source responses used in integration tests (Section 3) are **recorded fixtures** captured from real API/bulk-data interactions at a point in time, replayed deterministically in CI — this both avoids flaky tests depending on live external services and creates a natural, growing regression corpus as new recordings are added over time.

---

## 7. Testing the Untestable-Seeming Parts

- **AI layer testing** (see [`AI_PIPELINE.md`](./AI_PIPELINE.md)): while LLM output isn't deterministic, the citation-verification logic (Section 5 of that document) — mapping claims to evidence, rejecting uncited claims — is fully deterministic application code and is unit tested like any other validation logic. Retrieval correctness (does the right evidence come back for a given query) is tested against seeded canonical data, independent of the LLM call itself.
- **Retry/backoff timing**: tested with a fake clock, never real `sleep()` calls, so the test suite doesn't spend real wall-clock time verifying exponential backoff math.
- **Streaming/memory-bounded parsing** (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md), [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md)): tested with a synthetic large input and an assertion on peak memory usage staying within a defined bound, not just a functional correctness check — this is a performance-characteristic test, and treated as a real, required test class rather than an informal manual check.

---

## 8. CI Enforcement

- Unit and integration tests run on every pull request; a PR cannot merge with a failing test, and cannot merge with test coverage regressing on touched code without explicit justification in review.
- Golden-file and snapshot test failures block merge by default — an intentional format/output change requires explicit, reviewed snapshot/golden-file updates in the same PR, never a suppressed or skipped assertion.
- Linting and type-checking run alongside tests as a baseline quality gate, not a substitute for behavioral tests — passing type checks proves shapes align, not that behavior is correct.
