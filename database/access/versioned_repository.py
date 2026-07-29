from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import sqlalchemy as sa
from sqlalchemy.orm import Session

IdentityT = TypeVar("IdentityT")
VersionT = TypeVar("VersionT")


@dataclass
class VersionedEntityRepository(Generic[IdentityT, VersionT]):
    """Create/query logic shared by every identity+version entity pair.

    `Ingredient`/`IngredientVersion`, `Manufacturer`/`ManufacturerVersion`, and
    `Product`/`ProductVersion` all follow the same append-only version chain
    pattern (see DATABASE_DESIGN.md Section 2): a stable identity row whose
    `current_version_id` points at the latest of an immutable, numbered
    sequence of version rows. This class holds that mechanic once instead of
    three times; entity-specific fields (name, dosage_form, ...) are passed
    through as `**version_fields` and are never inspected here.

    There is deliberately no delete/retract method: soft deletes are just
    `add_version(status=RecordStatus.RETRACTED, ...)` (Section 3), and hard
    deletes are an operator-invoked exception, not a repository operation.
    """

    session: Session
    identity_model: type[IdentityT]
    version_model: type[VersionT]
    entity_id_column: str
    id_prefix: str
    id_sequence: str

    def _next_id(self) -> str:
        next_value = self.session.execute(sa.select(sa.func.nextval(self.id_sequence))).scalar_one()
        return f"{self.id_prefix}-{next_value:06d}"

    def create(self, **version_fields: Any) -> IdentityT:
        """Create a new canonical entity with its first version (version_number=1)."""
        entity_id = self._next_id()
        # `identity_model`/`version_model` are unbound TypeVars from the caller's
        # perspective; mypy can't know their constructors accept these kwargs, but
        # every identity/version model pair in database/models/ does.
        identity = self.identity_model(id=entity_id)  # type: ignore[call-arg]
        self.session.add(identity)
        self.session.flush()

        version = self.version_model(  # type: ignore[call-arg]
            **{self.entity_id_column: entity_id}, version_number=1, **version_fields
        )
        self.session.add(version)
        self.session.flush()

        identity.current_version_id = version.id  # type: ignore[attr-defined]
        self.session.flush()
        return identity

    def add_version(self, entity_id: str, **version_fields: Any) -> VersionT:
        """Append a new version to an existing entity and repoint `current_version_id`."""
        identity = self.session.get(self.identity_model, entity_id)
        if identity is None:
            raise ValueError(f"{self.identity_model.__name__} '{entity_id}' does not exist")

        last_version_number = self.session.execute(
            sa.select(sa.func.max(self.version_model.version_number)).where(  # type: ignore[attr-defined]
                getattr(self.version_model, self.entity_id_column) == entity_id
            )
        ).scalar_one()

        version = self.version_model(  # type: ignore[call-arg]
            **{self.entity_id_column: entity_id},
            version_number=last_version_number + 1,
            **version_fields,
        )
        self.session.add(version)
        self.session.flush()

        identity.current_version_id = version.id  # type: ignore[attr-defined]
        self.session.flush()
        return version

    def get_current(self, entity_id: str) -> IdentityT | None:
        """Fetch the identity row; `.current_version` gives the current state (Section 2)."""
        return self.session.get(self.identity_model, entity_id)

    def get_history(self, entity_id: str) -> list[VersionT]:
        """Fetch every version ever written for this entity, oldest first."""
        stmt = (
            sa.select(self.version_model)
            .where(getattr(self.version_model, self.entity_id_column) == entity_id)
            .order_by(self.version_model.version_number)  # type: ignore[attr-defined]
        )
        return list(self.session.execute(stmt).scalars().all())
