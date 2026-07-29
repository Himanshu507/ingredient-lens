from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OpenFdaDrugLabelRecord:
    """Source-shaped intermediate object for one openFDA `drug/label` record.

    Field names deliberately mirror openFDA's own vocabulary, not the
    canonical model's — nothing past `parse()` is allowed to know this shape
    exists (see CANONICAL_MODEL.md Section 1). `transform()` (Brick 6) is
    what maps this into `Product`/`Ingredient`/`Warning` objects.
    """

    set_id: str
    version: str | None
    effective_time: str | None
    brand_name: str | None
    generic_name: str | None
    manufacturer_name: str | None
    substance_name: tuple[str, ...]
    product_type: str | None
    route: tuple[str, ...]
    active_ingredient_text: tuple[str, ...]
    inactive_ingredient_text: tuple[str, ...]
    warnings_text: tuple[str, ...]
    boxed_warning_text: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False)
