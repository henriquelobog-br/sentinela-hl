"""Elegibilidade genérica de ResearcherSignal para persistência."""

from __future__ import annotations

from sentinela.interest import InterestMatchChannel
from sentinela.projection import ResearcherSignal

_THEMATIC_CHANNELS = frozenset({
    InterestMatchChannel.CONCEPT,
    InterestMatchChannel.DOMAIN,
})


def signal_contribution_channels(signal: ResearcherSignal) -> tuple[tuple[str, str], ...]:
    """Expõe escopo/canal das contribuições positivas estruturadas."""
    return tuple(
        (match.scope.value, match.channel.value)
        for match in signal.matched_concepts
        if match.contribution > 0
    )


def is_signal_eligible_for_persistence(
    signal: ResearcherSignal, *, direct_concept_ids: frozenset[str] | None = None,
) -> bool:
    """Exige relevância positiva e ao menos uma contribuição temática."""
    if signal.relevance_score <= 0:
        return False
    for match in signal.matched_concepts:
        if match.contribution <= 0:
            continue
        if match.channel not in _THEMATIC_CHANNELS:
            continue
        if direct_concept_ids is None or match.fingerprint_concept_id in direct_concept_ids:
            return True
    return False


__all__ = ["is_signal_eligible_for_persistence", "signal_contribution_channels"]
