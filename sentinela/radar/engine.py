"""Engine do Event Radar — Documento 112.7E §13-§16, §23.

Identificação de sinais (§13) → contribuição signal_weight × concept_weight
(§14) → saturação em 1.0 → arredondamento de 6 casas → EventSignificance
pelos thresholds V1 (§11) → razões determinísticas (§15).

Proibições honradas: nenhuma leitura de campos semânticos do Event, nenhuma
consulta à Taxonomia, nenhuma expansão, nenhuma fonte externa.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from sentinela.core.models import Event
from sentinela.fingerprint.models import ConceptFingerprint

from .models import (
    EventRadarConfig,
    EventRadarResult,
    EventSignificance,
    RadarSignal,
)

SUPPORTED_ALGORITHM_VERSION = "1.0"

_QUANTUM = Decimal("0.000001")
_REQUIRED_PLACEHOLDERS = {
    "signal_id",
    "concept_id",
    "signal_weight",
    "concept_weight",
    "contribution",
}


class EventRadarError(Exception):
    """Base dos erros públicos do Event Radar (112.7E §32)."""


class EventRadarInputError(EventRadarError):
    """Entradas estruturalmente inválidas ou inconsistentes."""


class EventRadarVersionError(EventRadarError):
    """Versão de algoritmo ou de taxonomia incompatível."""


def _format_decimal(value: Decimal) -> str:
    """§15: valores numéricos nas razões com seis casas decimais."""
    quantized = value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    if quantized == 0:
        quantized = Decimal("0.000000")
    return format(quantized, ".6f")


class EventRadar:
    """112.7E §23 — `radar.evaluate(event, fingerprint)`."""

    def __init__(self, config: EventRadarConfig) -> None:
        if config.algorithm_version != SUPPORTED_ALGORITHM_VERSION:
            raise EventRadarVersionError(
                f"algorithm_version {config.algorithm_version!r} não "
                f"suportado; esperado {SUPPORTED_ALGORITHM_VERSION!r}"
            )
        for signal in config.signals:
            if signal.enabled:
                placeholders = set()
                for chunk in signal.reason_template.split("{"):
                    if "}" in chunk:
                        placeholders.add(chunk.split("}", 1)[0])
                if placeholders != _REQUIRED_PLACEHOLDERS:
                    raise EventRadarInputError(
                        f"reason_template do sinal {signal.id!r} deve conter "
                        f"exatamente os placeholders {_REQUIRED_PLACEHOLDERS}"
                    )
        self._config = config

    def evaluate(
        self,
        event: Event,
        fingerprint: ConceptFingerprint,
    ) -> EventRadarResult:
        # §8.4 — consistência entre entradas antes de qualquer score
        if event is None or fingerprint is None:
            raise EventRadarInputError("event e fingerprint são obrigatórios")
        if event.id is None or fingerprint.event_id is None:
            raise EventRadarInputError(
                "event.id e fingerprint.event_id são obrigatórios"
            )
        if event.id != fingerprint.event_id:
            raise EventRadarInputError(
                "event.id diverge de fingerprint.event_id: "
                f"{event.id} != {fingerprint.event_id}"
            )
        if (
            fingerprint.taxonomy_version
            != self._config.compatible_taxonomy_version
        ):
            raise EventRadarVersionError(
                f"taxonomy_version {fingerprint.taxonomy_version!r} "
                f"incompatível com "
                f"{self._config.compatible_taxonomy_version!r}"
            )

        # §8.3 — conceitos elegíveis: direct_weight > 0 ou inherited > 0
        eligible = {
            signal.concept_id: signal
            for signal in fingerprint.concepts
            if signal.direct_weight > 0.0 or signal.inherited_weight > 0.0
        }

        # §13 — identificação de sinais
        activations: list[tuple[RadarSignal, str, Decimal]] = []
        for signal in self._config.signals:
            if not signal.enabled:
                continue
            candidates = [
                eligible[concept_id]
                for concept_id in signal.concept_ids
                if concept_id in eligible
            ]
            if not candidates:
                continue
            # maior ConceptSignal.weight; empate → menor concept_id (§13)
            best = min(
                candidates,
                key=lambda concept: (-concept.weight, concept.concept_id),
            )
            contribution = Decimal(str(signal.weight)) * Decimal(
                str(best.weight)
            )
            activations.append((signal, best.concept_id, contribution))

        # §14 — score: soma, saturação, arredondamento de 6 casas
        raw_score = sum(
            (contribution for _, _, contribution in activations),
            Decimal("0"),
        )
        bounded_score = min(Decimal("1"), raw_score)
        score = bounded_score.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
        if score == 0:
            score = Decimal("0.000000")

        # §11 — thresholds V1, limites inferiores inclusivos
        thresholds = self._config.thresholds
        if score >= Decimal(str(thresholds.critical_min)):
            level = EventSignificance.CRITICAL
        elif score >= Decimal(str(thresholds.high_min)):
            level = EventSignificance.HIGH
        elif score >= Decimal(str(thresholds.moderate_min)):
            level = EventSignificance.MODERATE
        else:
            level = EventSignificance.LOW

        # §9.1 — matched_signals lexicográfico crescente
        matched_signals = tuple(
            sorted(signal.id for signal, _, _ in activations)
        )

        # §15/§9.2 — razões: contribuição DESC, signal_id ASC
        ordered = sorted(activations, key=lambda a: (-a[2], a[0].id))
        reasons = tuple(
            signal.reason_template.replace("{signal_id}", signal.id)
            .replace("{concept_id}", concept_id)
            .replace("{signal_weight}", _format_decimal(Decimal(str(signal.weight))))
            .replace("{concept_weight}", _format_decimal(
                Decimal(str(eligible[concept_id].weight))
            ))
            .replace("{contribution}", _format_decimal(contribution))
            for signal, concept_id, contribution in ordered
        )

        return EventRadarResult(
            significance_score=float(score),
            significance_level=level,
            matched_signals=matched_signals,
            reasons=reasons,
        )
