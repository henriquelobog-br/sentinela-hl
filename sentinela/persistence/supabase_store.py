"""Adapters Supabase de persistencia (PostgREST via httpx).

Nenhuma regra científica aqui: o adapter serializa ResearcherSignal com
`model_dump(mode="json")` e executa upsert pela coluna `id`.

Segurança:
- URL e service role key vêm exclusivamente de variáveis de ambiente
  (via Settings: SENTINELA_SUPABASE_URL / SENTINELA_SUPABASE_SERVICE_KEY),
  salvo injeção explícita em testes com valores sintéticos;
- a chave nunca é registrada em logs nem incluída em mensagens de erro;
- timeout HTTP explícito;
- erros externos (rede, HTTP 4xx/5xx, JSON inválido) são convertidos em
  ResearcherSignalStoreError, sem credenciais na mensagem.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from sentinela.core.models import Event
from sentinela.projection import ResearcherSignal
from sentinela.seismic_editorial.persistence import SeismicEditorialRecord
from sentinela.volcanic_editorial.persistence import VolcanicEditorialRecord

from .errors import (
    EventStoreError,
    PipelineRunAuditStoreError,
    ResearcherSignalStoreError,
    SeismicEditorialStoreError,
    VolcanicEditorialStoreError,
)
from .run_audit import (
    CollectorRunAudit,
    PipelineRunAuditFinal,
    PipelineRunAuditStart,
)
from .store import (
    EventStoreResult,
    ResearcherSignalStoreResult,
    SeismicEditorialStoreResult,
    VolcanicEditorialStoreResult,
)

_DEFAULT_TIMEOUT_SECONDS = 10.0


def _build_headers(service_key: str) -> dict[str, str]:
    """Headers de autenticação PostgREST conforme o formato da chave.

    - Chave nova `sb_secret_...`: não é JWT — enviada somente como
      `apikey` (enviá-la como `Authorization: Bearer` produz HTTP 401).
    - Chave legada service_role (JWT): `apikey` + `Authorization: Bearer`.

    A chave nunca é registrada em logs nem incluída em mensagens de erro.
    """
    headers = {"apikey": service_key}
    if not service_key.startswith("sb_secret_"):
        headers["authorization"] = f"Bearer {service_key}"
    return headers


def _event_payload(event: Event) -> dict[str, Any]:
    if event.id is None:
        raise EventStoreError("Event.id é obrigatório para persistência canônica")
    return event.model_dump(mode="json")


class SupabaseEventStore:
    """EventStore sobre PostgREST (`knowledge.events`)."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        client: Optional[Any] = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if url is None or service_key is None:
            from sentinela.core.config import get_settings

            settings = get_settings()
            url = url if url is not None else settings.supabase_url
            service_key = service_key if service_key is not None else settings.supabase_service_key

        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(timeout=timeout)

    def upsert_many(self, events: tuple[Event, ...]) -> EventStoreResult:
        received = len(events)
        if received == 0:
            return EventStoreResult(received=0, persisted=0, persisted_ids=())

        payload = [_event_payload(event) for event in events]
        try:
            response = self._client.post(
                f"{self._url}/rest/v1/events",
                params={"on_conflict": "id"},
                json=payload,
                headers={
                    **_build_headers(self._service_key),
                    "content-profile": "knowledge",
                    "content-type": "application/json",
                    "prefer": "resolution=merge-duplicates,return=representation",
                },
            )
            response.raise_for_status()
            rows = response.json()
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status is not None else type(exc).__name__
            raise EventStoreError(f"falha ao persistir Events no Supabase: {detail}") from exc
        except (ValueError, TypeError, AttributeError) as exc:
            raise EventStoreError(
                f"resposta inválida do Supabase: {type(exc).__name__}"
            ) from exc

        persisted_ids = tuple(str(row["id"]) for row in rows)
        return EventStoreResult(
            received=received,
            persisted=len(persisted_ids),
            persisted_ids=persisted_ids,
        )


