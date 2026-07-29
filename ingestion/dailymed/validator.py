from ingestion.dailymed.document_metadata import DocumentMetadata
from ingestion.dailymed.manufacturer_extractor import ManufacturerCandidate
from ingestion.dailymed.models import IngredientCandidate


def validate_spl_document(
    metadata: DocumentMetadata,
    ingredients: list[IngredientCandidate],
    manufacturer: ManufacturerCandidate | None,
) -> list[str]:
    """Reject malformed/incomplete SPL documents before transform().

    Per DAILYMED_INGESTION.md Section 6: ingredient extraction requires at
    least one ingredient, manufacturer extraction requires a labeler name.
    A missing warnings/dosage section is *not* checked here — those are
    legitimately optional (Section 9).
    """
    reasons: list[str] = []

    if not metadata.product_name:
        reasons.append("missing product name")

    if not ingredients:
        reasons.append("missing ingredients (no ingredients section, or none had a name)")

    if manufacturer is None:
        reasons.append("missing manufacturer/labeler name")

    return reasons
