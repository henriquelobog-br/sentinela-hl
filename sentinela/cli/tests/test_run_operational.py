from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from sentinela.cli import run_operational
from sentinela.real_signals import RealSignalRun, RunResult


def _complete_run() -> RealSignalRun:
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)

    return RealSignalRun(
        collections=(),
        events=(),
        signals=(),
        result=RunResult(
            run_id="8162c41d-cc89-4b4d-bc5e-fac79cb73aee",
            started_at=now,
            completed_at=now,
            requested_sources=run_operational.ACTIVATION_SOURCES,
            consulted_sources=run_operational.ACTIVATION_SOURCES,
            supporting_sources=(),
            successful_sources=run_operational.ACTIVATION_SOURCES,
            failed_sources=(),
            records_received=0,
            events_produced=0,
            signals_produced=0,
            signals_eligible=0,
            signals_persisted=0,
        ),
    )


def test_activation_source_set_is_exact_and_deferred_is_excluded():
    assert run_operational.ACTIVATION_SOURCES == (
        "cmr",
        "usgs",
        "openmeteo-weather",
        "openmeteo-marine",
        "nws-alerts",
        "donki",
        "noaa-coops",
        "noaa-ndbc",
        "usgs-volcano",
        "gvp",
        "gdelt",
        "firms",
    )

    assert set(run_operational.ACTIVATION_SOURCES).isdisjoint(
        run_operational.DEFERRED_SOURCES
    )

    assert set(run_operational.DEFERRED_SOURCES) == {
        "acled",
        "cams",
        "merra2",
    }


def test_run_once_uses_canonical_path_and_exact_sources(
    monkeypatch,
    tmp_path,
):
    calls = {}
    audit_store = object()
    canonical_store = object()
    settings = SimpleNamespace(timeout_seconds=30.0)

    monkeypatch.setattr(
        run_operational,
        "_load_environment",
        lambda path: {
            "SENTINELA_SUPABASE_URL": run_operational.EXPECTED_SUPABASE_URL,
            "SENTINELA_SUPABASE_SERVICE_KEY": "sb_secret_test",
            "SENTINELA_FIRMS_MAP_KEY": "firms-test",
        },
    )

    monkeypatch.setattr(
        run_operational.RealSignalSettings,
        "from_env",
        lambda: settings,
    )

    @contextmanager
    def guard(**kwargs):
        calls["guard"] = kwargs
        yield

    def audit_factory(**kwargs):
        calls["audit_factory"] = kwargs
        return audit_store

    def canonical_factory(**kwargs):
        calls["canonical_factory"] = kwargs
        return canonical_store

    def fake_run(**kwargs):
        calls["run"] = kwargs
        return _complete_run()

    run = run_operational.run_once(
        env_file=tmp_path / ".env",
        lock_file=tmp_path / "runner.lock",
        guard=guard,
        run_fn=fake_run,
        audit_store_factory=audit_factory,
        canonical_store_factory=canonical_factory,
    )

    assert run.result.status == "complete"

    assert calls["guard"]["url"] == run_operational.EXPECTED_SUPABASE_URL

    assert calls["run"]["sources"] == run_operational.ACTIVATION_SOURCES

    assert calls["run"]["event_store"] is None
    assert calls["run"]["store"] is None
    assert calls["run"]["audit_store"] is audit_store
    assert calls["run"]["canonical_store"] is canonical_store
    assert calls["run"]["audit_mode"] == "persist"

    assert calls["run"]["audit_initiated_by"] == run_operational.INITIATED_BY


def test_main_without_execute_is_non_mutating(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        run_operational,
        "run_once",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert run_operational.main([]) == 2

    output = capsys.readouterr().out

    assert "O4C_OPERATIONAL_EXECUTION_GATE=HOLD" in output
    assert "O4C_OPERATIONAL_RUN_EXECUTED=NO" in output
