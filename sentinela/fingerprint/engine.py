"""Engine do Concept Fingerprint — Documento 112.7D (happy path normativo).

Pipeline V1: extração de termos (§18) → correspondência direta (§12) →
expansão hierárquica (§13) e por relacionados (§14) → agregação noisy-or
(§16) com separação dos pesos (§17) → ordenação estável (§23).

Determinístico: mesma entrada, taxonomia e configuração produzem o mesmo
conteúdo lógico (§25). Nenhum LLM, nenhuma rede, nenhum banco.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sentinela.core.models import Event
from sentinela.taxonomy.models import Concept, normalize_term
from sentinela.taxonomy.taxonomy import TaxonomyIndex

from .models import (
    ConceptFingerprint,
    ConceptMatchType,
    ConceptSignal,
    FingerprintConfig,
    FingerprintField,
    MatchEvidence,
    UnmatchedTerm,
)

_DIRECT_TYPES = frozenset(
    {
        ConceptMatchType.CONCEPT_ID,
        ConceptMatchType.CANONICAL_NAME,
        ConceptMatchType.SYNONYM,
    }
)

# campos de valor discreto (§18.1): atributo do Event → campo do fingerprint
_DISCRETE_SINGLE = (
    (FingerprintField.CATEGORY, "category"),
    (FingerprintField.SCIENTIFIC_AREA, "scientific_area"),
    (FingerprintField.COUNTRY, "country"),
)


def _noisy_or(contributions: list[float]) -> float:
    """112.7D §16 — peso final = 1 - produto(1 - contribuição_i)."""
    product = 1.0
    for contribution in contributions:
        product *= 1.0 - contribution
    return 1.0 - product


class ConceptFingerprintEngine:
    """112.7D §30 — `engine.build(event) -> ConceptFingerprint`."""

    def __init__(
        self,
        taxonomy: TaxonomyIndex,
        config: FingerprintConfig,
    ) -> None:
        self._taxonomy = taxonomy
        self._config = config
        # índice determinístico de termos (§18.2/§18.3):
        # (termo normalizado, termo original, conceito, tipo)
        terms: list[tuple[str, str, Concept, ConceptMatchType]] = []
        for concept in taxonomy.taxonomy.concepts:
            terms.append(
                (
                    normalize_term(concept.name),
                    concept.name,
                    concept,
                    ConceptMatchType.CANONICAL_NAME,
                )
            )
            for synonym in concept.synonyms:
                terms.append(
                    (
                        normalize_term(synonym),
                        synonym,
                        concept,
                        ConceptMatchType.SYNONYM,
                    )
                )
        terms.sort(key=lambda t: (-len(t[0]), -len(t[0].split()), t[0]))
        self._terms = tuple(terms)

    # ------------------------------------------------------------ público
    def build(self, event: Event) -> ConceptFingerprint:
        evidences: list[MatchEvidence] = []
        unmatched: list[UnmatchedTerm] = []
        source_fields: set[str] = set()

        # campos discretos de valor único (category, scientific_area, country)
        for field, attr in _DISCRETE_SINGLE:
            raw = getattr(event, attr)
            if raw and raw.strip():
                source_fields.add(field.value)
                self._resolve_discrete(field, raw, evidences, unmatched)

        # keywords (§18.1)
        if event.keywords:
            source_fields.add(FingerprintField.KEYWORD.value)
            for keyword in event.keywords:
                if keyword and keyword.strip():
                    self._resolve_discrete(
                        FingerprintField.KEYWORD, keyword, evidences, unmatched
                    )

        # entities (§21): somente formas explicitamente suportadas
        entity_terms = self._entity_terms(event.entities)
        if entity_terms:
            source_fields.add(FingerprintField.ENTITY.value)
            for term in entity_terms:
                self._resolve_discrete(
                    FingerprintField.ENTITY, term, evidences, unmatched
                )

        # evidence (§7.3): somente texto claramente identificado
        evidence_terms = self._evidence_terms(event.evidence)
        if evidence_terms:
            source_fields.add(FingerprintField.EVIDENCE.value)
            for term in evidence_terms:
                self._resolve_discrete(
                    FingerprintField.EVIDENCE, term, evidences, unmatched
                )

        # título e resumo (§18.2): busca por termos taxonômicos no texto
        for field, attr in (
            (FingerprintField.TITLE, "title"),
            (FingerprintField.SUMMARY, "summary"),
        ):
            raw = getattr(event, attr)
            if raw and raw.strip():
                source_fields.add(field.value)
                self._resolve_text(field, raw, evidences)

        signals = self._aggregate(evidences)

        return ConceptFingerprint(
            event_id=event.id,
            taxonomy_version=self._taxonomy.taxonomy.version,
            generated_at=datetime.now(timezone.utc),
            concepts=signals,
            unmatched_terms=tuple(
                sorted(unmatched, key=lambda u: (u.field.value, u.normalized_term))
            ),
            source_fields=tuple(sorted(source_fields)),
            algorithm_version=self._config.version,
        )

    # ----------------------------------------------------------- extração
    @staticmethod
    def _entity_terms(entities: list[dict]) -> list[str]:
        """§21: aceita ["NASA", ...] ou [{"name": ...}]; ignora o resto."""
        terms: list[str] = []
        for item in entities:
            if isinstance(item, str) and item.strip():
                terms.append(item)
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name.strip():
                    terms.append(name)
        return terms

    @staticmethod
    def _evidence_terms(evidence: list[dict]) -> list[str]:
        """§7.3: somente estruturas com texto claramente identificado."""
        terms: list[str] = []
        for item in evidence:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    terms.append(text)
        return terms

    # ------------------------------------------------ correspondência (§12)
    def _resolve_discrete(
        self,
        field: FingerprintField,
        raw_term: str,
        evidences: list[MatchEvidence],
        unmatched: list[UnmatchedTerm],
    ) -> None:
        normalized = normalize_term(raw_term)
        if not normalized:
            return

        concept: Optional[Concept] = None
        match_type: Optional[ConceptMatchType] = None
        matched_term: Optional[str] = None

        direct = self._taxonomy.get(normalized)
        if direct is not None:
            concept, match_type, matched_term = (
                direct,
                ConceptMatchType.CONCEPT_ID,
                direct.id,
            )
        else:
            found = self._taxonomy.find_by_term(normalized)
            if found is not None:
                concept = found
                if normalize_term(found.name) == normalized:
                    match_type = ConceptMatchType.CANONICAL_NAME
                    matched_term = found.name
                else:
                    match_type = ConceptMatchType.SYNONYM
                    matched_term = next(
                        (
                            s
                            for s in found.synonyms
                            if normalize_term(s) == normalized
                        ),
                        found.name,
                    )

        if concept is None or match_type is None or matched_term is None:
            unmatched.append(
                UnmatchedTerm(
                    field=field,
                    input_term=raw_term,
                    normalized_term=normalized,
                    reason="not_in_taxonomy",
                )
            )
            return

        weight = getattr(self._config.weights, field.value)
        evidence = MatchEvidence(
            field=field,
            input_term=raw_term,
            normalized_term=normalized,
            matched_term=matched_term,
            canonical_concept_id=concept.id,
            match_type=match_type,
            contribution=weight,  # §12: peso do campo × 1.00 (V1)
        )
        self._expand(evidence, concept, evidences)

    def _resolve_text(
        self,
        field: FingerprintField,
        raw_text: str,
        evidences: list[MatchEvidence],
    ) -> None:
        """§18.2 — fronteira de palavras, termos mais longos primeiro,
        sem duplicação por sobreposição."""
        normalized = normalize_term(raw_text)
        padded = f" {normalized} "
        claimed: list[tuple[int, int]] = []
        seen_concepts: set[str] = set()
        weight = getattr(self._config.weights, field.value)

        for term, original, concept, match_type in self._terms:
            if not term or concept.id in seen_concepts:
                continue
            needle = f" {term} "
            start = padded.find(needle)
            if start < 0:
                continue
            span = (start, start + len(needle))
            if any(start < end and span[0] < end and start < span[1] for start, end in claimed):
                continue
            claimed.append(span)
            seen_concepts.add(concept.id)
            evidence = MatchEvidence(
                field=field,
                input_term=raw_text,
                normalized_term=normalized,
                matched_term=original,
                canonical_concept_id=concept.id,
                match_type=match_type,
                contribution=weight,
            )
            self._expand(evidence, concept, evidences)

    # --------------------------------------------------- expansões (§13/§14)
    def _expand(
        self,
        direct_evidence: MatchEvidence,
        concept: Concept,
        evidences: list[MatchEvidence],
    ) -> None:
        evidences.append(direct_evidence)

        if self._config.include_parents:
            ancestors = self._taxonomy.ancestors(concept.id)
            for distance, ancestor in enumerate(ancestors, start=1):
                if distance > self._config.max_parent_depth:
                    break
                evidences.append(
                    MatchEvidence(
                        field=direct_evidence.field,
                        input_term=direct_evidence.input_term,
                        normalized_term=direct_evidence.normalized_term,
                        matched_term=ancestor.name,
                        canonical_concept_id=ancestor.id,
                        match_type=ConceptMatchType.PARENT,
                        contribution=direct_evidence.contribution
                        * self._config.weights.parent_decay**distance,
                    )
                )

        if self._config.include_related and self._config.max_related_depth >= 1:
            for related in self._taxonomy.related(concept.id):
                evidences.append(
                    MatchEvidence(
                        field=direct_evidence.field,
                        input_term=direct_evidence.input_term,
                        normalized_term=direct_evidence.normalized_term,
                        matched_term=related.name,
                        canonical_concept_id=related.id,
                        match_type=ConceptMatchType.RELATED,
                        contribution=direct_evidence.contribution
                        * self._config.weights.related_decay,
                    )
                )

    # ------------------------------------------------- agregação (§16/§17)
    def _aggregate(
        self, evidences: list[MatchEvidence]
    ) -> tuple[ConceptSignal, ...]:
        minimum = self._config.minimum_contribution
        by_concept: dict[str, list[MatchEvidence]] = {}
        for evidence in evidences:
            if evidence.contribution < minimum:
                continue
            by_concept.setdefault(evidence.canonical_concept_id, []).append(
                evidence
            )

        signals: list[ConceptSignal] = []
        for concept_id, group in by_concept.items():
            concept = self._taxonomy.get(concept_id)
            if concept is None:
                continue
            direct = [
                e.contribution
                for e in group
                if e.match_type in _DIRECT_TYPES
            ]
            inherited = [
                e.contribution
                for e in group
                if e.match_type is ConceptMatchType.PARENT
            ]
            related = [
                e.contribution
                for e in group
                if e.match_type is ConceptMatchType.RELATED
            ]
            ordered_evidence = tuple(
                sorted(
                    group,
                    key=lambda e: (
                        e.field.value,
                        -e.contribution,
                        e.normalized_term,
                        e.canonical_concept_id,
                    ),
                )
            )
            signals.append(
                ConceptSignal(
                    concept_id=concept.id,
                    domain_id=concept.domain,
                    weight=_noisy_or([e.contribution for e in group]),
                    direct_weight=_noisy_or(direct) if direct else 0.0,
                    inherited_weight=(
                        _noisy_or(inherited) if inherited else 0.0
                    ),
                    related_weight=_noisy_or(related) if related else 0.0,
                    evidence=ordered_evidence,
                )
            )

        # §23: weight DESC, direct_weight DESC, concept_id ASC
        signals.sort(
            key=lambda s: (-s.weight, -s.direct_weight, s.concept_id)
        )
        return tuple(signals)
