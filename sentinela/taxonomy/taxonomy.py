"""
Sentinela HL — API de consulta da Taxonomia (Documento 112.7A).

Índice imutável e determinístico sobre a Taxonomy validada. É o que os
componentes seguintes (Research Profile, Fingerprint, Interest Engine) vão
consumir: lookup por termo, hierarquia (ancestrais/descendentes) e vizinhança
(related, 1 salto).

NÃO implementa matching, scoring nem fingerprint — só consulta de vocabulário.
"""

from __future__ import annotations

from typing import Optional

from sentinela.taxonomy.models import Concept, Taxonomy, normalize_term


class TaxonomyIndex:
    """Consulta O(1) sobre a taxonomia. Construído uma vez; somente leitura."""

    def __init__(self, taxonomy: Taxonomy):
        self.taxonomy = taxonomy
        self._by_id: dict[str, Concept] = {}
        self._by_term: dict[str, Concept] = {}      # nome+sinônimos normalizados
        self._children: dict[str, list[str]] = {}

        for c in taxonomy.concepts:
            self._by_id[c.id] = c
            for term in [c.name, *c.synonyms]:
                self._by_term[normalize_term(term)] = c
            if c.parent:
                self._children.setdefault(c.parent, []).append(c.id)

    # ------------------------------------------------------------- lookup
    def get(self, concept_id: str) -> Optional[Concept]:
        return self._by_id.get(concept_id)

    def find_by_term(self, term: str) -> Optional[Concept]:
        """Resolve um termo livre (nome ou sinônimo) para o conceito.
        Case-insensitive e insensível a acento."""
        return self._by_term.get(normalize_term(term))

    def concepts_of_domain(self, domain_id: str) -> list[Concept]:
        return [c for c in self.taxonomy.concepts if c.domain == domain_id]

    # ---------------------------------------------------------- hierarquia
    def ancestors(self, concept_id: str) -> list[Concept]:
        """Cadeia de pais, do imediato à raiz."""
        out: list[Concept] = []
        node = self._by_id.get(concept_id)
        while node and node.parent:
            node = self._by_id.get(node.parent)
            if node:
                out.append(node)
        return out

    def children(self, concept_id: str) -> list[Concept]:
        return [self._by_id[i] for i in self._children.get(concept_id, [])]

    def descendants(self, concept_id: str) -> list[Concept]:
        """Toda a subárvore abaixo do conceito (determinístico, DFS)."""
        out: list[Concept] = []
        stack = list(self._children.get(concept_id, []))
        while stack:
            cid = stack.pop(0)
            c = self._by_id[cid]
            out.append(c)
            stack.extend(self._children.get(cid, []))
        return out

    # ---------------------------------------------------------- vizinhança
    def related(self, concept_id: str) -> list[Concept]:
        """Conceitos relacionados (1 salto), incluindo relações declaradas no
        sentido inverso — a relação é tratada como simétrica na consulta."""
        c = self._by_id.get(concept_id)
        if not c:
            return []
        ids = set(c.related)
        for other in self.taxonomy.concepts:          # inverso
            if concept_id in other.related:
                ids.add(other.id)
        ids.discard(concept_id)
        return [self._by_id[i] for i in sorted(ids) if i in self._by_id]

    # ------------------------------------------------------------- métricas
    def stats(self) -> dict:
        return {
            "domains": len(self.taxonomy.domains),
            "concepts": len(self.taxonomy.concepts),
            "terms": len(self._by_term),
            "relations": sum(len(c.related) for c in self.taxonomy.concepts),
        }
