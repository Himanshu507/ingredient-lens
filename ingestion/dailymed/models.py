from dataclasses import dataclass
from typing import Literal

IngredientRole = Literal["active", "inactive"]


@dataclass(frozen=True)
class IngredientCandidate:
    """Source-shaped ingredient data extracted from one SPL document.

    Field names deliberately mirror SPL's own vocabulary (ingredientSubstance,
    UNII, numerator/denominator quantity) — nothing past extraction is allowed
    to know this shape exists (CANONICAL_MODEL.md Section 1); `transform()`
    (Brick 9) maps this into canonical `Ingredient`/`ProductIngredient` objects.
    """

    name: str
    role: IngredientRole
    unii: str | None
    quantity_numerator: float | None
    quantity_numerator_unit: str | None
    quantity_denominator: float | None
    quantity_denominator_unit: str | None
