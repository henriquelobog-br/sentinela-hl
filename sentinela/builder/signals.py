"""
Sentinela HL — sinais do Claim Builder (Documento 112.2C).

Funções puras, determinísticas, sem LLM. Cada sinal é auditável isoladamente.
Nenhuma delas tenta descobrir a verdade — só derivam metadados mecânicos que o
Agente 113 depois audita.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from sentinela.core.models import ReliabilityTier

# domínios científicos/institucionais de alta confiabilidade (extensível)
HIGH_RELIABILITY_DOMAINS = {
    "nature.com", "science.org", "pnas.org", "cell.com", "thelancet.com",
    "nasa.gov", "noaa.gov", "esa.int", "usgs.gov", "copernicus.org",
    "agu.org", "ametsoc.org", "springer.com", "wiley.com", "sciencedirect.com",
}
# domínios genéricos / de baixa confiabilidade editorial
GENERIC_OR_LOW_DOMAINS = {
    "blogspot.com", "wordpress.com", "medium.com", "substack.com",
    "tumblr.com", "wixsite.com", "blogger.com",
}

# termos que sinalizam escopo científico
SCIENCE_TERMS = {"study", "research", "paper", "journal", "climate", "data",
                 "estudo", "pesquisa", "científic", "clima"}

# stopwords mínimas (pt + en) para extração de keywords
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over",
    "para", "com", "que", "uma", "dos", "das", "por", "como", "sobre",
    "the", "was", "are", "não", "mais", "seu", "sua", "foi", "ser",
}


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def derive_reliability(url: str | None) -> ReliabilityTier:
    """high se domínio na allowlist; low se sem url ou domínio genérico;
    medium caso contrário."""
    dom = _domain(url)
    if not dom:
        return ReliabilityTier.LOW
    if any(dom == d or dom.endswith("." + d) for d in HIGH_RELIABILITY_DOMAINS):
        return ReliabilityTier.HIGH
    if any(dom == d or dom.endswith("." + d) for d in GENERIC_OR_LOW_DOMAINS):
        return ReliabilityTier.LOW
    return ReliabilityTier.MEDIUM


def confidence_for(tier: ReliabilityTier) -> float:
    return {ReliabilityTier.HIGH: 0.60,
            ReliabilityTier.MEDIUM: 0.50,
            ReliabilityTier.LOW: 0.40}.get(tier, 0.50)


def derive_category(text: str) -> str:
    """science_research se houver termo científico; general caso contrário."""
    low = (text or "").lower()
    return "science_research" if any(t in low for t in SCIENCE_TERMS) else "general"


def extract_keywords(text: str, limit: int = 10) -> list[str]:
    """palavras relevantes (>=4 chars), sem stopwords, sem repetição, até `limit`."""
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", (text or "").lower())
    out: list[str] = []
    seen: set[str] = set()
    for tok in tokens:
        if len(tok) >= 4 and tok not in _STOPWORDS and tok not in seen:
            seen.add(tok)
            out.append(tok)
        if len(out) >= limit:
            break
    return out


def statement_from(title: str | None, excerpt: str | None) -> str:
    """title se existir; senão a primeira frase do excerpt."""
    if title and title.strip():
        return title.strip()
    text = (excerpt or "").strip()
    if not text:
        return ""
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return first.strip()


# ---------------------------------------------------------------------
# 112.2C Rev 2 — sinais de evidência (observação vs estudo)
# Agências oficiais ANUNCIAM observações (podem virar fato); journals
# PUBLICAM estudos (permanecem hipótese). Domínio sozinho nunca basta.
# ---------------------------------------------------------------------

import re as _re

OFFICIAL_AGENCY_DOMAINS = {
    "nasa.gov", "noaa.gov", "usgs.gov", "esa.int", "copernicus.eu",
    "weather.gov", "earthquake.usgs.gov", "cpc.ncep.noaa.gov",
}

# termos que sinalizam observação/anúncio (habilitam confirmed_fact)
_OBSERVATION_TERMS = {
    "reported", "recorded", "announced", "detected", "observed", "measured",
    "confirmed", "launched", "magnitude", "earthquake", "eruption", "record",
    "issued", "occurred", "released", "registrou", "detectou", "anunciou",
    "observou", "terremoto", "erupção", "lançou",
}
# termos que sinalizam estudo/interpretação/preliminar (vetam confirmed_fact)
_STUDY_TERMS = {
    "study", "research", "paper", "hypothesis", "suggests", "suggest", "may",
    "could", "preliminary", "projection", "projects", "estimate", "estimates",
    "proposes", "propose", "model", "estudo", "pesquisa", "hipótese",
    "preliminar", "sugere", "pode", "projeção",
}


def is_official_agency(url: str | None) -> bool:
    dom = _domain(url)
    if not dom:
        return False
    return any(dom == d or dom.endswith("." + d) for d in OFFICIAL_AGENCY_DOMAINS)


def _has_term(text: str, terms: set[str]) -> str | None:
    low = (text or "").lower()
    for t in terms:
        if _re.search(rf"\b{_re.escape(t)}\b", low):
            return t
    return None


def derive_epistemics(url: str | None, text: str):
    """Retorna (epistemic_status_value, confidence, reliability, notes).

    confirmed_fact SÓ com porta tripla: agência oficial + sinal de observação
    + ausência de sinal de estudo. Caso contrário, hypothesis (default seguro).
    """
    reliability = derive_reliability(url)
    official = is_official_agency(url)
    obs = _has_term(text, _OBSERVATION_TERMS)
    study = _has_term(text, _STUDY_TERMS)

    if official and obs and not study:
        notes = f"source=official({_domain(url)}) evidence=observation({obs}) -> confirmed_fact"
        return "confirmed_fact", 0.75, reliability, notes

    reason = f"study({study})" if study else ("no-observation" if official else "not-official")
    notes = f"reliability={reliability.value} evidence={reason} -> hypothesis"
    return "hypothesis", confidence_for(reliability), reliability, notes
