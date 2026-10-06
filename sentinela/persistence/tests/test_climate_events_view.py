from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sentinela.cli.generate_real_signals import OPERATIONAL_SOURCES
from sentinela.core.models import EventStatus
from sentinela.real_signals.climate import OpenMeteoClimateCollector
from sentinela.real_signals.multithematic import OpenMeteoWeatherCollector
from sentinela.real_signals.nws import NwsAlertsCollector


MIGRATION = Path("supabase/migrations/027_public_climate_events_view.sql")
SEISMIC_CURRENT = Path("supabase/migrations/021_canonical_event_provenance_v1.sql")


def migration_text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def migration_sql() -> str:
    return migration_text().lower()


def _view_body(sql: str) -> str:
    start = sql.index("create view public.v_climate_events")
    return sql[start : sql.index("alter view public.v_climate_events", start)]


def _public_columns(select_sql: str) -> list[str]:
    select = select_sql.split("select", 1)[1].split("from knowledge.events", 1)[0]
    return [line.strip(" ,") for line in select.splitlines() if line.strip(" ,")]


def test_027_is_next_free_migration_after_026():
    names = [path.name for path in sorted(Path("supabase/migrations").glob("*.sql"))]
    assert "027_public_climate_events_view.sql" in names
    assert names.index("027_public_climate_events_view.sql") == (
        names.index("026_research_public_view.sql") + 1
    )


def test_view_creates_only_climate_events_contract():
    sql = migration_sql()
    assert sql.count("create view public.v_climate_events") == 1
    assert "create or replace view" not in sql
    assert "create table" not in sql
    assert "create function" not in sql
    assert "create or replace function" not in sql
    assert "create policy" not in sql
    assert "enable row level security" not in sql
    assert "insert " not in sql
    assert "update " not in sql
    assert "delete " not in sql
    assert "drop " not in sql


def test_view_matches_seismic_public_columns_and_security():
    climate = _view_body(migration_sql())
    seismic = SEISMIC_CURRENT.read_text(encoding="utf-8").lower()
    seismic_view = seismic.split(
        "create or replace view public.v_seismic_events", 1
    )[1].split("alter view public.v_seismic_events", 1)[0]
    assert _public_columns(climate) == _public_columns(seismic_view)
    assert "with (security_invoker = true)" in climate
    sql = migration_sql()
    assert "alter view public.v_climate_events owner to postgres" in sql
    assert (
        "revoke all on public.v_climate_events from public, anon, authenticated, service_role"
        in sql
    )
    assert "grant select on public.v_climate_events to service_role" in sql
    assert "grant usage on schema knowledge to service_role" in sql
    assert "to anon" not in sql.replace("from public, anon, authenticated, service_role", "")
    assert "to authenticated" not in sql.replace(
        "from public, anon, authenticated, service_role", ""
    )
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql


def test_view_includes_forecast_and_official_alert_only():
    where = _view_body(migration_sql()).split("where", 1)[1]
    assert "scientific_area = 'climate_science'" in where
    assert "event_status in ('forecast', 'official_alert')" in where
    assert "publication_approved" in where
    assert "'model_projection'" not in where
    assert "seismology" not in where
    assert "earthquake_detected" not in where
    assert "openmeteo-climate" not in where
    assert "cmip6" not in where


def test_view_comment_excludes_model_projection():
    sql = migration_sql()
    assert "excludes model_projection" in sql
    assert "forecast and official_alert" in sql


def test_view_does_not_operationalize_cmip6_or_change_eligibility():
    sql = migration_sql()
    assert "openmeteo-climate" not in sql
    assert "is_signal_eligible_for_persistence" not in sql
    assert "operational_sources" not in sql
    assert "openmeteo-climate" not in OPERATIONAL_SOURCES
    assert "openmeteo-weather" in OPERATIONAL_SOURCES
    assert "nws-alerts" in OPERATIONAL_SOURCES
    source = Path("sentinela/real_signals/climate.py").read_text(encoding="utf-8")
    assert "event_status=EventStatus.MODEL_PROJECTION" in source
    assert '"classification": "climate_projection"' in source
    assert '"operational_feed": False' in source


def test_operational_collectors_keep_distinct_event_status():
    weather = Path("sentinela/real_signals/multithematic.py").read_text(encoding="utf-8")
    nws = Path("sentinela/real_signals/nws.py").read_text(encoding="utf-8")
    assert "event_status=EventStatus.FORECAST" in weather
    assert "event_status=EventStatus.OFFICIAL_ALERT" in nws
    assert EventStatus.FORECAST.value == "forecast"
    assert EventStatus.OFFICIAL_ALERT.value == "official_alert"
    assert EventStatus.MODEL_PROJECTION.value == "model_projection"
    assert OpenMeteoWeatherCollector.__name__ == "OpenMeteoWeatherCollector"
    assert NwsAlertsCollector.__name__ == "NwsAlertsCollector"
    assert OpenMeteoClimateCollector.__name__ == "OpenMeteoClimateCollector"


def test_027_does_not_rewrite_frozen_migrations():
    expected = {
        "021_canonical_event_provenance_v1.sql": (
            "fff557ecf8d253f506a2537f6bd335563bde97d62165a02a55b6896ae222d9e7"
        ),
        "022_fix_canonical_event_revision_conflict.sql": (
            "93bb9a695dc1bfa66ce0a6d715a6d546dc70312bf93b7db35909f8118d3a8f4b"
        ),
        "023_fix_canonical_signal_disposition_ambiguity.sql": (
            "f632b012b4bdc59c7677f0406aafb60588f9e0b9389e06d1fd6ae92c4a9cb4bf"
        ),
    }
    for name, digest in expected.items():
        actual = hashlib.sha256(
            (Path("supabase/migrations") / name).read_bytes()
        ).hexdigest()
        assert actual == digest


def test_column_grant_is_limited_to_view_inputs():
    sql = migration_sql()
    grant = sql.split("grant select (", 1)[1].split(") on knowledge.events", 1)[0]
    columns = [item.strip() for item in grant.split(",")]
    assert columns == [
        "id",
        "title",
        "summary",
        "category",
        "source",
        "event_status",
        "country",
        "scientific_area",
        "evidence",
        "occurred_at",
        "validated_at",
        "publication_approved",
    ]
    assert re.search(r"(?m)^\s*grant select \*", sql) is None
