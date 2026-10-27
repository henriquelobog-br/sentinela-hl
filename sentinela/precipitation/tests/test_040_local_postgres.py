from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest


LOCAL_CONTAINER = "supabase_db_sentinela-hl"
LOCAL_DB_PHASE_ENV = "SENTINELA_LOCAL_DB_PHASE"
pytestmark = pytest.mark.local_db
TOKEN = uuid4().hex


def _sha(label: str) -> str:
    return hashlib.sha256(f"{TOKEN}:{label}".encode()).hexdigest()


def _psql(sql: str, *, check: bool = True) -> str:
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
    if check and proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.stdout.strip() if proc.returncode == 0 else proc.stderr.strip()


@pytest.fixture(scope="module", autouse=True)
def local_only():
    if os.environ.get(LOCAL_DB_PHASE_ENV) != "040":
        pytest.skip(f"{LOCAL_DB_PHASE_ENV}=040 required")
    versions = _psql(
        "select string_agg(version, ',' order by version) "
        "from supabase_migrations.schema_migrations;"
    ).split(",")
    assert versions[-1] == "040"


def _new_run() -> str:
    run_id = str(uuid4())
    _psql(
        f"""
        insert into raw.pipeline_runs(
            id, initiated_by, mode, status, started_at,
            requested_sources, requested_source_count
        ) values (
            '{run_id}', 'precip_040_test', 'persist', 'running', now(),
            array['imerg'], 1
        );
        """
    )
    return run_id


def _forecast_item(
    model: str = "gfs",
    *,
    run_time: str = "2026-10-01T00:00:00Z",
    lead_hours: int = 24,
    valid_from: str = "2026-10-02T00:00:00Z",
    valid_to: str = "2026-10-03T00:00:00Z",
) -> dict:
    run_key = run_time.replace(":", "").replace("-", "")
    return {
        "region": {
            "region_key": f"test-roi-040-{TOKEN}",
            "name": "Test ROI",
            "roi_geojson": {"type": "Polygon", "coordinates": []},
            "roi_sha256": _sha("roi"),
            "min_lat": -1,
            "max_lat": 1,
            "min_lon": -1,
            "max_lon": 1,
        },
        "artifact": {
            "artifact_sha256": _sha(f"forecast-artifact:{model}:{run_key}"),
            "source_uri": f"file:///forecast-{model}.nc",
            "media_type": "application/x-netcdf",
            "retrieved_at": "2026-10-01T00:30:00Z",
            "metadata": {},
        },
        "forecast": {
            "model": model,
            "run_time": run_time,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "threshold_mm": 25,
            "probability": 0.5,
            "lead_hours": lead_hours,
            "grid_sha256": _sha("forecast-grid"),
            "forecast_field_sha256": _sha(f"forecast-field:{model}:{run_key}"),
            "provenance": {"test": "040"},
        },
    }


def _persist_forecasts(run_id: str, items: list[dict]) -> list[dict]:
    payload = json.dumps(items).replace("'", "''")
    return json.loads(
        _psql(
            f"""
            select jsonb_agg(to_jsonb(result))
            from public.persist_precip_forecast_batch(
                '{run_id}'::uuid, '{payload}'::jsonb
            ) as result;
            """
        )
    )


def _observation() -> dict:
    return {
        "artifact": {
            "artifact_sha256": _sha("observation-artifact"),
            "source_uri": "file:///3B-HHR.V07C.20261002-S000000.h5",
            "media_type": "application/x-hdf5",
            "retrieved_at": "2026-10-02T01:00:00Z",
            "metadata": {},
        },
        "observation": {
            "product": "IMERG-FINAL",
            "source_granule_id": f"20261002-S000000-{TOKEN}",
            "filename_version": "V07C",
            "internal_product_version": "07B",
            "algorithm_version": "IMERG-V07",
            "revision": 1,
            "granule_start": "2026-10-02T00:00:00Z",
            "granule_end": "2026-10-02T00:30:00Z",
            "generation_time": "2026-10-02T00:35:00Z",
            "available_at": "2026-10-02T00:40:00Z",
            "retrieved_at": "2026-10-02T01:00:00Z",
            "variable_name": "precipitationCal",
            "units": "mm/h",
            "fill_value": -9999.9,
            "source_grid": {"resolution_deg": 0.1},
            "grid_sha256": _sha("observation-grid"),
            "field_sha256": _sha("observation-field"),
            "provenance": {"test": "040"},
        },
    }


