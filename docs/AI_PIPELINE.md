# AI_PIPELINE.md

## Purpose of This Document

This document specifies the AI reasoning layer: the only part of RIE allowed to call an LLM, and the part with the narrowest, most tightly-scoped mandate in the entire system. Everything in this document exists in service of one rule, stated in [`README.md`](./README.md) and repeated here because it cannot be repeated too often:

**The AI never decides compliance. It explains evidence.**

---

## 1. What the AI Layer Is and Is Not

**Is**: a retrieval-grounded explanation layer. Given a user question, it retrieves relevant canonical records (ingredients, warnings, recalls, products), and generates a natural-language answer that is explicitly and verifiably tied to those records.

**Is not**: a source of regulatory truth, a compliance decision-maker, or a system that reasons from its own training knowledge about FDA regulations. If the canonical database has no evidence relevant to a question, the correct answer is "no evidence found," not a plausible-sounding answer synthesized from the model's general knowledge.

```
Wrong:    "This product is FDA approved."
Correct:  "According to DailyMed (SPL document dated 2026-03-01), this product's
           label lists [ingredient X] as an active ingredient. According to
           openFDA enforcement records, no recall is currently associated with
           this product."
```

The AI explains. Rules — and the underlying data itself — decide. This distinction is not a tone preference; it is the load-bearing safety property of the entire system. An LLM asserting "FDA approved" is a hallucination risk with real-world consequences for a regulatory intelligence product; an LLM citing what the retrieved evidence actually says is a bounded, verifiable claim.

---

## 2. Why RAG, and Why Not Fine-Tuning or Raw Prompting

| Approach | Description | Verdict |
|---|---|---|
| Fine-tune a model on regulatory data | Bakes knowledge into model weights | Rejected — knowledge goes stale the moment the underlying data changes (and regulatory data changes constantly); no per-answer citation is possible from weights; retraining cost for every ingestion update is untenable |
| Prompt the model with general knowledge, no retrieval | Simplest to build | Rejected — the model's training data has an unknown cutoff, no guaranteed coverage of specific SPL/openFDA records, and zero ability to cite a specific canonical record; this is exactly the hallucination risk the project exists to avoid |
| Retrieval-Augmented Generation (RAG) against the canonical model (chosen) | Retrieve relevant canonical records at query time, inject them into the prompt as the only permitted evidence, generate an answer constrained to that evidence | **Selected** |

RAG is chosen specifically because it keeps the canonical database — not the model — as the system of record. Every fact the AI states is traceable to a retrieval result, and retrieval always reflects the current state of the canonical model, since it queries the live database at request time.

---

## 3. Retrieval

### What is retrieved

Retrieval never touches raw source payloads or bypasses the canonical model — it queries exactly the same canonical entities (`Ingredient`, `Product`, `Warning`, `Recall`, and their current versions) that the Search API in [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) exposes. The AI layer is a consumer of the canonical model and the search layer, architecturally downstream of both, per [`ARCHITECTURE.md`](./ARCHITECTURE.md).

### How retrieval works (phase 1)

- Phase 1 retrieval uses the same PostgreSQL full-text search described in [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) Section 9 — keyword/entity-name matching against the user's query, returning the top-N most relevant canonical records (and their attached warnings/recalls) as retrieval results.
- Each retrieval result carries its full provenance chain (the `Source` links described in [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) Section 7) — this is not optional context, it is the material the citation step (Section 5) depends on.
- Retrieval is not a single fixed pass the model has no say in. The model is given one tool, `search_evidence(query)`, and decides for itself what to search and how many times (bounded by a fixed iteration cap) before answering — see Section 4. It queries and re-ranks the same canonical model either way; the only thing the model controls is the query string, never the SQL, the schema, or which tables are touched. This exists specifically to handle a user typing a bare product/ingredient name or otherwise not phrasing a proper question — a single fixed retrieval pass on the raw input returns nothing useful in that case, since the model never gets a chance to reformulate the query itself.

### Future: semantic/vector retrieval

Deferred until phase-1 keyword retrieval's recall proves insufficient for natural-language queries that don't share vocabulary with canonical record text (e.g., a user asking about "stuff that causes drowsiness" should retrieve warnings mentioning "somnolence"). When introduced, embeddings are generated from canonical record text (never from raw source payloads, preserving the same "canonical model is the only downstream-visible shape" rule from [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md)) and stored as a derived index alongside — not inside — the canonical schema. See [`ROADMAP.md`](./ROADMAP.md).

---

## 4. Prompt Engineering

The prompt sent to the LLM is structured to make evidence-bound answering the path of least resistance, not just an instruction hoping the model complies:

