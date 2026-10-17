from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import hashlib
import json
import os
import subprocess
import threading
import time

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from sentinela.canonical_provenance.models import (
    CanonicalPersistenceItemResult,
    PersistenceDisposition,
)
from sentinela.persistence.canonical_store import SupabaseCanonicalProvenanceStore

LOCAL_CONTAINER = "supabase_db_sentinela-hl"
LOCAL_DB = "postgres"
LOCAL_USER = "postgres"
LOCAL_DB_PHASE_ENV = "SENTINELA_LOCAL_DB_PHASE"
REQUIRED_PHASE = "039"
FROZEN_038_SHA256 = "9e873499e4f6f5367405c39c76dd6b9233ca32157e58838c5a20a858c03ae160"
FROZEN_039_SHA256 = "34c4a4a7a7c7d9aaf1b20d968e3dcc677158c92c6cf4af3808ac98879e7bfcb7"

pytestmark = pytest.mark.local_db


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "supabase").is_dir():
            return candidate
    raise AssertionError("repository root not found from test module")


def _psql(sql: str, *, db: str = LOCAL_DB) -> str:
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            LOCAL_CONTAINER,
            "psql",
            "-U",
            LOCAL_USER,
            "-d",
            db,
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
        ],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _require_local() -> None:
    inspect = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            "{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            LOCAL_CONTAINER,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if inspect.returncode != 0 or LOCAL_CONTAINER not in inspect.stdout:
        raise AssertionError("local supabase postgres container is unavailable")
    db = _psql("select current_database();")
    assert db == "postgres"
    versions = _psql(
        "select string_agg(version, ',' order by version) from supabase_migrations.schema_migrations;"
    )
    if "039" not in versions.split(","):
        raise AssertionError(f"local DB is not at 039: {versions}")
    if "038" not in versions.split(","):
        raise AssertionError(f"local DB missing 038: {versions}")


def _event_payload(event_id: UUID, source_event_id: str, updated_at: str, magnitude: float) -> str:
    event = {
        "id": str(event_id),
        "title": "USGS local test",
        "summary": "local",
        "epistemic_status": "confirmed_fact",
        "event_status": "observed_fact",
        "category": "earthquake_detected",
        "source": "USGS",
        "scientific_area": "seismology",
        "entities": [],
        "keywords": ["earthquake"],
        "evidence": [
            {
                "text": "earthquake",
                "source": "USGS",
                "source_event_id": source_event_id,
                "updated_at": updated_at,
                "magnitude": magnitude,
                "magnitude_type": "mww",
                "place": "test",
                "latitude": -20.0,
                "longitude": -40.0,
                "depth_km": 10.0,
            }
        ],
        "occurred_at": updated_at,
        "supporting_sources": [],
    }
    item = {
        "event": event,
        "collector": "usgs",
        "collector_role": "requested",
        "content_hash": "a" * 64,
    }
    return json.dumps(item).replace("'", "''")


def _new_run() -> str:
    run_id = str(uuid4())
    _psql(
        f"""
        insert into raw.pipeline_runs (
            id, initiated_by, mode, status, started_at,
            requested_sources, requested_source_count
        ) values (
            '{run_id}', 'local_039', 'persist', 'running', now(),
            array['usgs'], 1
        );
        select public.begin_canonical_run_manifest('{run_id}'::uuid);
        """
    )
    return run_id


def _persist(run_id: str, payload_json: str) -> list[dict]:
    sql = f"""
    select coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb)
    from public.persist_canonical_event_batch(
        '{run_id}'::uuid,
        jsonb_build_array('{payload_json}'::jsonb),
        '[]'::jsonb
    ) as r;
    """
    raw = _psql(sql)
    return json.loads(raw)


class _BaseRunnerItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    artifact_id: str
    canonical_event_id: UUID | None = None
    disposition: str
    content_hash: str | None = None
    revision_id: UUID | None = None


def _parse_base_runner(row: dict) -> _BaseRunnerItem:
    return _BaseRunnerItem(
        artifact_id=str(row["artifact_id"]),
        canonical_event_id=(
            UUID(str(row["canonical_event_id"]))
            if row.get("canonical_event_id") is not None
            else None
        ),
        disposition=str(row["disposition"]),
        content_hash=(
            str(row["content_hash"]) if row.get("content_hash") is not None else None
        ),
        revision_id=row.get("revision_id"),
    )