def _persist_observation(run_id: str, payload: dict, *, check: bool = True) -> str:
    encoded = json.dumps(payload).replace("'", "''")
    return _psql(
        f"select public.persist_precip_observation_granule("
        f"'{run_id}'::uuid, '{encoded}'::jsonb);",
        check=check,
    )


def test_schema_rls_rpc_and_index_contract():
    assert _psql(
        """
        select count(*) from pg_class c
        join pg_namespace n on n.oid=c.relnamespace
        where n.nspname in ('raw','knowledge')
          and c.relkind='r' and c.relname like 'precip_%';
        """
    ) == "9"
    assert _psql(
        """
        select count(*) from pg_class c
        join pg_namespace n on n.oid=c.relnamespace
        where n.nspname in ('raw','knowledge')
          and c.relkind='r' and c.relname like 'precip_%' and c.relrowsecurity;
        """
    ) == "9"
    assert _psql(
        """
        select count(*) from pg_proc p
        join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='public' and p.proname like 'persist_precip_%'
          and p.prosecdef and p.proconfig = array['search_path=pg_catalog']
          and has_function_privilege('service_role', p.oid, 'EXECUTE')
          and not has_function_privilege('anon', p.oid, 'EXECUTE')
          and not has_function_privilege('authenticated', p.oid, 'EXECUTE');
        """
    ) == "3"
    assert _psql(
        """
        select count(*) from pg_indexes
        where indexname in (
          'precip_forecasts_region_valid_idx', 'precip_forecasts_run_time_idx',
          'precip_event_groups_region_valid_idx',
          'precip_verification_expectations_state_expected_idx',
          'precip_verification_expectations_state_expires_idx',
          'precip_verification_summaries_event_generated_idx',
          'precip_observation_granules_product_revision_start_idx'
        );
        """
    ) == "7"
    expectation_contract = json.loads(
        _psql(
            """
            select jsonb_build_object(
              'forecast_column', exists(
                select 1 from information_schema.columns
                where table_schema='knowledge'
                  and table_name='precip_verification_expectations'
                  and column_name='forecast_id' and is_nullable='NO'
              ),
              'event_group_column', exists(
                select 1 from information_schema.columns
                where table_schema='knowledge'
                  and table_name='precip_verification_expectations'
                  and column_name='event_group_id'
              ),
              'forecast_unique', exists(
                select 1
                from pg_constraint c
                join pg_class r on r.oid=c.conrelid
                join pg_namespace n on n.oid=r.relnamespace
                where n.nspname='knowledge'
                  and r.relname='precip_verification_expectations'
                  and c.contype='u'
                  and pg_get_constraintdef(c.oid)='UNIQUE (forecast_id)'
              ),
              'forecast_fk', exists(
                select 1
                from pg_constraint c
                join pg_class r on r.oid=c.conrelid
                join pg_namespace n on n.oid=r.relnamespace
                where n.nspname='knowledge'
                  and r.relname='precip_verification_expectations'
                  and c.contype='f'
                  and pg_get_constraintdef(c.oid) like
                    'FOREIGN KEY (forecast_id) REFERENCES knowledge.precip_forecasts(id)%'
              )
            );
            """
        )
    )
    assert expectation_contract == {
        "forecast_column": True,
        "event_group_column": False,
        "forecast_unique": True,
        "forecast_fk": True,
    }
    summary_contract = json.loads(
        _psql(
            """
            select jsonb_build_object(
              'forecast_column', exists(
                select 1 from information_schema.columns
                where table_schema='knowledge'
                  and table_name='precip_verification_summaries'
                  and column_name='forecast_id' and is_nullable='NO'
              ),
              'forecast_observation_unique', exists(
                select 1
                from pg_constraint c
                join pg_class r on r.oid=c.conrelid
                join pg_namespace n on n.oid=r.relnamespace
                where n.nspname='knowledge'
                  and r.relname='precip_verification_summaries'
                  and c.contype='u'
                  and pg_get_constraintdef(c.oid)=
                    'UNIQUE (forecast_id, observation_granule_id)'
              ),
              'event_observation_unique', exists(
                select 1
                from pg_constraint c
                join pg_class r on r.oid=c.conrelid
                join pg_namespace n on n.oid=r.relnamespace
                where n.nspname='knowledge'
                  and r.relname='precip_verification_summaries'
                  and c.contype='u'
                  and pg_get_constraintdef(c.oid)=
                    'UNIQUE (event_group_id, observation_granule_id)'
              ),
              'forecast_fk', exists(
                select 1
                from pg_constraint c
                join pg_class r on r.oid=c.conrelid
                join pg_namespace n on n.oid=r.relnamespace
                where n.nspname='knowledge'
                  and r.relname='precip_verification_summaries'
                  and c.contype='f'
                  and pg_get_constraintdef(c.oid) like
                    'FOREIGN KEY (forecast_id) REFERENCES knowledge.precip_forecasts(id)%'
              )
            );
            """
        )
    )
    assert summary_contract == {
        "forecast_column": True,
        "forecast_observation_unique": True,
        "event_observation_unique": False,
        "forecast_fk": True,
    }


