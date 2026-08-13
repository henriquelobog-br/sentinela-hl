"""Modelos do Prioritized Bulletin — Documento 112.7G §10-§42.

Modelo de domínio puro: nenhum timestamp de runtime, nenhum campo visual,
nenhuma referência mutável às entradas. Reusa os enums upstream
(EventSignificance do 112.7E; InterestPriority, InterestConceptMatch e
ResearchLineMatch do 112.7F) — não duplica contratos.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinela.core.models import Event
from sentinela.core.models import EventStatus
from sentinela.interest.engine import (
    InterestConceptMatch,
    InterestPriority,
    InterestResult,
    ResearchLineMatch,
)
from sentinela.radar.models import EventSignificance


class PrioritizedBulletinSectionType(str, Enum):
    """112.7G §32 — único valor aceito na V1."""

    PRIORITY = "priority"


class PrioritizedBulletinGroupingPolicy(str, Enum):
    """112.7G §39 — política de agrupamento V1."""

    PRIORITY = "priority"


class PrioritizedBulletinDeduplicationPolicy(str, Enum):
    """112.7G §39 — política de deduplicação V1."""

    PRIMARY_CLAIM_OR_EVENT_ID = "primary_claim_or_event_id"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _trimmed(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("string obrigatória não pode ser vazia após trim")
    return trimmed


def _trimmed_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("string presente não pode ficar vazia após trim")
    return trimmed


class PrioritizedBulletinContext(_Base):
    """112.7G §11 — todas as strings obrigatórias, trim na fronteira."""

    researcher_id: str
    profile_version: str
    taxonomy_version: str
    interest_algorithm_version: str
    interest_config_version: str

    @field_validator(
        "researcher_id",
        "profile_version",
        "taxonomy_version",
        "interest_algorithm_version",
        "interest_config_version",
    )
    @classmethod
    def _trim(cls, value: str) -> str:
        return _trimmed(value)


class PrioritizedBulletinEntry(_Base):
    """112.7G §12 — os dois lados obrigatórios da associação.

    Frozen somente quanto à substituição dos próprios atributos; o Event
    é contrato upstream de entrada (exceção superficial da §12).
    """

    event: Event
    interest_result: InterestResult


class PrioritizedBulletinRequest(_Base):
    """112.7G §10 — contexto obrigatório; entries=() é válido."""

    context: PrioritizedBulletinContext
    entries: tuple[PrioritizedBulletinEntry, ...]


class PrioritizedBulletinMember(_Base):
    """112.7G §16 — explicabilidade preservada de cada evento do grupo."""

    event_id: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    significance_score: float = Field(ge=0.0, le=1.0)
    significance_level: EventSignificance
    priority_score: float = Field(ge=0.0, le=1.0)
    priority_level: InterestPriority
    matched_concepts: tuple[InterestConceptMatch, ...]
    matched_research_lines: tuple[ResearchLineMatch, ...]
    reasons: tuple[str, ...]
    requires_human_review: bool


class PrioritizedBulletinItem(_Base):
    """112.7G §17 — exatamente um grupo deduplicado."""

    representative_event_id: str
    member_event_ids: tuple[str, ...]

    title: str
    summary: Optional[str]
    scientific_area: Optional[str]
    category: Optional[str]
    source: Optional[str]
    supporting_sources: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    event_status: EventStatus
    occurred_at: Optional[datetime]
    validated_at: Optional[datetime]

    relevance_score: float = Field(ge=0.0, le=1.0)
    significance_score: float = Field(ge=0.0, le=1.0)
    significance_level: EventSignificance
    priority_score: float = Field(ge=0.0, le=1.0)
    priority_level: InterestPriority

    matched_concepts: tuple[InterestConceptMatch, ...]
    matched_research_lines: tuple[ResearchLineMatch, ...]
    reasons: tuple[str, ...]

    requires_human_review: bool
    members: tuple[PrioritizedBulletinMember, ...]

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        return _trimmed(value)

    @field_validator("summary", "scientific_area", "category")
    @classmethod
    def _trim_optional(cls, value: Optional[str]) -> Optional[str]:
        return _trimmed_optional(value)


class PrioritizedBulletinSection(_Base):
    """112.7G §33 — uma seção por prioridade presente."""

    section_type: PrioritizedBulletinSectionType
    section_key: InterestPriority
    title: str
    items: tuple[PrioritizedBulletinItem, ...]

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        return _trimmed(value)


class PrioritizedBulletin(_Base):
    """112.7G §35 — saída: sem timestamps de runtime, sem apresentação."""

    context: PrioritizedBulletinContext
    prioritized_bulletin_algorithm_version: str
    prioritized_bulletin_config_version: str
    total_input_entries: int = Field(ge=0)
    total_groups: int = Field(ge=0)
    total_items: int = Field(ge=0)
    sections: tuple[PrioritizedBulletinSection, ...]


class PrioritizedBulletinSectionTitle(_Base):
    """112.7G §38 — título configurado por prioridade."""

    priority: InterestPriority
    title: str

    @field_validator("title")
    @classmethod
    def _trim_title(cls, value: str) -> str:
        return _trimmed(value)


class PrioritizedBulletinConfig(_Base):
    """112.7G §38 — organização, versão e limites; sem pesos científicos."""

    algorithm_version: str
    config_version: str
    grouping_policy: PrioritizedBulletinGroupingPolicy
    deduplication_policy: PrioritizedBulletinDeduplicationPolicy
    priority_order: tuple[InterestPriority, ...]
    section_titles: tuple[PrioritizedBulletinSectionTitle, ...]
    maximum_entries: int = Field(ge=1)
    maximum_group_members: int = Field(ge=1)
    maximum_sections: int = Field(ge=1)
    maximum_items_per_section: int = Field(ge=1)

    @field_validator("algorithm_version", "config_version")
    @classmethod
    def _trim_version(cls, value: str) -> str:
        return _trimmed(value)

    @model_validator(mode="after")
    def _sections_consistent(self) -> "PrioritizedBulletinConfig":
        """§34 — cada InterestPriority exatamente uma vez, na mesma ordem."""
        if len(set(self.priority_order)) != len(self.priority_order):
            raise ValueError("priority_order não pode conter duplicatas")
        if set(self.priority_order) != set(InterestPriority):
            raise ValueError(
                "priority_order deve conter cada InterestPriority "
                "exatamente uma vez"
            )
        title_priorities = tuple(t.priority for t in self.section_titles)
        if title_priorities != tuple(self.priority_order):
            raise ValueError(
                "section_titles deve cobrir cada prioridade exatamente uma "
                "vez, na mesma ordem de priority_order"
            )
        return self


__all__ = [
    "PrioritizedBulletin",
    "PrioritizedBulletinConfig",
    "PrioritizedBulletinContext",
    "PrioritizedBulletinDeduplicationPolicy",
    "PrioritizedBulletinEntry",
    "PrioritizedBulletinGroupingPolicy",
    "PrioritizedBulletinItem",
    "PrioritizedBulletinMember",
    "PrioritizedBulletinRequest",
    "PrioritizedBulletinSection",
    "PrioritizedBulletinSectionTitle",
    "PrioritizedBulletinSectionType",
]
