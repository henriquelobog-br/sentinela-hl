"""Adapter Supabase para ResearcherSignalStore (PostgREST via httpx).

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

from sentinela.projection import ResearcherSignal

from .errors import ResearcherSignalStoreError
from .store import ResearcherSignalStoreResult

_DEFAULT_TIMEOUT_SECONDS = 10.0


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
                    "apikey": self._service_key,
                    "authorization": f"Bearer {self._service_key}",
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


__all__ = ["SupabaseResearcherSignalStore"]
