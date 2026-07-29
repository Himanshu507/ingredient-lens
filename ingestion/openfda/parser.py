from typing import Any

from ingestion.openfda.models import OpenFdaDrugLabelRecord


class OpenFdaParseError(Exception):
    """A record is too structurally malformed to even form an intermediate object.

    Distinct from validation (Brick 6): this is "we can't parse this at all,"
    not "this parsed but fails a business rule."
    """


def _first(values: list[str] | None) -> str | None:
    return values[0] if values else None


def _tuple(values: list[str] | None) -> tuple[str, ...]:
    return tuple(values) if values else ()


def parse_drug_label_record(raw: dict[str, Any]) -> OpenFdaDrugLabelRecord:
    """Parse one raw `drug/label` JSON record into a source-shaped intermediate object.

    Every field is read defensively — real openFDA records vary widely in
    which optional sections are present (see TESTING_STRATEGY.md Section 4;
    tests/golden/openfda/ holds real examples of this variation).
    """
    set_id = raw.get("set_id") or raw.get("id")
    if not set_id:
        raise OpenFdaParseError("record has neither 'set_id' nor 'id'")

    openfda_meta: dict[str, Any] = raw.get("openfda", {})

    return OpenFdaDrugLabelRecord(
        set_id=set_id,
        version=raw.get("version"),
        effective_time=raw.get("effective_time"),
        brand_name=_first(openfda_meta.get("brand_name")),
        generic_name=_first(openfda_meta.get("generic_name")),
        manufacturer_name=_first(openfda_meta.get("manufacturer_name")),
        substance_name=_tuple(openfda_meta.get("substance_name")),
        unii=_tuple(openfda_meta.get("unii")),
        product_type=_first(openfda_meta.get("product_type")),
        route=_tuple(openfda_meta.get("route")),
        active_ingredient_text=_tuple(raw.get("active_ingredient")),
        inactive_ingredient_text=_tuple(raw.get("inactive_ingredient")),
        warnings_text=_tuple(raw.get("warnings")),
        boxed_warning_text=_tuple(raw.get("boxed_warning")),
        raw=raw,
    )
