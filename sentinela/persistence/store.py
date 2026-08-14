"""Contrato de persistência de ResearcherSignal.

Abstração pequena que desacopla o pipeline do SDK/HTTP do Supabase
(mesmo padrão de `sentinela/clients/base.py`: o resto da aplicação
conhece só o Protocol, nunca o provedor).

Sem regra científica aqui: o store só transporta a serialização pública
de ResearcherSignal.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from sentinela.core.models import Event
from sentinela.projection import ResearcherSignal


class EventStoreResult(BaseModel):
    """Resultado de uma operação de persistência canônica de Event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    received: int = Field(ge=0)
    persisted: int = Field(ge=0)
    persisted_ids: tuple[str, ...]


@runtime_checkable
class EventStore(Protocol):
    """Fronteira de persistência da memória científica canônica."""

    def upsert_many(self, events: tuple[Event, ...]) -> EventStoreResult:
        """Persiste Events por sua identidade determinística `Event.id`."""
        ...


class ResearcherSignalStoreResult(BaseModel):
    """Resultado de uma operação de persistência em lote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    received: int = Field(ge=0)
    persisted: int = Field(ge=0)
    persisted_ids: tuple[str, ...]


@runtime_checkable
class ResearcherSignalStore(Protocol):
    """Fronteira de persistência de sinais do pesquisador."""

    def upsert_many(
        self,
        signals: tuple[ResearcherSignal, ...],
    ) -> ResearcherSignalStoreResult:
        """Persiste sinais de forma idempotente, usando
        `ResearcherSignal.id` como chave de upsert."""
        ...


__all__ = [
    "EventStore",
    "EventStoreResult",
    "ResearcherSignalStore",
    "ResearcherSignalStoreResult",
]
