"""Runs pipeline Stages 1-4 end to end against the live FDA page.

Run on the host (not in a container) via: uv run python run_pipeline.py
Connects to Postgres via its exposed docker-compose port.
"""
from __future__ import annotations

import logging

import config
from pipeline import ingest, load, normalize, parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_pipeline")


def main() -> None:
    log.info("Stage 1: fetching %s", config.FDA_SOURCE_URL)
    html_path = ingest.fetch_and_save()
    log.info("saved raw HTML to %s", html_path)

    log.info("Stage 2: parsing")
    rows = parse.parse_html(html_path)
    parse.save_json(rows, config.PARSED_JSON_PATH)
    log.info("parsed %d rows", len(rows))

    log.info("Stage 3: normalizing via %s", config.OPENAI_MODEL)
    normalized = normalize.normalize_rows(rows)
    normalize.save_json(normalized, config.NORMALIZED_JSON_PATH)
    flagged = sum(1 for r in normalized if r.needs_review)
    log.info("normalized %d rows, %d flagged for review", len(normalized), flagged)

    log.info("Stage 4: loading into DB")
    load.load_normalized(normalized)
    log.info("pipeline complete")


if __name__ == "__main__":
    main()
