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
from sentinela.seismic_editorial.persistence import SeismicEditorialRecord
from sentinela.volcanic_editorial.persistence import VolcanicEditorialRecord


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


class SeismicEditorialStoreResult(BaseModel):
    """Resultado de uma operacao de persistencia editorial em lote."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    received: int = Field(ge=0)
    persisted: int = Field(ge=0)
    persisted_ids: tuple[str, ...]


@runtime_checkable
class SeismicEditorialStore(Protocol):
    """Fronteira de persistencia de conteudo editorial ja produzido."""

    def upsert_many(
        self,
        records: tuple[SeismicEditorialRecord, ...],
    ) -> SeismicEditorialStoreResult:
        """Persiste pela chave Event, versao editorial e locale."""
        ...


class VolcanicEditorialStoreResult(BaseModel):
    """Resultado de uma operacao de persistencia editorial vulcanologica."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    received: int = Field(ge=0)
    persisted: int = Field(ge=0)
    persisted_ids: tuple[str, ...]


@runtime_checkable
class VolcanicEditorialStore(Protocol):
    """Fronteira de persistencia de grupos editoriais ja produzidos."""

    def upsert_many(
        self,
        records: tuple[VolcanicEditorialRecord, ...],
    ) -> VolcanicEditorialStoreResult:
        """Persiste por grupo editorial, versao e locale."""
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
    "SeismicEditorialStore",
    "SeismicEditorialStoreResult",
    "VolcanicEditorialStore",
    "VolcanicEditorialStoreResult",
]
