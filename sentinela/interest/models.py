"""Modelos do Research Profile — Documento 112.7B.

O objeto final contém apenas identificadores canônicos da Scientific Taxonomy.
Este módulo não calcula relevância, matching ou score.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

Weight = Annotated[float, Field(ge=0.0, le=1.0)]
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_id(value: str) -> str:
    value = value.strip()
    if not _ID_RE.fullmatch(value):
        raise ValueError("o identificador deve usar snake_case ASCII")
    return value


class ResearchIdentity(_StrictModel):
    id: str
    name: str = Field(min_length=1)
    version: int = Field(ge=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_id(value)


class ResearchDomain(_StrictModel):
    domain_id: str
    weight: Weight = 1.0

    @field_validator("domain_id")
    @classmethod
    def validate_domain_id(cls, value: str) -> str:
        return _validate_id(value)


class ResearchConcept(_StrictModel):
    concept_id: str
    weight: Weight = 1.0

    @field_validator("concept_id")
    @classmethod
    def validate_concept_id(cls, value: str) -> str:
        return _validate_id(value)


class ResearchRegion(ResearchConcept):
    pass


class ResearchInstrument(ResearchConcept):
    pass


class PreferredSource(_StrictModel):
    source_id: str
    weight: Weight = 1.0

    @field_validator("source_id")
    @classmethod
    def validate_source_id(cls, value: str) -> str:
        return _validate_id(value)


class ResolutionRecord(_StrictModel):
    field: str = Field(min_length=1)
    input_term: str = Field(min_length=1)
    canonical_concept_id: str

    @field_validator("canonical_concept_id")
    @classmethod
    def validate_concept_id(cls, value: str) -> str:
        return _validate_id(value)


class ResearchLine(_StrictModel):
    id: str
    title: str = Field(min_length=1)
    description: str | None = None
    question: str | None = None
    priority: Weight = 1.0
    concepts: tuple[ResearchConcept, ...] = ()
    regions: tuple[ResearchRegion, ...] = ()
    instruments: tuple[ResearchInstrument, ...] = ()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _validate_id(value)


class ResearchProfile(_StrictModel):
    researcher: ResearchIdentity
    domains: tuple[ResearchDomain, ...] = ()
    concepts: tuple[ResearchConcept, ...] = ()
    regions: tuple[ResearchRegion, ...] = ()
    instruments: tuple[ResearchInstrument, ...] = ()
    preferred_sources: tuple[PreferredSource, ...] = ()
    excluded_topics: tuple[str, ...] = ()
    research_lines: tuple[ResearchLine, ...] = ()
    resolution_log: tuple[ResolutionRecord, ...] = ()

    @field_validator("excluded_topics")
    @classmethod
    def validate_exclusions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("excluded_topics não pode conter termo vazio")
        return values
