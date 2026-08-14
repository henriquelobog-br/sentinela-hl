"""Contrato imutavel da Editorial Sismologia v1."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SeismicEditorialContent(BaseModel):
    """Projecao editorial separada do Event canonico."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    editorial_title: str = Field(max_length=120)
    editorial_subtitle: str = Field(max_length=180)
    editorial_summary: str = Field(max_length=800)
    seo_title: str = Field(max_length=70)
    seo_description: str = Field(max_length=180)
    seo_keywords: tuple[str, ...] = Field(default=(), max_length=8)
