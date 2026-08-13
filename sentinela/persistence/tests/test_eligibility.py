from __future__ import annotations

import pytest

from sentinela.interest import (
    InterestConceptMatch,
    InterestMatchChannel,
    InterestMatchScope,
)
from sentinela.persistence import (
    is_signal_eligible_for_persistence,
    signal_contribution_channels,
)
from sentinela.persistence.tests.test_supabase_store import single_signals


def contribution(
    scope: str,
    channel: str,
    value: float = 0.2,
    concept: str = "test_concept",
) -> InterestConceptMatch:
    return InterestConceptMatch(
        fingerprint_concept_id=concept,
        domain_id="test_domain",
        scope=InterestMatchScope(scope),
        channel=InterestMatchChannel(channel),
        profile_item_id="test",
        research_line_id="test_line" if scope == "research_line" else None,
        fingerprint_weight=1.0,
        profile_weight=1.0,
        line_priority=1.0 if scope == "research_line" else None,
        channel_weight=1.0,
        contribution=value,
    )


def signal(
    *,
    relevance: float = 0.5,
    contributions: tuple[InterestConceptMatch, ...] = (),
    reasons: tuple[str, ...] = (),
):
    return single_signals()[0].model_copy(update={
        "relevance_score": relevance,
        "priority_score": relevance * 0.75,
        "matched_concepts": contributions,
        "reasons": reasons,
    })


def test_relevance_zero_bloqueado():
    assert not is_signal_eligible_for_persistence(
        signal(relevance=0, contributions=(contribution("global", "concept"),))
    )


def test_relevancia_apenas_regional_bloqueada():
    item = signal(contributions=(
        contribution("global", "region"),
        contribution("research_line", "region"),
    ))
    assert signal_contribution_channels(item) == (("global", "region"), ("research_line", "region"))
    assert not is_signal_eligible_for_persistence(item)


@pytest.mark.parametrize(
    "scope,channel",
    [("global", "concept"), ("global", "domain"), ("research_line", "concept")],
)
def test_contribuicao_tematica_permite_elegibilidade(scope, channel):
    assert is_signal_eligible_for_persistence(
        signal(contributions=(contribution(scope, channel),))
    )


def test_instrumento_isolado_nao_basta():
    assert not is_signal_eligible_for_persistence(
        signal(contributions=(contribution("global", "instrument"),))
    )


def test_regiao_mais_conceito_passa():
    item = signal(contributions=(
        contribution("global", "region"),
        contribution("research_line", "concept"),
    ))
    assert is_signal_eligible_for_persistence(item)


def test_conceito_relacionado_nao_basta_quando_diretos_sao_informados():
    item = signal(contributions=(contribution("global", "domain"),))
    assert not is_signal_eligible_for_persistence(
        item, direct_concept_ids=frozenset({"another_concept"}),
    )


@pytest.mark.parametrize(
    "source,relevance,contributions,expected",
    [
        ("USGS Earthquakes", 0.0, (), False),
        ("CMR", 0.8, (contribution("global", "domain"), contribution("global", "instrument")), True),
        ("Weather", 0.4, (contribution("global", "domain"), contribution("global", "region")), True),
        ("GDELT", 0.6, (contribution("research_line", "concept"),), True),
        ("USGS Volcano", 0.3, (contribution("research_line", "concept"),), True),
        ("sinal anterior", 0.7, (contribution("global", "concept"),), True),
    ],
)
def test_regressao_dos_canais_das_fontes_existentes(source, relevance, contributions, expected):
    assert is_signal_eligible_for_persistence(
        signal(relevance=relevance, contributions=contributions)
    ) is expected


def test_texto_da_reason_nao_muda_elegibilidade():
    structured = (contribution("research_line", "concept"),)
    legacy = signal(
        contributions=structured,
        reasons=("Conceito test_concept, dominio test_domain, escopo research_line, canal concept.",),
    )
    rewritten = signal(
        contributions=structured,
        reasons=("Correspondencia direta: test_concept.",),
    )
    assert is_signal_eligible_for_persistence(legacy)
    assert is_signal_eligible_for_persistence(rewritten)


def test_contribuicao_zero_nao_passa():
    assert not is_signal_eligible_for_persistence(
        signal(contributions=(contribution("global", "concept", value=0),))
    )
