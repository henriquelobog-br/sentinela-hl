from __future__ import annotations

import json
import subprocess
import sys

import pytest

from sentinela.cli import operational_bridge as bridge


def test_tier_partition_is_exact():
    flattened = tuple(
        source
        for tier in bridge.TIER_SOURCES.values()
        for source in tier
    )

    assert len(flattened) == 12
    assert len(set(flattened)) == 12
    assert set(flattened) == set(bridge.ALL_SOURCES)


def test_frozen_tier_mapping():
    assert bridge.TIER_SOURCES == {
        "urgent": (
            "usgs",
            "nws-alerts",
            "usgs-volcano",
            "gdelt",
            "donki",
        ),
        "coastal_forecast": (
            "openmeteo-weather",
            "openmeteo-marine",
            "noaa-coops",
            "noaa-ndbc",
            "firms",
        ),
        "satellite_catalog": ("cmr",),
        "contextual": ("gvp",),
    }


def test_protocol_accepts_tier_only_payload():
    payload = json.dumps(
        {
            "protocol": bridge.PROTOCOL,
            "tier": "urgent",
        }
    ).encode()

    assert bridge._parse_request(payload) == "urgent"


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b'{"protocol":"json_line_v1","tier":"bad"}',
        b'{"protocol":"bad","tier":"urgent"}',
        b'{"protocol":"json_line_v1","tier":"urgent","x":1}',
    ],
)
def test_protocol_rejects_invalid_payload(payload):
    with pytest.raises(bridge.BridgeProtocolError):
        bridge._parse_request(payload)


def test_command_contract():
    command = bridge._command_for_tier("urgent")

    assert "--execute" in command
    assert "--env-file" in command
    assert str(bridge.RUNNER_ENV_FILE) in command
    assert "--lock-file" in command
    assert str(bridge.LOCK_FILE) in command
    assert "--sources" in command
    assert (
        "usgs,nws-alerts,usgs-volcano,gdelt,donki"
        in command
    )
    assert "--job-timeout-seconds" in command
    assert str(bridge.JOB_TIMEOUT_SECONDS) in command
    assert bridge.JOB_TIMEOUT_SECONDS == 900
    assert bridge.BRIDGE_WATCHDOG_SECONDS == 1020


def test_command_removes_only_disabled_source(tmp_path, monkeypatch, capsys):
    disabled = tmp_path / "disabled-sources"
    disabled.write_text("usgs\nusgs\n\n", encoding="utf-8")
    monkeypatch.setattr(bridge, "DISABLED_SOURCES_FILE", disabled)

    command = bridge._command_for_tier("urgent")

    sources = command[command.index("--sources") + 1]
    assert sources == "nws-alerts,usgs-volcano,gdelt,donki"
    assert "gdelt" in sources.split(",")
    assert capsys.readouterr().out == (
        "SENTINELA_OPERATIONAL_MAINTENANCE tier=urgent "
        "skipped_sources=usgs "
        "effective_sources=nws-alerts,usgs-volcano,gdelt,donki\n"
    )


def test_absent_disabled_sources_file_restores_frozen_tier(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        bridge, "DISABLED_SOURCES_FILE", tmp_path / "missing"
    )

    command = bridge._command_for_tier("urgent")

    assert command[command.index("--sources") + 1] == (
        "usgs,nws-alerts,usgs-volcano,gdelt,donki"
    )
    assert capsys.readouterr().out == ""


def test_unknown_disabled_source_fails_closed(tmp_path, monkeypatch):
    disabled = tmp_path / "disabled-sources"
    disabled.write_text("usgs\nunknown-source\n", encoding="utf-8")
    monkeypatch.setattr(bridge, "DISABLED_SOURCES_FILE", disabled)

    with pytest.raises(RuntimeError, match="unknown disabled operational source"):
        bridge._command_for_tier("urgent")


def test_fully_disabled_tier_fails_closed(tmp_path, monkeypatch):
    disabled = tmp_path / "disabled-sources"
    disabled.write_text("gvp\n", encoding="utf-8")
    monkeypatch.setattr(bridge, "DISABLED_SOURCES_FILE", disabled)

    with pytest.raises(RuntimeError, match="all sources"):
        bridge._command_for_tier("contextual")


def test_response_contains_no_runner_output():
    response = bridge._response(
        tier="urgent",
        status="succeeded",
        exit_code=0,
    )

    assert response == {
        "protocol": "json_line_v1",
        "tier": "urgent",
        "status": "succeeded",
        "exit_code": 0,
    }


def test_bridge_forwards_only_stale_revision_lines(monkeypatch, capsys):
    completed = subprocess.CompletedProcess(
        args=("python", "-m", "sentinela.cli.run_operational"),
        returncode=0,
        stdout=(
            "run_id=623634f0-941a-47ec-bd7c-cddc26ce9e43\n"
            "SENTINELA_STALE_REVISION_SKIPPED source_event_id=us6000stale "
            "incoming_updated_at=2026-08-13T12:00:00Z "
            "stored_updated_at=2026-08-13T18:00:00Z\n"
            "run_status=complete\n"
        ),
        stderr="Traceback (most recent call last):\nValueError: noise\n",
    )
    monkeypatch.setattr(
        bridge, "_command_for_tier", lambda tier: ("python", "-c", "pass")
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: completed)

    response = bridge._run_tier("urgent")
    out = capsys.readouterr().out
    assert out.count("SENTINELA_STALE_REVISION_SKIPPED") == 1
    assert "source_event_id=us6000stale" in out
    assert "run_id=" not in out
    assert "Traceback" not in out
    assert "ValueError" not in out
    assert response["exit_code"] == 0
    assert response["status"] == "succeeded"


def test_timeout_forwards_stale_line_from_real_child(monkeypatch, capsys):
    monkeypatch.setattr(bridge, "BRIDGE_WATCHDOG_SECONDS", 0.4)
    script = (
        "import sys, time\n"
        "print("
        "'SENTINELA_STALE_REVISION_SKIPPED source_event_id=us1 "
        "incoming_updated_at=2026-08-13T12:00:00Z "
        "stored_updated_at=2026-08-13T18:00:00Z', flush=True)\n"
        "print('noise-out', flush=True)\n"
        "print('noise-err', file=sys.stderr, flush=True)\n"
        "time.sleep(5)\n"
    )
    monkeypatch.setattr(
        bridge,
        "_command_for_tier",
        lambda tier: (sys.executable, "-c", script),
    )
    response = bridge._run_tier("urgent")
    out = capsys.readouterr().out
    assert response["status"] == "watchdog_timeout_manual_reconciliation_required"
    assert response["exit_code"] == 1
    assert out.count("SENTINELA_STALE_REVISION_SKIPPED") == 1
    assert "source_event_id=us1" in out
    assert "noise-out" not in out
    assert "noise-err" not in out


def test_timeout_bytes_capture_does_not_become_bridge_error():
    exc = subprocess.TimeoutExpired(
        cmd=("python", "-c", "pass"),
        timeout=0.1,
        output=(
            b"SENTINELA_STALE_REVISION_SKIPPED source_event_id=us1 "
            b"incoming_updated_at=2026-08-13T12:00:00Z "
            b"stored_updated_at=2026-08-13T18:00:00Z\nnoise-out\n"
        ),
        stderr=b"noise-err\n",
    )
    lines = bridge._stale_revision_log_lines(exc.stdout)
    assert len(lines) == 1
    assert lines[0].startswith("SENTINELA_STALE_REVISION_SKIPPED ")
    assert bridge._stale_revision_log_lines(exc.stderr) == ()
