"""Persistência — contratos e adapters de armazenamento."""

from .errors import ResearcherSignalStoreError
from .store import ResearcherSignalStore, ResearcherSignalStoreResult
from .supabase_store import SupabaseResearcherSignalStore

__all__ = [
    "ResearcherSignalStore",
    "ResearcherSignalStoreError",
    "ResearcherSignalStoreResult",
    "SupabaseResearcherSignalStore",
]
