"""Persistência — contratos e adapters de armazenamento."""

from .errors import EventStoreError, ResearcherSignalStoreError
from .store import EventStore, EventStoreResult, ResearcherSignalStore, ResearcherSignalStoreResult
from .supabase_store import SupabaseEventStore, SupabaseResearcherSignalStore
from .eligibility import is_signal_eligible_for_persistence, signal_contribution_channels

__all__ = [
    "EventStore",
    "EventStoreError",
    "EventStoreResult",
    "ResearcherSignalStore",
    "ResearcherSignalStoreError",
    "ResearcherSignalStoreResult",
    "SupabaseEventStore",
    "SupabaseResearcherSignalStore",
    "is_signal_eligible_for_persistence",
    "signal_contribution_channels",
]
