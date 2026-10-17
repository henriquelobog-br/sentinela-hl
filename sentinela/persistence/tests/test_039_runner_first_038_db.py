from __future__ import annotations

from uuid import uuid4
import json
import os
import subprocess

import pytest

from sentinela.persistence.canonical_store import SupabaseCanonicalProvenanceStore

LOCAL_CONTAINER = "supabase_db_sentinela-hl"
LOCAL_DB_PHASE_ENV = "SENTINELA_LOCAL_DB_PHASE"
REQUIRED_PHASE = "038"

pytestmark = pytest.mark.local_db


def _psql(sql: str) -> str:
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            LOCAL_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
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


@pytest.fixture(scope="module", autouse=True)
def require_phase_038():
    phase = os.environ.get(LOCAL_DB_PHASE_ENV)
    if not phase:
        pytest.skip(f"{LOCAL_DB_PHASE_ENV} not set")
    if phase not in {"038", "039"}:
        pytest.fail(f"invalid {LOCAL_DB_PHASE_ENV}={phase!r}")
    if phase != REQUIRED_PHASE:
        pytest.fail(f"{LOCAL_DB_PHASE_ENV}={phase} but this module requires {REQUIRED_PHASE}")
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.Name}}", LOCAL_CONTAINER],
        text=True,
        capture_output=True,
        check=False,
    )
    if inspect.returncode != 0 or LOCAL_CONTAINER not in inspect.stdout:
        pytest.fail("local supabase postgres container is unavailable")
    versions = _psql(
        "select string_agg(version, ',' order by version) from supabase_migrations.schema_migrations;"
    )
    if "038" not in versions.split(","):
        pytest.fail(f"local DB missing 038: {versions}")
    if "039" in versions.split(","):
        pytest.fail(f"local DB is not exactly 038: {versions}")


def test_p3_runner_first_038_db_has_no_stored_updated_at_and_does_not_false_stale():
    result = _psql(
        """
        select pg_get_function_result(p.oid)
        from pg_proc p
        join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public'
          and p.proname='persist_canonical_event_batch'
          and pg_get_function_identity_arguments(p.oid)
              = 'p_run_id uuid, p_accepted jsonb, p_rejected jsonb';
        """
    )
    assert "stored_updated_at" not in result
    run_id = str(uuid4())
    event_id = str(uuid4())
    source_id = f"us-p3-{uuid4().hex[:8]}"
    payload = json.dumps(
        {
            "event": {
                "id": event_id,
                "title": "USGS p3",
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
                        "source_event_id": source_id,
                        "updated_at": "2026-08-13T12:00:00Z",
                        "magnitude": 5.0,
                    }
                ],
                "occurred_at": "2026-08-13T12:00:00Z",
                "supporting_sources": [],
            },
            "collector": "usgs",
            "collector_role": "requested",
            "content_hash": "a" * 64,
        }
    ).replace("'", "''")
    _psql(
        f"""
        insert into raw.pipeline_runs (
            id, initiated_by, mode, status, started_at,
            requested_sources, requested_source_count
        ) values (
            '{run_id}', 'local_p3', 'persist', 'running', now(),
            array['usgs'], 1
        );
        select public.begin_canonical_run_manifest('{run_id}'::uuid);
        """
    )
    raw = _psql(
        f"""
        select coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb)
        from public.persist_canonical_event_batch(
            '{run_id}'::uuid,
            jsonb_build_array('{payload}'::jsonb),
            '[]'::jsonb
        ) as r;
        """
    )
    rows = json.loads(raw)
    assert len(rows) == 1
    assert "stored_updated_at" not in rows[0]
    item = SupabaseCanonicalProvenanceStore._item(rows[0])
    assert item.stored_updated_at is None
    assert item.disposition.value == "inserted"


def test_r6_drop_create_rollback_keeps_038_rpc():
    before = _psql(
        """
        select pg_get_function_result(p.oid)
        from pg_proc p
        join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public'
          and p.proname='persist_canonical_event_batch'
          and pg_get_function_identity_arguments(p.oid)
              = 'p_run_id uuid, p_accepted jsonb, p_rejected jsonb';
        """
    )
    assert "stored_updated_at" not in before
    err = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            LOCAL_CONTAINER,
            "psql",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
        ],
        input=(
            "begin;\n"
            "drop function public.persist_canonical_event_batch(uuid, jsonb, jsonb);\n"
            "do $$ begin raise exception 'controlled 039 install failure'; end $$;\n"
            "commit;\n"
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert err.returncode != 0
    assert "controlled 039 install failure" in (err.stderr or err.stdout)
    after = _psql(
        """
        select pg_get_function_result(p.oid)
        from pg_proc p
        join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public'
          and p.proname='persist_canonical_event_batch'
          and pg_get_function_identity_arguments(p.oid)
              = 'p_run_id uuid, p_accepted jsonb, p_rejected jsonb';
        """
    )
    assert after == before
    execute = _psql(
        """
        select jsonb_build_object(
          'service_role', has_function_privilege(
              'service_role',
              'public.persist_canonical_event_batch(uuid,jsonb,jsonb)',
              'EXECUTE'
          ),
          'anon', has_function_privilege(
              'anon',
              'public.persist_canonical_event_batch(uuid,jsonb,jsonb)',
              'EXECUTE'
          )
        );
        """
    )
    privileges = json.loads(execute)
    assert privileges["service_role"] is True
    assert privileges["anon"] is False