def test_forecast_rpc_idempotency_and_scientific_uniqueness():
    run_id = _new_run()
    first = _persist_forecasts(run_id, [_forecast_item()])[0]
    retry = _persist_forecasts(run_id, [_forecast_item()])[0]
    second_run = _persist_forecasts(
        run_id,
        [
            _forecast_item(
                run_time="2026-10-01T06:00:00Z",
                lead_hours=18,
            )
        ],
    )[0]
    assert first["disposition"] == "inserted"
    assert retry["disposition"] == "existing"
    assert retry["forecast_id"] == first["forecast_id"]
    assert second_run["forecast_id"] != first["forecast_id"]
    assert second_run["event_group_id"] == first["event_group_id"]
    assert _psql(
        "select count(*) from knowledge.precip_forecasts "
        "where region_id=(select id from knowledge.precip_regions "
        f"where region_key='test-roi-040-{TOKEN}');"
    ) == "2"
    assert _psql(
        "select count(*) from knowledge.precip_event_groups "
        "where region_id=(select id from knowledge.precip_regions "
        f"where region_key='test-roi-040-{TOKEN}');"
    ) == "1"
    assert _psql(
        f"select count(*) from knowledge.precip_event_forecasts "
        f"where event_group_id='{first['event_group_id']}';"
    ) == "2"
    assert _psql(
        f"select count(*) from knowledge.precip_verification_expectations e "
        f"join knowledge.precip_event_forecasts ef on ef.forecast_id=e.forecast_id "
        f"where ef.event_group_id='{first['event_group_id']}';"
    ) == "2"
    assert _psql(
        f"select count(*) from knowledge.precip_verification_expectations "
        f"where forecast_id='{first['forecast_id']}';"
    ) == "1"
    timing = _psql(
        f"""
        select bool_and(e.expected_at=f.valid_to+interval '4 hours')::text || ',' ||
               bool_and(e.expires_at=f.valid_to+interval '8 hours')::text
        from knowledge.precip_verification_expectations e
        join knowledge.precip_forecasts f on f.id=e.forecast_id
        join knowledge.precip_event_forecasts ef on ef.forecast_id=f.id
        where ef.event_group_id='{first['event_group_id']}';
        """
    )
    assert timing == "true,true"


def test_observation_versions_are_immutable_and_not_equated():
    run_id = _new_run()
    payload = _observation()
    first_id = _persist_observation(run_id, payload)
    assert _persist_observation(run_id, payload) == first_id
    versions = _psql(
        f"select filename_version || ',' || internal_product_version "
        f"from knowledge.precip_observation_granules where id='{first_id}';"
    )
    assert versions == "V07C,07B"
    conflict = deepcopy(payload)
    conflict["observation"]["field_sha256"] = "a" * 64
    error = _persist_observation(run_id, conflict, check=False)
    assert "conflicting immutable precipitation observation revision" in error


