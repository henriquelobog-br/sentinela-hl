"""Modelos do Event Radar — Documento 112.7E §9-§12, §18, §20-§21."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventSignificance(str, Enum):
    """112.7E §10 — nível de significância objetiva."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class RadarDomain(str, Enum):
    """112.7E §12 — os oito domínios canônicos da V1."""

    ATMOSPHERE = "atmosphere"
    ASTRONOMY = "astronomy"
    OCEANOGRAPHY = "oceanography"
    GEOLOGY = "geology"
    VOLCANOLOGY = "volcanology"
    SEISMOLOGY = "seismology"
    SCIENTIFIC_GEOPOLITICS = "scientific_geopolitics"
    REMOTE_SENSING = "remote_sensing"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RadarSignal(_Base):
    """112.7E §12 — sinal do catálogo versionado."""

    id: str = Field(min_length=1)
    domain: RadarDomain
    description: str = Field(min_length=1)
    concept_ids: tuple[str, ...]
    weight: float = Field(ge=0.0, le=1.0)
    reason_template: str = Field(min_length=1)
    enabled: bool = True

    @model_validator(mode="after")
    def _unique_concepts(self) -> "RadarSignal":
        if len(set(self.concept_ids)) != len(self.concept_ids):
            raise ValueError("concept_ids não pode conter duplicatas")
        if not self.concept_ids:
            raise ValueError("concept_ids não pode ser vazio")
        return self


class EventRadarThresholds(_Base):
    """112.7E §11/§18 — thresholds V1, estritamente crescentes."""

    moderate_min: float = Field(default=0.25, ge=0.0, le=1.0)
    high_min: float = Field(default=0.50, ge=0.0, le=1.0)
    critical_min: float = Field(default=0.75, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _v1_values(self) -> "EventRadarThresholds":
        expected = (0.25, 0.50, 0.75)
        actual = (self.moderate_min, self.high_min, self.critical_min)
        if actual != expected:
            raise ValueError(
                f"thresholds V1 devem ser exatamente {expected}: {actual}"
            )
        return self


class EventRadarLimits(_Base):
    """112.7E §18 — limites operacionais, obrigatórios e positivos."""

    maximum_signals: int = Field(gt=0)
    maximum_concepts_per_signal: int = Field(gt=0)
    maximum_signal_id_length: int = Field(gt=0)
    maximum_description_length: int = Field(gt=0)
    maximum_reason_template_length: int = Field(gt=0)


class EventRadarConfig(_Base):
    """112.7E §18 — configuração imutável do radar."""

    config_version: str = Field(min_length=1)
    algorithm_version: str = Field(min_length=1)
    compatible_taxonomy_version: str = Field(min_length=1)
    thresholds: EventRadarThresholds
    limits: EventRadarLimits
    signals: tuple[RadarSignal, ...]

    @model_validator(mode="after")
    def _catalog(self) -> "EventRadarConfig":
        if not self.signals:
            raise ValueError("pelo menos um sinal deve ser configurado")
        ids = [signal.id for signal in self.signals]
        if len(set(ids)) != len(ids):
            raise ValueError("IDs de sinais devem ser únicos")
        if len(self.signals) > self.limits.maximum_signals:
            raise ValueError("quantidade de sinais excede maximum_signals")
        for signal in self.signals:
            if (
                len(signal.concept_ids)
                > self.limits.maximum_concepts_per_signal
            ):
                raise ValueError(
                    f"sinal {signal.id!r} excede maximum_concepts_per_signal"
                )
            if len(signal.id) > self.limits.maximum_signal_id_length:
                raise ValueError(
                    f"sinal {signal.id!r} excede maximum_signal_id_length"
                )
            if len(signal.description) > self.limits.maximum_description_length:
                raise ValueError(
                    f"sinal {signal.id!r} excede maximum_description_length"
                )
            if (
                len(signal.reason_template)
                > self.limits.maximum_reason_template_length
            ):
                raise ValueError(
                    f"sinal {signal.id!r} excede maximum_reason_template_length"
                )
        return self


class EventRadarResult(_Base):
    """112.7E §9 — saída: imutável, sem timestamp, sem event_id."""

    significance_score: float = Field(ge=0.0, le=1.0)
    significance_level: EventSignificance
    matched_signals: tuple[str, ...]
    reasons: tuple[str, ...]


__all__ = [
    "EventRadarConfig",
    "EventRadarLimits",
    "EventRadarResult",
    "EventRadarThresholds",
    "EventSignificance",
    "RadarDomain",
    "RadarSignal",
]
