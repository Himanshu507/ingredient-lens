# DAILYMED_INGESTION.md

## Purpose of This Document

This document specifies how RIE ingests data from DailyMed. It assumes [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) as baseline and only covers what's specific to DailyMed. DailyMed is architecturally the harder of the two phase-1 sources: it distributes data as **archives of archives containing mostly things we don't want**, wrapping the one thing we do want (HL7 Structured Product Labeling XML) in several layers of packaging.

---

## 1. The Distribution Shape

DailyMed bulk downloads are structured like this:

```
dailymed_bulk_export.zip                 (large outer ZIP)
  ├── package_1.zip                       (nested ZIP, one per label/product)
  │     ├── image1.jpg                     ← discard
  │     ├── image2.jpg                     ← discard
  │     ├── insert.pdf                      ← discard
  │     └── <setid>.xml                      ← the SPL document — this is what we want
  ├── package_2.zip
  │     └── ...
  └── ... (thousands of nested ZIPs)
```

Every nested ZIP contains exactly one thing of value to us: an XML file conforming to the **HL7 Structured Product Labeling (SPL)** standard. Everything else — product images, PDF package inserts, occasionally other auxiliary files — is not modeled by RIE and is discarded.

---

## 2. Why We Discard Images, PDFs, and Other Assets

- **They are not machine-readable structured data.** RIE's entire value proposition is a canonical, queryable data model. A PDF package insert would require a separate, much less reliable OCR/document-parsing pipeline to extract anything structured from it — and the SPL XML already contains the same information (ingredients, warnings, dosage) in structured form. Parsing the PDF would be duplicating worse what the XML already gives us better.
- **They are large relative to their information density.** Images and PDFs dominate the byte size of each nested ZIP while contributing nothing to the canonical model. Extracting and storing them would multiply our storage and I/O cost for zero query value.
- **Out of scope, not forgotten.** If a future requirement needs the original package insert PDF for human display (not structured extraction), that's an additive feature — store a reference/pointer to it, not a reason to build a PDF-parsing pipeline into the ingestion core now. See [`ROADMAP.md`](./ROADMAP.md).

**The rule: ingestion only ever extracts files matching the SPL XML pattern. Every other file in every archive is skipped at the point of discovery, before extraction — not extracted and then discarded, which would waste I/O for no benefit.**

---

## 3. Automatic XML Discovery

The downloader does not assume a fixed file name or fixed archive layout — DailyMed's packaging has historically had minor structural variation across export batches. Instead, discovery works by pattern:

1. Walk the outer ZIP's entry list without extracting.
2. For each entry that is itself a ZIP (nested archive), walk *its* entry list without extracting.
3. For each entry whose name matches the expected SPL XML pattern (`.xml` extension, and — as a stronger check — content sniffed for the SPL root element/namespace once opened), mark it for extraction.
4. Anything not matching — images, PDFs, checksums, README-style metadata files occasionally included by the exporter — is skipped at the listing stage, never opened or extracted.

This pattern-based discovery, rather than a hardcoded expected filename, is what keeps ingestion resilient to the kind of minor packaging drift that a rigid "the XML is always named `X.xml` at path `Y`" assumption would break on.

---

## 4. Recursive ZIP Traversal Without Full Extraction

### The problem

A full DailyMed bulk export can be tens of gigabytes compressed, expanding to substantially more uncompressed, spread across thousands of nested ZIPs. Extracting the entire outer archive to disk before processing — the naive approach — means holding the full dataset's storage footprint twice over (compressed + uncompressed) before a single record is ingested, and means a crash 90% through extraction wastes that entire effort.

### The approach

- The outer ZIP is opened in **streaming read mode** — its central directory is read to enumerate entries, but entries are only decompressed one at a time, on demand.
- For each nested ZIP entry, its bytes are streamed directly from the outer archive into an in-memory buffer (nested ZIPs are typically small enough per-package that this is safe) or a scratch temp file for larger packages — never extracted to a permanent location on disk.
- That nested ZIP is then itself opened in streaming mode, and per Section 3, only the matching SPL XML entry within it is decompressed and handed to the parser.
- Once a package's XML has been parsed, validated, and transformed, its scratch buffer/temp file is discarded immediately — nothing from a processed package lingers past its own processing.

This means at any point in time, the ingestion process holds at most "the current nested ZIP plus the current XML document" in memory — a small, bounded footprint regardless of whether the outer archive contains 100 packages or 100,000.

### Why not just extract everything to disk first, then process

| Approach | Peak disk/memory use | Resumability | Verdict |
|---|---|---|---|
| Extract entire outer ZIP to disk, then process each file | Full dataset size, twice (compressed archive + extracted tree) | Poor — a crash after full extraction but before processing loses no work, but the extraction step itself is a large, un-checkpointed, all-or-nothing operation | Rejected |
| Stream-traverse and process one package at a time (chosen) | Bounded by one package's size | Good — checkpointing (Section 8) can resume at the package level | **Selected** |

---

## 5. XML Parsing Strategy: Targeted Extraction, Not Full Parsing

### Why we never parse the whole XML document into a full object model

SPL XML documents are verbose — deeply nested, heavily namespaced HL7 CDA-derived structure, much of which (document metadata, author signatures, boilerplate structural elements required by the HL7 standard) is irrelevant to RIE's canonical model. Fully deserializing every SPL document into a complete in-memory object tree — building the equivalent of a full DOM for every field the standard defines — does unnecessary parsing work at scale and, more importantly, **couples our extraction logic to the entire HL7 SPL schema instead of just the handful of sections we actually need.**

