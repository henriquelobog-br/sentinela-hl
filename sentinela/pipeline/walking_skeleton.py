"""Walking skeleton 112.7 — orquestração de ponta a ponta do happy path.

Fluxo:

    Event
    → ConceptFingerprint        (112.7D, ConceptFingerprintEngine)
    → EventRadarResult          (112.7E, EventRadar)
    → InterestResult            (112.7F, InterestEngine)
    → PrioritizedBulletin       (112.7G, PrioritizedBulletinEngine)

ScientificTaxonomy e ResearchProfile são entradas complementares.
Cada etapa consome exclusivamente os contratos públicos da etapa anterior.
"""

from __future__ import annotations

from typing import Union

from sentinela.core.models import Event
from sentinela.fingerprint import ConceptFingerprintEngine, FingerprintConfig
from sentinela.interest import (
    InterestEngine,
    InterestEngineConfig,
    ResearchProfile,
)
from sentinela.prioritized_bulletin import (
    PrioritizedBulletin,
    PrioritizedBulletinConfig,
    PrioritizedBulletinContext,
    PrioritizedBulletinEngine,
    PrioritizedBulletinEntry,
    PrioritizedBulletinRequest,
)
from sentinela.radar import EventRadar, EventRadarConfig
from sentinela.taxonomy.models import Taxonomy
from sentinela.taxonomy.taxonomy import TaxonomyIndex


def run_walking_skeleton(
    *,
    event: Event,
    taxonomy: Union[Taxonomy, TaxonomyIndex],
    profile: ResearchProfile,
    fingerprint_config: FingerprintConfig,
    radar_config: EventRadarConfig,
    interest_config: InterestEngineConfig,
    bulletin_config: PrioritizedBulletinConfig,
) -> PrioritizedBulletin:
    """Executa o pipeline completo para um único evento.

    Determinístico: sem rede, sem LLM, sem banco e sem relógio não
    controlado — o PrioritizedBulletin não contém timestamps de runtime.
    """
    index = (
        taxonomy
        if isinstance(taxonomy, TaxonomyIndex)
        else TaxonomyIndex(taxonomy)
    )

    # 112.7D — Event → ConceptFingerprint
    fingerprint = ConceptFingerprintEngine(
        taxonomy=index,
        config=fingerprint_config,
    ).build(event)

    # 112.7E — (Event, ConceptFingerprint) → EventRadarResult
    radar_result = EventRadar(radar_config).evaluate(
        event=event,
        fingerprint=fingerprint,
    )

    # 112.7F — (Event, Fingerprint, RadarResult, Profile) → InterestResult
    interest_result = InterestEngine(interest_config).evaluate(
        event=event,
        fingerprint=fingerprint,
        radar_result=radar_result,
        profile=profile,
    )

    # 112.7G — (Event, InterestResult) → PrioritizedBulletin
    context = PrioritizedBulletinContext(
        researcher_id=interest_result.researcher_id,
        profile_version=interest_result.profile_version,
        taxonomy_version=interest_result.taxonomy_version,
        interest_algorithm_version=interest_result.algorithm_version,
        interest_config_version=interest_result.config_version,
    )
    request = PrioritizedBulletinRequest(
        context=context,
        entries=(
            PrioritizedBulletinEntry(
                event=event,
                interest_result=interest_result,
            ),
        ),
    )
    return PrioritizedBulletinEngine(bulletin_config).build(request)


__all__ = ["run_walking_skeleton"]
