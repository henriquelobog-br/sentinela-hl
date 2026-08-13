"""ResearcherSignal — projeção estável e serializável do PrioritizedBulletin.

Os boletins dos testes são gerados pelos engines reais do pipeline 112.7
(walking skeleton), sem banco, rede, LLM ou relógio de runtime.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from sentinela.core.models import EpistemicStatus, Event
from sentinela.fingerprint import ConceptFingerprintEngine
from sentinela.interest import InterestEngine, InterestPriority
from sentinela.pipeline.tests.test_walking_skeleton import (
    EVENT_ID,
    build_bulletin_config,
    build_event,
    build_fingerprint_config,
    build_interest_config,
    build_profile,
    build_radar_config,
    build_taxonomy,
)
from sentinela.pipeline.walking_skeleton import run_walking_skeleton
from sentinela.prioritized_bulletin import (
    PrioritizedBulletinContext,
    PrioritizedBulletinEngine,
    PrioritizedBulletinEntry,
    PrioritizedBulletinRequest,
)
from sentinela.projection import (
    ResearcherSignal,
    project_researcher_signals,
)
from sentinela.radar import EventRadar, EventSignificance
from sentinela.taxonomy.taxonomy import TaxonomyIndex

SECOND_EVENT_ID = UUID("87654321-4321-4321-4321-cba987654321")


# --------------------------------------------------------------- fixtures
def single_item_bulletin():
    """Boletim real gerado pelo walking skeleton (1 item, URGENT)."""
    return run_walking_skeleton(
        event=build_event(),
        taxonomy=build_taxonomy(),
        profile=build_profile(),
        fingerprint_config=build_fingerprint_config(),
        radar_config=build_radar_config(),
        interest_config=build_interest_config(),
        bulletin_config=build_bulletin_config(),
    )


def second_event() -> Event:
    """Evento sem correspondência taxonômica: prioridade LOW."""
    return Event(
        id=SECOND_EVENT_ID,
        title="Local sports championship results announced",
        summary="A regional tournament concluded yesterday.",
        epistemic_status=EpistemicStatus.CONFIRMED_FACT,
        confidence_score=0.7,
        keywords=["sports", "championship"],
        occurred_at=datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc),
        validated_at=datetime(2026, 7, 19, 18, 0, 0, tzinfo=timezone.utc),
    )


def multi_item_bulletin():
    """Boletim real com dois itens (URGENT e LOW), gerado pelos engines."""
    index = TaxonomyIndex(build_taxonomy())
    profile = build_profile()
    fingerprint_config = build_fingerprint_config()
    radar_config = build_radar_config()
    interest_config = build_interest_config()

    entries = []
    for event in (build_event(), second_event()):
        fingerprint = ConceptFingerprintEngine(
            taxonomy=index,
            config=fingerprint_config,
        ).build(event)
        radar_result = EventRadar(radar_config).evaluate(
            event=event,
            fingerprint=fingerprint,
        )
        interest_result = InterestEngine(interest_config).evaluate(
            event=event,
            fingerprint=fingerprint,
            radar_result=radar_result,
            profile=profile,
        )
        entries.append(
            PrioritizedBulletinEntry(
                event=event,
                interest_result=interest_result,
            )
        )

    context = PrioritizedBulletinContext(
        researcher_id=profile.researcher.id,
        profile_version=str(profile.researcher.version),
        taxonomy_version=profile.taxonomy_version,
        interest_algorithm_version=interest_config.algorithm_version,
        interest_config_version=interest_config.config_version,
    )
    request = PrioritizedBulletinRequest(
        context=context,
        entries=tuple(entries),
    )
    return PrioritizedBulletinEngine(build_bulletin_config()).build(request)


def empty_bulletin():
    """Boletim vazio: contrato 112.7G §10 permite entries=()."""
    profile = build_profile()
    context = PrioritizedBulletinContext(
        researcher_id=profile.researcher.id,
        profile_version=str(profile.researcher.version),
        taxonomy_version=profile.taxonomy_version,
        interest_algorithm_version="1.0",
        interest_config_version="1",
    )
    request = PrioritizedBulletinRequest(context=context, entries=())
    return PrioritizedBulletinEngine(build_bulletin_config()).build(request)


# ------------------------------------------------------------------ testes
def test_projeta_boletim_com_um_item():
    bulletin = single_item_bulletin()

    signals = project_researcher_signals(bulletin)

    assert len(signals) == 1
    signal = signals[0]
    item = bulletin.sections[0].items[0]

    assert signal.researcher_id == "hl"
    assert signal.research_profile_version == "1"
    assert signal.event_id == str(EVENT_ID)
    assert signal.representative_event_id == item.representative_event_id
    assert signal.member_event_ids == item.member_event_ids
    assert signal.title == item.title
    assert signal.summary == item.summary
    assert signal.category == item.category
    assert signal.source == item.source
    assert signal.supporting_sources == item.supporting_sources
    assert signal.evidence == item.evidence
    assert signal.taxonomy_version == "1"
    assert (
        signal.algorithm_version
        == bulletin.context.interest_algorithm_version
    )
    assert signal.config_version == bulletin.context.interest_config_version


def test_preserva_scores_niveis_e_reasons():
    bulletin = single_item_bulletin()
    item = bulletin.sections[0].items[0]

    (signal,) = project_researcher_signals(bulletin)

    assert signal.priority_score == item.priority_score == 1.0
    assert signal.priority_level is InterestPriority.URGENT
    assert signal.relevance_score == item.relevance_score == 1.0
    assert signal.significance_score == item.significance_score == 1.0
    assert signal.significance_level is EventSignificance.CRITICAL
    assert signal.matched_concepts == item.matched_concepts
    assert signal.reasons == item.reasons
    assert len(signal.reasons) > 0
    assert signal.requires_human_review is False
    assert signal.occurred_at == item.occurred_at
    assert signal.validated_at == item.validated_at


def test_preserva_ordem_do_boletim():
    bulletin = multi_item_bulletin()

    signals = project_researcher_signals(bulletin)

    assert len(signals) == 2
    assert signals[0].priority_level is InterestPriority.URGENT
    assert signals[1].priority_level is InterestPriority.LOW

    expected_order = [
        item.representative_event_id
        for section in bulletin.sections
        for item in section.items
    ]
    assert [
        signal.representative_event_id for signal in signals
    ] == expected_order


def test_serializacao_json():
    (signal,) = project_researcher_signals(single_item_bulletin())

    payload = json.loads(signal.model_dump_json())

    assert payload["id"] == signal.id
    assert payload["researcher_id"] == "hl"
    assert payload["event_id"] == str(EVENT_ID)
    assert payload["priority_level"] == "urgent"
    assert payload["significance_level"] == "critical"
    assert payload["priority_score"] == 1.0
    assert isinstance(payload["matched_concepts"], list)
    assert isinstance(payload["reasons"], list)
    assert payload["requires_human_review"] is False

    restored = ResearcherSignal.model_validate_json(
        signal.model_dump_json()
    )
    assert restored == signal


def test_determinismo_entre_execucoes():
    first = project_researcher_signals(single_item_bulletin())
    second = project_researcher_signals(single_item_bulletin())

    assert [s.model_dump(mode="json") for s in first] == [
        s.model_dump(mode="json") for s in second
    ]


def test_id_estavel():
    (first,) = project_researcher_signals(single_item_bulletin())
    (second,) = project_researcher_signals(single_item_bulletin())

    assert first.id == second.id
    assert len(first.id) == 64  # SHA-256 hex

    others = project_researcher_signals(multi_item_bulletin())
    assert others[1].id != first.id


def test_boletim_vazio_retorna_tupla_vazia():
    bulletin = empty_bulletin()

    assert bulletin.total_items == 0
    assert project_researcher_signals(bulletin) == ()
