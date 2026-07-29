import enum

from sqlalchemy import Enum as SAEnum


def _values(enum_cls: type[enum.Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def str_enum(enum_cls: type[enum.Enum]) -> SAEnum:
    """Enum column stored as VARCHAR + CHECK constraint, not a native Postgres enum type.

    Reference/status vocabularies here are expected to grow as new sources and
    entity types are added (see CANONICAL_MODEL.md Section 6), and native Postgres
    enums require a non-transactional `ALTER TYPE ... ADD VALUE` to extend — this
    trades a small amount of storage/validation efficiency for migrations that stay
    simple, reviewable `ALTER TABLE ... CHECK` changes.
    """
    return SAEnum(enum_cls, values_callable=_values, native_enum=False, validate_strings=True)
