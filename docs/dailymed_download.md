# DailyMed — Files to Download

Reference list for manual download, matched against what RIE's ingestion code
actually consumes (see [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md)).
Source page: https://dailymed.nlm.nih.gov/dailymed/spl-resources-all-drug-labels.cfm
(linked from the spl-resources.cfm page you found). All links below were live
on that page as of this writing — dates in daily/weekly/monthly filenames
change constantly; re-check the page before downloading, don't assume these
exact URLs stay valid.

Every file below has the same shape RIE's code already expects — an outer ZIP
containing thousands of nested per-package ZIPs, each holding one SPL XML plus
discardable images/PDFs (`ingestion/dailymed/discovery.py` walks this
generically by pattern, not by category, so nothing below needs different
code — same adapter handles all of it).

---

## 1. Full Release — Human Prescription Labels (download this first)

The core dataset: prescription drug SPL documents, which is what most of
`WarningExtractor`/`IngredientExtractor`'s test fixtures and this project's
real-data verifications have exercised. 6 parts, ~3GB each:

| Part | Size | Files | URL |
|---|---|---|---|
| 1 | 3.00 GB | 14,992 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_rx_part1.zip |
| 2 | 3.00 GB | 9,588 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_rx_part2.zip |
| 3 | 3.00 GB | 9,092 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_rx_part3.zip |
| 4 | 3.00 GB | 8,244 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_rx_part4.zip |
| 5 | 3.00 GB | 8,939 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_rx_part5.zip |
| 6 | 1.53 GB | 3,794 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_rx_part6.zip |

You don't need all 6 for dev/testing — any single part gives you thousands of
real SPL documents, plenty to exercise the full extract → validate →
transform → save path.

## 2. Full Release — Human OTC Labels

Same shape, over-the-counter products (this is where the Tylenol/acetaminophen
records used in this project's Brick 14–17 live verifications actually came
from, via openFDA rather than DailyMed, but the DailyMed OTC release covers
the same drug category). 11 parts:

| Part | Size | Files | URL |
|---|---|---|---|
| 1 | 3.00 GB | 12,139 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part1.zip |
| 2 | 3.00 GB | 8,819 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part2.zip |
| 3 | 3.00 GB | 6,066 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part3.zip |
| 4 | 3.00 GB | 6,333 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part4.zip |
| 5 | 3.00 GB | 7,150 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part5.zip |
| 6 | 3.00 GB | 7,820 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part6.zip |
| 7 | 3.00 GB | 10,447 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part7.zip |
| 8 | 3.00 GB | 7,589 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part8.zip |
| 9 | 3.00 GB | 7,838 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part9.zip |
| 10 | 3.00 GB | 8,296 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part10.zip |
| 11 | 2.68 GB | 6,366 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_human_otc_part11.zip |

## 3. Full Release — Other categories (optional, lower priority)

Same SPL structure, different product categories. Download only if your use
case needs them — nothing in this project's docs specifically calls these out
as required:

| Category | Size | Files | URL |
|---|---|---|---|
| Homeopathic | 5.50 GB | 15,997 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_homeopathic.zip |
| Animal | 1.17 GB | 3,582 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_animal.zip |
| Remainder (everything not in the above categories) | 628.91 MB | 2,505 | https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_release_remainder.zip |

## 4. Incremental updates — for keeping data current after an initial backfill

`DAILYMED_INGESTION.md` §7: "incremental ingestion uses the delta files as the
primary sync mechanism, with the full bulk export used for periodic
reconciliation." These are what you'd download on a recurring basis, not
once. **The exact filenames below are stale by the time you read this** —
DailyMed publishes a new one daily/weekly/monthly; go back to
spl-resources-all-drug-labels.cfm for the current one. Filename pattern:

- Daily: `dm_spl_daily_update_MMDDYYYY.zip` — e.g.
  https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_daily_update_07292026.zip
  (109 labels, 58.40 MB) — this is the exact pattern
  `fetch_and_parse_drug_labels`-equivalent DailyMed live verification used in
  earlier bricks of this project.
- Weekly: `dm_spl_weekly_update_MMDDYY_MMDDYY.zip` — e.g.
  https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_weekly_update_072026_072426.zip
  (982 labels, 424.99 MB)
- Monthly: `dm_spl_monthly_update_monYYYY.zip` — e.g.
  https://dailymed-data.nlm.nih.gov/public-release-files/dm_spl_monthly_update_jun2026.zip
  (4,163 labels, 1.73 GB)

## 5. Explicitly not downloaded

- **Indexing & REMS files**, **Mapping files** (SPL Set ID → other
  identifiers) — linked from spl-resources.cfm but not fetched here: nothing
  in `ingestion/dailymed/` reads these; `DAILYMED_INGESTION.md` doesn't
  reference them as an ingestion input. Cross-source identity mapping in this
  project is handled by the entity resolution layer
  (`ENTITY_RESOLUTION.md`), not a DailyMed-provided mapping file.
