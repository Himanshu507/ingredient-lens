# ENTITY_RESOLUTION.md

## Purpose of This Document

Entity resolution is the hardest engineering problem in this system, and this document treats it that way. The problem: openFDA says `Vitamin C`, DailyMed says `ASCORBIC ACID`, a third source might say `L-Ascorbic Acid` or the E-number `E300` — and these are, chemically and practically, the same ingredient. RIE must recognize that, merge the records into one canonical `Ingredient`, and do so without ever silently merging two things that are actually different (e.g., "Vitamin B12" and "Vitamin B6" must never collapse into one entity because a fuzzy matcher got overzealous).

This document covers ingredient resolution in depth; the same architecture applies, at smaller scale, to manufacturer resolution (Section 8).

---

## 1. Why This Is Hard

- **No universal identifier.** Not every source provides a CAS number or UNII for every ingredient. When they do, they don't always agree on format (leading zeros, hyphenation).
- **Naming is inconsistent by nature, not by error.** "Vitamin C" and "Ascorbic Acid" are both *correct* names for the same substance — one common, one chemical. There is no typo to fix; there is a synonym relationship to know.
- **Fuzzy matching is a double-edged tool.** String-similarity matching that's loose enough to catch "Acetaminophen" vs "Paracetamol" (same substance, genuinely different names — not even similar strings) will also be loose enough to risk conflating distinct substances with similar names. Precision and recall trade off directly against each other here, and the cost of a false merge (silently telling a user two different substances are the same) is much higher than the cost of a false split (two records that should merge, sitting unmerged a bit longer).
- **The stakes are asymmetric.** This is a *regulatory* platform. An incorrect ingredient merge could mean a warning attached to the wrong substance. The system is deliberately biased toward under-merging with a manual review safety net, never toward aggressive auto-merging.

---

## 2. Resolution Pipeline

