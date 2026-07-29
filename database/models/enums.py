import enum


class EntityType(enum.StrEnum):
    """Discriminator for the polymorphic `aliases`/`references` tables."""

    INGREDIENT = "ingredient"
    MANUFACTURER = "manufacturer"
    PRODUCT = "product"


class RecordStatus(enum.StrEnum):
    """Lifecycle status shared by version rows and warnings — see DATABASE_DESIGN.md Section 3."""

    ACTIVE = "active"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class ReferenceType(enum.StrEnum):
    """Open-ended: new source identifier schemes are expected as sources are added."""

    CAS = "cas"
    UNII = "unii"
    NDC = "ndc"
    SPL_SET_ID = "spl_set_id"
    OPENFDA_ID = "openfda_id"
    FDA_LABELER_CODE = "fda_labeler_code"
    DUNS = "duns"


class WarningCategory(enum.StrEnum):
    BOXED_WARNING = "boxed_warning"
    CONTRAINDICATION = "contraindication"
    PRECAUTION = "precaution"


class RecallClassification(enum.StrEnum):
    CLASS_I = "class_i"
    CLASS_II = "class_ii"
    CLASS_III = "class_iii"
    UNCLASSIFIED = "unclassified"


class RecallStatus(enum.StrEnum):
    ONGOING = "ongoing"
    COMPLETED = "completed"
    TERMINATED = "terminated"


class ProductIngredientRole(enum.StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class IngestionRunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


class ReviewStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DeadLetterStage(enum.StrEnum):
    """The pipeline stage a record was rejected at — ERROR_HANDLING.md Section 3."""

    VALIDATION = "validation"
    TRANSFORM = "transform"
    SAVE = "save"
