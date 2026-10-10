"""Permanent degraded operational runner for canonical real-signal ingestion.

O4-C1 deliberately remains fail-closed until a server-side concurrency
lease/guard is installed in a later gate.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

import httpx
from dotenv import dotenv_values

from sentinela.persistence import (
    SupabaseCanonicalProvenanceStore,
    SupabasePipelineRunAuditStore,
)
from sentinela.real_signals import RealSignalRun, RealSignalSettings, run_real_signals


ACTIVATION_SOURCES = (
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

DEFERRED_SOURCES = ("acled", "cams", "merra2")

EXPECTED_SUPABASE_URL = "https://bugnxcgvnnxxfwnzskbm.supabase.co"
INITIATED_BY = "o4c_continuous_degraded_v1"
LEASE_NAME = "real_signals_degraded_v1"

DEFAULT_ENV_FILE = Path(".env")
DEFAULT_LOCK_FILE = Path("/tmp/sentinela-hl-o4c-operational.lock")


class OperationalRunnerError(RuntimeError):
    """Base error for fail-closed operational runner gates."""


class OperationalLeaseHeld(OperationalRunnerError):
    """Raised when the authoritative remote lease cannot be acquired."""


def _load_environment(path: Path) -> dict[str, str]:
    if not path.exists():
        raise OperationalRunnerError("operational env file is missing")
    if path.is_symlink():
        raise OperationalRunnerError("operational env file must not be a symlink")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise OperationalRunnerError("operational env file mode must be 0600")

    parsed = dotenv_values(path, interpolate=False)
    values = {
        str(key): str(value)
        for key, value in parsed.items()
        if value is not None
    }

    if values.get("SENTINELA_SUPABASE_URL") != EXPECTED_SUPABASE_URL:
        raise OperationalRunnerError("unexpected Supabase production target")

    service_key = values.get("SENTINELA_SUPABASE_SERVICE_KEY", "")
    if not service_key or not service_key.startswith(("sb_secret_", "eyJ")):
        raise OperationalRunnerError("Supabase service credential gate failed")

    if not values.get("SENTINELA_FIRMS_MAP_KEY", ""):
        raise OperationalRunnerError("FIRMS credential gate failed")

    # Preserve the exact O4-B1 behavior: .env is authoritative for
    # the child process and overwrites existing process values.
    for key, value in values.items():
        os.environ[key] = value

    return values


def _headers(service_key: str) -> dict[str, str]:
    headers = {
        "apikey": service_key,
        "content-type": "application/json",
    }
    if not service_key.startswith("sb_secret_"):
        headers["authorization"] = f"Bearer {service_key}"
    return headers


def _rpc_bool(
    *,
    url: str,
    service_key: str,
    function: str,
    payload: dict[str, str],
    timeout: float,
) -> bool:
    response = httpx.post(
        f"{url.rstrip('/')}/rest/v1/rpc/{function}",
        headers=_headers(service_key),
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()

    value = response.json()
    if not isinstance(value, bool):
        raise OperationalRunnerError(
            "operational lease RPC returned a non-boolean response"
        )
    return value


@contextmanager
def _remote_concurrency_guard(
    *,
    url: str,
    service_key: str,
    timeout: float,
) -> Iterator[None]:
    token = str(uuid4())

    acquired = _rpc_bool(
        url=url,
        service_key=service_key,
        function="acquire_operational_run_lease",
        payload={
            "p_lease_name": LEASE_NAME,
            "p_token": token,
            "p_holder": INITIATED_BY,
        },
        timeout=timeout,
    )

    if not acquired:
        raise OperationalLeaseHeld(
            "authoritative operational lease is already held "
            "or a pipeline run is marked running"
        )

    try:
        yield
    finally:
        released = _rpc_bool(
            url=url,
            service_key=service_key,
            function="release_operational_run_lease",
            payload={
                "p_lease_name": LEASE_NAME,
                "p_token": token,
            },
            timeout=timeout,
        )
        if not released:
            raise OperationalRunnerError(
                "authoritative operational lease release was refused"
            )


@contextmanager
def _exclusive_local_lock(path: Path) -> Iterator[None]:
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OperationalRunnerError(
                "another operational runner holds the local lock"
            ) from exc
        yield
    finally:
        os.close(fd)


def run_once(
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    lock_file: Path = DEFAULT_LOCK_FILE,
    guard: Callable[..., Any] | None = None,
    run_fn: Callable[..., RealSignalRun] = run_real_signals,
    audit_store_factory: Callable[..., Any] = (
        SupabasePipelineRunAuditStore
    ),
    canonical_store_factory: Callable[..., Any] = (
        SupabaseCanonicalProvenanceStore
    ),
) -> RealSignalRun:
    values = _load_environment(env_file)
    settings = RealSignalSettings.from_env()
    guard_fn = guard or _remote_concurrency_guard

    with _exclusive_local_lock(lock_file):
        with guard_fn(
            url=values["SENTINELA_SUPABASE_URL"],
            service_key=values["SENTINELA_SUPABASE_SERVICE_KEY"],
            timeout=settings.timeout_seconds,
        ):
            audit_store = audit_store_factory(
                url=values["SENTINELA_SUPABASE_URL"],
                service_key=values["SENTINELA_SUPABASE_SERVICE_KEY"],
                timeout=settings.timeout_seconds,
            )

            canonical_store = canonical_store_factory(
                url=values["SENTINELA_SUPABASE_URL"],
                service_key=values["SENTINELA_SUPABASE_SERVICE_KEY"],
                timeout=settings.timeout_seconds,
            )

            return run_fn(
                settings=settings,
                sources=ACTIVATION_SOURCES,
                event_store=None,
                store=None,
                audit_store=audit_store,
                canonical_store=canonical_store,
                audit_mode="persist",
                audit_initiated_by=INITIATED_BY,
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the permanent degraded canonical ingestion path."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required explicit execution interlock.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=DEFAULT_LOCK_FILE,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if not args.execute:
        print("O4C_OPERATIONAL_EXECUTION_GATE=HOLD")
        print("O4C_OPERATIONAL_RUN_EXECUTED=NO")
        return 2

    try:
        run = run_once(
            env_file=args.env_file,
            lock_file=args.lock_file,
        )
    except OperationalLeaseHeld:
        print("O4C_REMOTE_CONCURRENCY_GUARD=HELD")
        print("O4C_OPERATIONAL_RUN_EXECUTED=NO")
        return 3
    except (OperationalRunnerError, httpx.HTTPError, ValueError, RuntimeError):
        print("O4C_OPERATIONAL_RUN=HOLD")
        print("O4C_OPERATIONAL_RUN_EXECUTED=UNKNOWN_OR_NO")
        print("O4C_AUTOMATIC_RETRY=NO")
        return 1

    print(f"run_id={run.result.run_id}")
    print(f"run_status={run.result.status}")
    print(f"sources_requested={len(run.result.requested_sources)}")
    print(f"sources_successful={len(run.result.successful_sources)}")
    print(f"sources_failed={len(run.result.failed_sources)}")

    return 1 if run.result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
