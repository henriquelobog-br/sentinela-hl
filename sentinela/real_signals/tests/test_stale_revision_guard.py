from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sentinela.canonical_provenance.models import (
    CanonicalEventPersistenceResult,
    CanonicalPersistenceItemResult,
    PersistenceDisposition,
)
from sentinela.real_signals.collectors import CollectionResult
from sentinela.real_signals.orchestrator import run_real_signals
from sentinela.real_signals.tests.test_canonical_provenance_hooks import CanonicalStore
from sentinela.real_signals.tests.test_real_signals import FixedCollector, settings
from sentinela.real_signals.tests.test_run_audit import RecordingAuditStore
from sentinela.seismic_editorial.operational import (
    build_records,
    select_hourly_usgs_events,
)
from sentinela.seismic_editorial.persistence import seismic_input_facts_signature
from sentinela.seismic_editorial.tests.conftest import seismic_event

NOW = datetime(2026, 8, 13, 18, tzinfo=timezone.utc)
T1 = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
T2 = datetime(2026, 8, 13, 18, tzinfo=timezone.utc)
KEEPER_ID = UUID("22222222-2222-4222-8222-222222222222")
CANDIDATE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _usgs_event(*, event_id: UUID, updated_at: datetime, magnitude: float = 5.0):
    event = seismic_event(
        event_id=str(event_id),
        source_event_id="us6000stale",
        magnitude=magnitude,
        occurred_at=T1,
    )
    evidence = dict(event.evidence[0])
    evidence["updated_at"] = updated_at.isoformat().replace("+00:00", "Z")
    return event.model_copy(update={"evidence": [evidence]})


def _run(event, item, collectors_event=None):
    payload = collectors_event or event
    return run_real_signals(
        settings=settings(),
        sources=("usgs",),
        now=NOW,
        collectors={
            "usgs": FixedCollector(
                CollectionResult(source="usgs", events=(payload,), received=1)
            )
        },
        canonical_store=CanonicalStore(
            event_result=CanonicalEventPersistenceResult(
                received=1,
                accepted=1,
                rejected=0,
                items=(item,),
            )
        ),
        audit_store=RecordingAuditStore(),
        audit_mode="persist",
    )


def test_t1_stale_t2_then_t1_excludes_scientific_downstream(capsys):
    incoming = _usgs_event(event_id=CANDIDATE_ID, updated_at=T1, magnitude=4.1)
    keeper = _usgs_event(event_id=KEEPER_ID, updated_at=T2, magnitude=5.7)
    item = CanonicalPersistenceItemResult(
        artifact_id=str(CANDIDATE_ID),
        canonical_event_id=KEEPER_ID,
        disposition=PersistenceDisposition.OBSERVED_EXISTING,
        content_hash="a" * 64,
        stored_updated_at=T2,
    )
    run = _run(incoming, item)
    logged = capsys.readouterr().out
    assert logged.count("SENTINELA_STALE_REVISION_SKIPPED") == 1
    assert "source_event_id=us6000stale" in logged
    assert "incoming_updated_at=2026-08-13T12:00:00Z" in logged
    assert "stored_updated_at=2026-08-13T18:00:00Z" in logged
    assert run.events == ()
    assert select_hourly_usgs_events(run) == ()
    assert all(signal.representative_event_id != str(CANDIDATE_ID) for signal in run.signals)
    assert run.collections[0].events[0].id == CANDIDATE_ID
    assert run.canonical_event_acceptance.accepted[0].event.id == CANDIDATE_ID
    assert run.canonical_event_persistence.items[0].canonical_event_id == KEEPER_ID
    assert seismic_input_facts_signature(keeper) != seismic_input_facts_signature(incoming)


def test_t2a_equal_updated_at_same_hash_is_not_stale(capsys):
    event = _usgs_event(event_id=CANDIDATE_ID, updated_at=T2)
    item = CanonicalPersistenceItemResult(
        artifact_id=str(CANDIDATE_ID),
        canonical_event_id=CANDIDATE_ID,
        disposition=PersistenceDisposition.OBSERVED_EXISTING,
        content_hash="b" * 64,
        stored_updated_at=T2,
    )
    run = _run(event, item)
    assert "SENTINELA_STALE_REVISION_SKIPPED" not in capsys.readouterr().out
    assert [item.id for item in run.events] == [CANDIDATE_ID]
    assert select_hourly_usgs_events(run)[0].id == CANDIDATE_ID


