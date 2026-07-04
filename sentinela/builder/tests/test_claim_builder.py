"""Testes do Claim Builder e signals (112.2C) — offline, sem LLM."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sentinela.builder import signals
from sentinela.builder.claim_builder import ClaimBuilder
from sentinela.core.contract import FilterAgentInput
from sentinela.core.models import EpistemicStatus, RawItem, ReliabilityTier


# ---------- signals ----------
def test_reliability_allowlist():
    assert signals.derive_reliability("https://www.nature.com/articles/x") == ReliabilityTier.HIGH
    assert signals.derive_reliability("https://blogs.nature.com/x") == ReliabilityTier.HIGH  # subdomínio
    assert signals.derive_reliability("https://example.org/x") == ReliabilityTier.MEDIUM
    assert signals.derive_reliability("https://joe.medium.com/x") == ReliabilityTier.LOW
    assert signals.derive_reliability(None) == ReliabilityTier.LOW


def test_confidence_tiers():
    assert signals.confidence_for(ReliabilityTier.HIGH) == 0.60
    assert signals.confidence_for(ReliabilityTier.MEDIUM) == 0.50
    assert signals.confidence_for(ReliabilityTier.LOW) == 0.40


def test_category():
    assert signals.derive_category("new study on climate data") == "science_research"
    assert signals.derive_category("a random note about cats") == "general"


def test_keywords():
    kw = signals.extract_keywords("The study of climate and climate data for research", limit=10)
    assert "climate" in kw and "study" in kw
    assert kw.count("climate") == 1          # sem repetição
    assert "the" not in kw and "and" not in kw  # stopwords fora
    assert len(kw) <= 10


def test_statement_from():
    assert signals.statement_from("Título", "corpo") == "Título"
    assert signals.statement_from(None, "Primeira frase. Segunda frase.") == "Primeira frase."


# ---------- builder ----------
def _raw(**kw):
    base = dict(source_id=uuid4(), title="estudo sobre bloqueios atmosféricos",
                url="https://www.nature.com/x", normalized_content="resumo do achado climático.",
                content_hash="h", external_id="ext-1", published_at=datetime.now(timezone.utc))
    base.update(kw)
    return RawItem(**base)


def test_build_produz_filteragentinput_valido():
    inp = ClaimBuilder().build(_raw())
    assert isinstance(inp, FilterAgentInput)
    # re-valida no Pydantic (garante que o agente aceitaria)
    FilterAgentInput.model_validate(inp.model_dump())
    assert inp.claim.epistemic_status == EpistemicStatus.HYPOTHESIS  # sempre
    assert inp.claim.confidence_score == 0.60                        # nature.com = high
    assert inp.claim.source_reliability == ReliabilityTier.HIGH
    assert inp.source.excerpt                                        # não vazio (agente exige)
    assert "signals:" in inp.context.notes                          # sinais auditáveis


def test_build_sem_url_vira_low():
    inp = ClaimBuilder().build(_raw(url=None))
    assert inp.claim.source_reliability == ReliabilityTier.LOW
    assert inp.claim.confidence_score == 0.40


# ---------- 112.2C Rev 2: evidência (observação vs estudo) ----------
from sentinela.builder.evidence_builder import EvidenceBuilder
from sentinela.core.models import EpistemicStatus as _ES


def _raw_ev(url, title, summary):
    return RawItem(source_id=uuid4(), title=title, url=url,
                   normalized_content=summary, content_hash="h", external_id="e")


def test_official_observation_vira_confirmed_fact():
    inp = EvidenceBuilder().build(_raw_ev(
        "https://earthquake.usgs.gov/x",
        "M6.2 earthquake near coast",
        "USGS recorded a magnitude 6.2 earthquake that occurred at 03:00."))
    assert inp.claim.epistemic_status == _ES.CONFIRMED_FACT
    assert inp.claim.confidence_score == 0.75
    assert "confirmed_fact" in inp.context.notes


def test_official_mas_estudo_permanece_hypothesis():
    inp = EvidenceBuilder().build(_raw_ev(
        "https://www.nasa.gov/x",
        "New research on exoplanets",
        "A new study suggests the data may indicate distant planets."))
    assert inp.claim.epistemic_status == _ES.HYPOTHESIS   # veto de estudo


def test_journal_nao_e_agencia_permanece_hypothesis():
    inp = EvidenceBuilder().build(_raw_ev(
        "https://www.nature.com/x",
        "Report on climate",
        "Authors report a recorded change in the record."))
    assert inp.claim.epistemic_status == _ES.HYPOTHESIS   # nature = journal, não agência


def test_default_seguro_hypothesis():
    inp = EvidenceBuilder().build(_raw_ev(
        "https://example.org/x", "nota", "texto genérico sem sinais."))
    assert inp.claim.epistemic_status == _ES.HYPOTHESIS
