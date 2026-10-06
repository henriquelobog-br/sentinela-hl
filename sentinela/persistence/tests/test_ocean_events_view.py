from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sentinela.cli.generate_real_signals import OPERATIONAL_SOURCES
from sentinela.core.models import EventStatus
from sentinela.real_signals.multithematic import OpenMeteoMarineCollector
from sentinela.real_signals.noaa import NoaaCoopsCollector, NoaaNdbcCollector


MIGRATION = Path("supabase/migrations/028_public_ocean_events_view.sql")
CLIMATE_CURRENT = Path("supabase/migrations/027_public_climate_events_view.sql")


def migration_text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def migration_sql() -> str:
    return migration_text().lower()


def _view_body(sql: str) -> str:
    start = sql.index("create view public.v_ocean_events")
    return sql[start : sql.index("alter view public.v_ocean_events", start)]


def _public_columns(select_sql: str) -> list[str]:
    select = select_sql.split("select", 1)[1].split("from knowledge.events", 1)[0]
    return [line.strip(" ,") for line in select.splitlines() if line.strip(" ,")]


def test_028_exists_after_027():
    names = [path.name for path in sorted(Path("supabase/migrations").glob("*.sql"))]
    assert "028_public_ocean_events_view.sql" in names
    assert names.index("028_public_ocean_events_view.sql") == (
        names.index("027_public_climate_events_view.sql") + 1
    )


def test_view_creates_only_ocean_events_contract():
    sql = migration_sql()
    assert sql.count("create view public.v_ocean_events") == 1
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


def test_view_matches_climate_public_columns_and_security():
    ocean = _view_body(migration_sql())
    climate = CLIMATE_CURRENT.read_text(encoding="utf-8").lower()
    climate_view = climate.split("create view public.v_climate_events", 1)[1].split(
        "alter view public.v_climate_events", 1
    )[0]
    assert _public_columns(ocean) == _public_columns(climate_view)
    assert "with (security_invoker = true)" in ocean
    sql = migration_sql()
    assert "alter view public.v_ocean_events owner to postgres" in sql
    assert (
        "revoke all on public.v_ocean_events from public, anon, authenticated, service_role"
        in sql
    )
    assert "grant select on public.v_ocean_events to service_role" in sql
    assert "grant usage on schema knowledge to service_role" in sql
    assert "to anon" not in sql.replace("from public, anon, authenticated, service_role", "")
    assert "to authenticated" not in sql.replace(
        "from public, anon, authenticated, service_role", ""
    )
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql


def test_view_includes_observed_fact_and_forecast_only():
    where = _view_body(migration_sql()).split("where", 1)[1]
    assert "scientific_area = 'oceanography'" in where
    assert "event_status in ('observed_fact', 'forecast')" in where
    assert "publication_approved" in where
    assert "'model_projection'" not in where
    assert "climate_science" not in where
    assert "atmospheric_science" not in where
    assert "official_alert" not in where


def test_view_comment_excludes_model_projection():
    sql = migration_sql()
    assert "excludes model_projection" in sql
    assert "observed_fact and forecast" in sql


def test_view_does_not_change_collectors_or_eligibility():
    sql = migration_sql()
    assert "is_signal_eligible_for_persistence" not in sql
    assert "operational_sources" not in sql
    assert "openmeteo-marine" in OPERATIONAL_SOURCES
    assert "noaa-coops" in OPERATIONAL_SOURCES
    assert "noaa-ndbc" in OPERATIONAL_SOURCES
    assert EventStatus.OBSERVED_FACT.value == "observed_fact"
    assert EventStatus.FORECAST.value == "forecast"
    assert EventStatus.MODEL_PROJECTION.value == "model_projection"
    assert OpenMeteoMarineCollector.__name__ == "OpenMeteoMarineCollector"
    assert NoaaCoopsCollector.__name__ == "NoaaCoopsCollector"
    assert NoaaNdbcCollector.__name__ == "NoaaNdbcCollector"


def test_028_does_not_rewrite_frozen_climate_migration():
    digest = hashlib.sha256(CLIMATE_CURRENT.read_bytes()).hexdigest()
    assert digest == "793c760dd4ae311731790771a6d09c9b830f2999dd25e25da4cf16c2450d1e1d"


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
