from __future__ import annotations

import httpx
import pytest

from sentinela.canonical_provenance import (
    CanonicalEventCandidate,
    CollectorRole,
    accept_canonical_events,
    build_canonical_signal_record,
)
from pydantic import ValidationError

from sentinela.canonical_provenance.models import (
    CanonicalPersistenceItemResult,
    PersistenceDisposition,
    RunManifestFinal,
)
from sentinela.canonical_provenance.tests.test_gate import valid_event
from sentinela.persistence import (
    CanonicalFailureKind,
    CanonicalProvenanceStore,
    CanonicalProvenanceStoreError,
    SupabaseCanonicalProvenanceStore,
)
from sentinela.projection import project_researcher_signals
from sentinela.projection.tests.test_researcher_signal import single_item_bulletin

FAKE_URL = "https://fake-project.supabase.co"
FAKE_KEY = "fake-service-role-key"
RUN_ID = "11111111-1111-4111-8111-111111111111"


class Response:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", FAKE_URL)
            response = httpx.Response(
                self.status_code, request=request, json=self.payload
            )
            raise httpx.HTTPStatusError(
                "external secret=SECRET", request=request, response=response
            )

    def json(self):
        return self.payload


class Client:
    def __init__(self, responses):
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


def make_store(client):
    return SupabaseCanonicalProvenanceStore(
        url=FAKE_URL, service_key=FAKE_KEY, client=client
    )


def event_acceptance():
    return accept_canonical_events(
        (
            CanonicalEventCandidate(
                event=valid_event(),
                collector="usgs",
                collector_role=CollectorRole.REQUESTED,
            ),
        )
    )


def test_adapter_uses_restricted_event_signal_and_manifest_rpcs():
    event = valid_event()
    signal = project_researcher_signals(single_item_bulletin())[0]
    record = build_canonical_signal_record(
        signal,
        representative_event_id=signal.representative_event_id,
        contributor_event_ids=(),
        accepted_event_ids=frozenset({signal.representative_event_id}),
    )
    client = Client(
        [
            Response(None, 204),
            Response(
                [
                    {
                        "artifact_id": str(event.id),
                        "disposition": "inserted",
                        "content_hash": "a" * 64,
                        "revision_id": RUN_ID,
                    }
                ]
            ),
            Response(
                [
                    {
                        "artifact_id": signal.id,
                        "disposition": "inserted",
                        "content_hash": "b" * 64,
                    }
                ]
            ),
            Response(None, 204),
        ]
    )
    adapter = make_store(client)
    assert isinstance(adapter, CanonicalProvenanceStore)

    event_result = adapter.persist_events(RUN_ID, event_acceptance())
    signal_result = adapter.persist_signals(RUN_ID, (record,))
    adapter.finalize_manifest(RunManifestFinal(run_id=RUN_ID, stage="finalized"))

    assert event_result.items[0].disposition.value == "inserted"
    assert signal_result.persisted == 1
    assert [call["url"].rsplit("/", 1)[-1] for call in client.calls] == [
        "begin_canonical_run_manifest",
        "persist_canonical_event_batch",
        "persist_canonical_signal_batch",
        "finalize_canonical_run_manifest",
    ]
    assert client.calls[-1]["json"]["p_commit_state"] == "known"


def test_manifest_can_record_commit_ambiguity_without_retrying():
    client = Client([Response(None, 204)])
    make_store(client).finalize_manifest(
        RunManifestFinal(
            run_id=RUN_ID,
            stage="failed",
            commit_ambiguous=True,
            error_type="TimeoutError",
            error_message="commit outcome unknown",
        )
    )
    assert client.calls[0]["json"]["p_commit_state"] == "ambiguous"


def test_empty_signal_batch_does_not_call_network():
    client = Client([])
    result = make_store(client).persist_signals(RUN_ID, ())
    assert result.persisted == 0
    assert client.calls == []


