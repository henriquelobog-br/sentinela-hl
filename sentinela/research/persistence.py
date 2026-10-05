"""RPC adapter for ResearchWork observations and canonical persistence."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from sentinela.research.models import NormalizedResearchWork, raw_payload_hash
from sentinela.research.relevance import RelevanceResult

_RPC = "persist_research_work_batch"
_MAX_BATCH_SIZE = 500
_MAX_ERROR_FIELD_LENGTH = 256
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[-_ ]?key|service[-_ ]?role|password|token)"
    r"\s*[:=]\s*(?:bearer\s+)?[^\s,;]+|bearer\s+[^\s,;]+"
)


class ResearchWorkFailureKind(str, Enum):
    DEFINITIVE_REJECTION = "definitive_rejection"
    NOT_COMMITTED = "not_committed"
    COMMIT_AMBIGUOUS = "commit_ambiguous"


class ResearchWorkStoreError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_kind: ResearchWorkFailureKind,
        status_code: int | None = None,
        postgrest_code: str | None = None,
        postgrest_message: str | None = None,
        details: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.status_code = status_code
        self.postgrest_code = postgrest_code
        self.postgrest_message = postgrest_message
        self.details = details
        self.hint = hint

    @property
    def commit_ambiguous(self) -> bool:
        return self.failure_kind == ResearchWorkFailureKind.COMMIT_AMBIGUOUS


class ResearchWorkRawObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    source_work_id: str
    fetch_run_id: UUID
    retrieved_at: datetime
    payload: dict[str, Any]
    payload_hash: str

    @field_validator("retrieved_at")
    @classmethod
    def _timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _valid_payload_hash(self) -> "ResearchWorkRawObservation":
        if not re.fullmatch(r"[0-9a-f]{64}", self.payload_hash):
            raise ValueError("payload_hash must be lowercase SHA-256")
        if raw_payload_hash(self.payload) != self.payload_hash:
            raise ValueError("payload_hash does not match payload")
        return self


class ResearchWorkRelevancePersistence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mapping_version_requested: str | None = None
    mapping_version_applied: str | None = None
    relevance_status: str
    mapped_topic_ids: tuple[str, ...] | None = None

    @field_validator("relevance_status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in {"relevant", "unmapped", "not_evaluated"}:
            raise ValueError("invalid relevance_status")
        return value


class ResearchWorkPersistenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw: ResearchWorkRawObservation
    normalized: NormalizedResearchWork | None = None
    relevance: ResearchWorkRelevancePersistence | None = None

    @model_validator(mode="after")
    def _matching_identity(self) -> "ResearchWorkPersistenceItem":
        if self.normalized is None:
            return self
        if (
            self.raw.source != self.normalized.source
            or self.raw.source_work_id != self.normalized.source_work_id
            or self.raw.payload_hash != self.normalized.raw_payload_hash
        ):
            raise ValueError("raw and normalized identities must match")
        return self

    def to_rpc_item(self) -> dict[str, Any]:
        normalized = None
        if self.normalized is not None:
            normalized = self.normalized.model_dump(mode="json", exclude={"raw_payload_hash"})
        return {
            "raw": self.raw.model_dump(mode="json"),
            "normalized": normalized,
            "relevance": self.relevance.model_dump(mode="json") if self.relevance else None,
        }


class ResearchWorkPersistenceItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    item_index: int
    source: str | None
    source_work_id: str | None
    raw_disposition: str
    canonical_disposition: str
    temporal_disposition: str
    citation_disposition: str
    relevance_status: str
    identity_conflict: bool
    research_work_id: UUID | None
    raw_record_id: UUID | None
    error_code: str | None


class ResearchWorkBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    received: int
    items: tuple[ResearchWorkPersistenceItemResult, ...]


def build_research_work_persistence_item(
    *,
    fetch_run_id: UUID,
    retrieved_at: datetime,
    raw_payload: dict[str, Any],
    work: NormalizedResearchWork,
    relevance: RelevanceResult | None = None,
) -> ResearchWorkPersistenceItem:
    persisted_relevance = None
    if relevance is not None:
        persisted_relevance = ResearchWorkRelevancePersistence(
            mapping_version_requested=relevance.mapping_version,
            mapping_version_applied=relevance.mapping_version,
            relevance_status="relevant" if relevance.relevant else "unmapped",
            mapped_topic_ids=relevance.mapped_topic_ids,
        )
    return ResearchWorkPersistenceItem(
        raw=ResearchWorkRawObservation(
            source=work.source,
            source_work_id=work.source_work_id,
            fetch_run_id=fetch_run_id,
            retrieved_at=retrieved_at,
            payload=raw_payload,
            payload_hash=work.raw_payload_hash,
        ),
        normalized=work,
        relevance=persisted_relevance,
    )


@runtime_checkable
class ResearchWorkStore(Protocol):
    def persist_many(
        self, run_id: str, items: tuple[ResearchWorkPersistenceItem, ...]
    ) -> ResearchWorkBatchResult: ...


class SupabaseResearchWorkStore:
    def __init__(
        self,
        *,
        url: str | None = None,
        service_key: str | None = None,
        client: Any | None = None,
        timeout: float = 10.0,
    ) -> None:
        if url is None or service_key is None:
            from sentinela.core.config import get_settings

            settings = get_settings()
            url = url if url is not None else settings.supabase_url
            service_key = service_key if service_key is not None else settings.supabase_service_key
        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def persist_many(
        self, run_id: str, items: tuple[ResearchWorkPersistenceItem, ...]
    ) -> ResearchWorkBatchResult:
        canonical_run_id = str(UUID(run_id))
        if len(items) > _MAX_BATCH_SIZE:
            raise ValueError("research work batch exceeds 500 items")
        if not items:
            return ResearchWorkBatchResult(received=0, items=())
        rows = self._rpc({
            "p_run_id": canonical_run_id,
            "p_items": [item.to_rpc_item() for item in items],
        })
        try:
            parsed = tuple(ResearchWorkPersistenceItemResult.model_validate(row) for row in rows)
            if len(parsed) != len(items):
                raise ValueError("RPC result count mismatch")
            if tuple(item.item_index for item in parsed) != tuple(range(1, len(items) + 1)):
                raise ValueError("RPC item indexes are invalid")
        except (TypeError, ValueError) as exc:
            raise ResearchWorkStoreError(
                f"research work RPC response invalid: {type(exc).__name__}; rpc={_RPC}",
                failure_kind=ResearchWorkFailureKind.COMMIT_AMBIGUOUS,
            ) from None
        return ResearchWorkBatchResult(received=len(items), items=parsed)

    def _rpc(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            response = self._client.post(
                f"{self._url}/rest/v1/rpc/{_RPC}",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, list) or not all(isinstance(row, dict) for row in body):
                raise TypeError("RPC response must be a list of objects")
            return body
        except httpx.HTTPStatusError as exc:
            fields = self._postgrest_error_fields(exc.response)
            status = exc.response.status_code
            kind = (
                ResearchWorkFailureKind.DEFINITIVE_REJECTION
                if 400 <= status < 500
                else ResearchWorkFailureKind.COMMIT_AMBIGUOUS
            )
            details = "; ".join(
                f"{key}={value}" for key, value in fields.items() if value is not None
            )
            suffix = f"; {details}" if details else ""
            raise ResearchWorkStoreError(
                f"research work RPC failed: HTTP {status}; rpc={_RPC}{suffix}",
                failure_kind=kind,
                status_code=status,
                postgrest_code=fields["code"],
                postgrest_message=fields["message"],
                details=fields["details"],
                hint=fields["hint"],
            ) from None
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise ResearchWorkStoreError(
                f"research work RPC not sent: {type(exc).__name__}; rpc={_RPC}",
                failure_kind=ResearchWorkFailureKind.NOT_COMMITTED,
            ) from None
        except httpx.HTTPError as exc:
            raise ResearchWorkStoreError(
                f"research work RPC outcome unknown: {type(exc).__name__}; rpc={_RPC}",
                failure_kind=ResearchWorkFailureKind.COMMIT_AMBIGUOUS,
            ) from None
        except (TypeError, ValueError, AttributeError) as exc:
            raise ResearchWorkStoreError(
                f"research work RPC response invalid: {type(exc).__name__}; rpc={_RPC}",
                failure_kind=ResearchWorkFailureKind.COMMIT_AMBIGUOUS,
            ) from None

    def _headers(self) -> dict[str, str]:
        headers = {"apikey": self._service_key, "content-type": "application/json"}
        if not self._service_key.startswith("sb_secret_"):
            headers["authorization"] = f"Bearer {self._service_key}"
        return headers

    def _postgrest_error_fields(self, response: Any) -> dict[str, str | None]:
        try:
            body = response.json()
        except (ValueError, TypeError, AttributeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        return {
            field: self._sanitize_error_field(body.get(field))
            for field in ("code", "message", "details", "hint")
        }

    def _sanitize_error_field(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        sanitized = value.replace(self._service_key, "<redacted>")
        sanitized = _SECRET_PATTERN.sub(
            lambda match: f"{match.group(1) or 'credential'}=<redacted>", sanitized
        )
        return " ".join(sanitized.split())[:_MAX_ERROR_FIELD_LENGTH] or None
