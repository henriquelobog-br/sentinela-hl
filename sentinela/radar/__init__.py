"""Event Radar — Documento 112.7E.

Significância objetiva do evento a partir do ConceptFingerprint.
Determinístico, sem LLM, sem rede, sem consulta à Taxonomia.
"""

from .engine import (
    EventRadar,
    EventRadarError,
    EventRadarInputError,
    EventRadarVersionError,
)
from .models import (
    EventRadarConfig,
    EventRadarLimits,
    EventRadarResult,
    EventRadarThresholds,
    EventSignificance,
    RadarDomain,
    RadarSignal,
)

__all__ = [
    "EventRadar",
    "EventRadarConfig",
    "EventRadarError",
    "EventRadarInputError",
    "EventRadarLimits",
    "EventRadarResult",
    "EventRadarThresholds",
    "EventRadarVersionError",
    "EventSignificance",
    "RadarDomain",
    "RadarSignal",
]
