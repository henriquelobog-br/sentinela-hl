"""Persistência — contratos e adapters de armazenamento."""

from .errors import (
    CanonicalFailureKind,
    CanonicalProvenanceStoreError,
    EventStoreError,
    PipelineRunAuditStoreError,
    ResearcherSignalStoreError,
    SeismicEditorialStoreError,
    VolcanicEditorialStoreError,
)
from .canonical_store import (
    CanonicalProvenanceStore,
    SupabaseCanonicalProvenanceStore,
)
from .run_audit import (
    CollectorRunAudit,
    PipelineRunAuditFinal,
    PipelineRunAuditStart,
    PipelineRunAuditStore,
    safe_error_type,
    sanitize_audit_error,
)
from .store import (
    EventStore,
    EventStoreResult,
    ResearcherSignalStore,
    ResearcherSignalStoreResult,
    SeismicEditorialStore,
    SeismicEditorialStoreResult,
    VolcanicEditorialStore,
    VolcanicEditorialStoreResult,
)
from .supabase_store import (
    SupabaseEventStore,
    SupabasePipelineRunAuditStore,
    SupabaseResearcherSignalStore,
    SupabaseSeismicEditorialStore,
    SupabaseVolcanicEditorialStore,
)
from .eligibility import is_signal_eligible_for_persistence, signal_contribution_channels

__all__ = [
    "CanonicalProvenanceStore",
    "CanonicalFailureKind",
    "CanonicalProvenanceStoreError",
    "EventStore",
    "EventStoreError",
    "EventStoreResult",
    "CollectorRunAudit",
    "PipelineRunAuditFinal",
    "PipelineRunAuditStart",
    "PipelineRunAuditStore",
    "PipelineRunAuditStoreError",
    "ResearcherSignalStore",
    "ResearcherSignalStoreError",
    "ResearcherSignalStoreResult",
    "SeismicEditorialStore",
    "SeismicEditorialStoreError",
    "SeismicEditorialStoreResult",
    "SupabaseEventStore",
    "SupabaseCanonicalProvenanceStore",
    "SupabasePipelineRunAuditStore",
    "SupabaseResearcherSignalStore",
    "SupabaseSeismicEditorialStore",
    "SupabaseVolcanicEditorialStore",
    "VolcanicEditorialStore",
    "VolcanicEditorialStoreError",
    "VolcanicEditorialStoreResult",
    "is_signal_eligible_for_persistence",
    "signal_contribution_channels",
    "safe_error_type",
    "sanitize_audit_error",
]
