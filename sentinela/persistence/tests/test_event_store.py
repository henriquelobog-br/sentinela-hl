from __future__ import annotations

from pathlib import Path

from sentinela.core.models import Event
from sentinela.persistence import EventStoreResult, SupabaseEventStore
from sentinela.projection import project_researcher_signals
from sentinela.projection.tests.test_researcher_signal import single_item_bulletin
from sentinela.real_signals.multithematic import UsgsCollector
from sentinela.real_signals.orchestrator import run_real_signals
from sentinela.real_signals.tests.test_multithematic import (
    Client,
    NOW,
    settings,
    usgs_feature,
)

from .test_supabase_store import FAKE_SERVICE_KEY, FAKE_URL, FakeClient, FakeResponse


def earthquake_event():
    return UsgsCollector(
        settings(), Client([{"features": [usgs_feature()]}])
    ).collect(NOW).events[0]


def make_store(client):
    return SupabaseEventStore(
        url=FAKE_URL,
        service_key=FAKE_SERVICE_KEY,
        client=client,
    )


def test_event_payload_preserva_contrato_canonico_e_upsert_por_id():
    event = earthquake_event()
    client = FakeClient(response=FakeResponse([{"id": str(event.id)}]))

    result = make_store(client).upsert_many((event,))

    call = client.calls[0]
    payload = call["json"][0]
    assert call["url"] == f"{FAKE_URL}/rest/v1/events"
    assert call["params"] == {"on_conflict": "id"}
    assert call["headers"]["content-profile"] == "knowledge"
    assert "resolution=merge-duplicates" in call["headers"]["prefer"]
    assert payload["id"] == str(event.id)
    assert payload["primary_claim_id"] is None
    assert payload["event_status"] == "observed_fact"
    assert payload["source"] == "USGS"
    assert payload["category"] == "earthquake_detected"
    assert payload["evidence"] == event.model_dump(mode="json")["evidence"]
    assert result == EventStoreResult(
        received=1, persisted=1, persisted_ids=(str(event.id),)
    )


def test_mesmo_event_duas_vezes_mantem_uma_identidade():
    event = earthquake_event()
    client = FakeClient(response=FakeResponse([{"id": str(event.id)}]))
    store = make_store(client)

    first = store.upsert_many((event,))
    second = store.upsert_many((event,))

    assert first.persisted_ids == second.persisted_ids == (str(event.id),)
    assert client.calls[0]["json"] == client.calls[1]["json"]


def test_event_nao_contem_scores_personalizados():
    fields = Event.model_fields
    assert "relevance_score" not in fields
    assert "priority_score" not in fields


def test_profile_version_nao_muda_event_id_mas_muda_signal_id():
    bulletin = single_item_bulletin()
    revised = bulletin.model_copy(update={
        "context": bulletin.context.model_copy(update={"profile_version": "2"})
    })

    first_signal = project_researcher_signals(bulletin)[0]
    second_signal = project_researcher_signals(revised)[0]

    assert "research_profile_version" not in Event.model_fields
    assert first_signal.event_id == second_signal.event_id
    assert first_signal.id != second_signal.id


class RecordingEventStore:
    def __init__(self):
        self.calls = []

    def upsert_many(self, events):
        self.calls.append(events)
        return EventStoreResult(
            received=len(events),
            persisted=len(events),
            persisted_ids=tuple(str(event.id) for event in events),
        )


class RecordingSignalStore:
    def __init__(self):
        self.calls = []

    def upsert_many(self, signals):
        from sentinela.persistence import ResearcherSignalStoreResult

        self.calls.append(signals)
        return ResearcherSignalStoreResult(
            received=len(signals),
            persisted=len(signals),
            persisted_ids=tuple(signal.id for signal in signals),
        )


def test_usgs_event_canonico_persistivel_sinal_pessoal_inelegivel():
    event_store = RecordingEventStore()
    signal_store = RecordingSignalStore()
    collector = UsgsCollector(
        settings(), Client([{"features": [usgs_feature()]}])
    )

    run = run_real_signals(
        settings=settings(),
        sources=("usgs",),
        now=NOW,
        collectors={"usgs": collector},
        event_store=event_store,
        store=signal_store,
    )

    event = run.events[0]
    signal = run.signals[0]
    assert event.category == "earthquake_detected"
    assert event.source == "USGS"
    assert event.event_status.value == "observed_fact"
    assert event_store.calls == [(event,)]
    assert run.event_persistence.persisted == 1
    assert signal.relevance_score == 0
    assert signal.matched_concepts == ()
    assert signal.id not in run.eligible_signal_ids
    assert signal_store.calls == [()]
    assert run.persistence.persisted == 0


def test_execucao_normal_nao_persiste_event_silenciosamente():
    signal_store = RecordingSignalStore()
    collector = UsgsCollector(
        settings(), Client([{"features": [usgs_feature()]}])
    )

    run = run_real_signals(
        settings=settings(),
        sources=("usgs",),
        now=NOW,
        collectors={"usgs": collector},
        store=signal_store,
    )

    assert run.event_persistence is None
    assert signal_store.calls == [()]
    assert run.persistence.persisted == 0


def test_migration_event_e_aditiva_e_nao_toca_researcher_signals():
    migration = Path("supabase/migrations/014_canonical_events.sql").read_text()
    normalized = migration.lower()
    assert "alter table knowledge.events" in normalized
    assert "add column if not exists event_status" in normalized
    assert "add column if not exists source" in normalized
    assert "add column if not exists supporting_sources" in normalized
    statements = "\n".join(
        line for line in normalized.splitlines() if not line.lstrip().startswith("--")
    )
    assert "researcher_signals" not in statements
    assert " drop " not in normalized
    assert " delete " not in normalized
    assert " update " not in normalized
