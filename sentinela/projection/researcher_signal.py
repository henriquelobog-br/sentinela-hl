"""Projeção PrioritizedBulletin → ResearcherSignal.

Percorre seções e itens na ordenação já definida pelo 112.7G, copia os
campos públicos e deriva um id estável. Não reinterpreta scores nem
prioridades, não duplica regras do Interest Engine ou do Prioritized
Bulletin, não usa banco, rede, LLM ou relógio de runtime.
"""

from __future__ import annotations

import hashlib

from sentinela.prioritized_bulletin import PrioritizedBulletin

from .models import ResearcherSignal


def _stable_id(
    *,
    researcher_id: str,
    representative_event_id: str,
    research_profile_version: str,
    taxonomy_version: str,
    algorithm_version: str,
    config_version: str,
) -> str:
    """Id estável: SHA-256 hex da identidade funcional do sinal.

    Deriva de pesquisador + evento representativo + versões relevantes
    (perfil, taxonomia e algoritmo/config do Interest Engine, que
    produziram os scores projetados).
    """
    canonical = "|".join(
        (
            researcher_id,
            representative_event_id,
            research_profile_version,
            taxonomy_version,
            algorithm_version,
            config_version,
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def project_researcher_signals(
    bulletin: PrioritizedBulletin,
) -> tuple[ResearcherSignal, ...]:
    """Projeta cada item do boletim em um ResearcherSignal.

    Preserva a ordenação das seções e dos itens definida pelo
    PrioritizedBulletin. Boletim sem itens produz tupla vazia.
    """
    context = bulletin.context
    signals: list[ResearcherSignal] = []

    for section in bulletin.sections:
        for item in section.items:
            signals.append(
                ResearcherSignal(
                    id=_stable_id(
                        researcher_id=context.researcher_id,
                        representative_event_id=item.representative_event_id,
                        research_profile_version=context.profile_version,
                        taxonomy_version=context.taxonomy_version,
                        algorithm_version=(
                            context.interest_algorithm_version
                        ),
                        config_version=context.interest_config_version,
                    ),
                    researcher_id=context.researcher_id,
                    research_profile_version=context.profile_version,
                    event_id=item.representative_event_id,
                    representative_event_id=item.representative_event_id,
                    member_event_ids=item.member_event_ids,
                    title=item.title,
                    summary=item.summary,
                    occurred_at=item.occurred_at,
                    validated_at=item.validated_at,
                    priority_score=item.priority_score,
                    priority_level=item.priority_level,
                    relevance_score=item.relevance_score,
                    significance_score=item.significance_score,
                    significance_level=item.significance_level,
                    reasons=item.reasons,
                    requires_human_review=item.requires_human_review,
                    taxonomy_version=context.taxonomy_version,
                    algorithm_version=context.interest_algorithm_version,
                    config_version=context.interest_config_version,
                )
            )

    return tuple(signals)


__all__ = ["project_researcher_signals"]
