"""Configuração do Interest Engine — Documento 112.7F §31-§37.

Modelos estritos, frozen, `extra="forbid"`. Todos os campos são
obrigatórios: não existem defaults ocultos nem constantes mágicas no engine.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class InterestReasonType(str, Enum):
    """112.7F §36 — tipos vinculantes de razão sistêmica."""

    NO_POSITIVE_MATCH = "no_positive_match"
    RADAR_CONTRIBUTION = "radar_contribution"
    CRITICAL_WITHOUT_ALIGNMENT = "critical_without_alignment"
    HUMAN_REVIEW = "human_review"
    IGNORED_V1_FIELDS = "ignored_v1_fields"


# placeholders obrigatórios por template (112.7F §36)
_REQUIRED_PLACEHOLDERS: dict[str, frozenset[str]] = {
    "positive_global_match": frozenset(
        {
            "fingerprint_concept_id",
            "domain_id",
            "scope",
            "channel",
            "profile_item_id",
            "fingerprint_weight",
            "profile_weight",
            "channel_weight",
            "contribution",
        }
    ),
    "positive_research_line_match": frozenset(
        {
            "fingerprint_concept_id",
            "domain_id",
            "scope",
            "channel",
            "profile_item_id",
            "research_line_id",
            "fingerprint_weight",
            "profile_weight",
            "line_priority",
            "channel_weight",
            "contribution",
        }
    ),
    "no_positive_match": frozenset({"event_id", "researcher_id"}),
    "radar_contribution": frozenset(
        {
            "significance_score",
            "significance_level",
            "significance_factor",
            "significance_contribution",
        }
    ),
    "critical_without_alignment": frozenset(
        {
            "significance_score",
            "significance_level",
            "significance_contribution",
        }
    ),
    "human_review": frozenset({"event_id", "pipeline_status"}),
    "ignored_v1_fields": frozenset({"ignored_fields"}),
}

_V1_SYSTEM_ORDER = (
    InterestReasonType.NO_POSITIVE_MATCH,
    InterestReasonType.RADAR_CONTRIBUTION,
    InterestReasonType.CRITICAL_WITHOUT_ALIGNMENT,
    InterestReasonType.HUMAN_REVIEW,
    InterestReasonType.IGNORED_V1_FIELDS,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_template(name: str, template: str) -> str:
    """Gramática normativa (§36): placeholders simples `{identifier}`,
    cada obrigatório exatamente uma vez, nenhum adicional."""
    found = _PLACEHOLDER_RE.findall(template)
    residue = _PLACEHOLDER_RE.sub("", template)
    if "{" in residue or "}" in residue:
        raise ValueError(f"template {name}: chaves inválidas fora de placeholder")
    required = _REQUIRED_PLACEHOLDERS[name]
    if set(found) != set(required) or len(found) != len(required):
        raise ValueError(
            f"template {name}: placeholders devem ser exatamente "
            f"{sorted(required)}"
        )
    return template


class InterestScoringConfig(_Strict):
    """112.7F §32 — fatores V1: exatamente 0.75 e 0.25."""

    relevance_factor: float = Field(ge=0.0, le=1.0)
    significance_factor: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _v1(self) -> "InterestScoringConfig":
        total = Decimal(str(self.relevance_factor)) + Decimal(
            str(self.significance_factor)
        )
        if total != Decimal("1"):
            raise ValueError(
                "relevance_factor + significance_factor deve ser 1.0"
            )
        if (self.relevance_factor, self.significance_factor) != (0.75, 0.25):
            raise ValueError("fatores V1 devem ser exatamente 0.75 e 0.25")
        return self


class InterestChannelWeights(_Strict):
    """112.7F §19/§33 — pesos efetivos V1 dos canais."""

    concept: float = Field(ge=0.0, le=1.0)
    domain: float = Field(ge=0.0, le=1.0)
    region: float = Field(ge=0.0, le=1.0)
    instrument: float = Field(ge=0.0, le=1.0)
    research_line: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _v1(self) -> "InterestChannelWeights":
        expected = {
            "concept": 1.00,
            "domain": 0.65,
            "region": 0.55,
            "instrument": 0.55,
            "research_line": 0.85,
        }
        actual = {
            "concept": self.concept,
            "domain": self.domain,
            "region": self.region,
            "instrument": self.instrument,
            "research_line": self.research_line,
        }
        if actual != expected:
            raise ValueError(f"channel weights V1 devem ser {expected}")
        return self


class InterestPriorityThresholds(_Strict):
    """112.7F §16/§34 — thresholds V1, estritamente crescentes."""

    moderate_min: float = Field(ge=0.0, le=1.0)
    high_min: float = Field(ge=0.0, le=1.0)
    urgent_min: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _v1(self) -> "InterestPriorityThresholds":
        expected = (0.25, 0.50, 0.75)
        actual = (self.moderate_min, self.high_min, self.urgent_min)
        if actual != expected:
            raise ValueError(
                f"thresholds V1 devem ser exatamente {expected}: {actual}"
            )
        return self


class InterestEngineLimits(_Strict):
    """112.7F §35 — limites operacionais V1, obrigatórios e positivos."""

    maximum_profile_domains: int = Field(gt=0)
    maximum_profile_concepts: int = Field(gt=0)
    maximum_profile_regions: int = Field(gt=0)
    maximum_profile_instruments: int = Field(gt=0)
    maximum_research_lines: int = Field(gt=0)
    maximum_items_per_research_line: int = Field(gt=0)
    maximum_total_research_line_items: int = Field(gt=0)
    maximum_fingerprint_concepts: int = Field(gt=0)
    maximum_matches: int = Field(gt=0)
    maximum_reason_length: int = Field(gt=0)


class InterestReasonTemplates(_Strict):
    """112.7F §36 — templates versionados, em português, validados."""

    system_reason_order: tuple[InterestReasonType, ...]
    positive_global_match: str = Field(min_length=1)
    positive_research_line_match: str = Field(min_length=1)
    no_positive_match: str = Field(min_length=1)
    radar_contribution: str = Field(min_length=1)
    critical_without_alignment: str = Field(min_length=1)
    human_review: str = Field(min_length=1)
    ignored_v1_fields: str = Field(min_length=1)

    @model_validator(mode="after")
    def _v1(self) -> "InterestReasonTemplates":
        if tuple(self.system_reason_order) != _V1_SYSTEM_ORDER:
            raise ValueError(
                "system_reason_order V1 deve ser "
                f"{[t.value for t in _V1_SYSTEM_ORDER]}"
            )
        for name in _REQUIRED_PLACEHOLDERS:
            _validate_template(name, getattr(self, name))
        return self


class InterestEngineConfig(_Strict):
    """112.7F §31 — contrato principal de configuração."""

    config_version: str = Field(min_length=1)
    algorithm_version: str = Field(min_length=1)
    compatible_taxonomy_version: str = Field(min_length=1)
    compatible_fingerprint_algorithm_version: str = Field(min_length=1)

    scoring: InterestScoringConfig
    channel_weights: InterestChannelWeights
    thresholds: InterestPriorityThresholds
    limits: InterestEngineLimits
    reason_templates: InterestReasonTemplates


__all__ = [
    "InterestChannelWeights",
    "InterestEngineConfig",
    "InterestEngineLimits",
    "InterestPriorityThresholds",
    "InterestReasonTemplates",
    "InterestReasonType",
    "InterestScoringConfig",
]
