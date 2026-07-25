"""Interest Engine — Documento 112.7F (happy path normativo).

Priorização científica personalizada: matching por igualdade exata de IDs
canônicos (§17), contribuições em Decimal (§20/§21/§23), relevance com
saturação (§23.2), priority = relevância × 0.75 + significância × 0.25
(§25), razões determinísticas por templates versionados (§28/§36).

Sem LLM, sem I/O, sem efeitos colaterais (§7).
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinela.core.models import Event, PipelineStatus, ReviewDecision
from sentinela.fingerprint.models import ConceptFingerprint
from sentinela.radar.models import EventRadarResult, EventSignificance

from .config import InterestEngineConfig, InterestReasonType
from .errors import (
    InterestEngineCompatibilityError,
    InterestEngineInputError,
    InterestEngineVersionError,
    InterestEventFingerprintMismatchError,
)
from .models import ResearchProfile

SUPPORTED_ALGORITHM_VERSION = "1.0"

_QUANTUM = Decimal("0.000001")


# ------------------------------------------------------------------ enums
class InterestMatchScope(str, Enum):
    """112.7F §15 — onde o item está no perfil."""

    GLOBAL = "global"
    RESEARCH_LINE = "research_line"


class InterestMatchChannel(str, Enum):
    """112.7F §15 — qual tipo de item produziu o match."""

    CONCEPT = "concept"
    DOMAIN = "domain"
    REGION = "region"
    INSTRUMENT = "instrument"


class InterestPriority(str, Enum):
    """112.7F §15 — nível de prioridade personalizada."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    URGENT = "urgent"


# ranks normativos (§15) — única forma de ordenar enums
_SCOPE_RANK = {InterestMatchScope.GLOBAL: 0, InterestMatchScope.RESEARCH_LINE: 1}
_CHANNEL_RANK = {
    InterestMatchChannel.CONCEPT: 0,
    InterestMatchChannel.DOMAIN: 1,
    InterestMatchChannel.REGION: 2,
    InterestMatchChannel.INSTRUMENT: 3,
}


# ---------------------------------------------------------------- modelos
class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InterestConceptMatch(_Strict):
    """112.7F §13 — exatamente uma contribuição; nunca consolida linhas."""

    fingerprint_concept_id: str
    domain_id: str
    scope: InterestMatchScope
    channel: InterestMatchChannel
    profile_item_id: str
    research_line_id: Optional[str]

    fingerprint_weight: float = Field(ge=0.0, le=1.0)
    profile_weight: float = Field(ge=0.0, le=1.0)
    line_priority: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    channel_weight: float = Field(ge=0.0, le=1.0)
    contribution: float = Field(ge=0.0, le=1.0)


class ResearchLineMatch(_Strict):
    """112.7F §14 — somente linhas com ao menos um contributing_match."""

    research_line_id: str
    line_priority: float = Field(ge=0.0, le=1.0)
    matched_concept_ids: tuple[str, ...]
    score: float = Field(ge=0.0, le=1.0)


