"""Contrato do módulo de filtros — o coração do Sentinela.

Cada filtro recebe uma Claim + contexto e devolve UMA Classification.
A agregação em FilterReport (decisão pass/escalate/reject) e a LÓGICA de
cada filtro são o Documento 113 — aqui só o formato.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable
from shared.models import Claim, Classification, FilterContext, FilterKey, FilterReport


@runtime_checkable
class Filter(Protocol):
    """Um filtro isolado (ex.: proveniência, rótulo, calibração)."""
    key: FilterKey

    def evaluate(self, claim: Claim, context: FilterContext) -> Classification:
        ...


@runtime_checkable
class FilterPipeline(Protocol):
    """Roda os filtros habilitados e agrega no veredito."""
    def run(self, claim: Claim, context: FilterContext) -> FilterReport:
        ...
