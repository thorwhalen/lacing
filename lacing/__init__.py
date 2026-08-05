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
from lacing.otel import (
    get_tracer,
    instrument_app as instrument_otel,
    is_otel_active,
    maybe_span,
    traced,
)
from lacing.processors import (
    ProcessorError,
    register_processor,
    registered_processors,
    run_async as run_processor_async,
    run_sync as run_processor_sync,
)
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
from lacing.artifact import (
    Artifact,
    ArtifactKind,
    hash_bytes,
    hash_file,
)
from lacing.artifact_store import ArtifactStore
from lacing.digest import (
    annotation_body_digest,
    annotation_value_digest,
)
from lacing.store import (
    IntervalAnnotationStore,
    MemoryStore,
    SchemaMismatchError,
    SqliteStore,
)
from lacing.exhibit import render_artifact_exhibit
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
    # artifact
    "Artifact",
    "ArtifactKind",
    "ArtifactStore",
    "hash_bytes",
    "hash_file",
    # digest — three digests, three jobs; see lacing/digest.py's docstring.
    # (hash_bytes/hash_file address artifact BYTES; annotation_etag, under
    # lacing.server, is the If-Match concurrency digest over the WHOLE
    # annotation; these two address an annotation's VALUE, for freshness.)
    "annotation_value_digest",
    "annotation_body_digest",
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
    # processors
    "ProcessorError",
    "register_processor",
    "registered_processors",
    "run_processor_async",
    "run_processor_sync",
    # otel (no-op fallback when otel is not installed)
    "get_tracer",
    "maybe_span",
    "traced",
    "instrument_otel",
    "is_otel_active",
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
    "render_artifact_exhibit",
    "migrate",
    "validate_body",
    "BodySchemaError",
    "UnknownBodySchemaError",
    "MigrationError",
]
