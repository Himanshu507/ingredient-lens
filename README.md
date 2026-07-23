# ingredient-lens

## 1. What this is

Two parts, working together:

- **A) Reference pipeline** (batch, offline) — scrapes a real FDA regulatory source, uses an LLM to normalize the messy result into clean, confidence-scored status records, and loads them into a small Postgres/SQLite database.
- **B) Product checker app** (the "website") — no login, no accounts. Someone pastes an ingredient list, or uploads a photo of a product's ingredient label (text extracted client-side via OCR, image never touches the server), and gets back an instant regulatory-status read against the reference database built in (A).

This was built as a proof-of-work project for a job application (Kensai — "Market Expansion Intelligence" for regulated consumer products). The app layer exists because a SQL table nobody can query isn't actually useful — the whole point of the exercise is turning a messy government source into something a non-technical person can point at a product and get an answer from.

**Non-goals (stay scoped):** no auth, no accounts, no saved history, no multi-source aggregation, no multi-country data (single source: US/FDA), no admin panel. One page, one form, one result view. Resist generalizing before this one path works end to end.

## 2. Data source (Part A)

**URL:** `https://www.fda.gov/food/dietary-supplements/information-select-dietary-supplement-ingredients-and-other-substances`

FDA's public "Information on Select Dietary Supplement Ingredients and Other Substances" directory — a single HTML page, one table, ~90 ingredients. No auth, no CAPTCHA, no pagination, no rate-limit wall (static `.gov` informational page).

### Table structure

| Column | Notes |
|---|---|
| Ingredients | Primary ingredient name. Sometimes italicized (botanical/Latin names). |
| Other Known Names | Zero or more synonyms, `<br>`-separated within a cell. Sometimes `N/A`. |
| Agency Actions/Statements | One or more linked actions per cell (`<a href>`), `<br>`-separated, sometimes with a parenthetical date. Some links point off fda.gov (archive/wayback). |
| Category | One or more numeric codes (1–7), comma-separated. |
| Date | `YYYY/MM`. |

### Category legend (fixed — hardcode this, don't infer it)

1. Subject of an authorized health claim or qualified health claim
2. Subject of a safety communication
3. Not a "dietary ingredient" under FD&C Act §201(ff)(1)
4. Excluded from the dietary supplement definition under FD&C Act §201(ff)(3)
5. Dietary ingredient hasn't met the safety standard under FD&C Act §402(f)(1)(A)
6. New dietary ingredient hasn't met the safety standard under FD&C Act §402(f)(1)(B)
7. New dietary ingredient requiring premarket safety notification, none submitted, under FD&C Act §413(a)(2)

This legend is the raw material for a normalized `status` — category 1 reads as generally positive, 3–7 as varying flavors of restricted/unresolved. Mapping this cleanly is the first of two hard judgment calls (Section 9).

## 3. Part A — Reference pipeline (four stages)

Each stage's output is saved to disk between stages, so any stage can be re-run alone during development.

### Stage 1 — Ingest
- Fetch the live page over HTTP. Identify with a real `User-Agent`. One page, one request — no concurrency needed.
- Save the raw HTML untouched to disk, timestamped (e.g. `data/raw/fda_ingredient_directory_2026-07-23.html`), before any parsing touches it. This is the audit trail — never parse-then-discard the original.
- Fail loudly on a non-200 response; don't silently produce an empty parse.

### Stage 2 — Parse (raw HTML → messy structured rows)
- One row per ingredient: `ingredient_name`, `synonyms` (list), `actions` (list of `{text, url, date_text}`), `category_codes` (list of ints), `date_added`.
- Handle the real messiness: multi-line `<br>` cells, italicized names, `N/A` synonyms, multiple category codes per row, non-fda.gov links.
- Output: `data/parsed/ingredients_raw.json`. Still intentionally raw — don't guess regulatory status here.

### Stage 3 — Normalize (LLM: messy → structured, confidence-scored)
This is the stage that answers "connect raw data to an LLM reasoning layer to reliably capture structured, trustworthy output."

- Per ingredient, send the raw `actions` text + `category_codes` to an LLM, asking for:
  - `normalized_status`: one of `permitted_with_claim | caution_flagged | not_a_dietary_ingredient | excluded_from_definition | safety_standard_unmet | new_ingredient_unmet_safety | premarket_notification_required`
  - `reasoning`: one sentence, grounded only in the legend + action text
  - `confidence`: 0–1
- Every output row keeps a pointer back to its source row — no black-box guesses.
- Confidence below ~0.7 → `needs_review: true`, never silently dropped or silently accepted.
- Output: `data/normalized/ingredients_normalized.json`.