class SupabasePipelineRunAuditStore:
    """Operational audit adapter backed by restricted public RPCs."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        client: Optional[Any] = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if url is None or service_key is None:
            from sentinela.core.config import get_settings

            settings = get_settings()
            url = url if url is not None else settings.supabase_url
            service_key = (
                service_key
                if service_key is not None
                else settings.supabase_service_key
            )

        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(
            timeout=timeout
        )

    def create_run(self, run: PipelineRunAuditStart) -> None:
        self._call("create_pipeline_run_audit", "p_run", run)

    def record_collector(self, collector: CollectorRunAudit) -> None:
        self._call(
            "record_pipeline_collector_audit",
            "p_collector",
            collector,
        )

    def finalize_run(self, run: PipelineRunAuditFinal) -> None:
        self._call("finalize_pipeline_run_audit", "p_run", run)

    def _call(self, rpc: str, argument: str, payload: Any) -> None:
        try:
            response = self._client.post(
                f"{self._url}/rest/v1/rpc/{rpc}",
                json={argument: payload.model_dump(mode="json")},
                headers={
                    **_build_headers(self._service_key),
                    "content-type": "application/json",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status is not None else type(exc).__name__
            raise PipelineRunAuditStoreError(
                f"falha na auditoria operacional do pipeline: {detail}"
            ) from exc
        except (TypeError, AttributeError) as exc:
            raise PipelineRunAuditStoreError(
                f"payload inválido da auditoria: {type(exc).__name__}"
            ) from exc


def _seismic_editorial_payload(record: SeismicEditorialRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="json", exclude={"content"})
    payload.update(record.content.model_dump(mode="json"))
    return payload


class SupabaseSeismicEditorialStore:
    """SeismicEditorialStore sobre editorial.seismic_contents."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        client: Optional[Any] = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if url is None or service_key is None:
            from sentinela.core.config import get_settings

            settings = get_settings()
            url = url if url is not None else settings.supabase_url
            service_key = (
                service_key
                if service_key is not None
                else settings.supabase_service_key
            )

        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(
            timeout=timeout
        )

    def upsert_many(
        self,
        records: tuple[SeismicEditorialRecord, ...],
    ) -> SeismicEditorialStoreResult:
        received = len(records)
        if received == 0:
            return SeismicEditorialStoreResult(
                received=0,
                persisted=0,
                persisted_ids=(),
            )

        try:
            response = self._client.post(
                f"{self._url}/rest/v1/seismic_contents",
                params={
                    "on_conflict": "event_id,editorial_version,locale",
                },
                json=[_seismic_editorial_payload(record) for record in records],
                headers={
                    **_build_headers(self._service_key),
                    "content-profile": "editorial",
                    "content-type": "application/json",
                    "prefer": "resolution=merge-duplicates,return=representation",
                },
            )
            response.raise_for_status()
            rows = response.json()
            persisted_ids = tuple(str(row["id"]) for row in rows)
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status is not None else type(exc).__name__
            raise SeismicEditorialStoreError(
                f"falha ao persistir editorial sismico no Supabase: {detail}"
            ) from exc
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise SeismicEditorialStoreError(
                f"resposta invalida do Supabase: {type(exc).__name__}"
            ) from exc

        return SeismicEditorialStoreResult(
            received=received,
            persisted=len(persisted_ids),
            persisted_ids=persisted_ids,
        )


def _volcanic_editorial_payload(record: VolcanicEditorialRecord) -> dict[str, Any]:
    payload = record.model_dump(
        mode="json",
        exclude={"content", "id", "created_at", "updated_at"},
    )
    payload.update(record.content.model_dump(mode="json"))
    return payload


