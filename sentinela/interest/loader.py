"""Carregamento e resolução canônica do Research Profile."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import ValidationError

from .models import (
    PreferredSource,
    ResearchConcept,
    ResearchDomain,
    ResearchIdentity,
    ResearchInstrument,
    ResearchLine,
    ResearchProfile,
    ResearchRegion,
    ResolutionRecord,
)
from .validator import (
    ProfileValidationError,
    get_concept_domain,
    get_concept_id,
    normalize_free_term,
    validate_profile,
)

T = TypeVar("T", ResearchConcept, ResearchRegion, ResearchInstrument)


class ProfileLoadError(ValueError):
    """Falha de carregamento, resolução ou validação do perfil."""


def _taxonomy_domains(taxonomy: Any) -> set[str]:
    """Aceita tanto Taxonomy quanto TaxonomyIndex."""

    base = getattr(taxonomy, "taxonomy", taxonomy)
    domains = getattr(base, "domains", None)

    if isinstance(domains, Mapping):
        return {str(key) for key in domains}

    if isinstance(domains, (list, tuple, set, frozenset)):
        result: set[str] = set()

        for domain in domains:
            value = (
                getattr(domain, "domain_id", None)
                or getattr(domain, "id", None)
                or domain
            )
            if isinstance(value, str):
                result.add(value)

        return result

    concepts = getattr(base, "concepts", None)
    iterable = concepts.values() if isinstance(concepts, Mapping) else concepts or ()

    return {
        domain
        for concept in iterable
        if (domain := get_concept_domain(concept)) is not None
    }


def _concept_by_id(taxonomy: Any, concept_id: str) -> Any | None:
    concepts = getattr(taxonomy, "concepts", None)

    if isinstance(concepts, Mapping):
        return concepts.get(concept_id)

    for method_name in ("get", "get_concept", "concept"):
        method = getattr(taxonomy, method_name, None)

        if not callable(method):
            continue

        try:
            result = method(concept_id)
        except (KeyError, ValueError):
            result = None

        if result is not None:
            return result

    return None


def _resolve_concept(taxonomy: Any, term: str) -> Any:
    direct = _concept_by_id(taxonomy, term)

    if direct is not None:
        return direct

    for method_name in ("find_by_term", "resolve", "lookup"):
        method = getattr(taxonomy, method_name, None)

        if not callable(method):
            continue

        try:
            result = method(term)
        except (KeyError, ValueError):
            result = None

        if isinstance(result, (list, tuple, set)):
            if len(result) == 1:
                return next(iter(result))

            if len(result) > 1:
                raise ProfileLoadError(
                    f"termo ambíguo na taxonomia: {term!r}"
                )

        elif result is not None:
            return result

    raise ProfileLoadError(
        f"termo não resolvido pela taxonomia: {term!r}"
    )


def _weight(value: Any) -> float:
    if isinstance(value, Mapping):
        value = value.get("weight", 1.0)

    if value is None:
        return 1.0

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProfileLoadError(f"peso inválido: {value!r}") from exc


def _weighted_entries(raw: Any, *, field: str) -> list[tuple[str, float]]:
    if raw is None:
        return []

    if isinstance(raw, Mapping):
        return [
            (str(term), _weight(value))
            for term, value in raw.items()
        ]

    if isinstance(raw, list):
        result: list[tuple[str, float]] = []

        for item in raw:
            if isinstance(item, str):
                result.append((item, 1.0))
                continue

            if isinstance(item, Mapping):
                term = (
                    item.get("term")
                    or item.get("id")
                    or item.get("concept_id")
                )

                if not term:
                    raise ProfileLoadError(
                        f"{field}: entrada sem term/id/concept_id"
                    )

                result.append((str(term), _weight(item)))
                continue

            raise ProfileLoadError(
                f"{field}: entrada inválida: {item!r}"
            )

        return result

    raise ProfileLoadError(
        f"{field}: esperado mapping ou lista"
    )


def _canonical_weighted(
    raw: Any,
    *,
    field: str,
    taxonomy: Any,
    model: type[T],
    resolution_log: list[ResolutionRecord],
    allowed_domains: set[str] | None = None,
) -> tuple[T, ...]:
    canonical: dict[str, float] = {}
    source_terms: dict[str, str] = {}

    for term, weight in _weighted_entries(raw, field=field):
        concept = _resolve_concept(taxonomy, term)
        concept_id = get_concept_id(concept)
        domain = get_concept_domain(concept)

        if allowed_domains is not None and domain not in allowed_domains:
            allowed = ", ".join(sorted(allowed_domains))

            raise ProfileLoadError(
                f"{field}: {term!r} resolveu para {concept_id!r}, "
                f"domínio {domain!r}; esperado: {allowed}"
            )

        previous = canonical.get(concept_id)

        if previous is not None and previous != weight:
            raise ProfileLoadError(
                f"{field}: {source_terms[concept_id]!r} e {term!r} "
                f"resolvem para {concept_id!r} com pesos conflitantes "
                f"({previous} != {weight})"
            )

        canonical[concept_id] = weight
        source_terms.setdefault(concept_id, term)

        if term != concept_id:
            resolution_log.append(
                ResolutionRecord(
                    field=field,
                    input_term=term,
                    canonical_concept_id=concept_id,
                )
            )

    return tuple(
        model(
            concept_id=concept_id,
            weight=canonical[concept_id],
        )
        for concept_id in sorted(canonical)
    )


def _domains(raw: Any, taxonomy: Any) -> tuple[ResearchDomain, ...]:
    known = _taxonomy_domains(taxonomy)
    result: list[ResearchDomain] = []

    for domain_id, weight in _weighted_entries(raw, field="domains"):
        if domain_id not in known:
            raise ProfileLoadError(
                f"domínio inexistente: {domain_id!r}"
            )

        result.append(
            ResearchDomain(
                domain_id=domain_id,
                weight=weight,
            )
        )

    return tuple(
        sorted(result, key=lambda item: item.domain_id)
    )


def _preferred_sources(raw: Any) -> tuple[PreferredSource, ...]:
    entries = _weighted_entries(raw, field="preferred_sources")
    found: dict[str, float] = {}

    for source_id, weight in entries:
        normalized = normalize_free_term(source_id).replace(" ", "_")

        if normalized in found and found[normalized] != weight:
            raise ProfileLoadError(
                f"preferred_sources: {source_id!r} possui pesos conflitantes"
            )

        found[normalized] = weight

    return tuple(
        PreferredSource(
            source_id=source_id,
            weight=weight,
        )
        for source_id, weight in sorted(found.items())
    )


def _research_lines(
    raw: Any,
    *,
    taxonomy: Any,
    resolution_log: list[ResolutionRecord],
) -> tuple[ResearchLine, ...]:
    if raw is None:
        return ()

    if not isinstance(raw, list):
        raise ProfileLoadError(
            "research_lines: esperado lista"
        )

    lines: list[ResearchLine] = []

    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ProfileLoadError(
                f"research_lines[{index}]: esperado objeto"
            )

        identifier = item.get("id", index)
        prefix = f"research_lines[{identifier}]"

        try:
            line_id = str(item["id"])
            title = str(item["title"])
        except KeyError as exc:
            raise ProfileLoadError(
                f"{prefix}: campo obrigatório ausente: {exc.args[0]}"
            ) from exc

        lines.append(
            ResearchLine(
                id=line_id,
                title=title,
                description=item.get("description"),
                question=item.get("question"),
                priority=_weight(item.get("priority", 1.0)),
                concepts=_canonical_weighted(
                    item.get("concepts"),
                    field=f"{prefix}.concepts",
                    taxonomy=taxonomy,
                    model=ResearchConcept,
                    resolution_log=resolution_log,
                ),
                regions=_canonical_weighted(
                    item.get("regions"),
                    field=f"{prefix}.regions",
                    taxonomy=taxonomy,
                    model=ResearchRegion,
                    allowed_domains={"regions"},
                    resolution_log=resolution_log,
                ),
                instruments=_canonical_weighted(
                    item.get("instruments"),
                    field=f"{prefix}.instruments",
                    taxonomy=taxonomy,
                    model=ResearchInstrument,
                    allowed_domains={"remote_sensing"},
                    resolution_log=resolution_log,
                ),
            )
        )

    return tuple(lines)


def load_research_profile(
    path: str | Path,
    taxonomy: Any,
) -> ResearchProfile:
    profile_path = Path(path)

    try:
        raw = yaml.safe_load(
            profile_path.read_text(encoding="utf-8")
        )
    except OSError as exc:
        raise ProfileLoadError(
            f"não foi possível ler {profile_path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise ProfileLoadError(
            f"YAML inválido em {profile_path}: {exc}"
        ) from exc

    if not isinstance(raw, Mapping):
        raise ProfileLoadError(
            "a raiz do perfil deve ser um objeto YAML"
        )

    resolution_log: list[ResolutionRecord] = []

    try:
        researcher_raw = raw.get("researcher") or {}
        researcher = ResearchIdentity(**researcher_raw)

        excluded = {
            normalize_free_term(str(term))
            for term in (raw.get("excluded_topics") or [])
            if normalize_free_term(str(term))
        }

        profile = ResearchProfile(
            researcher=researcher,
            domains=_domains(raw.get("domains"), taxonomy),
            concepts=_canonical_weighted(
                raw.get("concepts"),
                field="concepts",
                taxonomy=taxonomy,
                model=ResearchConcept,
                resolution_log=resolution_log,
            ),
            regions=_canonical_weighted(
                raw.get("regions"),
                field="regions",
                taxonomy=taxonomy,
                model=ResearchRegion,
                allowed_domains={"regions"},
                resolution_log=resolution_log,
            ),
            instruments=_canonical_weighted(
                raw.get("instruments"),
                field="instruments",
                taxonomy=taxonomy,
                model=ResearchInstrument,
                allowed_domains={"remote_sensing"},
                resolution_log=resolution_log,
            ),
            preferred_sources=_preferred_sources(
                raw.get("preferred_sources")
            ),
            excluded_topics=tuple(sorted(excluded)),
            research_lines=_research_lines(
                raw.get("research_lines"),
                taxonomy=taxonomy,
                resolution_log=resolution_log,
            ),
            resolution_log=tuple(resolution_log),
        )

        validate_profile(profile)
        return profile

    except (
        KeyError,
        TypeError,
        ValidationError,
        ProfileValidationError,
    ) as exc:
        raise ProfileLoadError(
            f"perfil inválido em {profile_path}: {exc}"
        ) from exc
