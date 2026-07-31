"""Infer a field-name/type schema (no data values) from a large JSON bulk
file, streamed record-by-record via ijson -- never loads the whole file into
memory. Built for openFDA's `{meta: {...}, results: [...]}` bulk export
shape, but the array path is configurable for other JSON shapes.

Schema merges across every record, not just the first one: openFDA records
vary in which optional fields are present (TESTING_STRATEGY.md Section 4),
so a field only present on record #19,999 still needs to show up.

Usage:
    uv run python scripts/infer_json_schema.py <input.json>
    uv run python scripts/infer_json_schema.py <input.json> --output schema.json
    uv run python scripts/infer_json_schema.py <input.json> --array-key results.item
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import ijson

PROGRESS_INTERVAL = 2000


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _merge(schema: dict[str, Any], value: Any) -> None:
    """Fold one value's shape into the accumulated schema, in place.

    `schema["types"]` accumulates every type ever seen for this position
    (e.g. a field that's sometimes a string, sometimes null, across
    records). `properties`/`items` recurse the same way for objects/arrays.
    """
    schema.setdefault("types", set()).add(_type_name(value))

    if isinstance(value, dict):
        properties = schema.setdefault("properties", {})
        for key, sub_value in value.items():
            _merge(properties.setdefault(key, {}), sub_value)
    elif isinstance(value, list):
        items_schema = schema.setdefault("items", {})
        for item in value:
            _merge(items_schema, item)


def _to_serializable(schema: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"type": sorted(schema.get("types", set()))}
    if "properties" in schema:
        result["properties"] = {
            key: _to_serializable(sub_schema)
            for key, sub_schema in sorted(schema["properties"].items())
        }
    if "items" in schema:
        result["items"] = _to_serializable(schema["items"])
    return result


def infer_schema(path: Path, *, array_key: str) -> dict[str, Any]:
    schema: dict[str, Any] = {}
    count = 0
    with path.open("rb") as f:
        for record in ijson.items(f, array_key):
            _merge(schema, record)
            count += 1
            if count % PROGRESS_INTERVAL == 0:
                print(f"\r{count} records scanned", end="", file=sys.stderr)
    print(f"\rdone: {count} records scanned".ljust(40), file=sys.stderr)
    return _to_serializable(schema)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=None, help="default: <input>.schema.json")
    parser.add_argument(
        "--array-key",
        default="results.item",
        help="ijson path to the record array (default: results.item, matches openFDA bulk shape)",
    )
    args = parser.parse_args()

    schema = infer_schema(args.input, array_key=args.array_key)

    output_path = args.output or args.input.with_suffix(".schema.json")
    output_path.write_text(json.dumps(schema, indent=2))
    print(f"schema written to {output_path}")


if __name__ == "__main__":
    main()
