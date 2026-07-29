from sqlalchemy.orm import Session

from database.access.versioned_repository import VersionedEntityRepository
from database.models.manufacturer import Manufacturer, ManufacturerVersion


def manufacturer_repository(
    session: Session,
) -> VersionedEntityRepository[Manufacturer, ManufacturerVersion]:
    return VersionedEntityRepository(
        session=session,
        identity_model=Manufacturer,
        version_model=ManufacturerVersion,
        entity_id_column="manufacturer_id",
        id_prefix="MFR",
        id_sequence="manufacturer_id_seq",
    )
