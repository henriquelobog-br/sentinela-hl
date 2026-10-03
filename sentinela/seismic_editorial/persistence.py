"""Versioned persistence contract for Seismic Editorial v1."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentinela.core.models import Event

from .engine import _evidence, _facts, _text
from .models import SeismicEditorialContent

SEISMIC_EDITORIAL_VERSION = "seismic-v1"
SEISMIC_EDITORIAL_LOCALE = "pt-BR"
_INPUT_SIGNATURE_SCHEMA = "seismic-editorial-input-facts-v1"


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def seismic_input_facts(event: Event) -> dict[str, Any]:
    """Return the canonical facts consumed by the frozen v1 engine."""
    evidence = _evidence(event)
    facts = _facts(event)
    return {
        "category": event.category,
        "scientific_area": event.scientific_area,
        "magnitude": _decimal_text(facts.magnitude),
        "magnitude_type": facts.magnitude_type,
        "place": _text(evidence.get("place")),
        "depth_km": _decimal_text(facts.depth_km),
        "latitude": _decimal_text(facts.latitude),
        "longitude": _decimal_text(facts.longitude),
        "alert": facts.alert,
        "occurred_at": (
            facts.occurred_at.isoformat().replace("+00:00", "Z")
            if facts.occurred_at is not None
            else None
        ),
        "source": facts.source,
    }


def seismic_input_facts_signature(event: Event) -> str:
    """Hash canonical v1 inputs, independent of JSON key ordering."""
    payload = {
        "signature_schema": _INPUT_SIGNATURE_SCHEMA,
        "facts": seismic_input_facts(event),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SeismicEditorialRecord(BaseModel):
    """Immutable persistence envelope around generated editorial content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    editorial_version: str = Field(default=SEISMIC_EDITORIAL_VERSION, min_length=1)
    locale: str = Field(default=SEISMIC_EDITORIAL_LOCALE, min_length=1)
    content: SeismicEditorialContent
    input_facts_signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime

    @field_validator("editorial_version", "locale")
    @classmethod
    def normalize_key_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("editorial key fields must not be blank")
        return normalized

    @field_validator("generated_at")
    @classmethod
    def normalize_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value.astimezone(timezone.utc)

    @classmethod
    def from_generated_content(
        cls,
        *,
        event: Event,
        content: SeismicEditorialContent,
        generated_at: datetime,
        editorial_version: str = SEISMIC_EDITORIAL_VERSION,
        locale: str = SEISMIC_EDITORIAL_LOCALE,
    ) -> "SeismicEditorialRecord":
        if event.id is None:
            raise ValueError("Event.id is required for editorial persistence")
        return cls(
            event_id=event.id,
            editorial_version=editorial_version,
            locale=locale,
            content=content,
            input_facts_signature=seismic_input_facts_signature(event),
            generated_at=generated_at,
        )


__all__ = [
    "SEISMIC_EDITORIAL_LOCALE",
    "SEISMIC_EDITORIAL_VERSION",
    "SeismicEditorialRecord",
    "seismic_input_facts",
    "seismic_input_facts_signature",
]
