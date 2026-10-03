"""Pure deterministic gates for canonical Events and linked signals."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sentinela.core.models import Event, EventStatus
from sentinela.projection import ResearcherSignal

from .models import (
    CanonicalEventAcceptance,
    CanonicalEventCandidate,
    CanonicalEventRecord,
    CanonicalRejection,
    CanonicalRejectionCode,
    CanonicalSignalRecord,
    canonical_content_hash,
    canonical_event_content_hash,
)

RECOGNIZED_SCIENTIFIC_AREAS = frozenset(
    {
        "atmospheric_science",
        "climate_science",
        "oceanography",
        "seismology",
        "space_weather",
        "volcanology",
        "scientific_geopolitics",
        "environmental_monitoring",
    }
)

_REASON_ORDER = tuple(CanonicalRejectionCode)


def _ordered_reasons(
    values: set[CanonicalRejectionCode],
) -> tuple[CanonicalRejectionCode, ...]:
    return tuple(reason for reason in _REASON_ORDER if reason in values)


def _event_reasons(event: Event) -> tuple[CanonicalRejectionCode, ...]:
    reasons: set[CanonicalRejectionCode] = set()
    if event.id is None:
        reasons.add(CanonicalRejectionCode.MISSING_EVENT_ID)
    if not event.title.strip():
        reasons.add(CanonicalRejectionCode.MISSING_TITLE)
    if not event.source or not event.source.strip():
        reasons.add(CanonicalRejectionCode.MISSING_SOURCE)
    if not event.scientific_area or not event.scientific_area.strip():
        reasons.add(CanonicalRejectionCode.MISSING_SCIENTIFIC_AREA)
    elif event.scientific_area not in RECOGNIZED_SCIENTIFIC_AREAS:
        reasons.add(CanonicalRejectionCode.UNKNOWN_SCIENTIFIC_AREA)
    if not event.evidence:
        reasons.add(CanonicalRejectionCode.MISSING_EVIDENCE)
    elif not all(isinstance(item, dict) and item for item in event.evidence):
        reasons.add(CanonicalRejectionCode.INVALID_EVIDENCE)
    if event.occurred_at is not None and (
        not isinstance(event.occurred_at, datetime)
        or event.occurred_at.tzinfo is None
        or event.occurred_at.utcoffset() is None
    ):
        reasons.add(CanonicalRejectionCode.INVALID_OCCURRED_AT)
    if event.event_status == EventStatus.UNKNOWN:
        reasons.add(CanonicalRejectionCode.UNKNOWN_EVENT_STATUS)
    return _ordered_reasons(reasons)


def accept_canonical_events(
    candidates: tuple[CanonicalEventCandidate, ...],
) -> CanonicalEventAcceptance:
    grouped: dict[str, list[CanonicalEventCandidate]] = defaultdict(list)
    rejected: list[CanonicalRejection] = []

    for index, candidate in enumerate(candidates):
        candidate_id = str(candidate.event.id) if candidate.event.id else f"missing:{index}"
        reasons = _event_reasons(candidate.event)
        if reasons:
            rejected.append(
                CanonicalRejection(
                    candidate_id=candidate_id,
                    collector=candidate.collector,
                    collector_role=candidate.collector_role,
                    reasons=reasons,
                )
            )
            continue
        grouped[candidate_id].append(candidate)

    accepted: list[CanonicalEventRecord] = []
    for event_id in sorted(grouped):
        group = grouped[event_id]
        hashed = [
            (
                canonical_event_content_hash(item.event),
                item,
            )
            for item in group
        ]
        hashes = {item[0] for item in hashed}
        if len(hashes) != 1:
            for item in group:
                rejected.append(
                    CanonicalRejection(
                        candidate_id=event_id,
                        collector=item.collector,
                        collector_role=item.collector_role,
                        reasons=(CanonicalRejectionCode.DUPLICATE_ID_CONFLICT,),
                    )
                )
            continue
        content_hash, candidate = sorted(
            hashed, key=lambda item: (item[1].collector, item[1].collector_role.value)
        )[0]
        accepted.append(
            CanonicalEventRecord(
                event=candidate.event,
                collector=candidate.collector,
                collector_role=candidate.collector_role,
                content_hash=content_hash,
            )
        )

    return CanonicalEventAcceptance(
        accepted=tuple(accepted),
        rejected=tuple(
            sorted(rejected, key=lambda item: (item.candidate_id, item.collector))
        ),
    )


def build_canonical_signal_record(
    signal: ResearcherSignal,
    *,
    representative_event_id: str,
    contributor_event_ids: tuple[str, ...],
    accepted_event_ids: frozenset[str],
) -> CanonicalSignalRecord:
    try:
        representative = UUID(representative_event_id)
    except (ValueError, TypeError) as exc:
        raise ValueError(CanonicalRejectionCode.INVALID_CANONICAL_EVENT_ID.value) from exc
    if str(representative) not in accepted_event_ids:
        raise ValueError(CanonicalRejectionCode.REPRESENTATIVE_NOT_CANONICAL.value)

    contributors: list[UUID] = []
    for value in contributor_event_ids:
        try:
            contributor = UUID(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(CanonicalRejectionCode.INVALID_CANONICAL_EVENT_ID.value) from exc
        if str(contributor) not in accepted_event_ids:
            raise ValueError(CanonicalRejectionCode.CONTRIBUTOR_NOT_CANONICAL.value)
        if contributor != representative:
            contributors.append(contributor)

    return CanonicalSignalRecord(
        signal=signal,
        representative_event_id=representative,
        contributor_event_ids=tuple(contributors),
        content_hash=canonical_content_hash(signal.model_dump(mode="json")),
    )


__all__ = [
    "RECOGNIZED_SCIENTIFIC_AREAS",
    "accept_canonical_events",
    "build_canonical_signal_record",
]
