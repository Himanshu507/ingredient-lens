# Regulatory Intelligence Engine (RIE)

> **Build the data engine first. AI comes later.**
>
> This project is designed to demonstrate data engineering, system architecture, AI integration, and product thinking through a production-quality regulatory intelligence platform.

---

# Vision

The goal of this project is **NOT** to build an AI chatbot.

The goal is to build a **Regulatory Intelligence Engine** capable of ingesting heterogeneous government regulatory datasets, transforming them into a canonical knowledge model, and exposing trustworthy data for AI reasoning.

Think of this as building the **engine** behind a future compliance platform.

---

# Why This Project Exists

Regulatory information is scattered across:

* Government APIs
* XML files
* PDFs
* Product labels
* Recall databases
* Scientific publications
* Safety announcements

Every source has:

* Different schemas
* Different identifiers
* Different update frequencies
* Different naming conventions
* Different quality

Today companies spend hundreds of hours manually searching these sources.

This project solves one problem:

> **How do we transform messy regulatory data into one trusted source of truth?**

---

# What We Are NOT Building

This is equally important.

We are NOT building:

* ❌ FDA approval software
* ❌ Legal compliance software
* ❌ Regulatory submission software
* ❌ Enterprise workflow management
* ❌ Document management system
* ❌ AI chatbot

Those are products built **on top of** this engine.

---

# What We ARE Building

We are building the infrastructure layer.

```
Government Sources

↓

Data Ingestion

↓

Normalization

↓

Canonical Knowledge Model

↓

Search API

↓

AI Reasoning Layer
```

Everything revolves around **data quality**.

---

# Engineering Philosophy

This project follows one rule.

> Build brick by brick.

Not module by module.

Each brick should:

* compile
* run
* be testable
* improve the system

Never leave partially completed architecture.

---

# Building Strategy

Instead of this

```
Week 1

Authentication

Week 2

Dashboard

Week 3

AI

Week 4

Database
```

We build vertically.

Every brick should extend the previous one.

```
Brick 1

Project

↓

Brick 2

Database

↓

Brick 3

One Table

↓

Brick 4

One API

↓

Brick 5

One Parser

↓

Brick 6

One Source

↓

Brick 7

Normalization

↓

Brick 8

Search

↓

Brick 9

AI
```

At every stage the project works.

---

# Golden Rule

Never build functionality without data.

Never build AI without structured data.

Never build UI without APIs.

---

# Technology Stack

Backend

* Python
* FastAPI

Database

* PostgreSQL

ORM

* SQLAlchemy

Search

* PostgreSQL Full Text Search
* Elasticsearch/OpenSearch (future)

Background Jobs

* Celery or Temporal (future)

AI

* LangGraph
* LangChain
* OpenAI / Anthropic

Storage

* S3 (future)

Testing

* Pytest

Deployment

* Docker
* Docker Compose

CI

* GitHub Actions

---

# Initial Data Sources

## Source 1

openFDA

Purpose

* recalls
* adverse events
* enforcement
* drug labels

---

## Source 2

DailyMed

Purpose

* SPL XML
* ingredients
* warnings
* dosage
* package inserts

---

# Future Sources

FDA SRS

GRAS

21 CFR

NIH

EFSA

Health Canada

FSSAI

PubMed

---

# High Level Architecture

```
                   openFDA
                      │
                      ▼
              OpenFDA Adapter
                      │
                      ▼

                 Canonical Model

                      ▲

                      │

             DailyMed Adapter

                      ▲

                      │

                 DailyMed XML

                      │

                      ▼

              Validation Layer

                      │

                      ▼

          Ingredient Normalizer

                      │

                      ▼

              Entity Resolver

                      │

                      ▼

               PostgreSQL

                      │

                      ▼

                Search API

                      │

                      ▼

               AI Reasoning
```

---

# Repository Structure

```
regulatory-intelligence-engine/

docs/

backend/

database/

ingestion/

normalization/

api/

ai/

scripts/

tests/

docker/

.github/
```

No feature folders.

Only engineering layers.

---

# Brick-by-Brick Roadmap

---

# Brick 1

Repository

Goal

Working repository.

Tasks

* initialize git
* Docker
* FastAPI
* PostgreSQL
* Makefile
* pre-commit
* Ruff
* Black
* mypy

Done when

```
docker compose up
```

starts everything successfully.

---

# Brick 2

Database

Goal

One database.

Nothing else.

Tables

```
ingredients

products

sources

aliases

warnings

recalls

ingestion_logs
```

