# Regulatory Intelligence Engine (RIE) — Engineering Documentation

## What This Document Set Is

This `/docs` folder is the single source of truth for how the Regulatory Intelligence Engine is designed, built, and operated. It is written so that a new engineer joining the project can implement, extend, or debug any part of the system without asking a founding engineer for context. If a decision is not written down here, it is not a real decision — it is an assumption, and assumptions are how production systems rot.

This is not marketing material and not a pitch deck. It is an engineering reference. Where a design choice has real alternatives, we name them, weigh them, and say why the chosen one won. Where something is genuinely unresolved, we say so explicitly rather than papering over it with confident-sounding prose.

## The One-Sentence Version

RIE ingests heterogeneous regulatory data from official government sources (openFDA, DailyMed, and future sources), transforms it into one canonical, versioned, entity-resolved knowledge model stored in PostgreSQL, and exposes that model through a search API that an AI reasoning layer can query — but never bypass — to answer questions with cited evidence instead of hallucinated authority.

## What Is the Product

**The data engine is the product.** Not the AI. Not the UI. Not the chatbot.

An LLM wrapped around messy, unvalidated, duplicated, unversioned government data is a liability, not a feature — it will hallucinate with confidence, cite nothing, and be wrong in ways that are expensive to notice. The entire justification for this project's existence is that regulatory data is scattered, inconsistently shaped, and painful to reconcile across sources, and that reconciling it correctly — with entity resolution, versioning, provenance, and validation — is the actual hard engineering problem. The AI, when it arrives (see [`AI_PIPELINE.md`](./AI_PIPELINE.md)), is a thin, strictly-scoped reasoning layer bolted onto a foundation that does not need it to be trustworthy.

## Who This Is For

- **New engineers** onboarding onto the project who need to understand *why* the system is shaped the way it is, not just *what* the code does.
- **Reviewers** (technical or otherwise) evaluating the engineering quality and production-readiness of the design.
- **Future-us**, six months from now, who will have forgotten why we rejected the obvious-seeming alternative.

## How to Read This Documentation

Read in roughly this order if you are new:

| # | Document | What it answers |
|---|----------|------------------|
| 1 | [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md) | What rules govern every decision in this codebase? |
| 2 | [`ARCHITECTURE.md`](./ARCHITECTURE.md) | What are the system's components and how do they fit together? |
| 3 | [`INGESTION_STRATEGY.md`](./INGESTION_STRATEGY.md) | How do we pull data from external, uncooperative sources in general? |
| 4 | [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md) | How specifically do we ingest openFDA? |
| 5 | [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md) | How specifically do we ingest DailyMed SPL data? |
| 6 | [`CANONICAL_MODEL.md`](./CANONICAL_MODEL.md) | What does "clean" data look like once source noise is removed? |
| 7 | [`ENTITY_RESOLUTION.md`](./ENTITY_RESOLUTION.md) | How do we know "Vitamin C" and "Ascorbic Acid" are the same thing? |
| 8 | [`DATABASE_DESIGN.md`](./DATABASE_DESIGN.md) | How is this modeled and stored in PostgreSQL? |
| 9 | [`PIPELINE.md`](./PIPELINE.md) | How do all the moving parts connect end to end? |
| 10 | [`AI_PIPELINE.md`](./AI_PIPELINE.md) | How does the AI layer use this data without corrupting it? |
| 11 | [`ERROR_HANDLING.md`](./ERROR_HANDLING.md) | What happens when a source is down, malformed, or half-updated? |
| 12 | [`TESTING_STRATEGY.md`](./TESTING_STRATEGY.md) | How do we know any of this actually works? |
| 13 | [`OBSERVABILITY.md`](./OBSERVABILITY.md) | How do we know what the system is doing in production? |
| 14 | [`ROADMAP.md`](./ROADMAP.md) | What gets built, in what order, and why that order? |

`ARCHITECTURE.md` is the map. Everything else is a zoomed-in view of one region of that map.

## Project Goal

Build the data engine behind an AI-powered regulatory intelligence platform: ingest heterogeneous regulatory data from official government sources and transform it into one canonical knowledge model that can later power AI reasoning — safely, with provenance, and without ever letting a raw government schema leak into business logic.

This project exists to demonstrate, in a single coherent codebase, engineering competence in:

- Data engineering and ETL pipeline design
- Distributed, resumable, idempotent ingestion at scale
- AI infrastructure (retrieval-grounded, not hallucination-prone)
- Backend engineering and API design
- PostgreSQL schema and migration design
- Entity resolution and data normalization
- Production system architecture: observability, error handling, testing

## Primary Data Sources (Phase 1)

1. **openFDA** — official REST APIs and bulk download datasets covering drug labels, recalls, enforcement actions, and adverse events. See [`OPENFDA_INGESTION.md`](./OPENFDA_INGESTION.md).
2. **DailyMed** — HL7 Structured Product Labeling (SPL) XML distributed inside nested ZIP archives, covering ingredients, warnings, dosage, and manufacturer data. See [`DAILYMED_INGESTION.md`](./DAILYMED_INGESTION.md).

Additional sources (FDA SRS, GRAS, 21 CFR, NIH, EFSA, Health Canada, FSSAI, PubMed) are deferred to later phases — see [`ROADMAP.md`](./ROADMAP.md). The architecture is designed so that adding a source means writing one new adapter, not modifying the canonical model or downstream consumers.

## Engineering Philosophy in One Line

**Build brick by brick, never module by module.** Every brick compiles, runs, is tested, is deployable, and is documented before the next brick starts. See [`ENGINEERING_PRINCIPLES.md`](./ENGINEERING_PRINCIPLES.md) and [`ROADMAP.md`](./ROADMAP.md) for what this means in practice and why "build the auth module, then the dashboard module, then the AI module" is explicitly rejected in favor of vertical slices that each produce a working, if narrow, system.

## Non-Goals

Explicitly out of scope for this project, at any phase:

- FDA approval or regulatory submission software
- Legal compliance software (this system informs; it does not certify compliance)
- Enterprise workflow management
- General-purpose document management
- An AI chatbot as the primary deliverable

These are products that could be *built on top of* RIE. RIE itself is the infrastructure layer beneath them.

## Document Maintenance

Each document in this folder owns one concern and is the canonical answer for that concern. If a decision changes, the corresponding document is updated in the same pull request as the code change — documentation drift is treated as a bug, not a cleanup task for later.
