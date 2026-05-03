"""lacing — interval annotation system.

Standoff, interval-keyed annotations with rational time, ELAN tier
stereotypes, Allen's interval algebra, and a ``MutableMapping`` facade.

Quick start:

    >>> from lacing import RationalTime, TimeInterval, Annotation, MemoryStore
    >>> # Load a TextGrid, query overlaps, save as WebVTT — see misc/docs/.

Read ``CLAUDE.md`` and ``misc/docs/Lacing Development Roadmap.md`` for the
full story. ``.claude/skills/`` contains the rules.
"""

from lacing.allen import AllenRelation
from lacing.oplog import (
    InMemoryOpLog,
    OpLog,
    OpLogEntry,
    SqliteOpLog,
    replay as replay_oplog,
)
from lacing.quality import (
    boundary_iou,
    cohen_kappa,
    interval_iou,
    krippendorff_alpha,
)
from lacing.schema import (
    BodySchemaError,
    MigrationError,
    UnknownBodySchemaError,
    export_json_schemas,
    json_schema,
    migrate,
    register_body_schema,
    register_migration,
    validate as validate_body,
)
from lacing.model import (
    Annotation,
    AnnotationRef,
    MediaRef,
    NodeRef,
    Provenance,
    Reference,
)
from lacing.store import (
    IntervalAnnotationStore,
    MemoryStore,
    SchemaMismatchError,
    SqliteStore,
)
from lacing.tier import Tier, TierStereotype
from lacing.time import (
    DEFAULT_RATE,
    LossyTimeConversionError,
    RationalTime,
    TimeInterval,
)

__all__ = [
    # time
    "RationalTime",
    "TimeInterval",
    "DEFAULT_RATE",
    "LossyTimeConversionError",
    # tier
    "Tier",
    "TierStereotype",
    # model
    "Annotation",
    "Reference",
    "MediaRef",
    "NodeRef",
    "AnnotationRef",
    "Provenance",
    # allen
    "AllenRelation",
    # store
    "IntervalAnnotationStore",
    "MemoryStore",
    "SqliteStore",
    "SchemaMismatchError",
    # oplog
    "OpLog",
    "OpLogEntry",
    "InMemoryOpLog",
    "SqliteOpLog",
    "replay_oplog",
    # quality
    "cohen_kappa",
    "krippendorff_alpha",
    "interval_iou",
    "boundary_iou",
    # schema
    "register_body_schema",
    "register_migration",
    "json_schema",
    "export_json_schemas",
    "migrate",
    "validate_body",
    "BodySchemaError",
    "UnknownBodySchemaError",
    "MigrationError",
]