def test_verification_rpc_is_idempotent_and_summary_is_immutable():
    run_id = _new_run()
    forecast = _persist_forecasts(run_id, [_forecast_item()])[0]
    sibling = _persist_forecasts(
        run_id,
        [
            _forecast_item(
                model="verification-sibling",
                run_time="2026-10-01T06:00:00Z",
                lead_hours=18,
            )
        ],
    )[0]
    observation_id = _persist_observation(run_id, _observation())
    payload = {
        "event_group_id": forecast["event_group_id"],
        "forecast_id": forecast["forecast_id"],
        "observation_granule_id": observation_id,
        "verification_generated_at": "2026-10-03T03:00:00Z",
        "temporal_coverage": 1,
        "spatial_coverage": 1,
        "valid_roi_cells_fraction": 1,
        "valid_cell_count": 4,
        "total_cell_count": 4,
        "valid_area_km2": 100,
        "total_area_km2": 100,
        "hit_cell_count": 1,
        "hit_area_km2": 25,
        "hit_area_fraction": 0.25,
        "miss_cell_count": 1,
        "miss_area_km2": 25,
        "miss_area_fraction": 0.25,
        "false_alarm_cell_count": 1,
        "false_alarm_area_km2": 25,
        "false_alarm_area_fraction": 0.25,
        "correct_negative_cell_count": 1,
        "correct_negative_area_km2": 25,
        "correct_negative_area_fraction": 0.25,
        "observed_max_mm": 60,
        "observed_area_mean_mm": 20,
        "comparison_grid": {"resolution_deg": 0.25},
        "regrid_algorithm_version": "spherical-conservative-v1",
        "regrid_weights_sha256": "b" * 64,
        "cell_result_artifact_sha256": "c" * 64,
        "provenance": {"test": "040"},
    }
    encoded = json.dumps(payload).replace("'", "''")
    statement = (
        "select public.persist_precip_verification("
        f"'{run_id}'::uuid, '{encoded}'::jsonb);"
    )
    first_id = _psql(statement)
    assert _psql(statement) == first_id
    state = _psql(
        f"select state || ',' || attempt_count from "
        f"knowledge.precip_verification_expectations "
        f"where forecast_id='{forecast['forecast_id']}';"
    )
    assert state == "EARLY_VERIFIED,1"
    sibling_state = _psql(
        f"select state || ',' || attempt_count from "
        f"knowledge.precip_verification_expectations "
        f"where forecast_id='{sibling['forecast_id']}';"
    )
    assert sibling_state == "AWAITING_OBSERVATION,0"
    assert _psql(
        f"select forecast_id::text from knowledge.precip_verification_summaries "
        f"where id='{first_id}';"
    ) == forecast["forecast_id"]

    sibling_payload = deepcopy(payload)
    sibling_payload["forecast_id"] = sibling["forecast_id"]
    sibling_payload["cell_result_artifact_sha256"] = "e" * 64
    sibling_encoded = json.dumps(sibling_payload).replace("'", "''")
    sibling_summary_id = _psql(
        "select public.persist_precip_verification("
        f"'{run_id}'::uuid, '{sibling_encoded}'::jsonb);"
    )
    assert sibling_summary_id != first_id
    assert _psql(
        f"select count(*) from knowledge.precip_verification_summaries "
        f"where event_group_id='{forecast['event_group_id']}' "
        f"and observation_granule_id='{observation_id}';"
    ) == "2"

    other_group = _persist_forecasts(
        run_id,
        [
            _forecast_item(
                model="verification-other-group",
                run_time="2026-10-02T00:00:00Z",
                valid_from="2026-10-03T00:00:00Z",
                valid_to="2026-10-04T00:00:00Z",
            )
        ],
    )[0]
    mismatch = deepcopy(payload)
    mismatch["forecast_id"] = other_group["forecast_id"]
    mismatch_encoded = json.dumps(mismatch).replace("'", "''")
    mismatch_error = _psql(
        "select public.persist_precip_verification("
        f"'{run_id}'::uuid, '{mismatch_encoded}'::jsonb);",
        check=False,
    )
    assert "precipitation forecast does not belong to event group" in mismatch_error

    conflict = deepcopy(payload)
    conflict["cell_result_artifact_sha256"] = "d" * 64
    conflict_encoded = json.dumps(conflict).replace("'", "''")
    error = _psql(
        "select public.persist_precip_verification("
        f"'{run_id}'::uuid, '{conflict_encoded}'::jsonb);",
        check=False,
    )
    assert "conflicting immutable precipitation verification retry" in error


def test_migration_history_matches_repository_through_040():
    files = [
        path.name.split("_", 1)[0]
        for path in sorted(Path("supabase/migrations").glob("*.sql"))
        if path.name[:3].isdigit() and int(path.name[:3]) <= 40
    ]
    applied = _psql(
        "select string_agg(version, ',' order by version) "
        "from supabase_migrations.schema_migrations;"
    ).split(",")
    assert applied == files
