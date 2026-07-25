"""Walking skeleton 112.7 — integração ponta a ponta (happy path).

Fluxo comprovado:

    Event
    → ConceptFingerprint        (112.7D)
    → EventRadarResult          (112.7E)
    → InterestResult            (112.7F)
    → PrioritizedBulletin       (112.7G)

ScientificTaxonomy e ResearchProfile são entradas complementares.

Determinístico por contrato: sem rede, sem LLM, sem banco de dados e sem
relógio não controlado — o resultado final (112.7G) não contém timestamps
de runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sentinela.core.models import EpistemicStatus, Event
from sentinela.fingerprint import (
    ConceptFingerprintEngine,
    FingerprintConfig,
    FingerprintWeights,
)
from sentinela.interest import (
    InterestChannelWeights,
    InterestEngine,
    InterestEngineConfig,
    InterestEngineLimits,
    InterestPriority,
    InterestPriorityThresholds,
    InterestReasonTemplates,
    InterestReasonType,
    InterestScoringConfig,
    ResearchConcept,
    ResearchDomain,
    ResearchIdentity,
    ResearchInstrument,
    ResearchLine,
    ResearchProfile,
    ResearchRegion,
)
from sentinela.pipeline.walking_skeleton import run_walking_skeleton
from sentinela.prioritized_bulletin import (
    PrioritizedBulletinConfig,
    PrioritizedBulletinDeduplicationPolicy,
    PrioritizedBulletinGroupingPolicy,
    PrioritizedBulletinSectionTitle,
)
from sentinela.radar import (
    EventRadar,
    EventRadarConfig,
    EventRadarLimits,
    EventRadarThresholds,
    EventSignificance,
    RadarDomain,
    RadarSignal,
)
from sentinela.taxonomy.models import Concept, Domain, Taxonomy
from sentinela.taxonomy.taxonomy import TaxonomyIndex

EVENT_ID = UUID("12345678-1234-1234-1234-123456789abc")

RADAR_REASON_TEMPLATE = (
    "Sinal {signal_id} ativado pelo conceito {concept_id}: peso do sinal "
    "{signal_weight}, peso do conceito {concept_weight}, contribuição "
    "{contribution}."
)


# --------------------------------------------------------------- fixtures
def build_taxonomy() -> Taxonomy:
    """Taxonomia mínima válida, construída em memória."""
    return Taxonomy(
        version="1",
        domains=[
            Domain(
                id="atmospheric_science",
                name="Atmospheric Science",
                concepts=[
                    Concept(
                        id="aerosols",
                        name="Aerosols",
                        domain="atmospheric_science",
                        synonyms=["aerosol"],
                    ),
                    Concept(
                        id="mineral_dust",
                        name="Mineral dust",
                        domain="atmospheric_science",
                        synonyms=["desert dust"],
                        parent="aerosols",
                        related=["atmospheric_transport"],
                    ),
                    Concept(
                        id="atmospheric_transport",
                        name="Atmospheric transport",
                        domain="atmospheric_science",
                    ),
                ],
            ),
            Domain(
                id="remote_sensing",
                name="Remote Sensing",
                concepts=[
                    Concept(
                        id="satellite_instruments",
                        name="Satellite instruments",
                        domain="remote_sensing",
                        synonyms=["CALIPSO", "MODIS"],
                    ),
                ],
            ),
            Domain(
                id="regions",
                name="Regions",
                concepts=[
                    Concept(
                        id="south_atlantic",
                        name="South Atlantic",
                        domain="regions",
                    ),
                ],
            ),
        ],
    )


def build_event() -> Event:
    """Evento sintético válido e determinístico."""
    return Event(
        id=EVENT_ID,
        title="Mineral dust plume crosses the South Atlantic",
        summary="CALIPSO observes an aerosol plume.",
        epistemic_status=EpistemicStatus.CONFIRMED_FACT,
        confidence_score=0.9,
        keywords=[
            "mineral dust",
            "desert dust",
            "CALIPSO",
            "South Atlantic",
            "unresolved thing",
        ],
        entities=[{"name": "CALIPSO", "type": "instrument"}],
        occurred_at=datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc),
        validated_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=timezone.utc),
    )


def build_profile() -> ResearchProfile:
    """Research Profile mínimo válido, construído em memória."""
    return ResearchProfile(
        researcher=ResearchIdentity(id="hl", name="Henrique Lobo", version=1),
        taxonomy_version="1",
        domains=(ResearchDomain(domain_id="atmospheric_science", weight=1.0),),
        concepts=(ResearchConcept(concept_id="mineral_dust", weight=0.8),),
        regions=(ResearchRegion(concept_id="south_atlantic", weight=0.9),),
        instruments=(
            ResearchInstrument(concept_id="satellite_instruments", weight=1.0),
        ),
        research_lines=(
            ResearchLine(
                id="dust_transport",
                title="Transporte de poeira africana",
                priority=1.0,
                concepts=(
                    ResearchConcept(concept_id="mineral_dust"),
                    ResearchConcept(concept_id="atmospheric_transport"),
                ),
            ),
        ),
    )


def build_fingerprint_config() -> FingerprintConfig:
    return FingerprintConfig(version="1.0", weights=FingerprintWeights())


def build_radar_config() -> EventRadarConfig:
    return EventRadarConfig(
        config_version="1",
        algorithm_version="1.0",
        compatible_taxonomy_version="1",
        thresholds=EventRadarThresholds(),
        limits=EventRadarLimits(
            maximum_signals=256,
            maximum_concepts_per_signal=64,
            maximum_signal_id_length=128,
            maximum_description_length=1024,
            maximum_reason_template_length=2048,
        ),
        signals=(
            RadarSignal(
                id="atmosphere.mineral_dust",
                domain=RadarDomain.ATMOSPHERE,
                description="Presença conceitual de poeira mineral.",
                concept_ids=("mineral_dust",),
                weight=0.60,
                reason_template=RADAR_REASON_TEMPLATE,
            ),
            RadarSignal(
                id="remote_sensing.satellite_observation",
                domain=RadarDomain.REMOTE_SENSING,
                description="Presença de observação científica por satélite.",
                concept_ids=("satellite_instruments",),
                weight=0.40,
                reason_template=RADAR_REASON_TEMPLATE,
            ),
        ),
    )


def build_interest_config() -> InterestEngineConfig:
    return InterestEngineConfig(
        config_version="1",
        algorithm_version="1.0",
        compatible_taxonomy_version="1",
        compatible_fingerprint_algorithm_version="1.0",
        scoring=InterestScoringConfig(
            relevance_factor=0.75,
            significance_factor=0.25,
        ),
        channel_weights=InterestChannelWeights(
            concept=1.00,
            domain=0.65,
            region=0.55,
            instrument=0.55,
            research_line=0.85,
        ),
        thresholds=InterestPriorityThresholds(
            moderate_min=0.25,
            high_min=0.50,
            urgent_min=0.75,
        ),
        limits=InterestEngineLimits(
            maximum_profile_domains=1024,
            maximum_profile_concepts=4096,
            maximum_profile_regions=1024,
            maximum_profile_instruments=1024,
            maximum_research_lines=256,
            maximum_items_per_research_line=512,
            maximum_total_research_line_items=16384,
            maximum_fingerprint_concepts=4096,
            maximum_matches=8192,
            maximum_reason_length=2048,
        ),
        reason_templates=InterestReasonTemplates(
            system_reason_order=(
                InterestReasonType.NO_POSITIVE_MATCH,
                InterestReasonType.RADAR_CONTRIBUTION,
                InterestReasonType.CRITICAL_WITHOUT_ALIGNMENT,
                InterestReasonType.HUMAN_REVIEW,
                InterestReasonType.IGNORED_V1_FIELDS,
            ),
            positive_global_match=(
                "Conceito {fingerprint_concept_id}, domínio {domain_id}, "
                "escopo {scope}, canal {channel}, item do perfil "
                "{profile_item_id}: peso do fingerprint {fingerprint_weight}, "
                "peso do perfil {profile_weight}, peso efetivo do canal "
                "{channel_weight}, contribuição {contribution}."
            ),
            positive_research_line_match=(
                "Conceito {fingerprint_concept_id}, domínio {domain_id}, "
                "escopo {scope}, canal {channel}, item do perfil "
                "{profile_item_id}, linha {research_line_id}: peso do "
                "fingerprint {fingerprint_weight}, peso do perfil "
                "{profile_weight}, prioridade da linha {line_priority}, peso "
                "efetivo do canal {channel_weight}, contribuição "
                "{contribution}."
            ),
            no_positive_match=(
                "Evento {event_id} sem alinhamento positivo com a agenda do "
                "pesquisador {researcher_id}."
            ),
            radar_contribution=(
                "Significância objetiva preservada: score "
                "{significance_score}, nível {significance_level}, fator "
                "{significance_factor}, contribuição para a prioridade "
                "{significance_contribution}."
            ),
            critical_without_alignment=(
                "Evento crítico sem alinhamento positivo: score "
                "{significance_score}, nível {significance_level}, "
                "contribuição objetiva {significance_contribution}."
            ),
            human_review=(
                "Evento {event_id} no estado {pipeline_status} requer "
                "revisão humana."
            ),
            ignored_v1_fields=(
                "Campos do perfil não aplicados na V1: {ignored_fields}."
            ),
        ),
    )


def build_bulletin_config() -> PrioritizedBulletinConfig:
    return PrioritizedBulletinConfig(
        algorithm_version="1.0",
        config_version="1",
        grouping_policy=PrioritizedBulletinGroupingPolicy.PRIORITY,
        deduplication_policy=(
            PrioritizedBulletinDeduplicationPolicy.PRIMARY_CLAIM_OR_EVENT_ID
        ),
        priority_order=(
            InterestPriority.URGENT,
            InterestPriority.HIGH,
            InterestPriority.MODERATE,
            InterestPriority.LOW,
        ),
        section_titles=(
            PrioritizedBulletinSectionTitle(
                priority=InterestPriority.URGENT, title="Urgente"
            ),
            PrioritizedBulletinSectionTitle(
                priority=InterestPriority.HIGH, title="Alta prioridade"
            ),
            PrioritizedBulletinSectionTitle(
                priority=InterestPriority.MODERATE,
                title="Prioridade moderada",
            ),
            PrioritizedBulletinSectionTitle(
                priority=InterestPriority.LOW, title="Baixa prioridade"
            ),
        ),
        maximum_entries=5000,
        maximum_group_members=500,
        maximum_sections=4,
        maximum_items_per_section=5000,
    )


def run_skeleton() -> "object":
    return run_walking_skeleton(
        event=build_event(),
        taxonomy=build_taxonomy(),
        profile=build_profile(),
        fingerprint_config=build_fingerprint_config(),
        radar_config=build_radar_config(),
        interest_config=build_interest_config(),
        bulletin_config=build_bulletin_config(),
    )


# ------------------------------------------------------------------ testes
def test_walking_skeleton_end_to_end():
    bulletin = run_skeleton()

    assert bulletin.total_input_entries == 1
    assert bulletin.total_groups == 1
    assert bulletin.total_items == 1
    assert len(bulletin.sections) == 1

    section = bulletin.sections[0]
    assert section.section_key == InterestPriority.URGENT
    assert section.title == "Urgente"
    assert len(section.items) == 1

    item = section.items[0]
    # identificação do evento / evento representativo
    assert item.representative_event_id == str(EVENT_ID)
    assert item.member_event_ids == (str(EVENT_ID),)
    assert item.title == "Mineral dust plume crosses the South Atlantic"
    # score e nível de prioridade
    assert item.priority_score == 1.0
    assert item.priority_level == InterestPriority.URGENT
    assert item.significance_score == 1.0
    assert item.significance_level == EventSignificance.CRITICAL
    assert item.relevance_score == 1.0
    # justificativas
    assert len(item.reasons) > 0
    assert any(
        "Significância objetiva preservada" in reason
        for reason in item.reasons
    )
    # indicação de revisão humana
    assert item.requires_human_review is False


def test_walking_skeleton_deterministic():
    first = run_skeleton()
    second = run_skeleton()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_intermediate_contracts():
    """Cada elo intermediário respeita seu contrato público."""
    event = build_event()
    index = TaxonomyIndex(build_taxonomy())

    # 112.7D — Concept Fingerprint
    fingerprint = ConceptFingerprintEngine(
        taxonomy=index,
        config=build_fingerprint_config(),
    ).build(event)

    assert fingerprint.event_id == EVENT_ID
    concept_ids = {signal.concept_id for signal in fingerprint.concepts}
    assert {
        "mineral_dust",
        "aerosols",  # expansão hierárquica (parent de mineral_dust)
        "satellite_instruments",
        "south_atlantic",
        "atmospheric_transport",  # expansão por related de mineral_dust
    } <= concept_ids
    assert any(
        term.input_term == "unresolved thing"
        and term.reason == "not_in_taxonomy"
        for term in fingerprint.unmatched_terms
    )

    # 112.7E — Event Radar
    radar_result = EventRadar(build_radar_config()).evaluate(
        event=event,
        fingerprint=fingerprint,
    )

    assert radar_result.significance_score == 1.0
    assert radar_result.significance_level == EventSignificance.CRITICAL
    assert radar_result.matched_signals == (
        "atmosphere.mineral_dust",
        "remote_sensing.satellite_observation",
    )
    assert len(radar_result.reasons) == 2

    # 112.7F — Interest Engine
    interest_result = InterestEngine(build_interest_config()).evaluate(
        event=event,
        fingerprint=fingerprint,
        radar_result=radar_result,
        profile=build_profile(),
    )

    assert interest_result.event_id == str(EVENT_ID)
    assert interest_result.researcher_id == "hl"
    assert interest_result.taxonomy_version == "1"
    assert interest_result.priority_score == 1.0
    assert interest_result.priority_level == InterestPriority.URGENT
    assert interest_result.significance_score == 1.0
    assert interest_result.significance_level == EventSignificance.CRITICAL
    assert interest_result.requires_human_review is False
    assert len(interest_result.matched_concepts) > 0
    assert len(interest_result.matched_research_lines) == 1
    assert len(interest_result.reasons) > 0
