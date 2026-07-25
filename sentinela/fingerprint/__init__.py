"""Concept Fingerprint — Documento 112.7D.

Representação conceitual determinística de eventos científicos.
Sem LLM, sem embeddings, sem rede, sem banco.
"""

from .engine import ConceptFingerprintEngine
from .models import (
    ConceptFingerprint,
    ConceptMatchType,
    ConceptSignal,
    FingerprintConfig,
    FingerprintField,
    FingerprintWeights,
    MatchEvidence,
    UnmatchedTerm,
)

__all__ = [
    "ConceptFingerprint",
    "ConceptFingerprintEngine",
    "ConceptMatchType",
    "ConceptSignal",
    "FingerprintConfig",
    "FingerprintField",
    "FingerprintWeights",
    "MatchEvidence",
    "UnmatchedTerm",
]
