"""Compat: o Claim Builder foi renomeado para Evidence Builder (112.2C Rev 2).
Imports antigos continuam válidos via alias."""
from __future__ import annotations

from sentinela.builder.evidence_builder import EvidenceBuilder

# alias retrocompatível — pipeline/validation/tests que importam ClaimBuilder seguem ok
ClaimBuilder = EvidenceBuilder

__all__ = ["EvidenceBuilder", "ClaimBuilder"]
