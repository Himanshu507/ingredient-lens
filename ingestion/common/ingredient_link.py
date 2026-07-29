from dataclasses import dataclass

from database.models.enums import ProductIngredientRole


@dataclass(frozen=True)
class IngredientLink:
    """One ingredient a transformer wants linked to a product version.

    `unii`, when present, is what lets entity resolution (resolution/resolver.py)
    match this ingredient against an existing canonical `Ingredient` via
    Strategy 1 (authoritative identifier) instead of falling through to name
    matching.
    """

    name: str
    role: ProductIngredientRole
    unii: str | None = None
