"""Operational persistence boundary for Seismic Editorial v1."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from pydantic import BaseModel, ConfigDict, Field

from sentinela.core.models import Event
from sentinela.real_signals import RealSignalRun

from .engine import SeismicEditorialEngine
from .persistence import SeismicEditorialRecord


class SeismicEditorialOperationalError(RuntimeError):
    """Fail-closed boundary for seismic editorial operational I/O."""


class SeismicEditorialPersistenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    received: int = Field(ge=0)
    inserted: int = Field(ge=0)
    updated: int = Field(ge=0)
    unchanged: int = Field(ge=0)

    def plus(
        self, other: "SeismicEditorialPersistenceResult"
    ) -> "SeismicEditorialPersistenceResult":
        return SeismicEditorialPersistenceResult(
            received=self.received + other.received,
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            unchanged=self.unchanged + other.unchanged,
        )


_ZERO_RESULT = SeismicEditorialPersistenceResult(
    received=0,
    inserted=0,
    updated=0,
    unchanged=0,
)


def _is_usgs_seismic_event(event: Event) -> bool:
    return (
        event.id is not None
        and event.source == "USGS"
        and event.category == "earthquake_detected"
        and event.scientific_area == "seismology"
    )


def select_hourly_usgs_events(run: RealSignalRun) -> tuple[Event, ...]:
    """Select only current-run USGS Events proven persisted canonically."""
    candidates = tuple(
        event for event in run.events if _is_usgs_seismic_event(event)
    )
    if not candidates:
        return ()

    persistence = run.canonical_event_persistence
    if persistence is None:
        raise SeismicEditorialOperationalError(
            "USGS seismic Events exist without canonical persistence evidence"
        )

    persisted_ids = {
        item.artifact_id
        for item in persistence.items
        if item.disposition.value != "rejected"
    }
    candidate_ids = {str(event.id) for event in candidates}
    missing = candidate_ids - persisted_ids
    if missing:
        raise SeismicEditorialOperationalError(
            "canonical persistence evidence is incomplete for USGS seismic Events"
        )

    return candidates


class SupabaseSeismicEditorialStore:
    """Service-role adapter for the narrow seismic editorial RPC contract."""

    def __init__(
        self,
        *,
        url: str,
        service_key: str,
        client: Any | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {
            "apikey": self._service_key,
            "content-type": "application/json",
        }
        if not self._service_key.startswith("sb_secret_"):
            headers["authorization"] = f"Bearer {self._service_key}"
        return headers

    def list_events(
        self,
        *,
        limit: int = 250,
    ) -> tuple[Event, ...]:
        if not 1 <= limit <= 1000:
            raise ValueError("seismic editorial page limit must be between 1 and 1000")

        try:
            response = self._client.post(
                f"{self._url}/rest/v1/rpc/list_seismic_editorial_events",
                headers=self._headers(),
                json={"p_limit": limit},
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list):
                raise TypeError("seismic editorial event response must be a list")
            return tuple(Event.model_validate(row) for row in rows)
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status is not None else type(exc).__name__
            raise SeismicEditorialOperationalError(
                f"failed to read seismic editorial Events: {detail}"
            ) from None
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise SeismicEditorialOperationalError(
                f"invalid seismic editorial event response: {type(exc).__name__}"
            ) from None

    def persist_many(
        self,
        records: tuple[SeismicEditorialRecord, ...],
    ) -> SeismicEditorialPersistenceResult:
        if not records:
            return _ZERO_RESULT

        payload = []
        for record in records:
            content = record.content
            payload.append(
                {
                    "event_id": str(record.event_id),
                    "editorial_version": record.editorial_version,
                    "locale": record.locale,
                    "editorial_title": content.editorial_title,
                    "editorial_subtitle": content.editorial_subtitle,
                    "editorial_summary": content.editorial_summary,
                    "seo_title": content.seo_title,
                    "seo_description": content.seo_description,
                    "seo_keywords": list(content.seo_keywords),
                    "input_facts_signature": record.input_facts_signature,
                    "generated_at": record.generated_at.isoformat(),
                }
            )

        try:
            response = self._client.post(
                f"{self._url}/rest/v1/rpc/persist_seismic_editorial_batch",
                headers=self._headers(),
                json={"p_records": payload},
            )
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or len(rows) != len(records):
                raise TypeError(
                    "seismic editorial persistence response has invalid cardinality"
                )
            dispositions = [str(row["disposition"]) for row in rows]
            allowed = {"inserted", "updated", "unchanged"}
            if any(item not in allowed for item in dispositions):
                raise ValueError("unknown seismic editorial persistence disposition")
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status is not None else type(exc).__name__
            raise SeismicEditorialOperationalError(
                f"failed to persist seismic editorial content: {detail}"
            ) from None
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise SeismicEditorialOperationalError(
                f"invalid seismic editorial persistence response: {type(exc).__name__}"
            ) from None

        return SeismicEditorialPersistenceResult(
            received=len(records),
            inserted=dispositions.count("inserted"),
            updated=dispositions.count("updated"),
            unchanged=dispositions.count("unchanged"),
        )


def build_records(
    events: Iterable[Event],
    *,
    generated_at: datetime,
) -> tuple[SeismicEditorialRecord, ...]:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must include a timezone")
    generated_at = generated_at.astimezone(timezone.utc)
    engine = SeismicEditorialEngine()

    return tuple(
        SeismicEditorialRecord.from_generated_content(
            event=event,
            content=engine.build(event),
            generated_at=generated_at,
        )
        for event in events
        if _is_usgs_seismic_event(event)
    )


def generate_and_persist(
    events: Iterable[Event],
    *,
    store: SupabaseSeismicEditorialStore,
    generated_at: datetime,
) -> SeismicEditorialPersistenceResult:
    records = build_records(events, generated_at=generated_at)
    return store.persist_many(records)


__all__ = [
    "SeismicEditorialOperationalError",
    "SeismicEditorialPersistenceResult",
    "SupabaseSeismicEditorialStore",
    "build_records",
    "generate_and_persist",
    "select_hourly_usgs_events",
]
