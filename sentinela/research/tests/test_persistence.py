from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import httpx
import pytest

from sentinela.research.openalex import parse_openalex_work
from sentinela.research.persistence import (
    ResearchWorkFailureKind,
    ResearchWorkStore,
    ResearchWorkStoreError,
    SupabaseResearchWorkStore,
    build_research_work_persistence_item,
)
from sentinela.research.relevance import evaluate_relevance
from sentinela.research.tests.conftest import article_payload, mapping_table

URL = "https://fake-project.supabase.co"
KEY = "fake-service-role-key"
RUN_ID = "11111111-1111-4111-8111-111111111111"
FETCH_ID = UUID("22222222-2222-4222-8222-222222222222")


class Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", URL)
            response = httpx.Response(self.status_code, request=request, json=self.payload)
            raise httpx.HTTPStatusError("external", request=request, response=response)

    def json(self):
        return self.payload


class Client:
    def __init__(self, responses=()):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return next(self.responses)


class RaisingClient:
    def __init__(self, error):
        self.error = error

    def post(self, url, **kwargs):
        raise self.error


def item(*, relevant=True):
    payload = article_payload()
    work = parse_openalex_work(payload)
    relevance = evaluate_relevance(work, mapping_table(), "v1") if relevant else None
    return build_research_work_persistence_item(
        fetch_run_id=FETCH_ID,
        retrieved_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        raw_payload=payload,
        work=work,
        relevance=relevance,
    )


def row(index=1):
    return {
        "item_index": index,
        "source": "openalex",
        "source_work_id": "W2741809807",
        "raw_disposition": "inserted",
        "canonical_disposition": "inserted",
        "temporal_disposition": "fresh",
        "citation_disposition": "first_observation",
        "relevance_status": "relevant",
        "identity_conflict": False,
        "research_work_id": "33333333-3333-4333-8333-333333333333",
        "raw_record_id": "44444444-4444-4444-8444-444444444444",
        "error_code": None,
    }


def store(client):
    return SupabaseResearchWorkStore(url=URL, service_key=KEY, client=client)


def test_build_item_preserves_raw_normalized_and_relevance_contract():
    built = item()
    rpc = built.to_rpc_item()
    assert rpc["raw"]["fetch_run_id"] == str(FETCH_ID)
    assert rpc["raw"]["payload"]["id"].endswith("W2741809807")
    assert "raw_payload_hash" not in rpc["normalized"]
    assert rpc["relevance"] == {
        "mapping_version_requested": "v1",
        "mapping_version_applied": "v1",
        "relevance_status": "relevant",
        "mapped_topic_ids": ["T10178", "T11922"],
    }


def test_adapter_calls_only_research_batch_rpc_and_preserves_result():
    client = Client([Response([row()])])
    adapter = store(client)
    assert isinstance(adapter, ResearchWorkStore)
    result = adapter.persist_many(RUN_ID, (item(),))
    assert result.received == 1
    assert result.items[0].raw_disposition == "inserted"
    assert client.calls[0]["url"].endswith("/rpc/persist_research_work_batch")
    assert client.calls[0]["json"]["p_run_id"] == RUN_ID
    assert client.calls[0]["headers"]["authorization"] == f"Bearer {KEY}"


def test_empty_batch_does_not_call_transport():
    client = Client()
    assert store(client).persist_many(RUN_ID, ()).items == ()
    assert client.calls == []


def test_invalid_run_and_oversized_batch_fail_before_transport():
    client = Client()
    with pytest.raises(ValueError):
        store(client).persist_many("bad", (item(),))
    with pytest.raises(ValueError, match="500"):
        store(client).persist_many(RUN_ID, (item(),) * 501)
    assert client.calls == []


def test_invalid_result_count_is_commit_ambiguous():
    with pytest.raises(ResearchWorkStoreError) as caught:
        store(Client([Response([])])).persist_many(RUN_ID, (item(),))
    assert caught.value.commit_ambiguous is True


def test_http_400_is_definitive_and_redacts_credentials():
    client = Client([Response({
        "code": "22000",
        "message": "invalid payload",
        "details": f"Authorization: Bearer {KEY}",
        "hint": f"apikey={KEY}",
    }, 400)])
    with pytest.raises(ResearchWorkStoreError) as caught:
        store(client).persist_many(RUN_ID, (item(),))
    assert caught.value.failure_kind == ResearchWorkFailureKind.DEFINITIVE_REJECTION
    assert KEY not in str(caught.value)
    assert KEY not in (caught.value.details or "")


def test_connect_failure_is_known_not_committed():
    request = httpx.Request("POST", URL)
    adapter = store(RaisingClient(httpx.ConnectError("offline", request=request)))
    with pytest.raises(ResearchWorkStoreError) as caught:
        adapter.persist_many(RUN_ID, (item(),))
    assert caught.value.failure_kind == ResearchWorkFailureKind.NOT_COMMITTED


def test_read_timeout_is_commit_ambiguous():
    request = httpx.Request("POST", URL)
    adapter = store(RaisingClient(httpx.ReadTimeout("unknown", request=request)))
    with pytest.raises(ResearchWorkStoreError) as caught:
        adapter.persist_many(RUN_ID, (item(),))
    assert caught.value.commit_ambiguous is True


def test_naive_retrieved_at_is_rejected_locally():
    payload = article_payload()
    work = parse_openalex_work(payload)
    with pytest.raises(ValueError, match="timezone-aware"):
        build_research_work_persistence_item(
            fetch_run_id=FETCH_ID,
            retrieved_at=datetime(2026, 10, 4),
            raw_payload=payload,
            work=work,
        )
