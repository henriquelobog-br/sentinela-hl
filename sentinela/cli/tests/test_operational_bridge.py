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
