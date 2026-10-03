from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from sentinela.canonical_provenance import (
    CanonicalEventCandidate,
    CanonicalRejectionCode,
    CollectorRole,
    accept_canonical_events,
    build_canonical_signal_record,
    canonical_event_content_hash,
)
from sentinela.canonical_provenance.ownership import (
    EVENT_FIELD_OWNERSHIP,
    FieldOwnership,
    automatic_event_fields,
)
from sentinela.core.models import EventStatus
from sentinela.projection import project_researcher_signals
from sentinela.projection.tests.test_researcher_signal import single_item_bulletin
from sentinela.real_signals.collectors import _event

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)


def valid_event():
    return _event(
        event_type="earthquake_detected",
        source="USGS",
        product="earthquake-catalog",
        region="source-1",
        window="source-1|revision-1",
        group="usgs:source-1",
        title="Terremoto observado",
        summary="Evento factual normalizado.",
        occurred_at=NOW,
        evidence={"source": "USGS", "source_event_id": "source-1"},
        evidence_text="earthquake",
        keywords=["earthquake"],
        entities=[],
        scientific_area="seismology",
        event_status=EventStatus.OBSERVED_FACT,
    )


def candidate(event=None, collector="usgs"):
    return CanonicalEventCandidate(
        event=event or valid_event(),
        collector=collector,
        collector_role=CollectorRole.REQUESTED,
    )


def test_ownership_classifies_all_event_and_persistence_fields():
    expected = {
        "id", "primary_claim_id", "title", "summary", "epistemic_status",
        "confidence_score", "category", "country", "scientific_area",
        "entities", "keywords", "evidence", "occurred_at", "event_status",
        "source", "supporting_sources", "pipeline_status",
        "requires_human_review", "review_decision", "validated_by",
        "validated_at", "publication_approved", "publication_approved_by",
        "publication_approved_at", "created_at", "updated_at",
    }
    assert set(EVENT_FIELD_OWNERSHIP) == expected
    assert EVENT_FIELD_OWNERSHIP["id"] == FieldOwnership.IMMUTABLE_IDENTITY
    assert EVENT_FIELD_OWNERSHIP["review_decision"] == FieldOwnership.CURATOR_OWNED
    assert EVENT_FIELD_OWNERSHIP["validated_by"] == FieldOwnership.CURATOR_OWNED
    assert EVENT_FIELD_OWNERSHIP["epistemic_status"] == FieldOwnership.CURATOR_OWNED
    assert EVENT_FIELD_OWNERSHIP["confidence_score"] == FieldOwnership.CURATOR_OWNED
    assert EVENT_FIELD_OWNERSHIP["created_at"] == FieldOwnership.DERIVED_OPERATIONAL
    assert "review_decision" not in automatic_event_fields()
    assert "epistemic_status" not in automatic_event_fields()
    assert "title" in automatic_event_fields()


def test_gate_accepts_valid_event_and_is_researcher_independent():
    result = accept_canonical_events((candidate(),))
    assert len(result.accepted) == 1
    assert result.rejected == ()
    assert result.accepted[0].collector == "usgs"


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        ({"id": None}, CanonicalRejectionCode.MISSING_EVENT_ID),
        ({"source": None}, CanonicalRejectionCode.MISSING_SOURCE),
        ({"scientific_area": None}, CanonicalRejectionCode.MISSING_SCIENTIFIC_AREA),
        ({"scientific_area": "unknown_area"}, CanonicalRejectionCode.UNKNOWN_SCIENTIFIC_AREA),
        ({"evidence": []}, CanonicalRejectionCode.MISSING_EVIDENCE),
        ({"event_status": EventStatus.UNKNOWN}, CanonicalRejectionCode.UNKNOWN_EVENT_STATUS),
    ),
)
def test_gate_rejects_insufficient_provenance(changes, reason):
    result = accept_canonical_events((candidate(valid_event().model_copy(update=changes)),))
    assert result.accepted == ()
    assert reason in result.rejected[0].reasons


def test_gate_rejects_naive_occurred_at():
    event = valid_event().model_copy(update={"occurred_at": datetime(2026, 9, 28, 12)})
    result = accept_canonical_events((candidate(event),))
    assert CanonicalRejectionCode.INVALID_OCCURRED_AT in result.rejected[0].reasons


def test_same_event_is_observed_once_but_conflicting_content_is_rejected():
    event = valid_event()
    repeated = accept_canonical_events((candidate(event), candidate(event)))
    assert len(repeated.accepted) == 1
    assert repeated.rejected == ()

    conflict = event.model_copy(update={"title": "Outro título"})
    rejected = accept_canonical_events((candidate(event), candidate(conflict)))
    assert rejected.accepted == ()
    assert all(
        item.reasons == (CanonicalRejectionCode.DUPLICATE_ID_CONFLICT,)
        for item in rejected.rejected
    )


def test_event_hash_ignores_curator_fields_but_tracks_machine_facts():
    event = valid_event()
    curated = event.model_copy(
        update={"validated_by": "curator", "requires_human_review": True}
    )
    changed_fact = event.model_copy(update={"summary": "Fato revisado"})
    assert canonical_event_content_hash(event) == canonical_event_content_hash(curated)
    assert canonical_event_content_hash(event) != canonical_event_content_hash(changed_fact)


def test_signal_requires_real_canonical_representative_and_contributors():
    signal = project_researcher_signals(single_item_bulletin())[0]
    representative = signal.representative_event_id
    contributor = str(uuid4())
    record = build_canonical_signal_record(
        signal,
        representative_event_id=representative,
        contributor_event_ids=(contributor,),
        accepted_event_ids=frozenset({representative, contributor}),
    )
    assert str(record.representative_event_id) == representative
    assert record.contributor_event_ids == (UUID(contributor),)

    with pytest.raises(ValueError, match="contributor_not_canonical"):
        build_canonical_signal_record(
            signal,
            representative_event_id=representative,
            contributor_event_ids=(str(uuid4()),),
            accepted_event_ids=frozenset({representative}),
        )


def test_source_observation_id_is_not_reinterpreted_as_canonical_event():
    signal = project_researcher_signals(single_item_bulletin())[0]
    with pytest.raises(ValueError, match="invalid_canonical_event_id"):
        build_canonical_signal_record(
            signal,
            representative_event_id=signal.representative_event_id,
            contributor_event_ids=("source-observation-id",),
            accepted_event_ids=frozenset({signal.representative_event_id}),
        )