def test_t2b_equal_updated_at_updated_disposition_is_not_stale(capsys):
    event = _usgs_event(event_id=CANDIDATE_ID, updated_at=T2, magnitude=6.2)
    item = CanonicalPersistenceItemResult(
        artifact_id=str(CANDIDATE_ID),
        canonical_event_id=KEEPER_ID,
        disposition=PersistenceDisposition.UPDATED,
        content_hash="c" * 64,
        stored_updated_at=T2,
    )
    run = _run(event, item)
    assert "SENTINELA_STALE_REVISION_SKIPPED" not in capsys.readouterr().out
    assert run.events[0].id == KEEPER_ID
    assert run.events[0].evidence[0]["magnitude"] == 6.2
    selected = select_hourly_usgs_events(run)
    assert selected[0].id == KEEPER_ID
    records = build_records(selected, generated_at=NOW)
    assert records[0].event_id == KEEPER_ID
    assert records[0].input_facts_signature == seismic_input_facts_signature(run.events[0])


def test_t3_newer_updated_at_is_not_stale(capsys):
    event = _usgs_event(event_id=CANDIDATE_ID, updated_at=T2, magnitude=6.8)
    item = CanonicalPersistenceItemResult(
        artifact_id=str(CANDIDATE_ID),
        canonical_event_id=KEEPER_ID,
        disposition=PersistenceDisposition.UPDATED,
        content_hash="d" * 64,
        stored_updated_at=T2,
    )
    run = _run(event, item)
    assert "SENTINELA_STALE_REVISION_SKIPPED" not in capsys.readouterr().out
    assert len(run.events) == 1
    assert run.events[0].evidence[0]["updated_at"] == "2026-08-13T18:00:00Z"
    selected = select_hourly_usgs_events(run)
    assert selected[0].id == KEEPER_ID
    records = build_records(selected, generated_at=NOW)
    assert records[0].event_id == KEEPER_ID
    assert records[0].input_facts_signature == seismic_input_facts_signature(run.events[0])


def test_t4_stale_absent_from_scientific_consumers_provenance_kept(capsys):
    incoming = _usgs_event(event_id=CANDIDATE_ID, updated_at=T1)
    item = CanonicalPersistenceItemResult(
        artifact_id=str(CANDIDATE_ID),
        canonical_event_id=KEEPER_ID,
        disposition=PersistenceDisposition.OBSERVED_EXISTING,
        content_hash="e" * 64,
        stored_updated_at=T2,
    )
    run = _run(incoming, item)
    capsys.readouterr()
    scientific_ids = {str(event.id) for event in run.events}
    assert str(CANDIDATE_ID) not in scientific_ids
    assert all(
        str(CANDIDATE_ID) not in getattr(signal, "member_event_ids", ())
        for signal in run.signals
    )
    assert run.canonical_event_persistence.items[0].artifact_id == str(CANDIDATE_ID)
    assert run.canonical_event_acceptance.accepted[0].event.evidence[0]["updated_at"].startswith(
        "2026-08-13T12:00:00"
    )


def test_t5_old_rpc_without_stored_updated_at_does_not_false_stale(capsys):
    event = _usgs_event(event_id=CANDIDATE_ID, updated_at=T1)
    item = CanonicalPersistenceItemResult(
        artifact_id=str(CANDIDATE_ID),
        disposition=PersistenceDisposition.OBSERVED_EXISTING,
        content_hash="f" * 64,
    )
    run = _run(event, item)
    assert item.stored_updated_at is None
    assert "SENTINELA_STALE_REVISION_SKIPPED" not in capsys.readouterr().out
    assert run.events[0].id == CANDIDATE_ID


def test_t5_old_rpc_without_canonical_event_id_still_runs():
    event = _usgs_event(event_id=CANDIDATE_ID, updated_at=T2)
    item = CanonicalPersistenceItemResult(
        artifact_id=str(CANDIDATE_ID),
        disposition=PersistenceDisposition.OBSERVED_EXISTING,
        content_hash="a" * 64,
        stored_updated_at=T2,
    )
    run = _run(event, item)
    assert run.events[0].id == CANDIDATE_ID
    assert select_hourly_usgs_events(run)[0].id == CANDIDATE_ID