### The approach: XPath-targeted section extraction

Rather than a full-document deserialization, the parser:

1. Parses the XML with a standard tree parser (the documents are single-file and bounded in size, so full DOM parsing of *one document at a time* — as opposed to the whole archive — is fine; "never parse the whole XML" means never treating every element as meaningful, not avoiding a DOM library).
2. Runs **targeted XPath queries** against known SPL section codes (LOINC-coded sections are a core part of the SPL standard — e.g., specific codes identify the ingredients section, the warnings section, the dosage-and-administration section, the manufacturer/labeler section).
3. Extracts only the content under those specific section paths. Everything else in the document — sections we don't model, structural/administrative XML we don't care about — is never touched beyond the initial parse.

### Dedicated extractors, not a giant parser

Each canonical concern has its own extractor, implementing a narrow, single-purpose interface against the parsed XML tree:

- **`IngredientExtractor`** — pulls active/inactive ingredient names, quantities, and (where present) UNII/CAS identifiers from the ingredients section.
- **`WarningExtractor`** — pulls boxed warnings, contraindications, and precaution text from the warnings-related sections.
- **`ManufacturerExtractor`** — pulls labeler/manufacturer name and identifiers from the document header and establishment sections.
- **`DosageExtractor`** — pulls dosage form, strength, and administration instructions from the dosage section.
- Additional extractors (e.g., `IndicationsExtractor`, `PackagingExtractor`) are added the same way as new canonical fields are needed.

### Why extractor-based architecture beats one giant XML parser

| Approach | Description | Verdict |
|---|---|---|
| One large `parse_spl_document()` function that extracts every field RIE might ever need in one pass | Fewer files, looks simpler at first | Rejected — a single function accumulates unrelated concerns (ingredients, warnings, dosage all tangled together), is hard to unit test in isolation, and a bug fix to warning parsing risks touching code adjacent to ingredient parsing |
| One extractor class per canonical concern, each independently callable and testable (chosen) | Each extractor takes a parsed XML tree and returns one canonical fragment (e.g., a list of `Ingredient` candidates) | **Selected** — each extractor has a golden-file test suite (see [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md)) independent of the others; adding support for a new SPL section means adding a new extractor, not modifying an existing one; a malformed warnings section fails only `WarningExtractor`, not the whole document |

This mirrors the Single Responsibility principle applied at the parsing layer specifically because SPL documents are large enough, and our extraction needs narrow enough, that "one function does everything" becomes a real maintainability liability, not just a style preference.

---

## 6. Validation

Each extractor's output is validated independently before being handed to the transformer:

- `IngredientExtractor` output requires at least one ingredient with a non-empty name.
- `ManufacturerExtractor` output requires a labeler name.
- Missing or malformed required sections cause that specific extraction to be flagged invalid and dead-lettered (see [`ERROR_HANDLING.md`](./ERROR_HANDLING.md)) with the specific section and document ID recorded — but a failure in `WarningExtractor` does not block `IngredientExtractor`'s output from that same document from being valid and saved, since the two are extracted and validated independently.

---

## 7. Incremental Updates and Versioning

- DailyMed publishes both full bulk exports and incremental delta files (recently updated SPL documents) on a documented schedule; incremental ingestion uses the delta files as the primary sync mechanism, with the full bulk export used for periodic reconciliation (same rationale as openFDA — see [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md) Section 7).
- Each SPL document carries its own **SPL set ID and effective/version date** within the XML itself — this is the natural key used for idempotent upsert (see [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) Section 4) and for version comparison: if the incoming document's effective date is not newer than what we already have for that set ID, it's a no-op.
- As with all sources, an accepted change produces a new version of the canonical record; nothing is overwritten in place (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)).

---

## 8. Checkpointing and Resumable Ingestion

- Checkpoint granularity is the **nested-ZIP package**, not the outer archive and not the individual XML section. After a package's XML has been fully extracted, parsed, validated, transformed, and saved, the checkpoint store records that package's identifier (derived from its filename/SPL set ID) as complete.
- On restart, the outer archive is re-walked (walking the ZIP's directory listing is cheap and doesn't require re-downloading), but any package already marked complete in the checkpoint is skipped without re-extracting or re-parsing it — combined with idempotent upsert, this makes resumption both fast (skips completed work) and safe (re-processing a package that was only partially checkpointed is a no-op or a clean redo, never a duplicate).

---

## 9. Schema Evolution

SPL is a published HL7 standard, but real-world documents vary — different product types populate different optional sections, and the standard itself has evolved across versions.

- Extractors are written defensively against **optional sections being absent**, not just against malformed ones — an absent warnings section is a valid state for some product types, not an error.
- Extractors target **section LOINC codes**, which are stable identifiers, rather than positional XML structure (e.g., "the third `<section>` element") — this is what keeps extraction correct even as unrelated parts of a document's structure vary between SPL versions or product types.
- When DailyMed introduces a genuinely new section type we don't yet model, the safe default is: the unrecognized section is ignored (not an error), and a new dedicated extractor is added later, following the pattern in Section 5, once that section's data is needed in the canonical model. Silently-ignored-but-logged is the correct behavior for "new, not-yet-modeled" data — it is explicitly different from "expected, missing" data, which validation (Section 6) does flag.
