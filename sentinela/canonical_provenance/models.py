"""Operational DTOs for canonical persistence; scientific models stay unchanged."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinela.core.models import Event
from sentinela.projection import ResearcherSignal

from .ownership import automatic_event_fields


class CollectorRole(str, Enum):
    REQUESTED = "requested"
    SUPPORTING = "supporting"


class PersistenceDisposition(str, Enum):
    INSERTED = "inserted"
    UPDATED = "updated"
    OBSERVED_EXISTING = "observed_existing"
    REJECTED = "rejected"


class CanonicalRejectionCode(str, Enum):
    MISSING_EVENT_ID = "missing_event_id"
    MISSING_TITLE = "missing_title"
    MISSING_SOURCE = "missing_source"
    MISSING_SCIENTIFIC_AREA = "missing_scientific_area"
    UNKNOWN_SCIENTIFIC_AREA = "unknown_scientific_area"
    MISSING_EVIDENCE = "missing_evidence"
    INVALID_EVIDENCE = "invalid_evidence"
    INVALID_OCCURRED_AT = "invalid_occurred_at"
    UNKNOWN_EVENT_STATUS = "unknown_event_status"
    DUPLICATE_ID_CONFLICT = "duplicate_id_conflict"
    INVALID_CANONICAL_EVENT_ID = "invalid_canonical_event_id"
    REPRESENTATIVE_NOT_CANONICAL = "representative_not_canonical"
    CONTRIBUTOR_NOT_CANONICAL = "contributor_not_canonical"


def canonical_content_hash(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def canonical_event_content_hash(event: Event) -> str:
    payload = event.model_dump(mode="json")
    return canonical_content_hash(
        {field: payload.get(field) for field in sorted(automatic_event_fields())}
    )


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CanonicalEventCandidate(_FrozenModel):
    event: Event
    collector: str = Field(min_length=1, max_length=120)
    collector_role: CollectorRole = CollectorRole.REQUESTED


class CanonicalEventRecord(_FrozenModel):
    event: Event
    collector: str = Field(min_length=1, max_length=120)
    collector_role: CollectorRole
    content_hash: str

    @field_validator("content_hash")
    @classmethod
    def _hash_format(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("content_hash must be lowercase SHA-256 hex")
        return value

    def to_rpc_item(self) -> dict[str, Any]:
        return {
            "event": self.event.model_dump(mode="json"),
            "collector": self.collector,
            "collector_role": self.collector_role.value,
            "content_hash": self.content_hash,
        }


class CanonicalRejection(_FrozenModel):
    candidate_id: str
    collector: str = Field(min_length=1, max_length=120)
    collector_role: CollectorRole
    reasons: tuple[CanonicalRejectionCode, ...]

    @field_validator("reasons")
    @classmethod
    def _nonempty_reasons(
        cls, value: tuple[CanonicalRejectionCode, ...]
    ) -> tuple[CanonicalRejectionCode, ...]:
        if not value:
            raise ValueError("rejection requires at least one reason")
        return tuple(dict.fromkeys(value))

    def to_rpc_item(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "collector": self.collector,
            "collector_role": self.collector_role.value,
            "reasons": [reason.value for reason in self.reasons],
        }


class CanonicalEventAcceptance(_FrozenModel):
    accepted: tuple[CanonicalEventRecord, ...] = ()
    rejected: tuple[CanonicalRejection, ...] = ()


class CanonicalSignalRecord(_FrozenModel):
    signal: ResearcherSignal
    representative_event_id: UUID
    contributor_event_ids: tuple[UUID, ...] = ()
    content_hash: str

    @field_validator("contributor_event_ids")
    @classmethod
    def _unique_contributors(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(dict.fromkeys(value))

    @field_validator("content_hash")
    @classmethod
    def _signal_hash_format(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("content_hash must be lowercase SHA-256 hex")
        return value

    @model_validator(mode="after")
    def _representative_matches_signal(self) -> "CanonicalSignalRecord":
        if str(self.representative_event_id) != self.signal.representative_event_id:
            raise ValueError("representative canonical Event does not match signal")
        if self.representative_event_id in self.contributor_event_ids:
            raise ValueError("representative Event cannot also be a contributor")
        return self

    def to_rpc_item(self) -> dict[str, Any]:
        return {
            "signal": self.signal.model_dump(mode="json"),
            "representative_event_id": str(self.representative_event_id),
            "contributor_event_ids": [str(item) for item in self.contributor_event_ids],
            "content_hash": self.content_hash,
        }


class CanonicalPersistenceItemResult(_FrozenModel):
    artifact_id: str
    disposition: PersistenceDisposition
    content_hash: str | None = None
    revision_id: UUID | None = None

    @model_validator(mode="after")
    def _content_matches_disposition(self) -> "CanonicalPersistenceItemResult":
        if self.disposition == PersistenceDisposition.REJECTED:
            if self.content_hash is not None:
                raise ValueError("rejected artifact cannot have content_hash")
        elif self.content_hash is None:
            raise ValueError("persisted artifact requires content_hash")
        return self


class CanonicalEventPersistenceResult(_FrozenModel):
    received: int = Field(ge=0)
    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    items: tuple[CanonicalPersistenceItemResult, ...] = ()


class CanonicalSignalPersistenceResult(_FrozenModel):
    received: int = Field(ge=0)
    persisted: int = Field(ge=0)
    items: tuple[CanonicalPersistenceItemResult, ...] = ()


class RunManifestFinal(_FrozenModel):
    run_id: UUID
    stage: Literal["events_persisted", "signals_persisted", "finalized", "failed"]
    accepted_events: int = Field(default=0, ge=0)
    rejected_events: int = Field(default=0, ge=0)
    persisted_signals: int = Field(default=0, ge=0)
    versions: dict[str, str] = Field(default_factory=dict)
    commit_ambiguous: bool = False
    error_type: str | None = Field(default=None, max_length=120)
    error_message: str | None = Field(default=None, max_length=512)


__all__ = [
    "CanonicalEventAcceptance",
    "CanonicalEventCandidate",
    "CanonicalEventPersistenceResult",
    "CanonicalEventRecord",
    "CanonicalPersistenceItemResult",
    "CanonicalRejection",
    "CanonicalRejectionCode",
    "CanonicalSignalPersistenceResult",
    "CanonicalSignalRecord",
    "CollectorRole",
    "PersistenceDisposition",
    "RunManifestFinal",
    "canonical_content_hash",
    "canonical_event_content_hash",
]
