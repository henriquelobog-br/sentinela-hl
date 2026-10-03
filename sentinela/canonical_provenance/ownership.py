"""Explicit ownership policy for fields persisted in knowledge.events."""

from __future__ import annotations

from enum import Enum


class FieldOwnership(str, Enum):
    IMMUTABLE_IDENTITY = "immutable_identity"
    MACHINE_OWNED = "machine_owned"
    CURATOR_OWNED = "curator_owned"
    DERIVED_OPERATIONAL = "derived_operational"


EVENT_FIELD_OWNERSHIP: dict[str, FieldOwnership] = {
    "id": FieldOwnership.IMMUTABLE_IDENTITY,
    "primary_claim_id": FieldOwnership.CURATOR_OWNED,
    "title": FieldOwnership.MACHINE_OWNED,
    "summary": FieldOwnership.MACHINE_OWNED,
    "epistemic_status": FieldOwnership.CURATOR_OWNED,
    "confidence_score": FieldOwnership.CURATOR_OWNED,
    "category": FieldOwnership.MACHINE_OWNED,
    "country": FieldOwnership.MACHINE_OWNED,
    "scientific_area": FieldOwnership.MACHINE_OWNED,
    "entities": FieldOwnership.MACHINE_OWNED,
    "keywords": FieldOwnership.MACHINE_OWNED,
    "evidence": FieldOwnership.MACHINE_OWNED,
    "occurred_at": FieldOwnership.MACHINE_OWNED,
    "event_status": FieldOwnership.MACHINE_OWNED,
    "source": FieldOwnership.MACHINE_OWNED,
    "supporting_sources": FieldOwnership.MACHINE_OWNED,
    "pipeline_status": FieldOwnership.CURATOR_OWNED,
    "requires_human_review": FieldOwnership.CURATOR_OWNED,
    "review_decision": FieldOwnership.CURATOR_OWNED,
    "validated_by": FieldOwnership.CURATOR_OWNED,
    "validated_at": FieldOwnership.CURATOR_OWNED,
    "publication_approved": FieldOwnership.CURATOR_OWNED,
    "publication_approved_by": FieldOwnership.CURATOR_OWNED,
    "publication_approved_at": FieldOwnership.CURATOR_OWNED,
    "created_at": FieldOwnership.DERIVED_OPERATIONAL,
    "updated_at": FieldOwnership.DERIVED_OPERATIONAL,
}


def automatic_event_fields() -> frozenset[str]:
    """Fields that automatic canonical ingestion may insert/update directly."""
    return frozenset(
        field
        for field, owner in EVENT_FIELD_OWNERSHIP.items()
        if owner in {FieldOwnership.IMMUTABLE_IDENTITY, FieldOwnership.MACHINE_OWNED}
    )


__all__ = ["EVENT_FIELD_OWNERSHIP", "FieldOwnership", "automatic_event_fields"]
