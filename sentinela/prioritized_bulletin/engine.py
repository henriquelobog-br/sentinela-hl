"""Engine do Prioritized Bulletin — Documento 112.7G (happy path normativo).

Fluxo de build(): validações na ordem vinculante (associação §13,
homogeneidade §14, duplicidade §15, revisão §23) → deduplicação global por
identidade estruturada (§24-§26) → ordenação total (§27-§30) → agrupamento
por InterestPriority (§31-§34) → PrioritizedBulletin (§35-§36).

Puro, determinístico, sem I/O, sem recálculo de scores (§22).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sentinela.core.models import Event, PipelineStatus
from sentinela.interest.engine import InterestPriority, InterestResult

from .errors import (
    PrioritizedBulletinAssociationError,
    PrioritizedBulletinConfigError,
    PrioritizedBulletinContextMismatchError,
    PrioritizedBulletinDuplicateEntryError,
    PrioritizedBulletinInputError,
    PrioritizedBulletinLimitError,
    PrioritizedBulletinReviewMismatchError,
    PrioritizedBulletinVersionError,
)
from .models import (
    PrioritizedBulletin,
    PrioritizedBulletinConfig,
    PrioritizedBulletinDeduplicationPolicy,
    PrioritizedBulletinGroupingPolicy,
    PrioritizedBulletinItem,
    PrioritizedBulletinMember,
    PrioritizedBulletinRequest,
    PrioritizedBulletinSection,
    PrioritizedBulletinSectionType,
)

SUPPORTED_PRIORITIZED_BULLETIN_ALGORITHM_VERSION = "1.0"


class _Candidate:
    """Projeção defensiva (§12): captura de valores, imutável, sem
    referência ao Event original."""

    __slots__ = (
        "event_id",
        "dedup_key",
        "title",
        "summary",
        "scientific_area",
        "category",
        "source",
        "supporting_sources",
        "evidence",
        "event_status",
        "occurred_at",
        "validated_at",
        "relevance_score",
        "significance_score",
        "significance_level",
        "priority_score",
        "priority_level",
        "matched_concepts",
        "matched_research_lines",
        "reasons",
        "requires_human_review",
    )

    def __init__(self, event: Event, result: InterestResult) -> None:
        self.event_id = str(event.id)
        self.dedup_key = (
            ("PRIMARY_CLAIM", str(event.primary_claim_id))
            if event.primary_claim_id is not None
            else ("EVENT_ID", str(event.id))
        )
        self.title = event.title
        self.summary = event.summary
        self.scientific_area = event.scientific_area
        self.category = event.category
        self.source = event.source
        self.supporting_sources = event.supporting_sources
        self.evidence = tuple(dict(item) for item in event.evidence)
        self.event_status = event.event_status
        self.occurred_at = _as_utc(event.occurred_at)
        self.validated_at = _as_utc(event.validated_at)
        self.relevance_score = _normalize_zero(result.relevance_score)
        self.significance_score = _normalize_zero(result.significance_score)
        self.significance_level = result.significance_level
        self.priority_score = _normalize_zero(result.priority_score)
        self.priority_level = result.priority_level
        self.matched_concepts = result.matched_concepts
        self.matched_research_lines = result.matched_research_lines
        self.reasons = result.reasons
        self.requires_human_review = result.requires_human_review

    def sort_key(self) -> tuple:
        """§27 — chave total: priority DESC, review DESC, relevance DESC,
        significance DESC, occurred_at DESC (presente antes de None),
        validated_at DESC (presente antes de None), event_id ASC."""
        return (
            -self.priority_score,
            not self.requires_human_review,
            -self.relevance_score,
            -self.significance_score,
            _datetime_key(self.occurred_at),
            _datetime_key(self.validated_at),
            self.event_id,
        )


def _normalize_zero(value: float) -> float:
    """§22 — `-0.0` é normalizado para `0.0` na projeção pública."""
    return 0.0 if value == 0.0 else value


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """§21 — datetime timezone-aware convertido para UTC, ou None."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise PrioritizedBulletinInputError(
            f"datetime inválido: {value!r}"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise PrioritizedBulletinInputError(
            f"datetime deve ser timezone-aware: {value!r}"
        )
    return value.astimezone(timezone.utc)


