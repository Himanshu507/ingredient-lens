from sqlalchemy.orm import Session

from database.access.versioned_repository import VersionedEntityRepository
from database.models.product import Product, ProductVersion


def product_repository(session: Session) -> VersionedEntityRepository[Product, ProductVersion]:
    return VersionedEntityRepository(
        session=session,
        identity_model=Product,
        version_model=ProductVersion,
        entity_id_column="product_id",
        id_prefix="PRD",
        id_sequence="product_id_seq",
    )