@pytest.fixture(scope="module", autouse=True)
def local_only():
    phase = os.environ.get(LOCAL_DB_PHASE_ENV)
    if not phase:
        pytest.skip(f"{LOCAL_DB_PHASE_ENV} not set")
    if phase not in {"038", "039"}:
        pytest.fail(f"invalid {LOCAL_DB_PHASE_ENV}={phase!r}")
    if phase != REQUIRED_PHASE:
        pytest.fail(f"{LOCAL_DB_PHASE_ENV}={phase} but this module requires {REQUIRED_PHASE}")
    try:
        _require_local()
    except Exception as exc:
        pytest.fail(f"local DB unavailable for phase {REQUIRED_PHASE}: {exc}")


def test_p1_rpc039_catalog():
    row = json.loads(
        _psql(
            """
            select jsonb_build_object(
              'result', pg_get_function_result(p.oid),
              'security_definer', p.prosecdef,
              'search_path', p.proconfig,
              'service_role', has_function_privilege('service_role', p.oid, 'EXECUTE'),
              'anon', has_function_privilege('anon', p.oid, 'EXECUTE'),
              'authenticated', has_function_privilege('authenticated', p.oid, 'EXECUTE'),
              'public_execute', exists(
                 select 1
                 from aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
                 where a.grantee = 0 and a.privilege_type = 'EXECUTE'
              )
            )
            from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public'
              and p.proname = 'persist_canonical_event_batch'
              and pg_get_function_identity_arguments(p.oid)
                  = 'p_run_id uuid, p_accepted jsonb, p_rejected jsonb';
            """
        )
    )
    assert "stored_updated_at" in row["result"]
    assert "timestamp with time zone" in row["result"]
    assert row["security_definer"] is True
    assert row["search_path"] == ["search_path=pg_catalog"]
    assert row["service_role"] is True
    assert row["anon"] is False
    assert row["authenticated"] is False
    assert row["public_execute"] is False


def test_p2_db_first_extra_column_does_not_break_base_parser():
    source_id = f"us-p2-{uuid4().hex[:8]}"
    event_id = uuid4()
    run_id = _new_run()
    rows = _persist(
        run_id,
        _event_payload(event_id, source_id, "2026-08-13T18:00:00Z", 5.1),
    )
    assert len(rows) == 1
    assert "stored_updated_at" in rows[0]
    parsed = _parse_base_runner(rows[0])
    assert parsed.artifact_id == str(event_id)
    assert parsed.disposition == "inserted"
    with pytest.raises(ValidationError):
        _BaseRunnerItem.model_validate(rows[0])


def test_p4_local_stale_t2_then_t1():
    source_id = f"us-p4-{uuid4().hex[:8]}"
    keeper_id = uuid4()
    stale_id = uuid4()
    t2 = _persist(
        _new_run(),
        _event_payload(keeper_id, source_id, "2026-08-13T18:00:00Z", 5.7),
    )[0]
    t1 = _persist(
        _new_run(),
        _event_payload(stale_id, source_id, "2026-08-13T12:00:00Z", 4.1),
    )[0]
    assert t2["disposition"] == "inserted"
    assert t1["disposition"] == "observed_existing"
    assert t1["canonical_event_id"] == t2["canonical_event_id"] == str(keeper_id)
    assert t1["stored_updated_at"].startswith("2026-08-13T18:00:00")
    item = SupabaseCanonicalProvenanceStore._item(t1)
    incoming = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
    assert item.stored_updated_at is not None
    assert incoming < item.stored_updated_at.astimezone(timezone.utc)
    mag = _psql(
        f"""
        select evidence->0->>'magnitude'
        from knowledge.events
        where id = '{keeper_id}';
        """
    )
    assert mag == "5.7"
    dup = _psql(
        f"""
        select count(*)
        from knowledge.events
        where source='USGS' and scientific_area='seismology'
          and category='earthquake_detected'
          and nullif(btrim(evidence->0->>'source_event_id'),'') = '{source_id}';
        """
    )
    assert dup == "1"