class InterestResult(_Strict):
    """112.7F §12 — saída canônica do Interest Engine."""

    event_id: str
    researcher_id: str
    profile_version: str
    taxonomy_version: str

    relevance_score: float = Field(ge=0.0, le=1.0)
    priority_score: float = Field(ge=0.0, le=1.0)
    priority_level: InterestPriority

    significance_score: float = Field(ge=0.0, le=1.0)
    significance_level: EventSignificance

    matched_concepts: tuple[InterestConceptMatch, ...]
    matched_research_lines: tuple[ResearchLineMatch, ...]
    reasons: tuple[str, ...]

    requires_human_review: bool

    algorithm_version: str
    config_version: str

    @field_validator(
        "event_id",
        "researcher_id",
        "profile_version",
        "taxonomy_version",
        "algorithm_version",
        "config_version",
    )
    @classmethod
    def _trimmed(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("strings de identidade não podem ser vazias")
        return trimmed


# ----------------------------------------------------------- numérico (§23)
def _calculation_context() -> Context:
    """§23.1 — contexto de cálculo dedicado por chamada, prec=2048."""
    return Context(prec=2048, rounding=ROUND_HALF_EVEN)


def _quantization_context() -> Context:
    """§23.1 — contexto de quantização dedicado por chamada."""
    return Context(prec=2048, rounding=ROUND_HALF_EVEN)


def _quantize(value: Decimal, context: Context) -> Decimal:
    """Quantização pública de seis casas; zero negativo é proibido."""
    quantized = value.quantize(
        _QUANTUM, rounding=ROUND_HALF_EVEN, context=context
    )
    if quantized == 0:
        return Decimal("0.000000")
    return quantized


def _display(value: Decimal, context: Context) -> str:
    """§28 — formatação normativa: seis casas, sem locale, sem notação."""
    return format(_quantize(value, context), ".6f")


def _render(template: str, values: dict[str, str]) -> str:
    """§36 — interpolação por substituição direta de placeholders simples."""
    rendered = template
    for key, text in values.items():
        rendered = rendered.replace("{" + key + "}", text)
    return rendered


# ------------------------------------------------------------------ engine
class _Candidate:
    """Match bruto antes da classificação contributiva (§22.1)."""

    __slots__ = (
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
        "raw_contribution",
    )

    def __init__(
        self,
        *,
        fingerprint_concept_id: str,
        domain_id: str,
        scope: InterestMatchScope,
        channel: InterestMatchChannel,
        profile_item_id: str,
        research_line_id: Optional[str],
        fingerprint_weight: float,
        profile_weight: float,
        line_priority: Optional[float],
        channel_weight: float,
        raw_contribution: Decimal,
    ) -> None:
        self.fingerprint_concept_id = fingerprint_concept_id
        self.domain_id = domain_id
        self.scope = scope
        self.channel = channel
        self.profile_item_id = profile_item_id
        self.research_line_id = research_line_id
        self.fingerprint_weight = fingerprint_weight
        self.profile_weight = profile_weight
        self.line_priority = line_priority
        self.channel_weight = channel_weight
        self.raw_contribution = raw_contribution

    def dedup_key(self) -> tuple:
        """§22 — chave canônica de contribuição."""
        return (
            _SCOPE_RANK[self.scope],
            _CHANNEL_RANK[self.channel],
            self.profile_item_id,
            self.fingerprint_concept_id,
        )


class InterestEngine:
    """112.7F §7 — `engine.evaluate(event, fingerprint, radar, profile)`."""

    def __init__(self, config: InterestEngineConfig) -> None:
        if config.algorithm_version != SUPPORTED_ALGORITHM_VERSION:
            raise InterestEngineVersionError(
                f"algorithm_version {config.algorithm_version!r} não "
                f"suportado; esperado {SUPPORTED_ALGORITHM_VERSION!r}"
            )
        self._config = config

    def evaluate(
        self,
        event: Event,
        fingerprint: ConceptFingerprint,
        radar_result: EventRadarResult,
        profile: ResearchProfile,
    ) -> InterestResult:
        config = self._config
        calc = _calculation_context()
        quant = _quantization_context()

        # ------------------------------------------ validação estrutural
        if not isinstance(event, Event):
            raise InterestEngineInputError("event é obrigatório")
        if not isinstance(fingerprint, ConceptFingerprint):
            raise InterestEngineInputError("fingerprint é obrigatório")
        if not isinstance(radar_result, EventRadarResult):
            raise InterestEngineInputError("radar_result é obrigatório")
        if not isinstance(profile, ResearchProfile):
            raise InterestEngineInputError("profile é obrigatório")

        if event.id is None:
            raise InterestEngineInputError("event.id é obrigatório")
        if fingerprint.event_id is None:
            raise InterestEngineInputError(
                "fingerprint.event_id é obrigatório"
            )
        if event.id != fingerprint.event_id:
            raise InterestEventFingerprintMismatchError(
                f"event.id {event.id} != fingerprint.event_id "
                f"{fingerprint.event_id}"
            )

        # §10.2 — compatibilidade tríplice + versão do fingerprint
        if not (
            profile.taxonomy_version
            == fingerprint.taxonomy_version
            == config.compatible_taxonomy_version
        ):
            raise InterestEngineCompatibilityError(
                "taxonomy_version divergente: "
                f"profile={profile.taxonomy_version!r}, "
                f"fingerprint={fingerprint.taxonomy_version!r}, "
                f"config={config.compatible_taxonomy_version!r}"
            )
        if (
            fingerprint.algorithm_version
            != config.compatible_fingerprint_algorithm_version
        ):
            raise InterestEngineCompatibilityError(
                f"fingerprint.algorithm_version "
                f"{fingerprint.algorithm_version!r} incompatível com "
                f"{config.compatible_fingerprint_algorithm_version!r}"
            )

        # §11 — estados elegíveis (allowlist explícita)
        if event.review_decision is ReviewDecision.REJECTED:
            raise InterestEngineInputError(
                "evento rejeitado pela curadoria é inelegível"
            )
        if event.pipeline_status not in (
            PipelineStatus.VALIDATED,
            PipelineStatus.ESCALATED,
        ):
            raise InterestEngineInputError(
                f"pipeline_status {event.pipeline_status.value!r} inelegível"
            )
        if event.pipeline_status is PipelineStatus.ESCALATED:
            requires_human_review = True
        else:
            if not isinstance(event.requires_human_review, bool):
                raise InterestEngineInputError(
                    "event.requires_human_review deve ser bool"
                )
            requires_human_review = event.requires_human_review

        # §35 — limites operacionais (aceitar exatamente o limite)
        limits = config.limits
        if len(fingerprint.concepts) > limits.maximum_fingerprint_concepts:
            raise InterestEngineInputError(
                "fingerprint excede maximum_fingerprint_concepts"
            )

        # ------------------------------------------------ matching (§17)
        candidates = self._match(fingerprint, profile, calc)
        if len(candidates) > limits.maximum_matches:
            raise InterestEngineInputError(
                "quantidade de matches excede maximum_matches"
            )

        # §22 — deduplicação pela chave canônica
        deduped: dict[tuple, _Candidate] = {}
        for candidate in candidates:
            deduped.setdefault(candidate.dedup_key(), candidate)
        ordered_candidates = [
            deduped[key] for key in sorted(deduped)
        ]

        # §22.1 — contributing_match: public_contribution > 0
        contributing: list[tuple[_Candidate, Decimal]] = []
        for candidate in ordered_candidates:
            public = _quantize(candidate.raw_contribution, quant)
            if public > Decimal("0.000000"):
                contributing.append((candidate, public))

        # §23.2 — relevance: saturação após a soma Decimal completa
        relevance_raw = min(
            Decimal("1"),
            sum(
                (candidate.raw_contribution for candidate, _ in contributing),
                Decimal("0"),
            ),
        )
        relevance_score = _quantize(relevance_raw, quant)

        # §24 — score por linha de pesquisa
        line_matches = self._line_scores(contributing, calc, quant)

        # §25 — priority: relevância saturada não quantizada × 0.75
        #       + significância (copiada do Radar) × 0.25
        priority_raw = (
            relevance_raw * Decimal(str(config.scoring.relevance_factor))
            + Decimal(str(radar_result.significance_score))
            * Decimal(str(config.scoring.significance_factor))
        )
        priority_score = _quantize(min(Decimal("1"), priority_raw), quant)

        # §16 — nível derivado do priority_score público quantizado
        thresholds = config.thresholds
        if priority_score >= Decimal(str(thresholds.urgent_min)):
            priority_level = InterestPriority.URGENT
        elif priority_score >= Decimal(str(thresholds.high_min)):
            priority_level = InterestPriority.HIGH
        elif priority_score >= Decimal(str(thresholds.moderate_min)):
            priority_level = InterestPriority.MODERATE
        else:
            priority_level = InterestPriority.LOW

        # §27.1 — matched_concepts: contribution DESC, depois ranks/IDs
        contributing.sort(
            key=lambda pair: (
                -pair[1],
                _SCOPE_RANK[pair[0].scope],
                _CHANNEL_RANK[pair[0].channel],
                pair[0].profile_item_id,
                pair[0].fingerprint_concept_id,
            )
        )
        matched_concepts = tuple(
            InterestConceptMatch(
                fingerprint_concept_id=c.fingerprint_concept_id,
                domain_id=c.domain_id,
                scope=c.scope,
                channel=c.channel,
                profile_item_id=c.profile_item_id,
                research_line_id=c.research_line_id,
                fingerprint_weight=c.fingerprint_weight,
                profile_weight=c.profile_weight,
                line_priority=c.line_priority,
                channel_weight=c.channel_weight,
                contribution=float(public),
            )
            for c, public in contributing
        )

        # §28/§36 — razões determinísticas
        reasons = self._reasons(
            event=event,
            profile=profile,
            radar_result=radar_result,
            contributing=contributing,
            requires_human_review=requires_human_review,
            quant=quant,
        )

        return InterestResult(
            event_id=str(event.id),
            researcher_id=profile.researcher.id,
            profile_version=str(profile.researcher.version),
            taxonomy_version=profile.taxonomy_version,
            relevance_score=float(relevance_score),
            priority_score=float(priority_score),
            priority_level=priority_level,
            significance_score=radar_result.significance_score,
            significance_level=radar_result.significance_level,
            matched_concepts=matched_concepts,
            matched_research_lines=line_matches,
            reasons=reasons,
            requires_human_review=requires_human_review,
            algorithm_version=config.algorithm_version,
            config_version=config.config_version,
        )

    # -------------------------------------------------- matching interno
    def _match(
        self,
        fingerprint: ConceptFingerprint,
        profile: ResearchProfile,
        calc: Context,
    ) -> list[_Candidate]:
        """§17 — somente igualdade exata entre IDs canônicos."""
        weights = self._config.channel_weights
        global_channel_weight = {
            InterestMatchChannel.CONCEPT: weights.concept,
            InterestMatchChannel.DOMAIN: weights.domain,
            InterestMatchChannel.REGION: weights.region,
            InterestMatchChannel.INSTRUMENT: weights.instrument,
        }
        candidates: list[_Candidate] = []

        def multiply(*factors: float) -> Decimal:
            result = Decimal("1")
            for factor in factors:
                result = calc.multiply(result, Decimal(str(factor)))
            return result

        def add(
            signal,
            *,
            scope: InterestMatchScope,
            channel: InterestMatchChannel,
            profile_item_id: str,
            profile_weight: float,
            research_line_id: Optional[str] = None,
            line_priority: Optional[float] = None,
        ) -> None:
            if scope is InterestMatchScope.GLOBAL:
                channel_weight = global_channel_weight[channel]
                raw = multiply(
                    signal.weight, profile_weight, channel_weight
                )
            else:
                channel_weight = weights.research_line
                raw = multiply(
                    signal.weight,
                    profile_weight,
                    line_priority if line_priority is not None else 1.0,
                    channel_weight,
                )
            candidates.append(
                _Candidate(
                    fingerprint_concept_id=signal.concept_id,
                    domain_id=signal.domain_id,
                    scope=scope,
                    channel=channel,
                    profile_item_id=profile_item_id,
                    research_line_id=research_line_id,
                    fingerprint_weight=signal.weight,
                    profile_weight=profile_weight,
                    line_priority=line_priority,
                    channel_weight=channel_weight,
                    raw_contribution=raw,
                )
            )

        for signal in fingerprint.concepts:
            # §17.1 — conceito global
            for item in profile.concepts:
                if item.concept_id == signal.concept_id:
                    add(
                        signal,
                        scope=InterestMatchScope.GLOBAL,
                        channel=InterestMatchChannel.CONCEPT,
                        profile_item_id=item.concept_id,
                        profile_weight=item.weight,
                    )
            # §17.2 — domínio
            for item in profile.domains:
                if item.domain_id == signal.domain_id:
                    add(
                        signal,
                        scope=InterestMatchScope.GLOBAL,
                        channel=InterestMatchChannel.DOMAIN,
                        profile_item_id=item.domain_id,
                        profile_weight=item.weight,
                    )
            # §17.3 — região
            for item in profile.regions:
                if item.concept_id == signal.concept_id:
                    add(
                        signal,
                        scope=InterestMatchScope.GLOBAL,
                        channel=InterestMatchChannel.REGION,
                        profile_item_id=item.concept_id,
                        profile_weight=item.weight,
                    )
            # §17.4 — instrumento
            for item in profile.instruments:
                if item.concept_id == signal.concept_id:
                    add(
                        signal,
                        scope=InterestMatchScope.GLOBAL,
                        channel=InterestMatchChannel.INSTRUMENT,
                        profile_item_id=item.concept_id,
                        profile_weight=item.weight,
                    )
            # §17.5 — linhas de pesquisa
            for line in profile.research_lines:
                for item in line.concepts:
                    if item.concept_id == signal.concept_id:
                        add(
                            signal,
                            scope=InterestMatchScope.RESEARCH_LINE,
                            channel=InterestMatchChannel.CONCEPT,
                            profile_item_id=f"{line.id}:{item.concept_id}",
                            profile_weight=item.weight,
                            research_line_id=line.id,
                            line_priority=line.priority,
                        )
                for item in line.regions:
                    if item.concept_id == signal.concept_id:
                        add(
                            signal,
                            scope=InterestMatchScope.RESEARCH_LINE,
                            channel=InterestMatchChannel.REGION,
                            profile_item_id=f"{line.id}:{item.concept_id}",
                            profile_weight=item.weight,
                            research_line_id=line.id,
                            line_priority=line.priority,
                        )
                for item in line.instruments:
                    if item.concept_id == signal.concept_id:
                        add(
                            signal,
                            scope=InterestMatchScope.RESEARCH_LINE,
                            channel=InterestMatchChannel.INSTRUMENT,
                            profile_item_id=f"{line.id}:{item.concept_id}",
                            profile_weight=item.weight,
                            research_line_id=line.id,
                            line_priority=line.priority,
                        )
        return candidates

    def _line_scores(
        self,
        contributing: list[tuple[_Candidate, Decimal]],
        calc: Context,
        quant: Context,
    ) -> tuple[ResearchLineMatch, ...]:
        """§24 — soma por linha, saturação, quantização de seis casas."""
        by_line: dict[str, list[_Candidate]] = {}
        line_priority: dict[str, float] = {}
        for candidate, _ in contributing:
            if candidate.scope is not InterestMatchScope.RESEARCH_LINE:
                continue
            assert candidate.research_line_id is not None
            by_line.setdefault(candidate.research_line_id, []).append(
                candidate
            )
            line_priority[candidate.research_line_id] = (
                candidate.line_priority
                if candidate.line_priority is not None
                else 1.0
            )

        matches: list[ResearchLineMatch] = []
        for line_id, members in by_line.items():
            raw = min(
                Decimal("1"),
                sum(
                    (m.raw_contribution for m in members),
                    Decimal("0"),
                ),
            )
            score = _quantize(raw, quant)
            concept_ids = tuple(
                sorted({m.fingerprint_concept_id for m in members})
            )
            matches.append(
                ResearchLineMatch(
                    research_line_id=line_id,
                    line_priority=line_priority[line_id],
                    matched_concept_ids=concept_ids,
                    score=float(score),
                )
            )

        # §24 — score DESC, line_priority DESC, research_line_id ASC
        matches.sort(
            key=lambda m: (
                -m.score,
                -Decimal(str(m.line_priority)),
                m.research_line_id,
            )
        )
        return tuple(matches)

    # ------------------------------------------------- razões (§28/§36)
    def _reasons(
        self,
        *,
        event: Event,
        profile: ResearchProfile,
        radar_result: EventRadarResult,
        contributing: list[tuple[_Candidate, Decimal]],
        requires_human_review: bool,
        quant: Context,
    ) -> tuple[str, ...]:
        config = self._config
        templates = config.reason_templates
        maximum = config.limits.maximum_reason_length
        reasons: list[str] = []

        def emit(text: str) -> None:
            if len(text) > maximum:
                raise InterestEngineInputError(
                    "razão renderizada excede maximum_reason_length"
                )
            reasons.append(text)

        # razões positivas, uma por contributing_match, na ordenação canônica
        for candidate, public in contributing:
            values = {
                "fingerprint_concept_id": candidate.fingerprint_concept_id,
                "domain_id": candidate.domain_id,
                "scope": candidate.scope.value,
                "channel": candidate.channel.value,
                "profile_item_id": candidate.profile_item_id,
                "fingerprint_weight": _display(
                    Decimal(str(candidate.fingerprint_weight)), quant
                ),
                "profile_weight": _display(
                    Decimal(str(candidate.profile_weight)), quant
                ),
                "channel_weight": _display(
                    Decimal(str(candidate.channel_weight)), quant
                ),
                "contribution": _display(public, quant),
            }
            if candidate.scope is InterestMatchScope.RESEARCH_LINE:
                values["research_line_id"] = (
                    candidate.research_line_id or ""
                )
                values["line_priority"] = _display(
                    Decimal(
                        str(
                            candidate.line_priority
                            if candidate.line_priority is not None
                            else 1.0
                        )
                    ),
                    quant,
                )
                emit(
                    _render(templates.positive_research_line_match, values)
                )
            else:
                emit(_render(templates.positive_global_match, values))

        # razões sistêmicas, na ordem configurada
        significance_contribution = Decimal(
            str(radar_result.significance_score)
        ) * Decimal(str(config.scoring.significance_factor))

        for reason_type in templates.system_reason_order:
            if reason_type is InterestReasonType.NO_POSITIVE_MATCH:
                if not contributing:
                    emit(
                        _render(
                            templates.no_positive_match,
                            {
                                "event_id": str(event.id),
                                "researcher_id": profile.researcher.id,
                            },
                        )
                    )
            elif reason_type is InterestReasonType.RADAR_CONTRIBUTION:
                emit(
                    _render(
                        templates.radar_contribution,
                        {
                            "significance_score": _display(
                                Decimal(
                                    str(radar_result.significance_score)
                                ),
                                quant,
                            ),
                            "significance_level": radar_result.significance_level.value,
                            "significance_factor": _display(
                                Decimal(
                                    str(config.scoring.significance_factor)
                                ),
                                quant,
                            ),
                            "significance_contribution": _display(
                                significance_contribution, quant
                            ),
                        },
                    )
                )
            elif reason_type is InterestReasonType.CRITICAL_WITHOUT_ALIGNMENT:
                if (
                    radar_result.significance_level
                    is EventSignificance.CRITICAL
                    and not contributing
                ):
                    emit(
                        _render(
                            templates.critical_without_alignment,
                            {
                                "significance_score": _display(
                                    Decimal(
                                        str(
                                            radar_result.significance_score
                                        )
                                    ),
                                    quant,
                                ),
                                "significance_level": radar_result.significance_level.value,
                                "significance_contribution": _display(
                                    significance_contribution, quant
                                ),
                            },
                        )
                    )
            elif reason_type is InterestReasonType.HUMAN_REVIEW:
                if requires_human_review:
                    emit(
                        _render(
                            templates.human_review,
                            {
                                "event_id": str(event.id),
                                "pipeline_status": event.pipeline_status.value,
                            },
                        )
                    )
            elif reason_type is InterestReasonType.IGNORED_V1_FIELDS:
                ignored = [
                    name
                    for name, filled in (
                        ("preferred_sources", bool(profile.preferred_sources)),
                        ("excluded_topics", bool(profile.excluded_topics)),
                    )
                    if filled
                ]
                if ignored:
                    emit(
                        _render(
                            templates.ignored_v1_fields,
                            {"ignored_fields": ", ".join(ignored)},
                        )
                    )

        return tuple(reasons)


__all__ = [
    "InterestConceptMatch",
    "InterestEngine",
    "InterestMatchChannel",
    "InterestMatchScope",
    "InterestPriority",
    "InterestResult",
    "ResearchLineMatch",
    "SUPPORTED_ALGORITHM_VERSION",
]
