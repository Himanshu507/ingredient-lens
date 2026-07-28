# CANONICAL_MODEL.md

## Purpose of This Document

This document defines RIE's canonical data model — the single, source-agnostic representation that every adapter transforms into, and the only representation that anything downstream of ingestion (normalization, entity resolution, the API, the AI layer) is allowed to know about. This is a conceptual/entity-relationship document; the physical PostgreSQL schema (columns, types, indexes) lives in [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md).

---

## 1. Why Raw Government Schemas Must Never Leak Into Business Logic

### The problem this guards against

openFDA's JSON shape and DailyMed's SPL XML shape have almost nothing in common — different field names, different nesting, different identifier schemes, different units, different optionality rules. If downstream code (the API, the AI layer, the entity resolver) had to know about both shapes to do its job, every one of those layers would need source-specific branching logic. Worse: adding a third source would mean touching every downstream layer again, and a field rename in openFDA's API would ripple all the way to the API response your users see.

### The rule

**Nothing outside the `transform()` step of an adapter (see [`ARCHITECTURE.md`](./ARCHITECTURE.md) Section 2) is allowed to reference a source-specific field name, source-specific identifier scheme, or source-specific structure.** The canonical model is the contract. Adapters translate into it; nothing else translates out of source formats.

### Why this is worth the upfront cost

Defining a canonical model before you have three sources feels like premature abstraction — but it isn't, because the alternative isn't "no abstraction," it's "the abstraction leaks into every downstream consumer instead of living in one place." The cost of getting this wrong doesn't show up on day one; it shows up on the day a second source needs to populate the same conceptual entity (an `Ingredient` from both openFDA and DailyMed) and the codebase has no single place that means "ingredient" — it has an openFDA-shaped ingredient and a DailyMed-shaped ingredient, and every downstream consumer has to know about both.

### What "raw" data is kept, and where

We do not discard the original source payload — provenance and auditability require keeping it (Section 8). What we forbid is *business logic depending on its shape*. The raw payload is archived as an opaque reference attached to a `Source` record (Section 7); the canonical entity built from it is what everything else operates on.

---

## 2. Design Principles for the Canonical Model

- **Source-agnostic naming.** Field and entity names describe the real-world concept (`Ingredient.name`), never a source's field name (`substanceName`, `active_moiety`, etc.).
- **Every canonical fact is attributable.** A canonical record doesn't just say "this ingredient's name is X" — it says "this ingredient's name is X, according to source Y, as of version Z." See Section 8.
- **Union of needs, not union of fields.** The canonical model contains what RIE's use cases actually need across sources, not a superset of every field every source happens to expose. Fields are added when a real consumer needs them (see [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md) on YAGNI), not speculatively.
- **Stable identifiers are internal, not borrowed.** Canonical entities are identified by RIE-generated IDs (e.g., `ING-000123`). Source-provided identifiers (UNII, `set_id`, NDC codes) are stored as *references* to the canonical entity, not used as the canonical entity's primary identity — because no single source's identifier scheme is guaranteed to exist for every source, and the same canonical entity may need multiple source identifiers attached simultaneously (Section 6, `Reference`).

---

## 3. Core Entities

### `Ingredient`

The atomic substance-level concept — e.g., "Ascorbic Acid." This is the entity that entity resolution (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)) works hardest on, since the same real-world ingredient arrives from different sources under different names.

Conceptual attributes: canonical name, normalized name (for matching), ingredient type (active/inactive — contextual to a given product relationship, see `Product`), unit of measurement conventions, and links to `Alias` and `Reference` records.

### `Product`

A specific marketed product/label — e.g., a particular manufacturer's formulation of a drug or supplement. A `Product` is composed of one or more `Ingredient`s (with quantities), has one or more `Manufacturer`s, and is the entity that `Warning`s, `Recall`s, and dosage information attach to.

Conceptual attributes: product name, product type, dosage form, associated ingredients (with role: active/inactive, and quantity), associated manufacturer(s).

### `Manufacturer`

The legal entity responsible for producing or labeling a `Product`. Kept as its own entity (rather than a string field on `Product`) because the same manufacturer appears across many products and across both source systems under name variants that also need resolution (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) — manufacturer name resolution follows the same pattern as ingredient resolution, at smaller scale).

Conceptual attributes: canonical name, known aliases, registered identifiers (e.g., FDA labeler code) captured via `Reference`.

### `Warning`

A safety-relevant statement attached to a `Product` — boxed warnings, contraindications, precautions. Kept as a distinct entity (not a text blob on `Product`) because warnings have their own lifecycle (they can be added, strengthened, or removed independent of the rest of the label) and because the AI reasoning layer needs to cite specific warnings as discrete pieces of evidence (see [`AI_PIPELINE.md`](./AI_PIPELINE.md)).

Conceptual attributes: warning text, warning category (boxed warning / contraindication / precaution), the `Product` it applies to, source and version provenance.

### `Recall`

A regulatory recall action against a `Product` or `Manufacturer`. Distinct from `Warning` — a recall is a discrete regulatory event with a status and reason, not a standing label statement.

