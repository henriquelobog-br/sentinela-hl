from __future__ import annotations

import pytest

from sentinela.canonical_provenance.models import (
    CanonicalEventPersistenceResult,
    CanonicalPersistenceItemResult,
    CanonicalSignalPersistenceResult,
    PersistenceDisposition,
)
from sentinela.persistence import (
    CanonicalFailureKind,
    CanonicalProvenanceStoreError,
)
from sentinela.real_signals.collectors import CollectionResult
from sentinela.real_signals.orchestrator import run_real_signals
from sentinela.real_signals.tests.test_real_signals import (
    NOW,
    FixedCollector,
    cams_result,
    cams_row,
    settings,
)
from sentinela.real_signals.tests.test_run_audit import RecordingAuditStore


class CanonicalStore:
    def __init__(
        self,
        fail_events=False,
        fail_signals=False,
        failure_kind=None,
        signal_result=None,
        mixed_signal_results=False,
    ):
        self.event_batches = []
        self.signal_batches = []
        self.manifests = []
        self.fail_events = fail_events
        self.fail_signals = fail_signals
        self.failure_kind = failure_kind
        self.signal_result = signal_result
        self.mixed_signal_results = mixed_signal_results

    def persist_events(self, run_id, acceptance):
        self.event_batches.append((run_id, acceptance))
        if self.fail_events:
            raise CanonicalProvenanceStoreError(
                "event failure",
                failure_kind=(
                    self.failure_kind or CanonicalFailureKind.COMMIT_AMBIGUOUS
                ),
            )
        return CanonicalEventPersistenceResult(
            received=len(acceptance.accepted) + len(acceptance.rejected),
            accepted=len(acceptance.accepted),
            rejected=len(acceptance.rejected),
            items=(),
        )

    def persist_signals(self, run_id, records):
        self.signal_batches.append((run_id, records))
        if self.fail_signals:
            raise CanonicalProvenanceStoreError(
                "signal failure",
                failure_kind=(
                    self.failure_kind or CanonicalFailureKind.DEFINITIVE_REJECTION
                ),
            )
        if self.signal_result is not None:
            return self.signal_result
        if self.mixed_signal_results:
            items = []
            for index, record in enumerate(records):
                if index == 1:
                    items.append(
                        CanonicalPersistenceItemResult(
                            artifact_id=record.signal.id,
                            disposition=PersistenceDisposition.REJECTED,
                        )
                    )
                elif index == 2:
                    items.append(
                        CanonicalPersistenceItemResult(
                            artifact_id=record.signal.id,
                            disposition=PersistenceDisposition.OBSERVED_EXISTING,
                            content_hash="c" * 64,
                        )
                    )
                else:
                    items.append(
                        CanonicalPersistenceItemResult(
                            artifact_id=record.signal.id,
                            disposition=PersistenceDisposition.INSERTED,
                            content_hash="a" * 64,
                        )
                    )
            persisted = sum(
                1
                for item in items
                if item.disposition != PersistenceDisposition.REJECTED
            )
            return CanonicalSignalPersistenceResult(
                received=len(records),
                persisted=persisted,
                items=tuple(items),
            )
        return CanonicalSignalPersistenceResult(
            received=len(records), persisted=len(records), items=()
        )

    def finalize_manifest(self, manifest):
        self.manifests.append(manifest)


def test_absent_canonical_store_preserves_legacy_behavior():
    result = cams_result(cams_row())
    run = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors={"cams": FixedCollector(result)},
    )
    assert run.canonical_event_acceptance is None
    assert run.canonical_event_persistence is None
    assert run.canonical_signal_persistence is None


def test_canonical_store_requires_audit_and_cannot_mix_legacy_stores():
    result = cams_result(cams_row())
    with pytest.raises(ValueError, match="requires PipelineRunAuditStore"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": FixedCollector(result)},
            canonical_store=CanonicalStore(),
            audit_mode="persist",
        )
    with pytest.raises(ValueError, match="cannot be combined"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": FixedCollector(result)},
            canonical_store=CanonicalStore(),
            audit_store=RecordingAuditStore(),
            store=object(),
            audit_mode="persist",
        )


def test_canonical_flow_persists_events_before_linked_signals_and_finalizes():
    result = cams_result(cams_row())
    canonical = CanonicalStore()
    run = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors={"cams": FixedCollector(result)},
        canonical_store=canonical,
        audit_store=RecordingAuditStore(),
        audit_mode="persist",
    )
    assert len(canonical.event_batches) == 1
    assert len(canonical.signal_batches) == 1
    assert run.canonical_event_acceptance.accepted
    assert run.canonical_signal_persistence.persisted == len(run.eligible_signal_ids)
    assert canonical.manifests[-1].stage == "finalized"


