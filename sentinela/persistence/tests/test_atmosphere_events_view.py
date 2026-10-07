from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sentinela.cli.generate_real_signals import OPERATIONAL_SOURCES
from sentinela.core.models import EventStatus
from sentinela.real_signals.collectors import CamsCollector, CmrCollector, Merra2Collector


MIGRATION = Path("supabase/migrations/029_public_atmosphere_events_view.sql")
OCEAN_CURRENT = Path("supabase/migrations/028_public_ocean_events_view.sql")
CLIMATE_CURRENT = Path("supabase/migrations/027_public_climate_events_view.sql")


def migration_text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def migration_sql() -> str:
    return migration_text().lower()


def _view_body(sql: str) -> str:
    start = sql.index("create view public.v_atmosphere_events")
    return sql[start : sql.index("alter view public.v_atmosphere_events", start)]


def _public_columns(select_sql: str) -> list[str]:
    select = select_sql.split("select", 1)[1].split("from knowledge.events", 1)[0]
    return [line.strip(" ,") for line in select.splitlines() if line.strip(" ,")]


def test_029_exists_after_028():
    names = [path.name for path in sorted(Path("supabase/migrations").glob("*.sql"))]
    assert "029_public_atmosphere_events_view.sql" in names
    assert names.index("029_public_atmosphere_events_view.sql") == (
        names.index("028_public_ocean_events_view.sql") + 1
    )


def test_view_creates_only_atmosphere_events_contract():
    sql = migration_sql()
    assert sql.count("create view public.v_atmosphere_events") == 1
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


def test_view_matches_ocean_public_columns_and_security():
    atmosphere = _view_body(migration_sql())
    ocean = OCEAN_CURRENT.read_text(encoding="utf-8").lower()
    ocean_view = ocean.split("create view public.v_ocean_events", 1)[1].split(
        "alter view public.v_ocean_events", 1
    )[0]
    assert _public_columns(atmosphere) == _public_columns(ocean_view)
    assert _public_columns(atmosphere) == [
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
    ]
    assert "with (security_invoker = true)" in atmosphere
    sql = migration_sql()
    assert "alter view public.v_atmosphere_events owner to postgres" in sql
    assert (
        "revoke all on public.v_atmosphere_events from public, anon, authenticated, service_role"
        in sql
    )
    assert "grant select on public.v_atmosphere_events to service_role" in sql
    assert "grant usage on schema knowledge to service_role" in sql
    assert "to anon" not in sql.replace("from public, anon, authenticated, service_role", "")
    assert "to authenticated" not in sql.replace(
        "from public, anon, authenticated, service_role", ""
    )
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql


def test_view_includes_observed_fact_forecast_and_catalog_record_only():
    where = _view_body(migration_sql()).split("where", 1)[1]
    assert "scientific_area = 'atmospheric_science'" in where
    assert "event_status in ('observed_fact', 'forecast', 'catalog_record')" in where
    assert "publication_approved" in where
    assert "'model_projection'" not in where
    assert "climate_science" not in where
    assert "oceanography" not in where
    assert "official_alert" not in where
    assert "source in" not in where
    assert "source =" not in where


def test_view_comment_preserves_catalog_record_as_availability():
    sql = migration_sql()
    assert "catalog_record is approved satellite product/granule availability" in sql
    assert "does not confirm an atmospheric phenomenon" in sql
    assert "observed_fact, forecast, and catalog_record" in sql
    assert "excludes model_projection and official_alert" in sql


def test_view_does_not_change_collectors_or_eligibility():
    sql = migration_sql()
    assert "is_signal_eligible_for_persistence" not in sql
    assert "operational_sources" not in sql
    assert "cams" in OPERATIONAL_SOURCES
    assert "cmr" in OPERATIONAL_SOURCES
    assert "merra2" in OPERATIONAL_SOURCES
    assert EventStatus.OBSERVED_FACT.value == "observed_fact"
    assert EventStatus.FORECAST.value == "forecast"
    assert EventStatus.CATALOG_RECORD.value == "catalog_record"
    assert EventStatus.MODEL_PROJECTION.value == "model_projection"
    assert EventStatus.OFFICIAL_ALERT.value == "official_alert"
    assert CamsCollector.__name__ == "CamsCollector"
    assert CmrCollector.__name__ == "CmrCollector"
    assert Merra2Collector.__name__ == "Merra2Collector"


def test_029_does_not_rewrite_frozen_climate_or_ocean_migrations():
    climate = hashlib.sha256(CLIMATE_CURRENT.read_bytes()).hexdigest()
    ocean = hashlib.sha256(OCEAN_CURRENT.read_bytes()).hexdigest()
    assert climate == "793c760dd4ae311731790771a6d09c9b830f2999dd25e25da4cf16c2450d1e1d"
    assert ocean == "aa2fe7d0d7f4a3b1bb8e55ec01a7908b47e6e7b787d70aa80480298644f57c42"


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