Conceptual attributes: recall reason, classification/severity, status (ongoing/completed/terminated), affected product(s), initiating source, dates.

### `Reference`

A typed pointer from a canonical entity to an external identifier or external document — a UNII code, a CAS number, an NDC code, a DailyMed `set_id`, an openFDA `recall_number`. This is the mechanism that lets a canonical `Ingredient` simultaneously "know about" its openFDA identity and its DailyMed identity without either one being treated as *the* identity.

Conceptual attributes: reference type (enum: CAS, UNII, NDC, SPL set ID, openFDA ID, etc.), reference value, the canonical entity it points from, the `Source` it came from.

### `Alias`

A known alternate name for an `Ingredient` or `Manufacturer` — "Vitamin C" as an alias of canonical `Ingredient` "Ascorbic Acid." Aliases are what the entity resolver matches incoming source names against (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)), and what search matches user queries against.

Conceptual attributes: alias text, normalized alias text, the canonical entity it resolves to, confidence (aliases learned via fuzzy matching carry a confidence score; aliases from an authoritative synonym dictionary do not need one).

### `Source`

The record of *where* a fact came from — which government system, which endpoint/dataset, which fetch run, and (critically) a reference to the archived raw payload that produced this canonical fact. Every canonical entity version links back to the `Source` record(s) that justify it.

Conceptual attributes: source system name (openFDA / DailyMed / future), endpoint or document type, fetch/ingestion run ID, raw payload reference, ingestion timestamp.

---

## 4. Relationships Between Entities

```
Manufacturer 1───* Product *───* Ingredient
                     │
                     ├──* Warning
                     │
                     └──* Recall

Ingredient 1───* Alias
Manufacturer 1───* Alias

Ingredient 1───* Reference
Manufacturer 1───* Reference
Product 1───* Reference

Every entity version ──* Source
```

- `Product` ↔ `Ingredient` is many-to-many (a product has multiple ingredients; an ingredient appears in multiple products), carrying relationship attributes (role: active/inactive, quantity) — this is a join entity in the physical schema (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)), not a simple foreign key.
- `Warning` and `Recall` both attach to `Product` (not directly to `Ingredient`) — a warning is about a specific marketed product's label, not about the substance in the abstract, even though the underlying safety concern is often ingredient-driven.
- `Alias` and `Reference` both attach to whichever entity type needs them (`Ingredient`, `Manufacturer`, and — for `Reference` — `Product`), rather than being hardcoded to a single entity type.

---

## 5. What the Canonical Model Deliberately Excludes

- **No embedded raw source structure.** No JSON blob of "the original openFDA record" living inside `Product`. That belongs in `Source`'s raw payload reference, not the canonical entity itself.
- **No source-specific enums leaking through.** E.g., openFDA's recall classification codes and any future source's equivalent are mapped to one canonical `Recall.classification` enum at transform time, not stored as source-specific raw strings on the canonical entity.
- **No AI-specific fields.** Confidence scores, embeddings, or retrieval metadata used by the AI layer (see [`AI_PIPELINE.md`](./AI_PIPELINE.md)) are not part of the canonical model — they're derived artifacts that live alongside it, not fields on `Ingredient` or `Product` themselves. This keeps the canonical model meaningful independent of whether the AI layer exists at all.

---

## 6. Multiple Identifiers, One Entity

A canonical `Ingredient` for ascorbic acid may simultaneously have:

- A `Reference` of type `UNII` from openFDA
- A `Reference` of type `CAS` from a synonym dictionary
- A `Reference` of type `DailyMed_SubstanceName` from DailyMed
- `Alias` records for "Vitamin C," "L-Ascorbic Acid," and "E300"

None of these is *the* identifier. The canonical `Ingredient.id` (an internally generated ID, e.g. `ING-000123`) is the only thing anything downstream treats as identity. This is precisely what makes entity resolution (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)) a well-defined problem: it doesn't have to pick a "winning" source identifier scheme — it just has to correctly attach references and aliases to the right internal ID.

---

## 7. Provenance and the `Source` Entity

Every version of every canonical entity (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) for the versioning schema) is linked to the `Source` record that produced it. This is not optional metadata — it is the mechanism that makes two things possible:

1. **Auditability**: for any fact in the system, "why do we believe this" resolves to a specific source system, endpoint, fetch run, and archived raw payload — not "the database says so."
2. **AI grounding**: the AI reasoning layer's citations (see [`AI_PIPELINE.md`](./AI_PIPELINE.md)) are generated directly from `Source` links on the canonical records it retrieves — a citation is never fabricated text, it's a pointer to a real, stored provenance chain.

---

## 8. Canonical Model Is a Contract, Not a Suggestion

Changes to the canonical model (adding a field, adding an entity, changing a relationship) are treated as schema changes with the same rigor as a database migration (see [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md)) — because that's what they are. Every adapter's `transform()` step, the normalizer, the entity resolver, the API layer, and the AI layer all depend on this model's shape being stable and intentional, not incidentally whatever shape the most recently added source happened to produce.
