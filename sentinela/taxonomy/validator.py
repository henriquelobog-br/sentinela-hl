"""
Sentinela HL — validação da Taxonomia (Documento 112.7A).

A taxonomia é um vocabulário com REFERÊNCIAS (parent, related, domain). O
validator garante integridade referencial — erro claro em vez de referência
silenciosamente quebrada. Determinístico; nenhuma chamada externa.
"""

from __future__ import annotations

from sentinela.taxonomy.models import Taxonomy, normalize_term


class TaxonomyValidationError(ValueError):
    """Erro de integridade com lista completa de problemas (não para no 1º)."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("taxonomia inválida:\n  - " + "\n  - ".join(problems))


def validate_taxonomy(tax: Taxonomy) -> None:
    """Valida integridade. Levanta TaxonomyValidationError com TODOS os problemas."""
    problems: list[str] = []

    domain_ids = {d.id for d in tax.domains}
    if len(domain_ids) != len(tax.domains):
        problems.append("ids de domínio duplicados")

    # unicidade global de ids de conceito
    seen_ids: dict[str, str] = {}
    for d in tax.domains:
        for c in d.concepts:
            if c.id in seen_ids:
                problems.append(f"conceito duplicado: '{c.id}' em '{d.id}' e '{seen_ids[c.id]}'")
            seen_ids[c.id] = d.id

    concept_ids = set(seen_ids)

    for d in tax.domains:
        for c in d.concepts:
            # domain do conceito deve ser o domínio do arquivo em que ele vive
            if c.domain != d.id:
                problems.append(f"conceito '{c.id}' declara domain='{c.domain}' mas vive em '{d.id}'")
            # parent deve existir
            if c.parent and c.parent not in concept_ids:
                problems.append(f"conceito '{c.id}' referencia parent inexistente: '{c.parent}'")
            # related devem existir e não apontar para si mesmo
            for r in c.related:
                if r == c.id:
                    problems.append(f"conceito '{c.id}' relaciona-se consigo mesmo")
                elif r not in concept_ids:
                    problems.append(f"conceito '{c.id}' referencia related inexistente: '{r}'")

    # ciclo na hierarquia parent (a hierarquia é árvore, não grafo)
    parent_of = {c.id: c.parent for c in tax.concepts if c.parent}
    for start in parent_of:
        node, hops = start, 0
        while node in parent_of:
            node = parent_of[node]
            hops += 1
            if node == start:
                problems.append(f"ciclo na hierarquia envolvendo '{start}'")
                break
            if hops > len(parent_of):
                break

    # colisão de sinônimos entre conceitos (o mesmo termo não pode mapear p/ 2 conceitos)
    term_owner: dict[str, str] = {}
    for c in tax.concepts:
        for term in [c.name, *c.synonyms]:
            key = normalize_term(term)
            if key in term_owner and term_owner[key] != c.id:
                problems.append(f"termo ambíguo '{term}' em '{c.id}' e '{term_owner[key]}'")
            term_owner.setdefault(key, c.id)

    if problems:
        raise TaxonomyValidationError(problems)
