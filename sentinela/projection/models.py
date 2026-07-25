"""Modelo público da projeção ResearcherSignal.

Projeção estável e serializável do PrioritizedBulletin (112.7G) para
consumo futuro pelo frontend. Contém exclusivamente campos disponíveis
nos contratos reais do boletim — nenhum campo é fabricado.

Imutável, `extra="forbid"`, serializável via Pydantic (`model_dump_json`).
Reusa os enums reais do projeto (InterestPriority do 112.7F,
EventSignificance do 112.7E) — não duplica contratos.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sentinela.interest.engine import InterestPriority
from sentinela.radar.models import EventSignificance


class ResearcherSignal(BaseModel):
    """Um sinal científico priorizado, pronto para serialização JSON.

    Granularidade: um ResearcherSignal por item do PrioritizedBulletin
    (grupo deduplicado). `event_id` identifica o evento do sinal, que é
    o representante do grupo no contrato 112.7G.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # identidade estável (SHA-256 de pesquisador + evento + versões)
    id: str
    researcher_id: str
    research_profile_version: str

    # evento
    event_id: str
    representative_event_id: str
    member_event_ids: tuple[str, ...]
    title: str
    summary: Optional[str]
    occurred_at: Optional[datetime]
    validated_at: Optional[datetime]

    # priorização (copiada, nunca recalculada)
    priority_score: float = Field(ge=0.0, le=1.0)
    priority_level: InterestPriority
    relevance_score: float = Field(ge=0.0, le=1.0)
    significance_score: float = Field(ge=0.0, le=1.0)
    significance_level: EventSignificance
    reasons: tuple[str, ...]
    requires_human_review: bool

    # proveniência de versões
    taxonomy_version: str
    algorithm_version: str
    config_version: str


__all__ = ["ResearcherSignal"]