def test_p5_equal_timestamp_same_and_different_hash():
    source_id = f"us-p5-{uuid4().hex[:8]}"
    first_id = uuid4()
    same = _persist(
        _new_run(),
        _event_payload(first_id, source_id, "2026-08-13T15:00:00Z", 5.0),
    )[0]
    reobs = _persist(
        _new_run(),
        _event_payload(uuid4(), source_id, "2026-08-13T15:00:00Z", 5.0),
    )[0]
    changed = _persist(
        _new_run(),
        _event_payload(uuid4(), source_id, "2026-08-13T15:00:00Z", 6.1),
    )[0]
    assert same["disposition"] == "inserted"
    assert reobs["disposition"] == "observed_existing"
    assert changed["disposition"] == "updated"
    mag = _psql(
        f"""
        select evidence->0->>'magnitude'
        from knowledge.events
        where id = '{first_id}';
        """
    )
    assert mag == "6.1"


def test_p6_newer_timestamp_updates_and_returns_post_decision():
    source_id = f"us-p6-{uuid4().hex[:8]}"
    keeper_id = uuid4()
    first = _persist(
        _new_run(),
        _event_payload(keeper_id, source_id, "2026-08-13T12:00:00Z", 5.0),
    )[0]
    newer = _persist(
        _new_run(),
        _event_payload(uuid4(), source_id, "2026-08-13T18:00:00Z", 6.4),
    )[0]
    assert first["disposition"] == "inserted"
    assert newer["disposition"] == "updated"
    assert newer["canonical_event_id"] == str(keeper_id)
    assert newer["stored_updated_at"].startswith("2026-08-13T18:00:00")
    mag = _psql(
        f"""
        select evidence->0->>'magnitude'
        from knowledge.events
        where id = '{keeper_id}';
        """
    )
    assert mag == "6.4"


def _lock_sql(source_id: str) -> str:
    return (
        "select pg_advisory_xact_lock(hashtextextended("
        f"'knowledge.events:USGS:earthquake_detected:{source_id}', 0));"
    )


def _persist_sql(run_id: str, payload_json: str) -> str:
    return f"""
    select row_to_json(r)
    from public.persist_canonical_event_batch(
        '{run_id}'::uuid,
        jsonb_build_array('{payload_json}'::jsonb),
        '[]'::jsonb
    ) as r;
    """


def _json_row(out: str) -> dict:
    for line in reversed(str(out).strip().splitlines()):
        text = line.strip()
        if text.startswith("{"):
            return json.loads(text)
    raise AssertionError(out)


def _psql_bg(sql: str) -> tuple[threading.Thread, dict[str, object]]:
    box: dict[str, object] = {}

    def work() -> None:
        proc = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                LOCAL_CONTAINER,
                "psql",
                "-U",
                LOCAL_USER,
                "-d",
                LOCAL_DB,
                "-v",
                "ON_ERROR_STOP=1",
                "-At",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        out, err = proc.communicate(sql, timeout=40)
        box["out"] = out
        box["err"] = err
        box["code"] = proc.returncode

    thread = threading.Thread(target=work)
    thread.start()
    return thread, box


def test_c1_insert_insert_race():
    source_id = f"us-c1-{uuid4().hex[:8]}"
    left_id, right_id = uuid4(), uuid4()
    left_run, right_run = _new_run(), _new_run()
    left_payload = _event_payload(left_id, source_id, "2026-08-13T18:00:00Z", 5.2)
    right_payload = _event_payload(right_id, source_id, "2026-08-13T18:00:00Z", 5.2)
    left_thread, left_box = _psql_bg(
        "begin;\n"
        + _lock_sql(source_id)
        + _persist_sql(left_run, left_payload)
        + "select pg_sleep(2);\ncommit;\n"
    )
    time.sleep(0.4)
    right_thread, right_box = _psql_bg(
        "begin;\n" + _persist_sql(right_run, right_payload) + "commit;\n"
    )
    left_thread.join(timeout=40)
    right_thread.join(timeout=40)
    assert left_box.get("code") == 0, left_box.get("err")
    assert right_box.get("code") == 0, right_box.get("err")
    left_row = _json_row(str(left_box["out"]))
    right_row = _json_row(str(right_box["out"]))
    assert left_row["canonical_event_id"] == right_row["canonical_event_id"]
    assert {left_row["disposition"], right_row["disposition"]} <= {
        "inserted",
        "observed_existing",
    }
    assert "inserted" in {left_row["disposition"], right_row["disposition"]}
    count = _psql(
        f"""
        select count(*) from knowledge.events
        where source='USGS' and scientific_area='seismology'
          and category='earthquake_detected'
          and nullif(btrim(evidence->0->>'source_event_id'),'')='{source_id}';
        """
    )
    assert count == "1"
    valid = _psql(
        """
        select bool_and(indisvalid and indisunique)
        from pg_index i
        join pg_class c on c.oid=i.indexrelid
        join pg_namespace n on n.oid=c.relnamespace
        where n.nspname='knowledge'
          and c.relname='events_usgs_seismic_source_event_id_uidx';
        """
    )
    assert valid == "t"


