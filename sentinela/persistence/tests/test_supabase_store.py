"""Persistência de ResearcherSignal — contrato ResearcherSignalStore e
adapter Supabase (PostgREST), testados com cliente fake injetado.

Nenhum acesso à rede real, nenhuma credencial real.
"""

from __future__ import annotations

import httpx
import pytest

from sentinela.persistence import (
    ResearcherSignalStoreError,
    ResearcherSignalStoreResult,
    SupabaseResearcherSignalStore,
)
from sentinela.projection import project_researcher_signals
from sentinela.projection.tests.test_researcher_signal import (
    multi_item_bulletin,
    single_item_bulletin,
)

FAKE_URL = "https://fake-project.supabase.co"
FAKE_SERVICE_KEY = "fake-service-role-key-for-tests"


# ------------------------------------------------------------------ fakes
class FakeResponse:
    """Resposta HTTP mínima compatível com o uso do adapter."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", f"{FAKE_URL}/rest/v1/x")
            response = httpx.Response(
                self.status_code,
                request=request,
                text="external failure",
            )
            raise httpx.HTTPStatusError(
                "server error", request=request, response=response
            )

    def json(self):
        return self._payload


class FakeClient:
    """Client HTTP injetado: registra chamadas e devolve resposta fixa."""

    def __init__(self, response=None, error: Exception | None = None):
        self.calls: list[dict] = []
        self._response = response
        self._error = error

    def post(self, url, *, params=None, json=None, headers=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "json": json,
                "headers": headers,
            }
        )
        if self._error is not None:
            raise self._error
        return self._response


# --------------------------------------------------------------- fixtures
def single_signals():
    return project_researcher_signals(single_item_bulletin())


def multi_signals():
    return project_researcher_signals(multi_item_bulletin())


def make_store(client) -> SupabaseResearcherSignalStore:
    return SupabaseResearcherSignalStore(
        url=FAKE_URL,
        service_key=FAKE_SERVICE_KEY,
        client=client,
    )


def ok_client(payload_count: int) -> FakeClient:
    signals = multi_signals()[:payload_count]
    return FakeClient(
        response=FakeResponse([{"id": s.id} for s in signals])
    )


# ------------------------------------------------------------------ testes
def test_payload_correto():
    signals = single_signals()
    client = FakeClient(
        response=FakeResponse([{"id": signals[0].id}])
    )

    make_store(client).upsert_many(signals)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == f"{FAKE_URL}/rest/v1/researcher_signals"
    assert call["json"] == [s.model_dump(mode="json") for s in signals]
    # nenhuma regra científica: o payload é exatamente a serialização pública
    assert call["json"][0]["priority_level"] == "urgent"
    assert isinstance(call["json"][0]["reasons"], list)
    assert isinstance(call["json"][0]["member_event_ids"], list)


def test_upsert_pela_chave_id():
    signals = single_signals()
    client = FakeClient(
        response=FakeResponse([{"id": signals[0].id}])
    )

    make_store(client).upsert_many(signals)

    call = client.calls[0]
    assert call["params"] == {"on_conflict": "id"}
    assert "resolution=merge-duplicates" in call["headers"]["prefer"]


def test_lote_vazio_nao_chama_rede():
    client = FakeClient(response=FakeResponse([]))

    result = make_store(client).upsert_many(())

    assert client.calls == []
    assert result == ResearcherSignalStoreResult(
        received=0,
        persisted=0,
        persisted_ids=(),
    )


def test_multiplos_sinais():
    signals = multi_signals()
    assert len(signals) == 2
    client = FakeClient(
        response=FakeResponse([{"id": s.id} for s in signals])
    )

    result = make_store(client).upsert_many(signals)

    assert len(client.calls) == 1
    assert len(client.calls[0]["json"]) == 2
    assert result.received == 2
    assert result.persisted == 2
    assert result.persisted_ids == tuple(s.id for s in signals)


def test_idempotencia_mesma_chave_mesmo_payload():
    signals = multi_signals()
    client = FakeClient(
        response=FakeResponse([{"id": s.id} for s in signals])
    )
    store = make_store(client)

    first = store.upsert_many(signals)
    second = store.upsert_many(signals)

    assert first == second
    assert len(client.calls) == 2
    assert client.calls[0]["json"] == client.calls[1]["json"]
    assert client.calls[0]["json"][0]["id"] == signals[0].id


def test_erro_externo_convertido():
    error = httpx.ConnectError("connection refused")
    client = FakeClient(error=error)

    with pytest.raises(ResearcherSignalStoreError) as excinfo:
        make_store(client).upsert_many(single_signals())

    assert excinfo.value.__cause__ is error


def test_erro_http_convertido_sem_credenciais():
    client = FakeClient(response=FakeResponse([], status_code=500))

    with pytest.raises(ResearcherSignalStoreError) as excinfo:
        make_store(client).upsert_many(single_signals())

    message = str(excinfo.value)
    assert "500" in message
    assert FAKE_SERVICE_KEY not in message
    assert FAKE_SERVICE_KEY not in repr(excinfo.value.__cause__)


def test_resultado_deterministico():
    signals = multi_signals()

    def run() -> ResearcherSignalStoreResult:
        client = FakeClient(
            response=FakeResponse([{"id": s.id} for s in signals])
        )
        return make_store(client).upsert_many(signals)

    first = run()
    second = run()

    assert first == second
    assert first.persisted_ids == second.persisted_ids