No APIs yet.

---

# Brick 3

Database Models

Implement

* SQLAlchemy models
* Alembic
* migrations

Done when

```
alembic upgrade head
```

works.

---

# Brick 4

First API

```
GET /

GET /health
```

Nothing more.

---

# Brick 5

First Source Adapter

Only openFDA.

Tasks

* API client
* pagination
* retry
* logging
* parser

Output

Canonical Python objects.

No database yet.

---

# Brick 6

Persist Data

Save parsed data.

Pipeline

```
API

↓

Parser

↓

Database
```

Done.

---

# Brick 7

DailyMed Adapter

Repeat.

Same interface.

Different implementation.

Adapters must implement identical methods.

Example

```
fetch()

parse()

validate()

save()
```

---

# Brick 8

Canonical Model

Now both sources map here.

Never expose raw source models.

Example

```
Ingredient

Product

Warning

Recall
```

Every adapter converts to these.

---

# Brick 9

Normalization

Example

```
Vitamin C

↓

Ascorbic Acid

↓

L-Ascorbic Acid

↓

ING-000123
```

No AI.

Pure engineering.

---

# Brick 10

Deduplication

Merge

```
openFDA

Vitamin C
```

and

```
DailyMed

ASCORBIC ACID
```

into

```
One ingredient.
```

---

# Brick 11

Search

Endpoints

```
/ingredients

/products

/warnings

/recalls
```

---

# Brick 12

Search UI

Very small.

Search box.

Nothing else.

---

# Brick 13

AI Layer

Only now.

Pipeline

```
Question

↓

Retriever

↓

Context

↓

LLM

↓

Answer

↓

Evidence
```

The LLM never accesses raw government sources.

---

# Adapter Design

Every source follows identical architecture.

```
Adapter

↓

Fetcher

↓

Parser

↓

Validator

↓

Transformer

↓

Saver
```

Every adapter should be swappable.

---

# Canonical Models

Core entities

```
Ingredient

Product

Manufacturer

Warning

Recall

Source

Reference

Alias
```

Never leak source-specific fields into business logic.

---

# Entity Resolution

One of the hardest engineering problems.

Example

```
Vitamin C

Ascorbic Acid

L-Ascorbic Acid

E300
```

↓

```
One Ingredient
```

Use

* synonym dictionary
* CAS numbers
* fuzzy matching
* manual review

---

# Versioning Strategy

Never overwrite data.

Instead

```
Ingredient

Version 1

Version 2

Version 3
```

Every update becomes history.

---

# Error Handling

Every ingestion run should produce

```
Started

↓

Fetched

↓

Parsed

↓

Validated

↓

Saved

↓

Completed
```

Failures must be resumable.

---

# Logging

Every ingestion should record

* runtime
* failures
* source
* records fetched
* records inserted
* records updated
* duplicates

---

# AI Strategy

The AI never decides compliance.

It explains evidence.

Wrong

```
FDA approved.
```

Correct

```
According to DailyMed...

According to openFDA...

Evidence...
```

AI explains.

Rules decide.

---

# Engineering Principles

## Single Responsibility

Every class has one job.

---

## Adapters

Every source is isolated.

---

## Testability

Everything should be mockable.

---

## Observability

Every pipeline should produce logs.

---

## Idempotency

Running ingestion twice should not duplicate data.

---

## Reproducibility

The same input always produces the same output.

---

# Definition of Done

Every brick must satisfy:

* Working
* Tested
* Documented
* Logged
* Dockerized

If not,

it is not finished.

---

# Future Roadmap

Phase 2

* FDA SRS

Phase 3

* GRAS

Phase 4

* 21 CFR

Phase 5

* Knowledge Graph

Phase 6

* Vector Search

Phase 7

* AI Reasoning

Phase 8

* Compliance Rules

Phase 9

* Multi-country Support

---

# What This Project Demonstrates

This project is intentionally designed to showcase skills valued in modern AI-native engineering teams:

* System architecture
* Data engineering
* ETL pipeline design
* Government data ingestion
* Schema design
* Entity resolution
* Search infrastructure
* Backend engineering
* AI integration
* Production thinking
* Clean software architecture
* Incremental delivery
* Evidence-based AI systems

---

# Final Principle

> **The success of this project is not measured by how many features it has. It is measured by how trustworthy, maintainable, and extensible its data engine becomes. Every new capability should emerge naturally from a solid foundation rather than being bolted on afterwards.**
