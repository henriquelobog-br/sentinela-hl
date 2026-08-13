"""Persistência — contratos e adapters de armazenamento."""

from .errors import ResearcherSignalStoreError
from .store import ResearcherSignalStore, ResearcherSignalStoreResult
from .supabase_store import SupabaseResearcherSignalStore
from .eligibility import is_signal_eligible_for_persistence, signal_contribution_channels

__all__ = [
    "ResearcherSignalStore",
    "ResearcherSignalStoreError",
    "ResearcherSignalStoreResult",
    "SupabaseResearcherSignalStore",
    "is_signal_eligible_for_persistence",
    "signal_contribution_channels",
]