def test_http_400_preserves_allowlisted_context_without_commit_ambiguity():
    client = Client([
        Response(None, 204),
        Response({
            "code": "42702",
            "message": "column content_hash is ambiguous",
            "details": "Authorization: Bearer TOP_SECRET",
            "hint": "apikey=TOP_SECRET",
            "payload": {"evidence": "must not escape"},
        }, 400),
    ])
    adapter = SupabaseCanonicalProvenanceStore(
        url=FAKE_URL,
        service_key="TOP_SECRET",
        client=client,
    )
    with pytest.raises(CanonicalProvenanceStoreError) as caught:
        adapter.persist_events(RUN_ID, event_acceptance())
    error = caught.value
    assert error.failure_kind == CanonicalFailureKind.DEFINITIVE_REJECTION
    assert error.commit_ambiguous is False
    assert error.status_code == 400
    assert error.postgrest_code == "42702"
    assert error.postgrest_message == "column content_hash is ambiguous"
    assert error.rpc == "persist_canonical_event_batch"
    assert error.run_id == RUN_ID
    assert error.operation == "canonical_event_persistence"
    assert "TOP_SECRET" not in str(error)
    assert "TOP_SECRET" not in (error.details or "")
    assert "TOP_SECRET" not in (error.hint or "")
    assert "must not escape" not in str(error)
    assert "authorization" in str(error).lower()
    assert "<redacted>" in str(error)
    assert error.__cause__ is None


def test_http_500_remains_conservatively_commit_ambiguous():
    client = Client([Response(None, 204), Response({"message": "gateway"}, 500)])
    with pytest.raises(CanonicalProvenanceStoreError) as caught:
        make_store(client).persist_events(RUN_ID, event_acceptance())
    assert caught.value.failure_kind == CanonicalFailureKind.COMMIT_AMBIGUOUS
    assert caught.value.commit_ambiguous is True


def test_invalid_run_id_fails_before_request_is_sent():
    client = Client([])
    with pytest.raises(ValueError):
        make_store(client).persist_events("not-a-uuid", event_acceptance())
    assert client.calls == []


def test_connect_failure_is_known_not_committed():
    request = httpx.Request("POST", FAKE_URL)
    client = RaisingClient(httpx.ConnectError("connect failed", request=request))
    with pytest.raises(CanonicalProvenanceStoreError) as caught:
        make_store(client).persist_events(RUN_ID, event_acceptance())
    assert caught.value.failure_kind == CanonicalFailureKind.NOT_COMMITTED
    assert caught.value.commit_ambiguous is False


def test_read_timeout_after_request_is_commit_ambiguous():
    request = httpx.Request("POST", FAKE_URL)
    client = RaisingClient(httpx.ReadTimeout("read failed", request=request))
    with pytest.raises(CanonicalProvenanceStoreError) as caught:
        make_store(client).persist_events(RUN_ID, event_acceptance())
    assert caught.value.failure_kind == CanonicalFailureKind.COMMIT_AMBIGUOUS
    assert caught.value.commit_ambiguous is True


@pytest.mark.parametrize("disposition", ("inserted", "updated", "observed_existing"))
def test_adapter_preserves_event_dispositions(disposition):
    client = Client([
        Response(None, 204),
        Response([{
            "artifact_id": str(valid_event().id),
            "disposition": disposition,
            "content_hash": "c" * 64,
            "revision_id": RUN_ID,
        }])
    ])
    result = make_store(client).persist_events(RUN_ID, event_acceptance())
    assert result.items[0].disposition.value == disposition


def signal_record(signal_id: str | None = None):
    signal = project_researcher_signals(single_item_bulletin())[0]
    if signal_id is not None:
        signal = signal.model_copy(update={"id": signal_id})
    return build_canonical_signal_record(
        signal,
        representative_event_id=signal.representative_event_id,
        contributor_event_ids=(),
        accepted_event_ids=frozenset({signal.representative_event_id}),
    )


def persist_signal_rows(adapter, rows, records=None):
    records = records if records is not None else tuple(
        signal_record(f"signal-{index}") for index in range(len(rows))
    )
    client = adapter._client
    client.responses = iter([Response(rows)])
    return adapter.persist_signals(RUN_ID, records), records


def test_adapter_accepts_rejected_occurrence_without_content_hash():
    rejected_event = valid_event().model_copy(update={"source": None})
    acceptance = accept_canonical_events((
        CanonicalEventCandidate(
            event=rejected_event,
            collector="usgs",
            collector_role=CollectorRole.REQUESTED,
        ),
    ))
    client = Client([
        Response(None, 204),
        Response([{
            "artifact_id": str(rejected_event.id),
            "disposition": "rejected",
            "content_hash": None,
            "revision_id": None,
        }])
    ])
    result = make_store(client).persist_events(RUN_ID, acceptance)
    assert result.rejected == 1
    assert result.items[0].content_hash is None


