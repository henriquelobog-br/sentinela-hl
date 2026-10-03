from __future__ import annotations

from datetime import datetime, timezone

from sentinela.cli import generate_real_signals
from sentinela.real_signals import RealSignalRun, RunResult


def _run(status: str) -> RealSignalRun:
    failed = () if status == "complete" else ("cmr",)
    successful = () if status == "failed" else ("cams",)
    return RealSignalRun(
        collections=(),
        events=(),
        signals=(),
        result=RunResult(
            run_id="run-test",
            started_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
            completed_at=datetime(2026, 8, 13, 0, 1, tzinfo=timezone.utc),
            requested_sources=("cams", "cmr"),
            consulted_sources=("cams", "cmr", "gdelt"),
            supporting_sources=("gdelt",),
            successful_sources=successful,
            failed_sources=failed if status != "failed" else ("cams", "cmr"),
            records_received=0,
            events_produced=0,
            signals_produced=0,
            signals_eligible=0,
            signals_persisted=0,
        ),
    )


def test_cli_imprime_status_e_fontes_sem_persistir(monkeypatch, capsys):
    monkeypatch.setattr(
        generate_real_signals,
        "SupabasePipelineRunAuditStore",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(generate_real_signals, "run_real_signals", lambda **kwargs: _run("partial"))

    exit_code = generate_real_signals.main(["--dry-run", "--source", "cams"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "run_status: partial" in output
    assert "sources_requested: cams, cmr" in output
    assert "sources_consulted: cams, cmr, gdelt" in output
    assert "supporting_sources: gdelt" in output
    assert "sources_successful: cams" in output
    assert "sources_failed: cmr" in output


def test_cli_falha_total_retorna_erro(monkeypatch):
    monkeypatch.setattr(
        generate_real_signals,
        "SupabasePipelineRunAuditStore",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(generate_real_signals, "run_real_signals", lambda **kwargs: _run("failed"))
    assert generate_real_signals.main(["--dry-run", "--source", "cams"]) == 1


def test_dry_run_uses_only_operational_audit_store(monkeypatch):
    calls = {}
    audit = object()

    monkeypatch.setattr(
        generate_real_signals,
        "SupabasePipelineRunAuditStore",
        lambda **kwargs: audit,
    )
    monkeypatch.setattr(
        generate_real_signals,
        "SupabaseResearcherSignalStore",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("scientific store")),
    )

    def fake_run(**kwargs):
        calls.update(kwargs)
        return _run("complete")

    monkeypatch.setattr(generate_real_signals, "run_real_signals", fake_run)

    assert generate_real_signals.main(["--dry-run", "--source", "cams"]) == 0
    assert calls["store"] is None
    assert calls["audit_store"] is audit
    assert calls["audit_mode"] == "dry_run"
    assert "event_store" not in calls
    assert "canonical_store" not in calls


def test_persist_uses_signal_store_without_event_or_editorial_stores(monkeypatch):
    calls = {}
    audit = object()
    signals = object()

    monkeypatch.setattr(
        generate_real_signals,
        "SupabasePipelineRunAuditStore",
        lambda **kwargs: audit,
    )
    monkeypatch.setattr(
        generate_real_signals,
        "SupabaseResearcherSignalStore",
        lambda **kwargs: signals,
    )

    def fake_run(**kwargs):
        calls.update(kwargs)
        return _run("complete")

    monkeypatch.setattr(generate_real_signals, "run_real_signals", fake_run)

    assert generate_real_signals.main(["--persist", "--source", "cams"]) == 0
    assert calls["store"] is signals
    assert calls["audit_store"] is audit
    assert calls["audit_mode"] == "persist"
    assert "event_store" not in calls
    assert "canonical_store" not in calls
    assert not any("editorial" in key for key in calls)
