from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sentinela.persistence import (
    PipelineRunAuditStoreError,
    ResearcherSignalStoreResult,
)
from sentinela.real_signals.collectors import CollectionResult
from sentinela.real_signals.orchestrator import run_real_signals
from sentinela.real_signals.tests.test_acled import (
    NOW as ACLED_NOW,
    collect as collect_acled,
    row as acled_row,
    settings as acled_settings,
)
from sentinela.real_signals.tests.test_real_signals import (
    NOW,
    FixedCollector,
    cams_result,
    cams_row,
    settings,
)


@dataclass
class RecordingAuditStore:
    starts: list = field(default_factory=list)
    collectors: list = field(default_factory=list)
    finals: list = field(default_factory=list)
    fail_create: bool = False
    fail_record: bool = False
    fail_finalize: bool = False

    def create_run(self, run):
        if self.fail_create:
            raise PipelineRunAuditStoreError("create failed")
        self.starts.append(run)

    def record_collector(self, collector):
        if self.fail_record:
            raise PipelineRunAuditStoreError("record failed")
        self.collectors.append(collector)

    def finalize_run(self, run):
        if self.fail_finalize:
            raise PipelineRunAuditStoreError("finalize failed")
        self.finals.append(run)


class CountingCollector:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def collect(self, now):
        self.calls += 1
        return self.result


class SignalStore:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def upsert_many(self, signals):
        self.calls.append(signals)
        if self.fail:
            raise RuntimeError("scientific persistence failed token=SECRET")
        return ResearcherSignalStoreResult(
            received=len(signals),
            persisted=len(signals),
            persisted_ids=tuple(signal.id for signal in signals),
        )


def test_succeeded_run_lifecycle_and_status_mapping():
    audit = RecordingAuditStore()
    result = cams_result(cams_row())

    run = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors={"cams": FixedCollector(result)},
        audit_store=audit,
    )

    assert run.result.status == "complete"
    assert len(audit.starts) == 1
    assert [item.status for item in audit.collectors] == ["running", "succeeded"]
    assert audit.finals[0].status == "succeeded"
    assert audit.finals[0].candidates_generated == len(run.events)
    assert audit.finals[0].signals_generated == len(run.signals)
    assert audit.starts[0].started_at.tzinfo is not None
    assert audit.finals[0].completed_at >= audit.starts[0].started_at


@pytest.mark.parametrize(
    ("successes", "failures", "expected"),
    ((1, 1, "partial"), (0, 2, "failed")),
)
def test_partial_and_failed_runs(successes, failures, expected):
    audit = RecordingAuditStore()
    collectors = {}
    sources = []
    for index in range(successes):
        name = f"ok-{index}"
        sources.append(name)
        collectors[name] = FixedCollector(CollectionResult(source=name))
    for index in range(failures):
        name = f"failed-{index}"
        sources.append(name)
        collectors[name] = FixedCollector(error=RuntimeError("offline"))

    run = run_real_signals(
        settings=settings(),
        sources=tuple(sources),
        now=NOW,
        collectors=collectors,
        audit_store=audit,
    )

    assert run.result.status == expected
    assert audit.finals[0].status == expected
    assert len(audit.finals[0].successful_sources) == successes
    assert len(audit.finals[0].failed_sources) == failures


def test_fifteen_successes_and_one_failure_is_partial():
    audit = RecordingAuditStore()
    sources = tuple(f"source-{index}" for index in range(16))
    collectors = {
        source: FixedCollector(
            error=RuntimeError("offline") if index == 15 else None,
            result=None if index == 15 else CollectionResult(source=source),
        )
        for index, source in enumerate(sources)
    }

    run = run_real_signals(
        settings=settings(),
        sources=sources,
        now=NOW,
        collectors=collectors,
        audit_store=audit,
    )

    assert run.result.status == "partial"
    assert audit.finals[0].status == "partial"
    assert len(audit.finals[0].successful_sources) == 15
    assert audit.finals[0].failed_sources == ("source-15",)


