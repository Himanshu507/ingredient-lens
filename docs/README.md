# ingredient-lens — Technical Docs

In-depth documentation of the codebase: architecture, diagrams, and what
every file does. For project scope, non-goals, and the def-of-done
checklist, see the root [`README.md`](../README.md) — this folder documents
*how it's built*, the root doc documents *what it's supposed to do*.

1. [**Overview**](00-overview.md) — container topology, request lifecycle,
   tech stack, why there are two separate LLM call sites.
2. [**Pipeline**](01-pipeline.md) — Part A, Stages 1-4, the FDA-scraping
   batch job. What each stage's interface is, what it hides, what's still
   unfinished (`needs_review` not surfaced in the UI yet).
3. [**Database**](02-database.md) — ER diagram, table-by-table column docs,
   the Alembic migration setup, the session-management split
   (`get_session()` vs `get_db()`).
4. [**API**](03-api.md) — the matching cascade (exact → synonym → fuzzy →
   LLM), why "not FDA-flagged" isn't a bug, candidate-splitting edge cases.
5. [**Frontend**](04-frontend.md) — component tree, data flow for a single
   submit (paste and photo paths), file-by-file breakdown.
6. [**File reference**](05-file-reference.md) — every file in the repo,
   one line each, organized by directory.

## Reading order

New to the codebase? Read in order (1 → 6). Debugging something specific?
Jump straight to the relevant doc — each one is self-contained and links
back here.

## Keeping this current

These docs describe the system as of this write-up. If you change a stage's
interface, a table's columns, the matching cascade's tiers, or a component's
props, update the corresponding doc in the same change — a diagram or
file-purpose line that's gone stale is worse than no diagram at all.
