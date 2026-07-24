"""
Sentinela HL — modelos do boletim (Documento 112.6A).

Modelo de domínio puro: nenhum campo visual, nenhuma decisão de apresentação,
nenhuma dependência de banco ou SQL. O mesmo BulletinModel poderá alimentar
HTML, WordPress, PDF, Markdown, API ou e-mail sem tocar a lógica científica
(ADR-006).

Reusa os enums de core.models — não duplica contrato.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sentinela.core.models import EpistemicStatus


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BulletinItem(_Base):
    """Um evento científico, organizado para o boletim.

    `requires_review` é preservado de propósito: um evento pode estar correto
    cientificamente e ainda exigir curadoria. Conhecimento validado != decisão
    editorial — quem publica é a curadoria, não este componente.
    """
    event_id: Optional[UUID] = None
    title: str
    summary: Optional[str] = None
    epistemic_status: EpistemicStatus
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    category: Optional[str] = None
    scientific_area: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    source_count: int = 0
    requires_review: bool = False


class BulletinSection(_Base):
    """Agrupamento por área científica (ou categoria, ou 'outros')."""
    title: str
    scientific_area: Optional[str] = None
    items: list[BulletinItem] = Field(default_factory=list)


class BulletinModel(_Base):
    """O boletim como conhecimento organizado — ainda não renderizado."""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_items: int = 0
    sections: list[BulletinSection] = Field(default_factory=list)


__all__ = ["BulletinItem", "BulletinSection", "BulletinModel"]