def test_supporting_collector_failure_is_audited_and_partial():
    acled, _ = collect_acled([acled_row()])
    audit = RecordingAuditStore()

    run = run_real_signals(
        settings=acled_settings(),
        sources=("acled",),
        now=ACLED_NOW,
        collectors={
            "acled": FixedCollector(acled),
            "gdelt": FixedCollector(error=RuntimeError("offline")),
        },
        audit_store=audit,
    )

    assert run.result.status == "partial"
    gdelt = [item for item in audit.collectors if item.collector == "gdelt"]
    assert [item.collector_role for item in gdelt] == ["supporting", "supporting"]
    assert gdelt[-1].status == "failed"
    assert audit.finals[0].failed_sources == ("gdelt",)


def test_create_failure_aborts_before_collector():
    collector = CountingCollector(CollectionResult(source="cams"))

    with pytest.raises(PipelineRunAuditStoreError):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": collector},
            audit_store=RecordingAuditStore(fail_create=True),
        )

    assert collector.calls == 0


def test_global_scientific_failure_is_finalized_without_masking_original():
    audit = RecordingAuditStore()
    result = cams_result(cams_row())

    with pytest.raises(RuntimeError, match="scientific persistence failed"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": FixedCollector(result)},
            store=SignalStore(fail=True),
            audit_store=audit,
        )

    assert audit.finals[0].status == "failed"
    assert audit.finals[0].error_stage == "signal_persistence"
    assert audit.finals[0].error_message == "pipeline execution failed"
    assert "SECRET" not in audit.finals[0].model_dump_json()


def test_collector_exception_and_controlled_error_are_sanitized():
    audit = RecordingAuditStore()
    secret_error = (
        "Authorization: Bearer SECRET apikey=SECRET token=SECRET "
        "password=SECRET SUPABASE_SERVICE_ROLE_KEY=SECRET"
    )
    run_real_signals(
        settings=settings(),
        sources=("raised", "controlled"),
        now=NOW,
        collectors={
            "raised": FixedCollector(error=RuntimeError(secret_error)),
            "controlled": FixedCollector(
                CollectionResult(source="controlled", error=secret_error)
            ),
        },
        audit_store=audit,
    )

    terminal = [item for item in audit.collectors if item.status != "running"]
    assert terminal[0].error_type == "RuntimeError"
    assert terminal[0].error_message == "collector execution failed"
    assert terminal[1].error_type == "CollectorReportedError"
    assert "SECRET" not in terminal[1].error_message
    assert "SECRET" not in "".join(item.model_dump_json() for item in terminal)


def test_record_and_finalize_failures_are_explicit():
    collector = CountingCollector(CollectionResult(source="cams"))
    with pytest.raises(PipelineRunAuditStoreError, match="record failed"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": collector},
            audit_store=RecordingAuditStore(fail_record=True),
        )
    assert collector.calls == 0

    with pytest.raises(PipelineRunAuditStoreError, match="finalize failed"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": FixedCollector(CollectionResult(source="cams"))},
            audit_store=RecordingAuditStore(fail_finalize=True),
        )


def test_audit_none_and_audit_store_produce_identical_science():
    result = cams_result(cams_row())
    collectors = {"cams": FixedCollector(result)}

    legacy = run_real_signals(
        settings=settings(), sources=("cams",), now=NOW, collectors=collectors
    )
    audited = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors=collectors,
        audit_store=RecordingAuditStore(),
    )
    repeated = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors=collectors,
        audit_store=RecordingAuditStore(),
    )

    assert [item.model_dump(mode="json") for item in legacy.events] == [
        item.model_dump(mode="json") for item in audited.events
    ]
    assert [item.model_dump(mode="json") for item in legacy.signals] == [
        item.model_dump(mode="json") for item in audited.signals
    ]
    assert legacy.eligible_signal_ids == audited.eligible_signal_ids
    assert legacy.result.run_id != audited.result.run_id != repeated.result.run_id
    assert [item.id for item in audited.events] == [item.id for item in repeated.events]
    assert [item.id for item in audited.signals] == [item.id for item in repeated.signals]