Every incoming canonical `Ingredient` candidate (produced by an adapter's `transform()` step, per [`ARCHITECTURE.md`](./ARCHITECTURE.md)) goes through a strictly ordered sequence of matching strategies, from highest-confidence to lowest. The pipeline stops at the first strategy that produces a confident match; it only falls through to a lower-confidence strategy if the higher ones find nothing.

```
Incoming ingredient candidate
        │
        ▼
1. Normalize (Section 3)
        │
        ▼
2. Exact match on authoritative identifier (CAS / UNII)   → match found? merge, done.
        │  (no match)
        ▼
3. Exact match on normalized name / known alias            → match found? merge, done.
        │  (no match)
        ▼
4. Fuzzy match against existing canonical ingredients        → high confidence? merge, done.
        │                                                       medium confidence? → manual review queue
        │  (no match at all)
        ▼
5. Create new canonical Ingredient
```

This ordering is deliberate: **structured identifiers beat name matching, and exact name matching beats fuzzy matching.** Reaching for fuzzy string similarity first would be reaching for the least reliable tool before exhausting the reliable ones.

---

## 3. Normalization (Pre-Matching)

Before any matching happens, every incoming name is normalized — this is a separate, simpler concern from resolution itself, handled by the `normalization/` layer (see [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 4):

- Case-folding (lowercase for matching purposes; display case is preserved separately)
- Whitespace collapsing and trimming
- Punctuation normalization (hyphens, periods, parenthetical qualifiers handled consistently)
- Unit and salt-form suffix handling where relevant (e.g., recognizing that a quantity/form qualifier is separate from the substance name itself)

Normalization is deterministic and source-agnostic — it never consults the database and never makes a "same or different" judgment. It only produces a canonical string representation that matching (Sections 4–6) operates on. This separation is what keeps normalization trivially unit-testable in isolation (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)).

---

## 4. Strategy 1: Authoritative Identifier Match

If the incoming record carries a structured identifier — a CAS number or UNII code, captured as a `Reference` candidate (see [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) Section 6) — this is checked first against existing `references` rows of the same type.

- An exact match on a CAS number or UNII is treated as **definitive** — these identifiers are assigned by authoritative bodies specifically to disambiguate substances, and are the strongest signal available. No confidence score is needed; this is a certain match.
- This is why the canonical model captures `Reference` as a first-class, typed, multi-valued concept (Section 6 of [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md)) rather than a single "external ID" field — it's what makes this the primary matching strategy rather than a fallback.

---

## 5. Strategy 2: Exact Name / Known Alias Match

If no authoritative identifier match is found (or the incoming record doesn't carry one), the normalized name is checked against:

- Existing canonical ingredients' normalized names, and
- The `aliases` table (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)) — which includes both names learned from prior fuzzy-match resolutions (Section 6) and entries from a curated synonym dictionary seeded from public chemical/pharmaceutical naming references.

An exact match here (post-normalization) is treated as high-confidence and merges automatically. This is the mechanism that correctly and immediately resolves "Vitamin C" to "Ascorbic Acid" *after* that synonym relationship has been established once — either by the curated dictionary or by a prior manual review decision (Section 7) — without needing fuzzy matching to rediscover it every time.

---

## 6. Strategy 3: Fuzzy Matching

Only reached when no authoritative identifier and no exact name/alias match exists.

### Method

- Candidate generation uses trigram similarity (PostgreSQL's `pg_trgm` extension) against existing canonical ingredient names and aliases, to cheaply narrow the space down from "every ingredient in the database" to a small set of plausible candidates.
- Those candidates are then scored with a string-similarity metric (e.g., normalized edit distance / token-based similarity) to produce a **confidence score** between 0 and 1.

### Confidence thresholds

| Confidence range | Action |
|---|---|
| Above high threshold (e.g., ≥ 0.92) | Auto-merge, and record the matched alias so future exact-match lookups (Section 5) catch it immediately without repeating fuzzy matching |
| Between medium and high threshold (e.g., 0.75–0.92) | Route to manual review queue (Section 7) — plausible but not certain |
| Below medium threshold | Treated as no match — a new canonical ingredient is created |

The exact threshold values are a tuned parameter, not an architectural commitment — they are expected to be adjusted based on observed false-positive/false-negative rates from the manual review queue (Section 7 doubles as a feedback and calibration mechanism for these thresholds).

### Why thresholds, and why manual review exists at all

A single hard cutoff ("similarity > 0.8 = same ingredient") either merges too aggressively (false positives, the dangerous failure mode — see Section 1) or misses too many legitimate matches (false negatives, an annoying but safe failure mode, since it just means a duplicate sits unmerged temporarily). A three-tier system — confident auto-merge, uncertain manual review, confident non-match — is what lets the system be safe by default (nothing merges without either certainty or a human) while still automating the clear-cut majority of cases.

---

## 7. Manual Review Queue

- Medium-confidence candidates are written to the `entity_resolution_reviews` table (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)) with both candidate records, the computed confidence score, and enough context (source, original name strings) for a human reviewer to make a fast, correct call.
- Until reviewed, **the incoming record is provisionally created as its own separate canonical entity** — it is never left "unpersisted and pending" (which would mean queries against the system are silently incomplete). This means a reviewer's job is specifically "approve this merge" (which then combines two existing canonical entities and re-points their references/aliases) rather than "approve this record's creation."
- A reviewer's decision (approve-merge or reject-as-distinct) is recorded and, on approval, the resulting alias relationship is written back into the `aliases` table — so the *same* pair of names is never re-queued for manual review again. This is what makes the review queue shrink over time relative to ingestion volume rather than grow linearly with it.
- Review queue age and volume are tracked as operational metrics (see [`OBSERVABILITY.md`](./OBSERVABILITY.md)) — a growing backlog is a signal that either thresholds need tuning or that review throughput needs attention.

---

## 8. Manufacturer Resolution

Manufacturer names follow the identical three-strategy pipeline (authoritative identifier → exact/alias → fuzzy match with manual review), using FDA labeler codes as the authoritative identifier where available in place of CAS/UNII. The scale is smaller (far fewer distinct manufacturers than ingredients), but the architecture is deliberately not special-cased — reusing the same resolver logic, parameterized by entity type, keeps the system from accumulating a second, subtly different resolution implementation.

---

## 9. Deduplication and Merge Semantics

Once two candidate records are determined to represent the same real-world entity (by any strategy above), the merge operation:

1. Selects (or confirms) the surviving canonical entity ID — for a brand-new fuzzy-match merge, this is the pre-existing canonical entity; incoming data never displaces an established canonical ID.
2. Attaches the incoming record's `Reference`s and any new `Alias` to the surviving canonical entity — references and aliases accumulate, they are never overwritten or discarded.
3. Creates a new version of the canonical entity if the incoming data contributes new or changed field values (per the versioning rules in [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)), preserving the `Source` link for the new information.
4. Never deletes or discards the losing side's provenance — a merge is additive to the surviving entity's history, not a destructive replace.

This is the concrete mechanism behind the example in the project's founding vision: openFDA's "Vitamin C" and DailyMed's "ASCORBIC ACID" become one canonical `Ingredient` record that can honestly say "known from both openFDA and DailyMed, under these names, as of these dates" — not a record that silently forgot one of its two source identities.
