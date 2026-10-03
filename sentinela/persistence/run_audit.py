"""Operational audit contracts for real-signal pipeline executions."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AUDIT_ERROR_MAX_LENGTH = 512
AuditMode = Literal["dry_run", "persist"]
AuditStatus = Literal["running", "succeeded", "partial", "failed"]
CollectorRole = Literal["requested", "supporting"]
NonNegativeInt = Annotated[int, Field(ge=0)]

_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)\b(authorization|proxy-authorization|apikey|api[_-]?key|token|"
    r"password|passwd|cookie|set-cookie|supabase_service_role_key|"
    r"[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD))\b\s*[:=]\s*"
    r"(?:Bearer\s+)?[^\s,;&]+"
)
_SENSITIVE_QUERY = re.compile(
    r"(?i)([?&](?:apikey|api[_-]?key|token|password|secret|key)=)[^&#\s]+"
)
_DSN = re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)://[^\s/@:]+:[^\s/@]+@[^\s]+")
_SAFE_ERROR_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,119}$")


def sanitize_audit_error(message: str | None) -> str | None:
    """Return bounded operational text with credential-shaped values removed."""
    if message is None:
        return None
    sanitized = _DSN.sub("[REDACTED_DSN]", str(message))
    sanitized = _CREDENTIAL_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", sanitized
    )
    sanitized = _SENSITIVE_QUERY.sub(r"\1[REDACTED]", sanitized)
    sanitized = " ".join(sanitized.split())
    return sanitized[:AUDIT_ERROR_MAX_LENGTH]


def safe_error_type(value: BaseException | str | None) -> str | None:
    """Return only a class-like identifier suitable for audit metadata."""
    if value is None:
        return None
    name = type(value).__name__ if isinstance(value, BaseException) else str(value)
    return name if _SAFE_ERROR_TYPE.fullmatch(name) else "OperationalError"


class _AuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("run_id", check_fields=False)
    @classmethod
    def _valid_run_id(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("started_at", "completed_at", check_fields=False)
    @classmethod
    def _utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("audit timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator(
        "requested_sources",
        "consulted_sources",
        "successful_sources",
        "failed_sources",
        "scientific_areas",
        check_fields=False,
    )
    @classmethod
    def _unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value if item.strip())
        return tuple(dict.fromkeys(cleaned))

    @field_validator("error_type", check_fields=False)
    @classmethod
    def _safe_error_type(cls, value: str | None) -> str | None:
        return safe_error_type(value)

    @field_validator("error_message", check_fields=False)
    @classmethod
    def _safe_error_message(cls, value: str | None) -> str | None:
        return sanitize_audit_error(value)


class PipelineRunAuditStart(_AuditModel):
    run_id: str
    initiated_by: str = Field(min_length=1, max_length=120)
    mode: AuditMode
    status: Literal["running"] = "running"
    started_at: datetime
    requested_sources: tuple[str, ...]


class CollectorRunAudit(_AuditModel):
    """One collector attempt; signals remain null when attribution is unsafe."""

    run_id: str
    collector: str = Field(min_length=1, max_length=120)
    collector_role: CollectorRole
    scientific_areas: tuple[str, ...] = ()
    status: AuditStatus
    started_at: datetime
    completed_at: datetime | None = None
    records_received: NonNegativeInt = 0
    candidates_generated: NonNegativeInt = 0
    signals_generated: NonNegativeInt | None = None
    error_type: str | None = None
    error_message: str | None = None
    attempt: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _valid_lifecycle(self) -> "CollectorRunAudit":
        if self.status == "running" and self.completed_at is not None:
            raise ValueError("running collector audit cannot be completed")
        if self.status != "running" and self.completed_at is None:
            raise ValueError("terminal collector audit requires completed_at")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self


class PipelineRunAuditFinal(_AuditModel):
    """Terminal aggregate using the existing orchestrator counter semantics.

    ``records_received`` counts requested sources only. Candidates are unique
    Events after batch deduplication. Signal counters represent projection,
    eligibility, and rows returned by the signal upsert respectively.
    """

    run_id: str
    status: Literal["succeeded", "partial", "failed"]
    started_at: datetime
    completed_at: datetime
    requested_sources: tuple[str, ...]
    consulted_sources: tuple[str, ...]
    successful_sources: tuple[str, ...]
    failed_sources: tuple[str, ...]
    records_received: NonNegativeInt = 0
    candidates_generated: NonNegativeInt = 0
    signals_generated: NonNegativeInt = 0
    signals_eligible: NonNegativeInt = 0
    signals_persisted: NonNegativeInt = 0
    error_stage: str | None = Field(default=None, max_length=80)
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def _valid_final_state(self) -> "PipelineRunAuditFinal":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.signals_persisted > self.signals_eligible:
            raise ValueError("signals_persisted cannot exceed signals_eligible")
        if len(self.successful_sources) + len(self.failed_sources) > len(
            self.consulted_sources
        ):
            raise ValueError("source outcome counts exceed consulted sources")
        return self


@runtime_checkable
class PipelineRunAuditStore(Protocol):
    """Persistence boundary for operational metadata only."""

    def create_run(self, run: PipelineRunAuditStart) -> None:
        ...

    def record_collector(self, collector: CollectorRunAudit) -> None:
        ...

    def finalize_run(self, run: PipelineRunAuditFinal) -> None:
        ...


__all__ = [
    "AUDIT_ERROR_MAX_LENGTH",
    "AuditMode",
    "AuditStatus",
    "CollectorRunAudit",
    "PipelineRunAuditFinal",
    "PipelineRunAuditStart",
    "PipelineRunAuditStore",
    "safe_error_type",
    "sanitize_audit_error",
]