def test_event_failure_prevents_linked_signal_persistence():
    result = cams_result(cams_row())
    canonical = CanonicalStore(fail_events=True)
    with pytest.raises(CanonicalProvenanceStoreError, match="event failure"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": FixedCollector(result)},
            canonical_store=canonical,
            audit_store=RecordingAuditStore(),
            audit_mode="persist",
        )
    assert canonical.signal_batches == []
    assert canonical.manifests[-1].stage == "failed"
    assert canonical.manifests[-1].commit_ambiguous is True


def test_definitive_event_rejection_is_not_recorded_as_commit_ambiguous():
    result = cams_result(cams_row())
    canonical = CanonicalStore(
        fail_events=True,
        failure_kind=CanonicalFailureKind.DEFINITIVE_REJECTION,
    )
    with pytest.raises(CanonicalProvenanceStoreError, match="event failure"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": FixedCollector(result)},
            canonical_store=canonical,
            audit_store=RecordingAuditStore(),
            audit_mode="persist",
        )
    assert canonical.manifests[-1].stage == "failed"
    assert canonical.manifests[-1].commit_ambiguous is False


def test_rejected_event_never_reaches_linked_signal_persistence():
    invalid = cams_result(cams_row()).events[0].model_copy(update={"source": None})
    canonical = CanonicalStore()
    run = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors={
            "cams": FixedCollector(CollectionResult(source="cams", events=(invalid,)))
        },
        canonical_store=canonical,
        audit_store=RecordingAuditStore(),
        audit_mode="persist",
    )
    assert run.events == ()
    assert run.canonical_event_acceptance.accepted == ()
    assert len(run.canonical_event_acceptance.rejected) == 1
    assert canonical.signal_batches == [(run.result.run_id, ())]


def test_multi_event_group_creates_one_representative_and_contributors():
    result = cams_result(
        cams_row(valid_time="2026-08-04T06:00:00Z"),
        cams_row(valid_time="2026-08-04T12:00:00Z"),
    )
    canonical = CanonicalStore()
    run = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors={"cams": FixedCollector(result)},
        canonical_store=canonical,
        audit_store=RecordingAuditStore(),
        audit_mode="persist",
    )
    records = canonical.signal_batches[0][1]
    assert len(run.events) == 2
    assert len(records) == 1
    assert len(records[0].contributor_event_ids) == 1
    assert records[0].representative_event_id not in records[0].contributor_event_ids


def test_mixed_legacy_signal_rejection_does_not_abort_canonical_stage():
    result = cams_result(
        cams_row(region="central_south_atlantic", valid_time="2026-08-04T06:00:00Z"),
        cams_row(region="southern_africa", valid_time="2026-08-04T12:00:00Z"),
        cams_row(region="brazil_coast", valid_time="2026-08-04T18:00:00Z"),
    )
    canonical = CanonicalStore(mixed_signal_results=True)
    run = run_real_signals(
        settings=settings(),
        sources=("cams",),
        now=NOW,
        collectors={"cams": FixedCollector(result)},
        canonical_store=canonical,
        audit_store=RecordingAuditStore(),
        audit_mode="persist",
    )
    items = run.canonical_signal_persistence.items
    assert len(items) >= 3
    assert [item.disposition for item in items[:3]] == [
        PersistenceDisposition.INSERTED,
        PersistenceDisposition.REJECTED,
        PersistenceDisposition.OBSERVED_EXISTING,
    ]
    assert run.canonical_signal_persistence.persisted == len(items) - 1
    assert run.result.signals_persisted == run.canonical_signal_persistence.persisted
    assert run.result.signals_persisted <= run.result.signals_eligible
    assert run.result.status == "complete"
    assert canonical.manifests[-1].stage == "finalized"
    assert canonical.manifests[-1].persisted_signals == run.result.signals_persisted
    assert canonical.manifests[-1].error_type is None


def test_signal_rpc_failure_still_finalizes_failed_manifest():
    result = cams_result(cams_row())
    canonical = CanonicalStore(fail_signals=True)
    with pytest.raises(CanonicalProvenanceStoreError, match="signal failure"):
        run_real_signals(
            settings=settings(),
            sources=("cams",),
            now=NOW,
            collectors={"cams": FixedCollector(result)},
            canonical_store=canonical,
            audit_store=RecordingAuditStore(),
            audit_mode="persist",
        )
    assert canonical.manifests[-1].stage == "failed"
    assert canonical.manifests[-1].commit_ambiguous is False
