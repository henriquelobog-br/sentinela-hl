from __future__ import annotations

from datetime import datetime, timezone
import pytest

from sentinela.canonical_provenance.models import (
    CanonicalEventPersistenceResult,
    CanonicalPersistenceItemResult,
    PersistenceDisposition,
)
from sentinela.real_signals import RealSignalRun, RunResult
from sentinela.seismic_editorial.operational import (
    SeismicEditorialOperationalError,
    SupabaseSeismicEditorialStore,
    build_records,
    select_hourly_usgs_events,
)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payload)


def _run(event, persistence):
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    return RealSignalRun(
        collections=(),
        events=(event,),
        signals=(),
        result=RunResult(
            run_id="8162c41d-cc89-4b4d-bc5e-fac79cb73aee",
            started_at=now,
            completed_at=now,
            requested_sources=("usgs",),
            consulted_sources=("usgs",),
            supporting_sources=(),
            successful_sources=("usgs",),
            failed_sources=(),
            records_received=1,
            events_produced=1,
            signals_produced=0,
            signals_eligible=0,
            signals_persisted=0,
        ),
        canonical_event_persistence=persistence,
    )


def test_hourly_selection_requires_canonical_persistence(sarangani_event):
    with pytest.raises(SeismicEditorialOperationalError):
        select_hourly_usgs_events(_run(sarangani_event, None))


def test_hourly_selection_accepts_persisted_usgs_event(sarangani_event):
    persistence = CanonicalEventPersistenceResult(
        received=1,
        accepted=1,
        rejected=0,
        items=(
            CanonicalPersistenceItemResult(
                artifact_id=str(sarangani_event.id),
                disposition=PersistenceDisposition.INSERTED,
                content_hash="a" * 64,
            ),
        ),
    )
    assert select_hourly_usgs_events(
        _run(sarangani_event, persistence)
    ) == (sarangani_event,)


def test_build_records_is_deterministic_for_same_event(sarangani_event):
    generated_at = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    first = build_records((sarangani_event,), generated_at=generated_at)
    second = build_records((sarangani_event,), generated_at=generated_at)
    assert first == second
    assert first[0].editorial_version == "seismic-v1"
    assert first[0].locale == "pt-BR"


def test_store_persists_batch_through_rpc(sarangani_event):
    generated_at = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    record = build_records((sarangani_event,), generated_at=generated_at)[0]
    client = _Client(
        [
            {
                "item_index": 0,
                "event_id": str(sarangani_event.id),
                "disposition": "inserted",
            }
        ]
    )
    store = SupabaseSeismicEditorialStore(
        url="https://example.supabase.co",
        service_key="sb_secret_test",
        client=client,
    )
    result = store.persist_many((record,))
    assert result.inserted == 1
    assert result.updated == 0
    assert result.unchanged == 0
    url, kwargs = client.calls[0]
    assert url.endswith("/rest/v1/rpc/persist_seismic_editorial_batch")
    assert kwargs["json"]["p_records"][0]["event_id"] == str(sarangani_event.id)
    assert "authorization" not in kwargs["headers"]


def test_store_lists_pending_events_without_offset(sarangani_event):
    client = _Client([sarangani_event.model_dump(mode="json")])
    store = SupabaseSeismicEditorialStore(
        url="https://example.supabase.co",
        service_key="sb_secret_test",
        client=client,
    )

    events = store.list_events(limit=17)

    assert events == (sarangani_event,)
    url, kwargs = client.calls[0]
    assert url.endswith("/rest/v1/rpc/list_seismic_editorial_events")
    assert kwargs["json"] == {"p_limit": 17}
