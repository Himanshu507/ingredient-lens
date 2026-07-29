from ingestion.openfda.models import OpenFdaDrugLabelRecord


def validate_drug_label_record(record: OpenFdaDrugLabelRecord) -> list[str]:
    """Reject malformed/incomplete records before they reach transform().

    Returns a list of rejection reasons (empty means valid). Distinct from
    `parser.OpenFdaParseError`: parsing already guarantees structural
    integrity (a `set_id` exists); this checks the *business* minimum needed
    to form a usable canonical `Product` — a name and at least one ingredient
    (INGESTION_STRATEGY.md Section 7).
    """
    reasons: list[str] = []

    if not (record.brand_name or record.generic_name):
        reasons.append("missing both brand_name and generic_name (no usable product name)")

    if not record.substance_name:
        reasons.append("missing substance_name (no ingredients to attach)")

    return reasons
