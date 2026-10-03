"""Erros controlados da camada de persistência."""

from __future__ import annotations

from enum import Enum


class EventStoreError(RuntimeError):
    """Falha controlada na persistência canônica de Event."""


class SeismicEditorialStoreError(RuntimeError):
    """Falha controlada na persistencia da projecao editorial sismica."""


class VolcanicEditorialStoreError(RuntimeError):
    """Falha controlada na persistencia da projecao editorial vulcanologica."""


class ResearcherSignalStoreError(RuntimeError):
    """Falha externa de persistência (rede, HTTP 4xx/5xx, resposta
    inválida), já convertida pelo adapter. Nunca contém credenciais."""


class PipelineRunAuditStoreError(RuntimeError):
    """Falha operacional da auditoria, separada da ciência do pipeline."""


class CanonicalFailureKind(str, Enum):
    """Quanto se sabe sobre o commit após uma falha canonical."""

    DEFINITIVE_REJECTION = "definitive_rejection"
    NOT_COMMITTED = "not_committed"
    COMMIT_AMBIGUOUS = "commit_ambiguous"


class CanonicalProvenanceStoreError(RuntimeError):
    """Falha canonical sanitizada, com semântica explícita de commit."""

    def __init__(
        self,
        message: str,
        *,
        failure_kind: CanonicalFailureKind = CanonicalFailureKind.COMMIT_AMBIGUOUS,
        status_code: int | None = None,
        postgrest_code: str | None = None,
        postgrest_message: str | None = None,
        details: str | None = None,
        hint: str | None = None,
        rpc: str | None = None,
        run_id: str | None = None,
        operation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.status_code = status_code
        self.postgrest_code = postgrest_code
        self.postgrest_message = postgrest_message
        self.details = details
        self.hint = hint
        self.rpc = rpc
        self.run_id = run_id
        self.operation = operation

    @property
    def commit_ambiguous(self) -> bool:
        return self.failure_kind == CanonicalFailureKind.COMMIT_AMBIGUOUS


__all__ = [
    "CanonicalFailureKind",
    "CanonicalProvenanceStoreError",
    "EventStoreError",
    "PipelineRunAuditStoreError",
    "ResearcherSignalStoreError",
    "SeismicEditorialStoreError",
    "VolcanicEditorialStoreError",
]
