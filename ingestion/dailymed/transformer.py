from dataclasses import dataclass

from database.models.enums import ProductIngredientRole, WarningCategory
from ingestion.dailymed.document_metadata import DocumentMetadata
from ingestion.dailymed.dosage_extractor import DosageCandidate
from ingestion.dailymed.manufacturer_extractor import ManufacturerCandidate
from ingestion.dailymed.models import IngredientCandidate
from ingestion.dailymed.warning_extractor import WarningCandidate

_ROLE_MAP: dict[str, ProductIngredientRole] = {
    "active": ProductIngredientRole.ACTIVE,
    "inactive": ProductIngredientRole.INACTIVE,
}
_CATEGORY_MAP: dict[str, WarningCategory] = {
    "boxed_warning": WarningCategory.BOXED_WARNING,
    "contraindication": WarningCategory.CONTRAINDICATION,
    "precaution": WarningCategory.PRECAUTION,
}


@dataclass(frozen=True)
class DailyMedCanonicalCandidate:
    """Canonical-model-shaped data derived from one SPL document's extractors.

    Plain data, not ORM objects — persistence (save()) turns this into
    `Product`/`Ingredient`/`Manufacturer`/`Warning` rows, exactly as
    `ingestion.openfda.transformer.DrugLabelCanonicalCandidate` does for
    openFDA (same shared save-path helpers, see
    `ingestion/common/canonical_save.py`).
    """

    natural_key: str
    product_name: str
    product_type: str | None
    dosage_form: str | None
    manufacturer_name: str
    ingredients: tuple[tuple[str, ProductIngredientRole], ...]
    warnings: tuple[tuple[WarningCategory, str], ...]


def transform_spl_document(
    metadata: DocumentMetadata,
    ingredients: list[IngredientCandidate],
    manufacturer: ManufacturerCandidate,
    dosage: DosageCandidate,
    warnings: list[WarningCandidate],
) -> DailyMedCanonicalCandidate:
    """Map extractor output into canonical-shaped data.

    Caller must have already run `validator.validate_spl_document` and
    confirmed no rejection reasons — this assumes a product name, at least
    one ingredient, and a manufacturer already exist.
    """
    if not metadata.product_name:
        raise ValueError("document has no product name — validate() should have rejected this")

    return DailyMedCanonicalCandidate(
        natural_key=metadata.set_id,
        product_name=metadata.product_name,
        product_type=metadata.product_type,
        dosage_form=dosage.dosage_form,
        manufacturer_name=manufacturer.name,
        ingredients=tuple((i.name, _ROLE_MAP[i.role]) for i in ingredients),
        warnings=tuple((_CATEGORY_MAP[w.category], w.text) for w in warnings),
    )
