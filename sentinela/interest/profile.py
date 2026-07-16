"""Operações puras sobre ResearchProfile."""

from __future__ import annotations

from .models import ResearchProfile


def canonical_concept_ids(profile: ResearchProfile) -> frozenset[str]:
    """Retorna todos os conceitos canônicos referenciados pelo perfil."""

    ids = {item.concept_id for item in profile.concepts}
    ids.update(item.concept_id for item in profile.regions)
    ids.update(item.concept_id for item in profile.instruments)

    for line in profile.research_lines:
        ids.update(item.concept_id for item in line.concepts)
        ids.update(item.concept_id for item in line.regions)
        ids.update(item.concept_id for item in line.instruments)

    return frozenset(ids)
