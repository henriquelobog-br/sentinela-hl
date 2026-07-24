"""Validações determinísticas do Research Profile."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from .models import ResearchProfile


class ProfileValidationError(ValueError):
    """Perfil inconsistente com a Scientific Taxonomy."""


def normalize_free_term(value: str) -> str:
    """Normaliza texto editorial sem transformá-lo em conceito científico."""
    value = unicodedata.normalize("NFKD", value.strip().casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def validate_unique_ids(values: Iterable[str], *, field: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()

    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)

    if duplicates:
        joined = ", ".join(sorted(duplicates))
        raise ProfileValidationError(f"{field}: ids duplicados: {joined}")


def validate_profile(profile: ResearchProfile) -> None:
    validate_unique_ids(
        (line.id for line in profile.research_lines),
        field="research_lines",
    )
    validate_unique_ids(
        (item.domain_id for item in profile.domains),
        field="domains",
    )
    validate_unique_ids(
        (item.concept_id for item in profile.concepts),
        field="concepts",
    )
    validate_unique_ids(
        (item.concept_id for item in profile.regions),
        field="regions",
    )
    validate_unique_ids(
        (item.concept_id for item in profile.instruments),
        field="instruments",
    )
    validate_unique_ids(
        (item.source_id for item in profile.preferred_sources),
        field="preferred_sources",
    )

    normalized = [normalize_free_term(item) for item in profile.excluded_topics]
    validate_unique_ids(normalized, field="excluded_topics")


def get_concept_id(concept: Any) -> str:
    for attr in ("concept_id", "id"):
        value = getattr(concept, attr, None)
        if isinstance(value, str) and value:
            return value

    if isinstance(concept, dict):
        for key in ("concept_id", "id"):
            value = concept.get(key)
            if isinstance(value, str) and value:
                return value

    raise ProfileValidationError("objeto de conceito sem concept_id/id")


def get_concept_domain(concept: Any) -> str | None:
    for attr in ("domain", "domain_id"):
        value = getattr(concept, attr, None)

        if isinstance(value, str) and value:
            return value

        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, str) and enum_value:
            return enum_value

    if isinstance(concept, dict):
        value = concept.get("domain") or concept.get("domain_id")
        if isinstance(value, str):
            return value

    return None
