from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from sentinela.persistence import (
    CollectorRunAudit,
    PipelineRunAuditFinal,
    PipelineRunAuditStart,
    PipelineRunAuditStore,
    PipelineRunAuditStoreError,
    SupabasePipelineRunAuditStore,
    sanitize_audit_error,
)

FAKE_URL = "https://fake-project.supabase.co"
FAKE_KEY = "fake-service-role-key"
RUN_ID = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)


class Response:
    status_code = 204

    def raise_for_status(self):
        return None


class Client:
    def __init__(self, *, error=None):
        self.calls = []
        self.error = error

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return Response()


def start() -> PipelineRunAuditStart:
    return PipelineRunAuditStart(
        run_id=RUN_ID,
        initiated_by="manual_cli",
        mode="dry_run",
        started_at=NOW,
        requested_sources=("cams",),
    )


def collector(status="succeeded") -> CollectorRunAudit:
    return CollectorRunAudit(
        run_id=RUN_ID,
        collector="cams",
        collector_role="requested",
        scientific_areas=("atmospheric_science",),
        status=status,
        started_at=NOW,
        completed_at=None if status == "running" else NOW + timedelta(seconds=1),
        records_received=2,
        candidates_generated=1,
    )


def final() -> PipelineRunAuditFinal:
    return PipelineRunAuditFinal(
        run_id=RUN_ID,
        status="succeeded",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        requested_sources=("cams",),
        consulted_sources=("cams",),
        successful_sources=("cams",),
        failed_sources=(),
        records_received=2,
        candidates_generated=1,
        signals_generated=1,
        signals_eligible=1,
        signals_persisted=0,
    )


def test_protocol_and_rpc_operations_are_separate():
    client = Client()
    store = SupabasePipelineRunAuditStore(
        url=FAKE_URL, service_key=FAKE_KEY, client=client
    )

    assert isinstance(store, PipelineRunAuditStore)
    store.create_run(start())
    store.record_collector(collector("running"))
    store.record_collector(collector())
    store.finalize_run(final())

    assert [call[0].rsplit("/", 1)[-1] for call in client.calls] == [
        "create_pipeline_run_audit",
        "record_pipeline_collector_audit",
        "record_pipeline_collector_audit",
        "finalize_pipeline_run_audit",
    ]
    assert client.calls[0][1]["json"]["p_run"]["status"] == "running"
    assert client.calls[-1][1]["json"]["p_run"]["status"] == "succeeded"


def test_adapter_error_is_sanitized():
    request = httpx.Request("POST", FAKE_URL)
    error = httpx.HTTPStatusError(
        "Authorization: Bearer SECRET",
        request=request,
        response=httpx.Response(500, request=request),
    )
    store = SupabasePipelineRunAuditStore(
        url=FAKE_URL,
        service_key="SUPABASE_SERVICE_ROLE_KEY=SECRET",
        client=Client(error=error),
    )

    with pytest.raises(PipelineRunAuditStoreError) as caught:
        store.create_run(start())

    assert "SECRET" not in str(caught.value)
    assert "HTTP 500" in str(caught.value)


@pytest.mark.parametrize(
    "secret",
    (
        "Authorization: Bearer SECRET",
        "apikey=SECRET",
        "token=SECRET",
        "password=SECRET",
        "SUPABASE_SERVICE_ROLE_KEY=SECRET",
        "postgresql://user:SECRET@host/database",
        "https://host/path?token=SECRET&ok=1",
    ),
)
def test_sanitizer_removes_secret_values(secret):
    sanitized = sanitize_audit_error(f"controlled failure {secret}")
    assert "SECRET" not in sanitized
    assert len(sanitized) <= 512


def test_models_normalize_utc_and_validate_order_and_counts():
    local = datetime(2026, 8, 15, 9, tzinfo=timezone(timedelta(hours=-3)))
    model = PipelineRunAuditStart(
        run_id=RUN_ID,
        initiated_by="manual_cli",
        mode="persist",
        started_at=local,
        requested_sources=("cams", "cams"),
    )
    assert model.started_at == NOW
    assert model.requested_sources == ("cams",)

    bounded = CollectorRunAudit(
        run_id=RUN_ID,
        collector="cams",
        collector_role="requested",
        status="failed",
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
        error_message="token=SECRET " + "x" * 1000,
    )
    assert len(bounded.error_message) == 512
    assert "SECRET" not in bounded.error_message

    with pytest.raises(ValidationError):
        CollectorRunAudit(
            run_id=RUN_ID,
            collector="cams",
            collector_role="requested",
            status="succeeded",
            started_at=NOW,
            completed_at=NOW - timedelta(seconds=1),
        )
    with pytest.raises(ValidationError):
        final().model_copy(update={"records_received": -1}, deep=True).__class__(
            **{
                **final().model_dump(),
                "records_received": -1,
            }
        )


def test_migration_020_contract_is_private_and_additive():
    path = Path("supabase/migrations/020_pipeline_run_audit.sql")
    sql = path.read_text(encoding="utf-8").lower()

    assert "create table if not exists raw.pipeline_runs" in sql
    assert "alter table raw.fetch_runs" in sql
    assert "pipeline_run_id uuid" in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog, public, raw" in sql
    assert "grant execute" in sql and "to service_role" in sql
    assert "from public, anon, authenticated" in sql
    assert "alter table raw.pipeline_runs enable row level security" in sql
    assert "create policy" not in sql
    assert "alter table knowledge.events" not in sql
    assert "alter table public.researcher_signals" not in sql
    assert "alter table editorial." not in sql
    assert "create table editorial." not in sql