def test_persist_signals_counts_only_successful_dispositions():
    adapter = make_store(Client([]))
    result, records = persist_signal_rows(
        adapter,
        [
            {
                "artifact_id": "inserted-id",
                "disposition": "inserted",
                "content_hash": "a" * 64,
            },
            {
                "artifact_id": "updated-id",
                "disposition": "updated",
                "content_hash": "b" * 64,
            },
            {
                "artifact_id": "observed-id",
                "disposition": "observed_existing",
                "content_hash": "c" * 64,
            },
        ],
    )
    assert result.received == 3
    assert result.persisted == 3
    assert len(records) == 3
    assert [item.disposition for item in result.items] == [
        PersistenceDisposition.INSERTED,
        PersistenceDisposition.UPDATED,
        PersistenceDisposition.OBSERVED_EXISTING,
    ]


def test_persist_signals_mixed_results_exclude_rejected_from_persisted():
    adapter = make_store(Client([]))
    result, _ = persist_signal_rows(
        adapter,
        [
            {
                "artifact_id": "inserted-id",
                "disposition": "inserted",
                "content_hash": "a" * 64,
            },
            {
                "artifact_id": "legacy-id",
                "disposition": "rejected",
                "content_hash": None,
            },
            {
                "artifact_id": "observed-id",
                "disposition": "observed_existing",
                "content_hash": "c" * 64,
            },
        ],
    )
    assert result.received == 3
    assert result.persisted == 2
    assert result.items[1].disposition == PersistenceDisposition.REJECTED
    assert result.items[1].content_hash is None


def test_persist_signals_all_rejected_persists_zero():
    adapter = make_store(Client([]))
    result, records = persist_signal_rows(
        adapter,
        [
            {
                "artifact_id": "legacy-a",
                "disposition": "rejected",
                "content_hash": None,
            },
            {
                "artifact_id": "legacy-b",
                "disposition": "rejected",
                "content_hash": None,
            },
        ],
    )
    assert result.received == 2
    assert result.persisted == 0
    assert len(records) == 2
    assert all(
        item.disposition == PersistenceDisposition.REJECTED
        and item.content_hash is None
        for item in result.items
    )


def test_rejected_result_with_content_hash_is_invalid():
    with pytest.raises(ValidationError, match="rejected artifact cannot have content_hash"):
        CanonicalPersistenceItemResult(
            artifact_id="legacy-id",
            disposition=PersistenceDisposition.REJECTED,
            content_hash="a" * 64,
        )


def test_successful_result_without_content_hash_is_invalid():
    with pytest.raises(ValidationError, match="persisted artifact requires content_hash"):
        CanonicalPersistenceItemResult(
            artifact_id="inserted-id",
            disposition=PersistenceDisposition.INSERTED,
            content_hash=None,
        )


def test_persist_signals_http_400_is_definitive_rejection():
    client = Client([
        Response({
            "code": "P0001",
            "message": "representative canonical Event not persisted in this run",
            "details": "Authorization: Bearer TOP_SECRET",
            "hint": "apikey=TOP_SECRET",
        }, 400),
    ])
    adapter = SupabaseCanonicalProvenanceStore(
        url=FAKE_URL,
        service_key="TOP_SECRET",
        client=client,
    )
    with pytest.raises(CanonicalProvenanceStoreError) as caught:
        adapter.persist_signals(RUN_ID, (signal_record(),))
    error = caught.value
    assert error.failure_kind == CanonicalFailureKind.DEFINITIVE_REJECTION
    assert error.commit_ambiguous is False
    assert error.status_code == 400
    assert error.postgrest_code == "P0001"
    assert error.rpc == "persist_canonical_signal_batch"
    assert error.operation == "canonical_signal_persistence"
    assert "TOP_SECRET" not in str(error)
    assert "<redacted>" in str(error)


def test_persist_signals_http_500_remains_commit_ambiguous():
    client = Client([Response({"message": "gateway"}, 500)])
    with pytest.raises(CanonicalProvenanceStoreError) as caught:
        make_store(client).persist_signals(RUN_ID, (signal_record(),))
    assert caught.value.failure_kind == CanonicalFailureKind.COMMIT_AMBIGUOUS
    assert caught.value.commit_ambiguous is True
