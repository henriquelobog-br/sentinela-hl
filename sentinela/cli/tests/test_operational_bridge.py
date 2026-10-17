from __future__ import annotations

import json

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
