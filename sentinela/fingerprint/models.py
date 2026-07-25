"""Modelos do Concept Fingerprint — Documento 112.7D §8, §9, §11, §27.

Contratos Pydantic v2, imutáveis, `extra="forbid"`, pesos entre 0 e 1.
Não duplicam contratos existentes: consomem `Event` (core) e `Taxonomy`
(taxonomy) como entradas.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FingerprintField(str, Enum):
    """112.7D §9.1 — campos do Event pesquisados pelo fingerprint."""

    TITLE = "title"
    SUMMARY = "summary"
    CATEGORY = "category"
    SCIENTIFIC_AREA = "scientific_area"
    KEYWORD = "keyword"
    ENTITY = "entity"
    COUNTRY = "country"
    EVIDENCE = "evidence"


class ConceptMatchType(str, Enum):
    """112.7D §9.2 — tipos de correspondência da V1 (sem fuzzy)."""

    CONCEPT_ID = "concept_id"
    CANONICAL_NAME = "canonical_name"
    SYNONYM = "synonym"
    PARENT = "parent"
    RELATED = "related"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MatchEvidence(_Base):
    """112.7D §8.2/§22 — proveniência auditável de cada correspondência."""

    field: FingerprintField
    input_term: str
    normalized_term: str
    matched_term: str
    canonical_concept_id: str
    match_type: ConceptMatchType
    contribution: float = Field(ge=0.0, le=1.0)


class UnmatchedTerm(_Base):
    """112.7D §8.3/§20 — lacuna vocabular registrada; nunca cria conceito."""

    field: FingerprintField
    input_term: str
    normalized_term: str
    reason: str


class ConceptSignal(_Base):
    """112.7D §8.1/§17 — o peso final não oculta a origem."""

    concept_id: str
    domain_id: str
    weight: float = Field(ge=0.0, le=1.0)
    direct_weight: float = Field(ge=0.0, le=1.0)
    inherited_weight: float = Field(ge=0.0, le=1.0)
    related_weight: float = Field(ge=0.0, le=1.0)
    evidence: tuple[MatchEvidence, ...] = ()


class ConceptFingerprint(_Base):
    """112.7D §8 — saída principal, modelo imutável."""

    event_id: Optional[UUID]
    taxonomy_version: str
    generated_at: datetime
    concepts: tuple[ConceptSignal, ...] = ()
    unmatched_terms: tuple[UnmatchedTerm, ...] = ()
    source_fields: tuple[str, ...] = ()
    algorithm_version: str


class FingerprintWeights(BaseModel):
    """112.7D §11 — valores iniciais de contrato, configuráveis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    keyword: float = Field(default=1.00, ge=0.0, le=1.0)
    scientific_area: float = Field(default=1.00, ge=0.0, le=1.0)
    category: float = Field(default=0.90, ge=0.0, le=1.0)
    entity: float = Field(default=0.90, ge=0.0, le=1.0)
    country: float = Field(default=0.85, ge=0.0, le=1.0)
    title: float = Field(default=0.85, ge=0.0, le=1.0)
    summary: float = Field(default=0.70, ge=0.0, le=1.0)
    evidence: float = Field(default=0.65, ge=0.0, le=1.0)
    parent_decay: float = Field(default=0.70, ge=0.0, le=1.0)
    related_decay: float = Field(default=0.40, ge=0.0, le=1.0)


class FingerprintConfig(BaseModel):
    """112.7D §27 — pesos e limites por contrato versionado."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = "1"
    weights: FingerprintWeights = FingerprintWeights()
    include_parents: bool = True
    max_parent_depth: int = 3
    include_related: bool = True
    max_related_depth: int = 1
    minimum_contribution: float = Field(default=0.05, ge=0.0, le=1.0)


__all__ = [
    "ConceptFingerprint",
    "ConceptMatchType",
    "ConceptSignal",
    "FingerprintConfig",
    "FingerprintField",
    "FingerprintWeights",
    "MatchEvidence",
    "UnmatchedTerm",
]