- **System instructions state the constraint explicitly and specifically**: answer only using evidence returned by the `search_evidence` tool; reformulate the user's question into good search queries rather than asking the user to rephrase; if a reasonable search effort still finds nothing relevant, say so explicitly rather than filling the gap with general knowledge; every factual claim must be attributable to a specific numbered evidence item.
- **Evidence is injected as a structured, numbered block per tool call**, not prose the model has to parse loosely — each `search_evidence` call's results are returned to the model with source, version/date, and content, numbered so the model (and the post-processing step in Section 5) can refer back to "[2]" unambiguously. Numbering is stable across multiple calls in the same conversation: the same underlying record re-surfaced by a second, differently-worded search keeps the citation number it was first assigned, not a new one.
- **The user's question is kept separate from tool results** in the message structure, reducing the chance that adversarial or confusing phrasing in the question gets misread as part of the evidence.
- **No system prompt ever asks the model to determine compliance, legality, or safety judgments** — only to summarize and explain what the evidence states. Questions that implicitly ask for a compliance judgment ("is this safe to take with X") are answered by presenting the relevant evidence (interactions/warnings on record) with an explicit statement that RIE provides evidence, not medical or regulatory judgment.

---

## 5. Source Attribution and Citation

Every generated answer is post-processed, not trusted verbatim:

- The model is required (by prompt instruction, and checked programmatically) to tag each claim with the evidence item number(s) it draws from.
- A post-processing step maps those citation markers back to the actual `Source` and canonical record IDs from Section 3, and renders them as concrete, checkable references in the final response (e.g., a link/reference to the specific product version and its DailyMed SPL provenance) — not just a citation number that means nothing outside the model's own output.
- **An answer with an uncited factual claim is treated as a defect**, not an acceptable stylistic gap — see Section 7 for how this is enforced.

---

## 6. Confidence

Two distinct notions of confidence exist in this layer, and they are not conflated:

- **Retrieval confidence**: how well the retrieved evidence actually matches the user's question (a search-relevance score). Low retrieval confidence across all results is surfaced to the user as "limited relevant evidence found" rather than letting the model generate a confident-sounding answer from weak evidence.
- **Entity resolution confidence**: inherited from the underlying canonical data itself (see [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md)) — if a retrieved ingredient's identity was established via a medium-confidence fuzzy match still pending manual review, that qualifier is passed through into the evidence block and, where relevant, surfaced in the answer rather than presented with false certainty.

The AI layer does not invent its own separate "confidence score" for its answers — confidence is a property of the retrieval and the underlying data, surfaced honestly, not a number the model is asked to self-report (which models are notoriously unreliable at).

---

## 7. Hallucination Prevention

Layered defenses, because no single one is sufficient on its own:

1. **Retrieval grounding** (Section 3): the model is given real evidence to work from, reducing the need to fabricate.
2. **Prompt constraints** (Section 4): explicit instruction to decline rather than fill gaps, and to cite every claim.
3. **Post-generation citation verification** (Section 5): every claim's citation is checked against the actual evidence block; a claim with no valid citation, or a citation pointing to evidence that doesn't actually support the claim, fails validation.
4. **Answer rejection on validation failure**: an answer that fails citation verification is not shown to the user as-is — it is either regenerated with stricter constraints or replaced with an explicit "insufficient evidence" response. The system is designed to prefer "I don't have evidence for that" over an unverified claim, every time.
5. **Bounded tool access, not raw database or filesystem access.** The model has exactly one tool, `search_evidence(query: str)` — a fixed, read-only, parameterized keyword search over the canonical model (Section 3), executed by application code, never by the model directly. It cannot issue arbitrary SQL, cannot write, cannot read raw source payloads or the filesystem, and the number of tool calls per question is capped (`MAX_TOOL_ITERATIONS`) so a confused or adversarial conversation can't loop indefinitely. This is narrower than "no tool access at all," which an earlier version of this document specified — that constraint assumed a single fixed retrieval pass run before the model ever saw the question, which meant a user who didn't phrase their input as a proper question (a bare product name, for instance) got "no evidence found" even when the data had a clean answer, since the model never got a chance to reformulate the query. The residual risk this narrowing accepts is retrieval hijacking — adversarial input in the question steering what the model searches for — which is low-severity here specifically because the tool is read-only over already-public regulatory data and every resulting answer still passes through citation verification (point 3) regardless of how the evidence was gathered.

---

## 8. What the AI Layer Never Does

- Never writes to the canonical database. Retrieval is read-only; nothing about answering a question changes the system of record.
- Never accesses raw source payloads (openFDA JSON, DailyMed XML) directly — only the transformed, resolved, canonical records and their provenance metadata.
- Never asserts a compliance, safety, or legal conclusion on its own authority — it surfaces the evidence that bears on the question and lets the evidence speak.
- Never receives an evidence block containing PII or data outside the regulatory domain — the retrieval layer's scope is exactly the canonical model defined in [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md), nothing broader.

This narrow mandate is what makes the AI layer additive rather than risky: because it cannot write, cannot see raw sources, and cannot claim authority it doesn't have, the worst-case failure mode of a bad AI response is an unhelpful or overly-cautious answer — never a corrupted database or a fabricated regulatory claim presented as fact.