def test_c2_newer_t2_wins_then_stale_t1():
    source_id = f"us-c2-{uuid4().hex[:8]}"
    t2_id, t1_id = uuid4(), uuid4()
    t2_run, t1_run = _new_run(), _new_run()
    t2_thread, t2_box = _psql_bg(
        "begin;\n"
        + _lock_sql(source_id)
        + _persist_sql(t2_run, _event_payload(t2_id, source_id, "2026-08-13T18:00:00Z", 5.9))
        + "select pg_sleep(2);\ncommit;\n"
    )
    time.sleep(0.4)
    t1_thread, t1_box = _psql_bg(
        "begin;\n"
        + _persist_sql(t1_run, _event_payload(t1_id, source_id, "2026-08-13T12:00:00Z", 4.0))
        + "commit;\n"
    )
    t2_thread.join(timeout=40)
    t1_thread.join(timeout=40)
    assert t2_box.get("code") == 0, t2_box.get("err")
    assert t1_box.get("code") == 0, t1_box.get("err")
    t1_row = _json_row(str(t1_box["out"]))
    assert t1_row["disposition"] == "observed_existing"
    assert t1_row["canonical_event_id"] == str(t2_id)
    assert t1_row["stored_updated_at"].startswith("2026-08-13T18:00:00")
    mag = _psql(f"select evidence->0->>'magnitude' from knowledge.events where id='{t2_id}';")
    assert mag == "5.9"


def test_c3_t1_first_t2_after():
    source_id = f"us-c3-{uuid4().hex[:8]}"
    t1_id, t2_id = uuid4(), uuid4()
    t1_run, t2_run = _new_run(), _new_run()
    t1_thread, t1_box = _psql_bg(
        "begin;\n"
        + _lock_sql(source_id)
        + _persist_sql(t1_run, _event_payload(t1_id, source_id, "2026-08-13T12:00:00Z", 5.0))
        + "select pg_sleep(2);\ncommit;\n"
    )
    time.sleep(0.4)
    t2_thread, t2_box = _psql_bg(
        "begin;\n"
        + _persist_sql(t2_run, _event_payload(t2_id, source_id, "2026-08-13T18:00:00Z", 6.6))
        + "commit;\n"
    )
    t1_thread.join(timeout=40)
    t2_thread.join(timeout=40)
    assert t1_box.get("code") == 0, t1_box.get("err")
    assert t2_box.get("code") == 0, t2_box.get("err")
    t2_row = _json_row(str(t2_box["out"]))
    assert t2_row["disposition"] == "updated"
    assert t2_row["canonical_event_id"] == str(t1_id)
    assert t2_row["stored_updated_at"].startswith("2026-08-13T18:00:00")
    mag = _psql(f"select evidence->0->>'magnitude' from knowledge.events where id='{t1_id}';")
    assert mag == "6.6"


def test_c4_stored_updated_at_is_transactional_not_later_select():
    source_id = f"us-c4-{uuid4().hex[:8]}"
    t2_id, t1_id = uuid4(), uuid4()
    t2_run, t1_run = _new_run(), _new_run()
    t2_thread, t2_box = _psql_bg(
        "begin;\n"
        + _lock_sql(source_id)
        + _persist_sql(t2_run, _event_payload(t2_id, source_id, "2026-08-13T18:00:00Z", 5.5))
        + "select pg_sleep(2);\ncommit;\n"
    )
    time.sleep(0.4)
    t1_thread, t1_box = _psql_bg(
        "begin;\n"
        + _persist_sql(t1_run, _event_payload(t1_id, source_id, "2026-08-13T12:00:00Z", 3.3))
        + "commit;\n"
    )
    t2_thread.join(timeout=40)
    t1_thread.join(timeout=40)
    assert t2_box.get("code") == 0, t2_box.get("err")
    assert t1_box.get("code") == 0, t1_box.get("err")
    t1_row = _json_row(str(t1_box["out"]))
    assert t1_row["stored_updated_at"].startswith("2026-08-13T18:00:00")
    assert t1_row["disposition"] == "observed_existing"
    t3_id = uuid4()
    t3 = _persist(
        _new_run(),
        _event_payload(t3_id, source_id, "2026-08-13T21:00:00Z", 7.1),
    )[0]
    assert t3["disposition"] == "updated"
    assert t3["stored_updated_at"].startswith("2026-08-13T21:00:00")
    assert not t1_row["stored_updated_at"].startswith("2026-08-13T21:00:00")


