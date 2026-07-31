# openFDA — Files to Download

Reference list for manual download, matched against what RIE's ingestion code
actually consumes (see [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md)). Not
everything on [open.fda.gov/data/downloads](https://open.fda.gov/data/downloads/)
is relevant — most of the ~30 categories there (medical devices, tobacco,
cosmetics, food, animal/vet, COVID serology, transparency letters) are outside
RIE's canonical model entirely and are not listed below.

Source of truth for these links: `https://api.fda.gov/download.json`, the same
machine-readable manifest `ingestion/openfda/bulk_manifest.py` parses. Re-run
that URL yourself before a real backfill — file names/counts change as FDA
republishes.

---

## 1. Drug Label (`drug/label`) — actively ingested, download this

This is the only openFDA endpoint the codebase currently has a full
adapter/transformer/persistence path for (`ingestion/openfda/adapter.py`,
`bulk_adapter.py`, `transformer.py`, `persistence.py`). It's what populates
`Product`, `Ingredient`, and `Warning` canonical records. Every brick's live
verification in this project used it.

261,114 records total, split into 14 partition files (gzip-compressed JSON,
`{ meta, results }` shape — the streaming parser in `bulk_adapter.py` expects
exactly this):

| Part | Size | Records | URL |
|---|---|---|---|
| 1/14 | 130.81 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0001-of-0014.json.zip |
| 2/14 | 142.08 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0002-of-0014.json.zip |
| 3/14 | 137.78 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0003-of-0014.json.zip |
| 4/14 | 136.81 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0004-of-0014.json.zip |
| 5/14 | 126.14 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0005-of-0014.json.zip |
| 6/14 | 132.45 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0006-of-0014.json.zip |
| 7/14 | 144.87 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0007-of-0014.json.zip |
| 8/14 | 135.30 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0008-of-0014.json.zip |
| 9/14 | 127.00 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0009-of-0014.json.zip |
| 10/14 | 132.97 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0010-of-0014.json.zip |
| 11/14 | 141.39 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0011-of-0014.json.zip |
| 12/14 | 133.56 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0012-of-0014.json.zip |
| 13/14 | 135.32 MB | 20,000 | https://download.open.fda.gov/drug/label/drug-label-0013-of-0014.json.zip |
| 14/14 | 5.91 MB | 1,114 | https://download.open.fda.gov/drug/label/drug-label-0014-of-0014.json.zip |

**You don't need all 14 for testing/dev.** Part 14 alone (5.91 MB, 1,114
records) is enough to exercise the full pipeline end to end. Download all 14
only for a real full backfill.

**You also don't need to download anything at all for day-to-day use.** Per
`OPENFDA_INGESTION.md` §2 ("full/backfill ingestion uses bulk downloads;
incremental ingestion uses the API"), every live verification this project
has done so far used the REST API directly
(`ingestion/openfda/adapter.py:fetch_and_parse_drug_labels`, e.g.
`search='openfda.brand_name:"Tylenol"'`) — no file download needed. Bulk
download is specifically for the *initial* backfill of the full dataset,
where paginating the live API 261,114/limit times would be slow and abusive
to a shared public API.

---

## 2. Drug Enforcement / Recalls (`drug/enforcement`) — canonical model has a slot, no adapter exists yet

17,832 records, single file:

| Size | Records | URL |
|---|---|---|
| 3.79 MB | 17,832 | https://download.open.fda.gov/drug/enforcement/drug-enforcement-0001-of-0001.json.zip |

The canonical `Recall` model (`database/models/recall.py`) exists in the
schema and `database/access/search.py` has `search_recalls()` — but **no
ingestion code reads this endpoint.** `grep -rn "enforcement" ingestion/`
returns nothing. Every `Recall` row created during this project's testing was
hand-inserted test fixture data, never a real FDA enforcement record.

Download this only if you're planning to build the enforcement adapter
(validator/transformer/persistence, mirroring `ingestion/openfda/*` for
`label`) — not useful to have sitting on disk otherwise.

---

## 3. Explicitly not downloaded

| Endpoint | Why skipped |
|---|---|
| `drug/event` (adverse events) | 20.3M records / 1,737 partition files — not referenced anywhere in `CANONICAL_MODEL.md`; no adverse-event entity in the schema |
| `drug/ndc` (NDC directory) | `ReferenceType.NDC` exists as a reference *type* on canonical entities, but no adapter parses the NDC directory bulk file itself |
| `drug/drugsfda`, `drug/orangebook`, `drug/shortages` | Not modeled by any canonical entity; out of scope per `ARCHITECTURE.md`'s "AI Reasoning Layer... never decides compliance" framing — these are approval/patent/shortage administrative datasets, not ingredient/warning/recall data |
| Medical device, food, animal/vet, cosmetics, tobacco, COVID, transparency categories | Entirely outside RIE's domain (regulatory intelligence for drug ingredients) |
