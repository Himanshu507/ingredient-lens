import enum

from sqlalchemy import Enum as SAEnum


def _values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def str_enum(enum_cls: type[enum.Enum]) -> SAEnum:
    """Enum column stored as plain VARCHAR, not a native Postgres enum type.

    Reference/status vocabularies here are expected to grow as new sources and
    entity types are added (see CANONICAL_MODEL.md Section 6), and native Postgres
    enums require a non-transactional `ALTER TYPE ... ADD VALUE` to extend.
    `native_enum=False` avoids that; SQLAlchemy's `create_constraint` defaults
    to `False` too, so no CHECK constraint is added either — adding a new
    Python enum member needs no migration at all. Validation of accepted
    values happens application-side (`validate_strings=True`), not in Postgres.
    """
    return SAEnum(enum_cls, values_callable=_values, native_enum=False, validate_strings=True)
