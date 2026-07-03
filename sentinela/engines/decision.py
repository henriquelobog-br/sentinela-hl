"""Sentinela HL — DecisionEngine (Documento 113.3).

Política de decisão do 112A. Determinística: sem estado, sem I/O, sem IA.
Recebe classifications[] e devolve (decision, requires_human_review).

Regra (subconjunto 1·2·4):
  qualquer fail  → reject
  qualquer flag  → escalate (requires_human_review = True)
  todos pass     → pass
"""
from __future__ import annotations

from sentinela.core.models import Classification, FilterResult, RoutingDecision


class DecisionEngine:
    @staticmethod
    def decide(classifications: list[Classification]) -> tuple[RoutingDecision, bool]:
        results = [c.result for c in classifications]
        if any(r == FilterResult.FAIL for r in results):
            return "reject", False
        if any(r == FilterResult.FLAG for r in results):
            return "escalate", True
        return "pass", False
