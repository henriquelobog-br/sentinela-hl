"""Explicit, non-scheduled backfill for Seismic Editorial v1."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from dotenv import dotenv_values

from sentinela.cli.run_operational import (
    DEFAULT_JOB_TIMEOUT_SECONDS,
    DEFAULT_LOCK_FILE,
    EXPECTED_SUPABASE_URL,
    LEASE_NAME,
    OperationalJobTimeout,
    OperationalLeaseHeld,
    OperationalRunnerError,
    _exclusive_local_lock,
    _job_timeout,
    _positive_job_timeout_seconds,
    _rpc_bool,
)
from sentinela.seismic_editorial.operational import (
    SeismicEditorialPersistenceResult,
    SupabaseSeismicEditorialStore,
    generate_and_persist,
)

BACKFILL_INITIATED_BY = "seismic_editorial_backfill_v1"
DEFAULT_ENV_FILE = Path(".env")
DEFAULT_PAGE_SIZE = 250


def _load_backfill_environment(path: Path) -> dict[str, str]:
    if not path.exists():
        raise OperationalRunnerError("backfill env file is missing")
    if path.is_symlink():
        raise OperationalRunnerError("backfill env file must not be a symlink")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise OperationalRunnerError("backfill env file mode must be 0600")

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

    for key in ("SENTINELA_SUPABASE_URL", "SENTINELA_SUPABASE_SERVICE_KEY"):
        os.environ[key] = values[key]
    return values


@contextmanager
def _backfill_remote_guard(
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
            "p_holder": BACKFILL_INITIATED_BY,
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
            payload={"p_lease_name": LEASE_NAME, "p_token": token},
            timeout=timeout,
        )
        if not released:
            raise OperationalRunnerError(
                "authoritative operational lease release was refused"
            )


def run_backfill(
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    lock_file: Path = DEFAULT_LOCK_FILE,
    page_size: int = DEFAULT_PAGE_SIZE,
    job_timeout_seconds: int = DEFAULT_JOB_TIMEOUT_SECONDS,
    timeout: float = 30.0,
    store_factory: Callable[..., Any] = SupabaseSeismicEditorialStore,
    guard: Callable[..., Any] = _backfill_remote_guard,
) -> SeismicEditorialPersistenceResult:
    if not 1 <= page_size <= 1000:
        raise ValueError("page_size must be between 1 and 1000")

    values = _load_backfill_environment(env_file)
    total = SeismicEditorialPersistenceResult(
        received=0,
        inserted=0,
        updated=0,
        unchanged=0,
    )
    generated_at = datetime.now(timezone.utc)

    with _exclusive_local_lock(lock_file):
        with guard(
            url=values["SENTINELA_SUPABASE_URL"],
            service_key=values["SENTINELA_SUPABASE_SERVICE_KEY"],
            timeout=timeout,
        ):
            store = store_factory(
                url=values["SENTINELA_SUPABASE_URL"],
                service_key=values["SENTINELA_SUPABASE_SERVICE_KEY"],
                timeout=timeout,
            )
            with _job_timeout(job_timeout_seconds):
                while True:
                    events = store.list_events(limit=page_size)
                    if not events:
                        break
                    batch = generate_and_persist(
                        events,
                        store=store,
                        generated_at=generated_at,
                    )
                    total = total.plus(batch)
                    if len(events) < page_size:
                        break

    return total


def _page_size(value: str) -> int:
    try:
        size = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("page size must be an integer") from exc
    if not 1 <= size <= 1000:
        raise argparse.ArgumentTypeError("page size must be between 1 and 1000")
    return size


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill deterministic Seismic Editorial v1 content."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Required explicit execution interlock.",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--page-size", type=_page_size, default=DEFAULT_PAGE_SIZE)
    parser.add_argument(
        "--job-timeout-seconds",
        type=_positive_job_timeout_seconds,
        default=DEFAULT_JOB_TIMEOUT_SECONDS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.execute:
        print("SEISMIC_EDITORIAL_BACKFILL_GATE=HOLD")
        print("SEISMIC_EDITORIAL_BACKFILL_EXECUTED=NO")
        return 2

    try:
        result = run_backfill(
            env_file=args.env_file,
            lock_file=args.lock_file,
            page_size=args.page_size,
            job_timeout_seconds=args.job_timeout_seconds,
        )
    except OperationalLeaseHeld:
        print("SEISMIC_EDITORIAL_BACKFILL_LEASE=HELD")
        print("SEISMIC_EDITORIAL_BACKFILL_EXECUTED=NO")
        return 3
    except (OperationalRunnerError, OperationalJobTimeout, ValueError, RuntimeError):
        print("SEISMIC_EDITORIAL_BACKFILL=HOLD")
        print("SEISMIC_EDITORIAL_BACKFILL_EXECUTED=UNKNOWN_OR_NO")
        print("SEISMIC_EDITORIAL_BACKFILL_AUTOMATIC_RETRY=NO")
        return 1

    print("SEISMIC_EDITORIAL_BACKFILL=PASS")
    print(f"received={result.received}")
    print(f"inserted={result.inserted}")
    print(f"updated={result.updated}")
    print(f"unchanged={result.unchanged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