def _datetime_key(value: Optional[datetime]) -> tuple:
    """Presente antes de None; instante UTC mais recente primeiro."""
    if value is None:
        return (1, 0.0)
    return (0, -value.timestamp())


class PrioritizedBulletinEngine:
    """112.7G §9 — `engine.build(request) -> PrioritizedBulletin`."""

    def __init__(self, config: PrioritizedBulletinConfig) -> None:
        if (
            config.algorithm_version
            != SUPPORTED_PRIORITIZED_BULLETIN_ALGORITHM_VERSION
        ):
            raise PrioritizedBulletinVersionError(
                f"algorithm_version {config.algorithm_version!r} não "
                f"suportado; esperado "
                f"{SUPPORTED_PRIORITIZED_BULLETIN_ALGORITHM_VERSION!r}"
            )
        if config.grouping_policy is not PrioritizedBulletinGroupingPolicy.PRIORITY:
            raise PrioritizedBulletinConfigError(
                "grouping_policy V1 deve ser PRIORITY"
            )
        if (
            config.deduplication_policy
            is not PrioritizedBulletinDeduplicationPolicy.PRIMARY_CLAIM_OR_EVENT_ID
        ):
            raise PrioritizedBulletinConfigError(
                "deduplication_policy V1 deve ser PRIMARY_CLAIM_OR_EVENT_ID"
            )
        self._config = config
        self._titles = {
            title.priority: title.title
            for title in config.section_titles
        }

    def build(
        self, request: PrioritizedBulletinRequest
    ) -> PrioritizedBulletin:
        config = self._config
        context = request.context

        if len(request.entries) > config.maximum_entries:
            raise PrioritizedBulletinLimitError(
                "request excede maximum_entries"
            )

        candidates: list[_Candidate] = []
        seen_keys: set[tuple] = set()
        for entry in request.entries:
            candidates.append(self._validate(entry, request, seen_keys))

        # §26 — deduplicação global, antes das seções
        groups: dict[tuple, list[_Candidate]] = {}
        for candidate in candidates:
            groups.setdefault(candidate.dedup_key, []).append(candidate)

        items: list[PrioritizedBulletinItem] = []
        for members in groups.values():
            if len(members) > config.maximum_group_members:
                raise PrioritizedBulletinLimitError(
                    "grupo excede maximum_group_members"
                )
            items.append(self._to_item(members))

        # §30 — itens ordenados pela chave total do representante
        items.sort(key=lambda item: _item_sort_key(item))

        # §31-§34 — agrupamento por InterestPriority, ordem configurada
        sections = self._sections(items)

        return PrioritizedBulletin(
            context=context,
            prioritized_bulletin_algorithm_version=config.algorithm_version,
            prioritized_bulletin_config_version=config.config_version,
            total_input_entries=len(request.entries),
            total_groups=len(groups),
            total_items=sum(len(section.items) for section in sections),
            sections=sections,
        )

    # --------------------------------------------------------- validações
    def _validate(
        self,
        entry,
        request: PrioritizedBulletinRequest,
        seen_keys: set[tuple],
    ) -> _Candidate:
        event = entry.event
        result = entry.interest_result
        context = request.context

        # §13 — associação Event–InterestResult
        if event is None or result is None:
            raise PrioritizedBulletinAssociationError(
                "entry deve conter event e interest_result"
            )
        if event.id is None:
            raise PrioritizedBulletinAssociationError(
                "event.id é obrigatório"
            )
        if not result.event_id or str(event.id) != result.event_id:
            raise PrioritizedBulletinAssociationError(
                f"str(event.id) {event.id} != interest_result.event_id "
                f"{result.event_id!r}"
            )

        # §14 — homogeneidade do request
        if (
            result.researcher_id != context.researcher_id
            or result.profile_version != context.profile_version
            or result.algorithm_version
            != context.interest_algorithm_version
            or result.config_version != context.interest_config_version
        ):
            raise PrioritizedBulletinContextMismatchError(
                "interest_result diverge do contexto do request"
            )

        # §15 — chave de avaliação única
        key = (
            result.event_id,
            result.researcher_id,
            result.profile_version,
            result.algorithm_version,
            result.config_version,
        )
        if key in seen_keys:
            raise PrioritizedBulletinDuplicateEntryError(
                f"chave de avaliação repetida: {key}"
            )
        seen_keys.add(key)

        # §23 — human review: valor esperado a partir do snapshot do Event
        if not isinstance(event.pipeline_status, PipelineStatus):
            raise PrioritizedBulletinInputError(
                "event.pipeline_status deve ser PipelineStatus válido"
            )
        if not isinstance(event.requires_human_review, bool):
            raise PrioritizedBulletinInputError(
                "event.requires_human_review deve ser bool estrito"
            )
        if not isinstance(result.requires_human_review, bool):
            raise PrioritizedBulletinInputError(
                "interest_result.requires_human_review deve ser bool estrito"
            )
        expected = (
            True
            if event.pipeline_status is PipelineStatus.ESCALATED
            else event.requires_human_review
        )
        if result.requires_human_review != expected:
            raise PrioritizedBulletinReviewMismatchError(
                f"requires_human_review {result.requires_human_review} "
                f"diverge do esperado {expected}"
            )

        return _Candidate(event, result)

    # ------------------------------------------------------------ saída
    def _to_item(
        self, members: list[_Candidate]
    ) -> PrioritizedBulletinItem:
        # §28-§29 — membros ordenados pela chave total; primeiro é o
        # representante (nunca seleção por primeira ocorrência)
        ordered = sorted(members, key=lambda m: m.sort_key())
        representative = ordered[0]

        member_models = tuple(
            PrioritizedBulletinMember(
                event_id=m.event_id,
                relevance_score=m.relevance_score,
                significance_score=m.significance_score,
                significance_level=m.significance_level,
                priority_score=m.priority_score,
                priority_level=m.priority_level,
                matched_concepts=m.matched_concepts,
                matched_research_lines=m.matched_research_lines,
                reasons=m.reasons,
                requires_human_review=m.requires_human_review,
            )
            for m in ordered
        )

        return PrioritizedBulletinItem(
            representative_event_id=representative.event_id,
            member_event_ids=tuple(m.event_id for m in ordered),
            title=representative.title,
            summary=representative.summary,
            scientific_area=representative.scientific_area,
            category=representative.category,
            source=representative.source,
            supporting_sources=representative.supporting_sources,
            evidence=representative.evidence,
            event_status=representative.event_status,
            occurred_at=representative.occurred_at,
            validated_at=representative.validated_at,
            relevance_score=representative.relevance_score,
            significance_score=representative.significance_score,
            significance_level=representative.significance_level,
            priority_score=representative.priority_score,
            priority_level=representative.priority_level,
            matched_concepts=representative.matched_concepts,
            matched_research_lines=representative.matched_research_lines,
            reasons=representative.reasons,
            # §23 — OR dos membros; não participa da ordenação
            requires_human_review=any(
                m.requires_human_review for m in ordered
            ),
            members=member_models,
        )

    def _sections(
        self, items: list[PrioritizedBulletinItem]
    ) -> tuple[PrioritizedBulletinSection, ...]:
        by_priority: dict[InterestPriority, list[PrioritizedBulletinItem]] = {}
        for item in items:
            by_priority.setdefault(item.priority_level, []).append(item)

        sections: list[PrioritizedBulletinSection] = []
        for priority in self._config.priority_order:
            group = by_priority.get(priority)
            if not group:
                continue  # seções vazias não são emitidas (§31)
            if len(group) > self._config.maximum_items_per_section:
                raise PrioritizedBulletinLimitError(
                    "seção excede maximum_items_per_section"
                )
            sections.append(
                PrioritizedBulletinSection(
                    section_type=PrioritizedBulletinSectionType.PRIORITY,
                    section_key=priority,
                    title=self._titles[priority],
                    items=tuple(group),
                )
            )
        if len(sections) > self._config.maximum_sections:
            raise PrioritizedBulletinLimitError(
                "request excede maximum_sections"
            )
        return tuple(sections)


def _item_sort_key(item: PrioritizedBulletinItem) -> tuple:
    """§30 — ordenação do item usa exclusivamente o representante;
    o último desempate é representative_event_id ASC."""
    representative = item.members[0]
    return (
        -item.priority_score,
        not representative.requires_human_review,
        -item.relevance_score,
        -item.significance_score,
        _datetime_key(item.occurred_at),
        _datetime_key(item.validated_at),
        item.representative_event_id,
    )
