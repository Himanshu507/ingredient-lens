from sqlalchemy.orm import Session

from database.access.versioned_repository import VersionedEntityRepository
from database.models.ingredient import Ingredient, IngredientVersion


def ingredient_repository(
    session: Session,
) -> VersionedEntityRepository[Ingredient, IngredientVersion]:
    return VersionedEntityRepository(
        session=session,
        identity_model=Ingredient,
        version_model=IngredientVersion,
        entity_id_column="ingredient_id",
        id_prefix="ING",
        id_sequence="ingredient_id_seq",
    )
