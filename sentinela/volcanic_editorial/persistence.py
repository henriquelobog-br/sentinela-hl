"""Versioned persistence contract for Volcanic Editorial v1."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinela.core.models import Event

from .engine import _evidence, _material_kind as _engine_material_kind, _text, _utc
from .models import VolcanicEditorialContent, VolcanicEditorialUnit

VOLCANIC_EDITORIAL_VERSION = "volcanic-v1"
VOLCANIC_EDITORIAL_LOCALE = "pt-BR"
_INPUT_SIGNATURE_SCHEMA = "volcanic-editorial-input-facts-v1"


def _datetime_text(value: datetime | None) -> str | None:
    normalized = _utc(value)
    if normalized is None:
        return None
    return normalized.isoformat().replace("+00:00", "Z")


def _evidence_datetime_text(value: Any) -> str | None:
    if isinstance(value, datetime):
        return _datetime_text(value)
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _datetime_text(parsed)


def _decimal_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _enum_text(value: Any) -> str | None:
    enum_value = getattr(value, "value", value)
    return _text(enum_value)


def _common_event_facts(event: Event) -> dict[str, Any]:
    evidence = _evidence(event)
    return {
        "category": event.category,
        "scientific_area": event.scientific_area,
        "source": _text(event.source),
        "event_status": _enum_text(event.event_status),
        "occurred_at": _datetime_text(event.occurred_at),
        "canonical_group_id": _text(evidence.get("canonical_group_id")),
    }


def _operational_facts(event: Event) -> dict[str, Any]:
    evidence = _evidence(event)
    return {
        "alert_level": _text(evidence.get("alert_level")),
        "aviation_color_code": _text(evidence.get("aviation_color_code")),
        "observatory": _text(evidence.get("observatory")),
    }


def _material_kind_from_summary(summary: str | None) -> str | None:
    return _engine_material_kind(summary)


def volcanic_input_facts(unit: VolcanicEditorialUnit) -> dict[str, Any]:
    """Return canonical facts consumed by the frozen volcanic v1 engine."""
    if not unit.member_events:
        raise ValueError("volcanic editorial unit must have members")

    member_ids = tuple(sorted(str(event.id) for event in unit.member_events))
    representative = unit.representative_event
    representative_id = str(representative.id)
    if representative_id not in member_ids:
        raise ValueError("representative Event must belong to the editorial unit")

    facts: dict[str, Any] = {
        "editorial_group_id": unit.editorial_group_id,
        "member_event_ids": member_ids,
        "representative_event_id": representative_id,
        "volcano_name": unit.volcano_name,
        "volcano_number": unit.volcano_number,
        "category": unit.category,
    }

    if unit.category == "volcano_vona_published":
        members = []
        for event in sorted(unit.member_events, key=lambda item: str(item.id)):
            evidence = _evidence(event)
            members.append(
                {
                    "event_id": str(event.id),
                    **_common_event_facts(event),
                    "notice_identifier": _text(evidence.get("notice_identifier")),
                    "material_kind": _material_kind_from_summary(
                        _text(evidence.get("official_summary"))
                    ),
                }
            )
        facts["members"] = members
        facts["representative_operational_facts"] = _operational_facts(
            representative
        )
        return facts

    evidence = _evidence(representative)
    event_facts = _common_event_facts(representative)

    if unit.category == "volcano_notice_published":
        event_facts["material_kind"] = _material_kind_from_summary(
            _text(evidence.get("official_summary"))
        )
        event_facts.update(_operational_facts(representative))
        event_facts["notice_type"] = _text(evidence.get("notice_type"))
    elif unit.category == "volcano_alert_elevated":
        event_facts["material_kind"] = _material_kind_from_summary(
            _text(evidence.get("official_summary"))
        )
        event_facts.update(_operational_facts(representative))
    elif unit.category == "volcanic_thermal_anomaly_candidate":
        event_facts.update(
            {
                "hotspot_count": evidence.get("hotspot_count"),
                "distance_to_volcano_km": _decimal_text(
                    evidence.get("distance_to_volcano_km")
                ),
                "sensors": tuple(str(value) for value in evidence.get("sensors") or ()),
                "earliest_acquisition": _evidence_datetime_text(
                    evidence.get("earliest_acquisition")
                ),
                "latest_acquisition": _evidence_datetime_text(
                    evidence.get("latest_acquisition")
                ),
            }
        )
    else:
        raise ValueError("unsupported volcanic editorial category")

    facts["event"] = event_facts
    return facts


def volcanic_input_facts_signature(unit: VolcanicEditorialUnit) -> str:
    """Hash canonical v1 inputs, independent of member input ordering."""
    payload = {
        "signature_schema": _INPUT_SIGNATURE_SCHEMA,
        "facts": volcanic_input_facts(unit),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class VolcanicEditorialRecord(BaseModel):
    """Immutable persistence envelope around one generated editorial group."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID | None = None
    editorial_group_id: str = Field(min_length=1)
    representative_event_id: UUID
    member_event_ids: tuple[UUID, ...] = Field(min_length=1)
    volcano_name: str = Field(min_length=1)
    volcano_number: str | None = None
    editorial_version: str = Field(default=VOLCANIC_EDITORIAL_VERSION, min_length=1)
    locale: str = Field(default=VOLCANIC_EDITORIAL_LOCALE, min_length=1)
    content: VolcanicEditorialContent
    input_facts_signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator(
        "editorial_group_id",
        "volcano_name",
        "editorial_version",
        "locale",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("editorial key fields must not be blank")
        return normalized

    @field_validator("volcano_number")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("member_event_ids")
    @classmethod
    def validate_member_event_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("member_event_ids must not contain duplicates")
        return value

    @field_validator("generated_at", "created_at", "updated_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("editorial timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_representative_membership(self) -> "VolcanicEditorialRecord":
        if self.representative_event_id not in self.member_event_ids:
            raise ValueError("representative_event_id must belong to member_event_ids")
        return self

    @property
    def logical_key(self) -> tuple[str, str, str]:
        return (self.editorial_group_id, self.editorial_version, self.locale)

    @classmethod
    def from_generated_content(
        cls,
        *,
        unit: VolcanicEditorialUnit,
        content: VolcanicEditorialContent,
        generated_at: datetime,
        editorial_version: str = VOLCANIC_EDITORIAL_VERSION,
        locale: str = VOLCANIC_EDITORIAL_LOCALE,
    ) -> "VolcanicEditorialRecord":
        return cls(
            editorial_group_id=unit.editorial_group_id,
            representative_event_id=unit.representative_event_id,
            member_event_ids=unit.member_event_ids,
            volcano_name=unit.volcano_name,
            volcano_number=unit.volcano_number,
            editorial_version=editorial_version,
            locale=locale,
            content=content,
            input_facts_signature=volcanic_input_facts_signature(unit),
            generated_at=generated_at,
        )


__all__ = [
    "VOLCANIC_EDITORIAL_LOCALE",
    "VOLCANIC_EDITORIAL_VERSION",
    "VolcanicEditorialRecord",
    "volcanic_input_facts",
    "volcanic_input_facts_signature",
]
