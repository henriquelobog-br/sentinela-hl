"""Contratos imutaveis da Editorial Vulcanologia v1."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from sentinela.core.models import Event


class VolcanicEditorialContent(BaseModel):
    """Projecao editorial separada dos Events canonicos."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    editorial_title: str = Field(max_length=120)
    editorial_subtitle: str = Field(max_length=180)
    editorial_summary: str = Field(max_length=800)
    seo_title: str = Field(max_length=70)
    seo_description: str = Field(max_length=180)
    seo_keywords: tuple[str, ...] = Field(default=(), max_length=8)


@dataclass(frozen=True)
class VolcanicEditorialUnit:
    """Unidade editorial deterministica sem perder Events membros."""

    editorial_group_id: str
    volcano_name: str
    volcano_number: str
    category: str
    member_events: tuple[Event, ...]
    representative_event: Event
    grouping_reason: str

    @property
    def member_event_ids(self) -> tuple[str, ...]:
        return tuple(str(event.id) for event in self.member_events)

    @property
    def representative_event_id(self) -> str:
        return str(self.representative_event.id)


__all__ = ["VolcanicEditorialContent", "VolcanicEditorialUnit"]