class SupabaseVolcanicEditorialStore:
    """VolcanicEditorialStore sobre editorial.volcanic_contents."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        client: Optional[Any] = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if url is None or service_key is None:
            from sentinela.core.config import get_settings

            settings = get_settings()
            url = url if url is not None else settings.supabase_url
            service_key = (
                service_key
                if service_key is not None
                else settings.supabase_service_key
            )

        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(
            timeout=timeout
        )

    def upsert_many(
        self,
        records: tuple[VolcanicEditorialRecord, ...],
    ) -> VolcanicEditorialStoreResult:
        received = len(records)
        if received == 0:
            return VolcanicEditorialStoreResult(
                received=0,
                persisted=0,
                persisted_ids=(),
            )

        try:
            response = self._client.post(
                f"{self._url}/rest/v1/volcanic_contents",
                params={
                    "on_conflict": "editorial_group_id,editorial_version,locale",
                },
                json=[_volcanic_editorial_payload(record) for record in records],
                headers={
                    **_build_headers(self._service_key),
                    "content-profile": "editorial",
                    "content-type": "application/json",
                    "prefer": "resolution=merge-duplicates,return=representation",
                },
            )
            response.raise_for_status()
            rows = response.json()
            persisted_ids = tuple(str(row["id"]) for row in rows)
        except httpx.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status is not None else type(exc).__name__
            raise VolcanicEditorialStoreError(
                f"falha ao persistir editorial vulcanologica no Supabase: {detail}"
            ) from exc
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            raise VolcanicEditorialStoreError(
                f"resposta invalida do Supabase: {type(exc).__name__}"
            ) from exc

        return VolcanicEditorialStoreResult(
            received=received,
            persisted=len(persisted_ids),
            persisted_ids=persisted_ids,
        )


class SupabaseResearcherSignalStore:
    """ResearcherSignalStore sobre PostgREST (`public.researcher_signals`).

    O client HTTP é injetável: produção usa `httpx.Client` com timeout;
    testes usam fake, sem rede e sem credenciais reais.
    """

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        service_key: Optional[str] = None,
        client: Optional[Any] = None,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if url is None or service_key is None:
            # carrega o ambiente somente quando necessário
            from sentinela.core.config import get_settings

            settings = get_settings()
            url = url if url is not None else settings.supabase_url
            service_key = (
                service_key
                if service_key is not None
                else settings.supabase_service_key
            )

        self._url = url.rstrip("/")
        self._service_key = service_key
        self._client = client if client is not None else httpx.Client(
            timeout=timeout
        )

    def upsert_many(
        self,
        signals: tuple[ResearcherSignal, ...],
    ) -> ResearcherSignalStoreResult:
        received = len(signals)
        if received == 0:
            return ResearcherSignalStoreResult(
                received=0,
                persisted=0,
                persisted_ids=(),
            )

        payload = [signal.model_dump(mode="json") for signal in signals]

        try:
            response = self._client.post(
                f"{self._url}/rest/v1/researcher_signals",
                params={"on_conflict": "id"},
                json=payload,
                headers={
                    **_build_headers(self._service_key),
                    "content-type": "application/json",
                    "prefer": "resolution=merge-duplicates,"
                    "return=representation",
                },
            )
            response.raise_for_status()
            rows = response.json()
        except httpx.HTTPError as exc:
            raise self._convert(exc) from exc
        except (ValueError, TypeError, AttributeError) as exc:
            raise ResearcherSignalStoreError(
                f"resposta inválida do Supabase: {type(exc).__name__}"
            ) from exc

        persisted_ids = tuple(str(row["id"]) for row in rows)
        return ResearcherSignalStoreResult(
            received=received,
            persisted=len(persisted_ids),
            persisted_ids=persisted_ids,
        )

    @staticmethod
    def _convert(exc: httpx.HTTPError) -> ResearcherSignalStoreError:
        """Erro externo → erro próprio, sem credenciais na mensagem."""
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is not None:
            detail = f"HTTP {status}"
        else:
            detail = type(exc).__name__
        return ResearcherSignalStoreError(
            f"falha ao persistir sinais no Supabase: {detail}"
        )


__all__ = [
    "SupabaseEventStore",
    "SupabasePipelineRunAuditStore",
    "SupabaseResearcherSignalStore",
    "SupabaseSeismicEditorialStore",
    "SupabaseVolcanicEditorialStore",
]
