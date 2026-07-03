"""
Sentinela HL — modelos de domínio (contrato central do pipeline).

Estes modelos SÃO o contrato que atravessa collector → parser → filters →
classifier → writer. Os enums abaixo espelham 1:1 os tipos do schema SQL
(Documento 101). Se um valor divergir do Postgres, há bug de serialização
silencioso na fronteira do banco — por isso o teste do 111 cruza estes
enums contra o arquivo .sql.

Pydantic v2: validação forte na fronteira (RSS, APIs, Claude, JSON).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# =====================================================================
# Enums — espelho EXATO de public.* no schema 101.
# (str, Enum) garante que .value seja a string idêntica ao Postgres.
# =====================================================================

class EpistemicStatus(str, Enum):
    """knowledge.claims/events.epistemic_status — o rótulo (o produto)."""
    CONFIRMED_FACT = "confirmed_fact"
    HYPOTHESIS = "hypothesis"
    INTERPRETATION = "interpretation"
    PRACTICAL_APPLICATION = "practical_application"


class PipelineStatus(str, Enum):
    """Estado de uma informação ao longo do pipeline."""
    COLLECTED = "collected"
    NORMALIZED = "normalized"
    DUPLICATE = "duplicate"
    DISCARDED = "discarded"
    IN_FILTER = "in_filter"
    ESCALATED = "escalated"
    VALIDATED = "validated"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    ARCHIVED = "archived"


class ReliabilityTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class SourceKind(str, Enum):
    RSS = "rss"
    API = "api"
    SCRAPER = "scraper"
    NEWSLETTER = "newsletter"
    MANUAL = "manual"


class FetchStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    ERROR = "error"


class FilterKey(str, Enum):
    """Os 6 filtros (Documento de avaliação)."""
    PROVENANCE = "provenance"                    # 1
    EPISTEMIC_LABEL = "epistemic_label"          # 2
    SOURCE_INDEPENDENCE = "source_independence"  # 3
    CALIBRATION = "calibration"                  # 4
    CONTRADICTION = "contradiction"              # 5
    EXTRAORDINARINESS = "extraordinariness"      # 6


class FilterResult(str, Enum):
    PASS = "pass"
    FLAG = "flag"
    FAIL = "fail"


class ReviewDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class BulletinStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SENT = "sent"
    FAILED = "failed"


# =====================================================================
# Base — configuração comum a todos os modelos.
# =====================================================================

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _Base(BaseModel):
    # extra='forbid': campo inesperado é erro — pega typo de contrato cedo.
    model_config = ConfigDict(extra="forbid", use_enum_values=False)


# =====================================================================
# BANCO BRUTO (raw.*)
# =====================================================================

class Source(_Base):
    """raw.sources"""
    id: Optional[UUID] = None
    name: str
    kind: SourceKind
    url: Optional[str] = None
    reliability: ReliabilityTier = ReliabilityTier.UNKNOWN
    config: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FetchRun(_Base):
    """raw.fetch_runs"""
    id: Optional[UUID] = None
    source_id: Optional[UUID] = None
    status: FetchStatus = FetchStatus.RUNNING
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    items_found: int = 0
    items_new: int = 0
    items_duplicate: int = 0
    error: Optional[str] = None
    log: dict[str, Any] = Field(default_factory=dict)


class RawItem(_Base):
    """raw.items — item bruto coletado. Dedup por (source_id, external_id)."""
    id: Optional[UUID] = None
    source_id: UUID
    fetch_run_id: Optional[UUID] = None
    external_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    raw_payload: Optional[dict[str, Any]] = None
    normalized_content: Optional[str] = None
    content_hash: Optional[str] = None
    published_at: Optional[datetime] = None
    collected_at: datetime = Field(default_factory=_utcnow)
    pipeline_status: PipelineStatus = PipelineStatus.COLLECTED
    duplicate_of: Optional[UUID] = None


# =====================================================================
# BANCO DE CONHECIMENTO (knowledge.*)
# =====================================================================

class Claim(_Base):
    """knowledge.claims — unidade informacional rotulável antes de virar evento."""
    id: Optional[UUID] = None
    raw_item_id: UUID                                  # proveniência (filtro 1)
    statement: str
    epistemic_status: Optional[EpistemicStatus] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    source_reliability: ReliabilityTier = ReliabilityTier.UNKNOWN
    category: Optional[str] = None
    country: Optional[str] = None
    scientific_area: Optional[str] = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    pipeline_status: PipelineStatus = PipelineStatus.IN_FILTER
    requires_human_review: bool = False
    review_reason: Optional[str] = None


class Classification(_Base):
    """knowledge.classifications — resultado de UM filtro sobre UMA claim.
    É o trilho de auditoria que torna o sistema 'inteligência verificável'."""
    id: Optional[UUID] = None
    claim_id: Optional[UUID] = None
    filter: FilterKey
    result: FilterResult
    rationale: Optional[str] = None
    detail: dict[str, Any] = Field(default_factory=dict)
    automated: bool = True
    model: Optional[str] = None
    prompt_version: Optional[str] = None



class Event(_Base):
    """knowledge.events — evento validado e promovido. Memória permanente."""
    id: Optional[UUID] = None
    primary_claim_id: Optional[UUID] = None
    title: str
    summary: Optional[str] = None
    epistemic_status: EpistemicStatus                  # rótulo FINAL (obrigatório)
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    category: Optional[str] = None
    country: Optional[str] = None
    scientific_area: Optional[str] = None
    entities: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    occurred_at: Optional[datetime] = None
    pipeline_status: PipelineStatus = PipelineStatus.VALIDATED
    requires_human_review: bool = False
    review_decision: ReviewDecision = ReviewDecision.PENDING
    validated_by: Optional[str] = None
    validated_at: Optional[datetime] = None


class Contradiction(_Base):
    """knowledge.contradictions — filtro 5. Liga claim nova a evento em conflito."""
    id: Optional[UUID] = None
    claim_id: UUID
    conflicting_event_id: UUID
    kind: str = "direct"                                # direct | partial | supersedes
    similarity: Optional[float] = Field(default=None, ge=0, le=1)
    detail: Optional[str] = None
    resolved: bool = False
    resolution: Optional[str] = None


class Bulletin(_Base):
    """knowledge.bulletins — o boletim diário."""
    id: Optional[UUID] = None
    bulletin_date: date
    status: BulletinStatus = BulletinStatus.DRAFT
    title: Optional[str] = None
    body: Optional[str] = None                          # markdown
    channel: str = "whatsapp"
    approved_by: Optional[str] = None
    sent_at: Optional[datetime] = None


# =====================================================================
# Objetos de transferência do pipeline (não são tabelas — são contratos
# que fluem entre módulos).
# =====================================================================

class FilterContext(_Base):
    """O que um filtro precisa além da claim para decidir.
    Ex.: o item bruto (proveniência), eventos relacionados (contradição)."""
    raw_item: Optional[RawItem] = None
    related_events: list[Event] = Field(default_factory=list)


# Decisão de roteamento após os filtros. A LÓGICA que a produz vive no
# Documento 113 — aqui é só o formato do resultado.
RoutingDecision = Literal["pass", "escalate", "reject"]


class FilterReport(_Base):
    """Veredito agregado dos filtros sobre uma claim.
    Contrato de saída do módulo `filters` → entrada da persistência/curadoria."""
    claim_id: Optional[UUID] = None
    classifications: list[Classification] = Field(default_factory=list)
    decision: RoutingDecision
    requires_human_review: bool = False
    notes: Optional[str] = None


__all__ = [
    # enums
    "EpistemicStatus", "PipelineStatus", "ReliabilityTier", "SourceKind",
    "FetchStatus", "FilterKey", "FilterResult", "ReviewDecision", "BulletinStatus",
    # raw
    "Source", "FetchRun", "RawItem",
    # knowledge
    "Claim", "Classification", "Event", "Contradiction", "Bulletin",
    # pipeline
    "FilterContext", "FilterReport", "RoutingDecision",
]