### Stage 4 — Load (structured → queryable schema)
- Load into `ingredients`, `ingredient_regulatory_status` (`country_id` hardcoded to a single `US` row — single-country by design, but the column exists so the shape matches a real multi-country schema), and `extraction_staging` (pre-promotion LLM output, confidence + source pointer, kept as an audit log — also doubles as Stage 3's idempotency cache, keyed by `ingredient_name` + input hash).
- Postgres, run locally via Docker Compose. SQLAlchemy ORM models, schema managed through Alembic migrations (auto-applied on API container startup).
- This database is what Part B queries — build it before touching the app layer.

## 4. Part B — Product checker app (the website)

### Why it exists
The pipeline alone produces a database only a SQL query can read. The app makes it something a real, non-technical person can use: paste what's on a label, or photograph it, get a straight answer.

### Frontend (no login, one page)
- Next.js (App Router). Single route, no router logic needed — it's one page, mostly client components (form state, OCR, results).
- A single input area with two modes:
  - **Paste text** — free-text ingredient list (one per line or comma-separated).
  - **Upload photo** — a single image of the product's ingredient label (JPG/PNG). Text is extracted **client-side, in the browser**, using an OCR library (e.g. Tesseract.js, WASM-based) — the image itself is never uploaded to the server. Once OCR produces text, it's shown to the user in an editable text box (OCR is imperfect — let them fix obvious misreads) before being submitted through the exact same path as the "paste text" mode.
- One submit button ("Check ingredients"), one loading state (OCR running client-side has its own brief "reading label…" state before the API call even starts), one results view.
- Results view: each submitted ingredient gets a status badge (color-coded), a one-line reason, and a citation link when flagged. Ingredients not found in the database are shown explicitly as **"not in database"** — never silently omitted.
- No persistence. Nothing is saved between visits; a refresh clears everything. This is a deliberate scope decision, not a missing feature.

### Backend API
- FastAPI, added alongside the pipeline code, reading from the same DB Stage 4 builds.
- `POST /api/check` — accepts **only** `{"ingredients_text": "..."}`. There is no image upload or vision handling on the backend at all — whether the text originated from typing or from client-side OCR is invisible to the API; it only ever sees plain text. This keeps the backend simpler and means a product photo never leaves the user's browser.
  - **Split/normalize:** break the ingredient text into individual candidate names.
  - **Match, cheapest-first:** try exact match, then synonym match (against the `synonyms` already captured in Stage 2/4), then a fuzzy string match. Only fall back to an LLM disambiguation call if all three fail or are ambiguous — don't reach for the LLM as the default tool when a plain lookup works.
  - **Lookup:** for matched ingredients, join against `ingredient_regulatory_status` for status + citation.
  - **Unmatched candidates:** returned explicitly as `status: "not_in_database"`, never dropped.
- Response shape: a list of `{submitted_name, matched_ingredient, status, reasoning, citation, confidence}`, plus a short summary count (e.g. "1 flagged, 8 clear, 2 not in database").

## 5. Non-functional requirements

**Pipeline:**
- Idempotent — re-running doesn't duplicate rows; Stage 3 caches by ingredient name + input hash so it doesn't re-call the LLM for unchanged rows.
- Logged, not silent — each stage reports rows processed, rows flagged, and any parse failures (with the offending row identified).
- Config, not hardcoding — source URL, confidence threshold, and model name live in one config file.
- No secrets committed — API keys from environment variables; ship `.env.example`, never a real key.

**App layer:**
- No auth, no accounts, no cookies or session storage — every request is stateless.
- No image ever reaches the server — OCR runs client-side, so the only thing that hits `/api/check` is plain text. Nothing to persist or hoard on the backend by construction, not just by policy.
- Reasonable client-side input limits: image size cap before handing to the OCR library (e.g. 5MB), reject non-image files with a clear message, cap text length before submission.
- Explicit UI states for "not in database" and "couldn't read that photo clearly — try again or type it manually" — never a silent empty result.
- Resist scope creep — one page, one form, one results view. History, comparisons, and saved lists are a different project.

## 6. Project structure

```
ingredient-lens/
├── README.md
├── .env.example
├── docker-compose.yml            <- Postgres + api + web, full local stack
├── pyproject.toml                <- uv-managed, Python 3.11+
├── config.py                     <- URL, threshold, model name (os.environ + python-dotenv)
├── db/                            <- shared DB layer (SQLAlchemy models, session, engine)
│   ├── models.py                   <- ingredients, ingredient_regulatory_status, extraction_staging
│   ├── session.py                   <- engine/session factory
│   └── alembic/                     <- migrations (auto-applied on API container startup)
├── pipeline/                     <- Part A, batch/offline
│   ├── ingest.py                  <- Stage 1
│   ├── parse.py                   <- Stage 2
│   ├── normalize.py                <- Stage 3 (OpenAI gpt-4o-mini), cache = extraction_staging
│   └── load.py                      <- Stage 4 (DB)
├── api/                           <- Part B backend (FastAPI, Dockerized)
│   ├── Dockerfile
│   ├── main.py                     <- FastAPI app, POST /api/check (text only)
│   ├── match.py                     <- exact -> synonym -> fuzzy (rapidfuzz) -> LLM fallback
│   └── models.py                     <- request/response pydantic schemas
├── web/                            <- Part B frontend (Next.js, Dockerized)
│   ├── Dockerfile
│   ├── app/
│   │   └── page.tsx                  <- single page: input + results
│   ├── components/
│   │   ├── IngredientInput.tsx     <- text / photo toggle, editable OCR output
│   │   └── ResultsList.tsx          <- status badges, citations
│   └── utils/
│       └── ocr.ts                  <- client-side OCR (Tesseract.js), image never leaves browser
├── run_pipeline.py                  <- runs Stages 1-4 in order, on host
├── tests/                            <- pytest: parse.py fixtures, match.py tiers, API TestClient
├── .github/workflows/ci.yml           <- ruff + pytest on push
└── data/
    ├── raw/
    ├── parsed/
    ├── normalized/
    └── output/
```

## 7. Build order (incremental)

1. Stage 1 + save raw HTML — verify a real fetch works.
2. Stage 2 — parse to raw JSON; spot-check 5–10 rows by hand against the live page.
3. Stage 4's schema/tables — build this before Stage 3, so normalized output has somewhere real to land.
4. Stage 3 — LLM normalization, with confidence + review flagging.
5. Wire `run_pipeline.py` end to end against the live page.
6. API: the one and only path (`ingredients_text` → split → exact/synonym match → lookup). This is the entire backend surface — get it fully solid.
7. Frontend: text-input form wired to the endpoint.
8. Frontend: add the photo-upload mode — wire in client-side OCR (`utils/ocr.ts`), show the extracted text as editable before submitting through the same endpoint as step 7.
9. Polish the results view — badges, "not in database" state, citation links.
10. Final write-up in this README: what it does, how to run pipeline + api + web together, and the two hard calls from Section 9.

## 8. Definition of done

- [ ] `python run_pipeline.py` runs clean end to end against the live FDA page, no manual steps.
- [ ] DB contains all ~90 ingredients with `normalized_status`, `confidence`, and a link back to the source action text.
- [ ] Low-confidence rows are visibly flagged, not silently dropped or accepted.
- [ ] A user can paste an ingredient list in the browser and get a status per ingredient back — no login.
- [ ] A user can upload a label photo, see the client-side OCR result, edit it if needed, and get the same result as the text path.
- [ ] Unmatched ingredients show as "not in database," never silently dropped.
- [ ] No image is ever sent to the server, and no submitted text is persisted after the response is returned.
- [ ] Whole thing runs locally with two commands: `docker-compose up` (Postgres + API + web, migrations auto-applied), then `uv run python run_pipeline.py` once (on host) to populate the DB.
- [ ] Repo pushable to GitHub with no secrets committed.

## 9. The hard part (call this out explicitly in the final write-up)

Two judgment calls worth naming, not hiding inside the code:

1. **The FDA's 7 categories aren't a clean traffic light.** Category 1 (health claim) and category 4 (excluded from the supplement definition entirely — e.g. a drug ingredient showing up where it shouldn't) mean very different things for a market-entry decision. A naive status mapping flattens that distinction; the write-up should explain in a sentence or two how the normalization step avoids doing that.
2. **Matching a real label's ingredient names against a government database's canonical names is genuinely hard — and OCR makes it noisier still.** Labels already use inconsistent naming, abbreviations, and ordering that rarely match official nomenclature; client-side OCR adds misread characters, merged words, and stray line breaks on top of that. The deliberate call here is cheap-first matching (exact, then synonym, then fuzzy) with an LLM only as a last resort, plus letting the user see and correct the OCR text before it's ever submitted — rather than forcing a possibly-wrong match on data nobody got to check. That restraint is itself the product judgment being demonstrated, not a limitation to apologize for.

## 10. Tech stack

- Python 3.11+, managed with **uv** (`pyproject.toml`), FastAPI, `httpx`/`requests`, `beautifulsoup4`, `pydantic`
- **Postgres** via Docker Compose, **SQLAlchemy** ORM, **Alembic** migrations (auto-applied on API container startup)
- **OpenAI** (`gpt-4o-mini`) for the Stage 3 normalization pass and the optional last-resort matching fallback in `api/match.py` — no LLM call anywhere in the image path, since there is no image path on the backend
- **rapidfuzz** for the fuzzy-match tier in `api/match.py`
- **Next.js** (App Router) for the frontend, managed with **pnpm**, styled with **Tailwind CSS** — no state management library needed, no auth library
- **Tesseract.js** in the browser for the photo-upload mode — runs entirely client-side, no server round trip for the image itself
- **pytest** for backend tests (parser fixtures, matcher tiers, API `TestClient`); **ruff** for Python lint/format; **ESLint + Prettier** for the frontend
- **GitHub Actions** CI: `uv sync` → `ruff check` → `pytest` on push
- Full local stack containerized via `docker-compose.yml` (Postgres + API + web); the one-off `run_pipeline.py` batch script runs on the host against the exposed Postgres port