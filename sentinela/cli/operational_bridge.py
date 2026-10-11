from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import socketserver
import stat
import subprocess
import sys
import threading
from typing import Final


PROTOCOL: Final = "json_line_v1"
SOCKET_PATH: Final = Path("/run/sentinela/operational.sock")
SOCKET_DIR: Final = SOCKET_PATH.parent
SOCKET_MODE: Final = 0o660
SOCKET_DIR_MODE: Final = 0o770
IPC_GID: Final = 2000

SECRET_SOURCE: Final = Path(
    "/run/secrets-source/sentinela_env"
)
RUNNER_ENV_FILE: Final = Path(
    "/run/secrets/sentinela_env"
)

LOCK_FILE: Final = Path(
    "/tmp/sentinela-hl-o4c-operational.lock"
)

JOB_TIMEOUT_SECONDS: Final = 900
BRIDGE_WATCHDOG_SECONDS: Final = 1020

TIER_SOURCES: Final = {
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
    "satellite_catalog": (
        "cmr",
    ),
    "contextual": (
        "gvp",
    ),
}

ALL_SOURCES: Final = (
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

_BUSY = threading.Lock()


class BridgeProtocolError(ValueError):
    pass


def _response(
    *,
    tier: str | None,
    status: str,
    exit_code: int,
) -> dict[str, object]:
    return {
        "protocol": PROTOCOL,
        "tier": tier,
        "status": status,
        "exit_code": exit_code,
    }


def _parse_request(line: bytes) -> str:
    if len(line) > 4096:
        raise BridgeProtocolError("request too large")

    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeProtocolError("invalid JSON request") from exc

    if not isinstance(payload, dict):
        raise BridgeProtocolError("request must be an object")

    if set(payload) != {"protocol", "tier"}:
        raise BridgeProtocolError(
            "request fields must be exactly protocol,tier"
        )

    if payload["protocol"] != PROTOCOL:
        raise BridgeProtocolError("unsupported protocol")

    tier = payload["tier"]

    if not isinstance(tier, str) or tier not in TIER_SOURCES:
        raise BridgeProtocolError("unknown tier")

    return tier


def _command_for_tier(tier: str) -> tuple[str, ...]:
    sources = TIER_SOURCES[tier]

    return (
        sys.executable,
        "-m",
        "sentinela.cli.run_operational",
        "--execute",
        "--env-file",
        str(RUNNER_ENV_FILE),
        "--lock-file",
        str(LOCK_FILE),
        "--sources",
        ",".join(sources),
        "--job-timeout-seconds",
        str(JOB_TIMEOUT_SECONDS),
    )


def _prepare_runtime() -> None:
    if os.geteuid() != 0:
        raise RuntimeError(
            "bridge initialization requires root only to prepare "
            "runtime permissions and runner secret"
        )

    SOCKET_DIR.mkdir(parents=True, exist_ok=True)
    os.chown(SOCKET_DIR, 0, IPC_GID)
    os.chmod(SOCKET_DIR, SOCKET_DIR_MODE)

    if not SECRET_SOURCE.is_file():
        raise RuntimeError("runner secret source is unavailable")

    RUNNER_ENV_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = RUNNER_ENV_FILE.with_suffix(".tmp")

    with SECRET_SOURCE.open("rb") as src, tmp.open("wb") as dst:
        shutil.copyfileobj(src, dst)

    os.chmod(tmp, 0o600)
    os.replace(tmp, RUNNER_ENV_FILE)
    os.chmod(RUNNER_ENV_FILE, 0o600)

    if SOCKET_PATH.exists() or SOCKET_PATH.is_symlink():
        mode = SOCKET_PATH.lstat().st_mode

        if not stat.S_ISSOCK(mode):
            raise RuntimeError(
                "refusing to remove non-socket IPC path"
            )

        SOCKET_PATH.unlink()


def _run_tier(tier: str) -> dict[str, object]:
    if not _BUSY.acquire(blocking=False):
        return _response(
            tier=tier,
            status="busy",
            exit_code=3,
        )

    try:
        try:
            completed = subprocess.run(
                _command_for_tier(tier),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=BRIDGE_WATCHDOG_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _response(
                tier=tier,
                status="watchdog_timeout_manual_reconciliation_required",
                exit_code=1,
            )

        code = int(completed.returncode)

        if code == 0:
            status = "succeeded"
        elif code == 1:
            status = "operational_hold"
        elif code == 2:
            status = "execute_not_authorized"
        elif code == 3:
            status = "lease_held"
        else:
            status = "unexpected_runner_exit"
            code = 1

        return _response(
            tier=tier,
            status=status,
            exit_code=code,
        )
    finally:
        _BUSY.release()


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        tier: str | None = None

        try:
            line = self.rfile.readline(4097)

            if not line or not line.endswith(b"\n"):
                raise BridgeProtocolError(
                    "request must be one newline-terminated JSON object"
                )

            tier = _parse_request(line.rstrip(b"\n"))
            response = _run_tier(tier)

        except BridgeProtocolError:
            response = _response(
                tier=tier,
                status="protocol_error",
                exit_code=1,
            )
        except Exception:
            response = _response(
                tier=tier,
                status="bridge_error",
                exit_code=1,
            )

        encoded = (
            json.dumps(
                response,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        self.wfile.write(encoded)


class _Server(
    socketserver.ThreadingMixIn,
    socketserver.UnixStreamServer,
):
    daemon_threads = True
    allow_reuse_address = False


def main() -> int:
    _prepare_runtime()

    with _Server(str(SOCKET_PATH), _Handler) as server:
        os.chown(SOCKET_PATH, 0, IPC_GID)
        os.chmod(SOCKET_PATH, SOCKET_MODE)

        print(
            "SENTINELA_OPERATIONAL_BRIDGE=READY",
            flush=True,
        )
        print(f"BRIDGE_PROTOCOL={PROTOCOL}", flush=True)
        print(
            f"BRIDGE_SOCKET={SOCKET_PATH}",
            flush=True,
        )
        print(
            f"BRIDGE_WATCHDOG_SECONDS="
            f"{BRIDGE_WATCHDOG_SECONDS}",
            flush=True,
        )

        server.serve_forever()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