def test_038_identity_guard_still_valid():
    valid = _psql(
        """
        select bool_and(indisvalid and indisunique)
        from pg_index i
        join pg_class c on c.oid=i.indexrelid
        join pg_namespace n on n.oid=c.relnamespace
        where n.nspname='knowledge'
          and c.relname='events_usgs_seismic_source_event_id_uidx';
        """
    )
    assert valid == "t"
    assert Path("supabase/migrations/038_usgs_seismic_source_identity_dedup.sql").exists()


def test_r9_replay_history_matches_repo_files():
    files = [
        path.name.split("_", 1)[0]
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
        if path.name[:3].isdigit() and int(path.name[:3]) <= 39
    ]
    applied = _psql(
        "select string_agg(version, ',' order by version) from supabase_migrations.schema_migrations;"
    ).split(",")
    assert applied == files
    assert applied[-1] == "039"
    assert "038" in applied
    root = _repo_root()
    sha038 = hashlib.sha256(
        (root / "supabase/migrations/038_usgs_seismic_source_identity_dedup.sql")
        .read_bytes()
    ).hexdigest()
    sha039 = hashlib.sha256(
        (root / "supabase/migrations/039_canonical_event_stored_updated_at.sql")
        .read_bytes()
    ).hexdigest()
    assert sha038 == FROZEN_038_SHA256
    assert sha039 == FROZEN_039_SHA256


def test_r8_postgrest_rpc_returns_stored_updated_at():
    import urllib.request

    status = subprocess.run(
        ["npx", "--yes", "supabase@2.109.0", "status", "-o", "env"],
        cwd=str(_repo_root()),
        text=True,
        capture_output=True,
        check=True,
    )
    key = ""
    for line in status.stdout.splitlines():
        if line.startswith("SERVICE_ROLE_KEY="):
            key = line.split("=", 1)[1].strip().strip('"')
            break
    assert key
    run_id = _new_run()
    event_id = str(uuid4())
    source_id = f"us-r8-{uuid4().hex[:8]}"
    body = json.dumps(
        {
            "p_run_id": run_id,
            "p_accepted": [
                json.loads(
                    _event_payload(
                        UUID(event_id),
                        source_id,
                        "2026-08-13T18:00:00Z",
                        5.4,
                    )
                )
            ],
            "p_rejected": [],
        }
    )
    request = urllib.request.Request(
        "http://127.0.0.1:54321/rest/v1/rpc/persist_canonical_event_batch",
        data=body.encode(),
        method="POST",
        headers={
            "apikey": key,
            "authorization": f"Bearer {key}",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        rows = json.loads(response.read().decode())
    key = ""
    assert isinstance(rows, list) and rows
    assert "stored_updated_at" in rows[0]
    assert str(rows[0]["stored_updated_at"]).startswith("2026-08-13T18:00:00")


def test_r12_retry_uses_current_stored_updated_at():
    source_id = f"us-r12-{uuid4().hex[:8]}"
    first_id = uuid4()
    first_run = _new_run()
    first = _persist(
        first_run,
        _event_payload(first_id, source_id, "2026-08-13T12:00:00Z", 5.0),
    )[0]
    assert first["disposition"] == "inserted"
    newer = _persist(
        _new_run(),
        _event_payload(uuid4(), source_id, "2026-08-13T18:00:00Z", 6.2),
    )[0]
    assert newer["disposition"] == "updated"
    _psql(
        f"update provenance.run_manifests set stage='started' where run_id='{first_run}';"
    )
    row = _persist(
        first_run,
        _event_payload(first_id, source_id, "2026-08-13T12:00:00Z", 5.0),
    )[0]
    assert row["disposition"] == "inserted"
    assert row["canonical_event_id"] == str(first_id)
    stored = datetime.fromisoformat(
        str(row["stored_updated_at"]).replace("Z", "+00:00")
    )
    incoming = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
    assert incoming < stored.astimezone(timezone.utc)
    mag = _psql(
        f"select evidence->0->>'magnitude' from knowledge.events where id='{first_id}';"
    )
    assert mag == "6.2"
