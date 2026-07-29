from dataclasses import dataclass

from database.models.enums import WarningCategory
from ingestion.openfda.models import OpenFdaDrugLabelRecord


@dataclass(frozen=True)
class DrugLabelCanonicalCandidate:
    """Canonical-model-shaped data derived from one `OpenFdaDrugLabelRecord`.

    Plain data, not ORM objects — persistence (save()) is what turns this
    into `Product`/`Ingredient`/`Manufacturer`/`Warning` rows. `natural_key`
    (openFDA's `set_id`) is what save() uses for idempotent upsert
    (OPENFDA_INGESTION.md Section 6) — never a freshly generated ID.
    """

    natural_key: str
    product_name: str
    product_type: str | None
    manufacturer_name: str | None
    ingredient_names: tuple[str, ...]
    warnings: tuple[tuple[WarningCategory, str], ...]


def transform_drug_label_record(record: OpenFdaDrugLabelRecord) -> DrugLabelCanonicalCandidate:
    """Map a validated `OpenFdaDrugLabelRecord` into canonical-shaped data.

    Caller must have already run `validator.validate_drug_label_record` and
    confirmed no rejection reasons — this assumes a usable name and at least
    one ingredient already exist.
    """
    product_name = record.brand_name or record.generic_name
    if not product_name:
        raise ValueError("record has no usable product name — validate() should have rejected this")

    warnings: list[tuple[WarningCategory, str]] = [
        (WarningCategory.BOXED_WARNING, text) for text in record.boxed_warning_text
    ]
    warnings.extend((WarningCategory.PRECAUTION, text) for text in record.warnings_text)

    return DrugLabelCanonicalCandidate(
        natural_key=record.set_id,
        product_name=product_name,
        product_type=record.product_type,
        manufacturer_name=record.manufacturer_name,
        ingredient_names=record.substance_name,
        warnings=tuple(warnings),
    )
