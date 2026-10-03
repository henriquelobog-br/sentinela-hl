"""Canonical Event provenance contracts and deterministic acceptance."""

from .gate import (
    RECOGNIZED_SCIENTIFIC_AREAS,
    accept_canonical_events,
    build_canonical_signal_record,
)
from .models import (
    CanonicalEventAcceptance,
    CanonicalEventCandidate,
    CanonicalEventRecord,
    CanonicalRejection,
    CanonicalRejectionCode,
    CanonicalSignalRecord,
    CollectorRole,
    PersistenceDisposition,
    canonical_content_hash,
    canonical_event_content_hash,
)
from .ownership import EVENT_FIELD_OWNERSHIP, FieldOwnership, automatic_event_fields

__all__ = [
    "CanonicalEventAcceptance",
    "CanonicalEventCandidate",
    "CanonicalEventRecord",
    "CanonicalRejection",
    "CanonicalRejectionCode",
    "CanonicalSignalRecord",
    "CollectorRole",
    "EVENT_FIELD_OWNERSHIP",
    "FieldOwnership",
    "PersistenceDisposition",
    "RECOGNIZED_SCIENTIFIC_AREAS",
    "accept_canonical_events",
    "automatic_event_fields",
    "build_canonical_signal_record",
    "canonical_content_hash",
    "canonical_event_content_hash",
]
