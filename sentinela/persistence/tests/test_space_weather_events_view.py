from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sentinela.cli.generate_real_signals import OPERATIONAL_SOURCES
from sentinela.core.models import EventStatus
from sentinela.real_signals.multithematic import DonkiCollector


MIGRATION = Path("supabase/migrations/030_public_space_weather_events_view.sql")
ATMOSPHERE_CURRENT = Path("supabase/migrations/029_public_atmosphere_events_view.sql")
OCEAN_CURRENT = Path("supabase/migrations/028_public_ocean_events_view.sql")
CLIMATE_CURRENT = Path("supabase/migrations/027_public_climate_events_view.sql")


def migration_text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def migration_sql() -> str:
    return migration_text().lower()


def _view_body(sql: str) -> str:
    start = sql.index("create view public.v_space_weather_events")
    return sql[start : sql.index("alter view public.v_space_weather_events", start)]


def _public_columns(select_sql: str) -> list[str]:
    select = select_sql.split("select", 1)[1].split("from knowledge.events", 1)[0]
    return [line.strip(" ,") for line in select.splitlines() if line.strip(" ,")]


def test_030_exists_after_029():
    names = [path.name for path in sorted(Path("supabase/migrations").glob("*.sql"))]
    assert "030_public_space_weather_events_view.sql" in names
    assert names.index("030_public_space_weather_events_view.sql") == (
        names.index("029_public_atmosphere_events_view.sql") + 1
    )


def test_view_creates_only_space_weather_events_contract():
    sql = migration_sql()
    assert sql.count("create view public.v_space_weather_events") == 1
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


def test_view_matches_atmosphere_public_columns_and_security():
    space_weather = _view_body(migration_sql())
    atmosphere = ATMOSPHERE_CURRENT.read_text(encoding="utf-8").lower()
    atmosphere_view = atmosphere.split("create view public.v_atmosphere_events", 1)[1].split(
        "alter view public.v_atmosphere_events", 1
    )[0]
    assert _public_columns(space_weather) == _public_columns(atmosphere_view)
    assert _public_columns(space_weather) == [
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
    assert "with (security_invoker = true)" in space_weather
    sql = migration_sql()
    assert "alter view public.v_space_weather_events owner to postgres" in sql
    assert (
        "revoke all on public.v_space_weather_events from public, anon, authenticated, service_role"
        in sql
    )
    assert "grant select on public.v_space_weather_events to service_role" in sql
    assert "grant usage on schema knowledge to service_role" in sql
    assert "to anon" not in sql.replace("from public, anon, authenticated, service_role", "")
    assert "to authenticated" not in sql.replace(
        "from public, anon, authenticated, service_role", ""
    )
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql


def test_view_includes_space_weather_catalog_record_only():
    where = _view_body(migration_sql()).split("where", 1)[1]
    assert "scientific_area = 'space_weather'" in where
    assert "event_status = 'catalog_record'" in where
    assert "publication_approved" in where
    assert "scientific_area = 'astronomy'" not in where
    assert "climate_science" not in where
    assert "atmospheric_science" not in where
    assert "oceanography" not in where
    assert "observed_fact" not in where
    assert "forecast" not in where
    assert "official_alert" not in where
    assert "model_projection" not in where
    assert "source in" not in where
    assert "source =" not in where
    assert "donki" not in where


def test_view_comment_preserves_catalog_record_without_earth_impact():
    sql = migration_sql()
    assert "catalog_record is an approved nasa donki activity record" in sql
    assert "does not confirm terrestrial impact" in sql
    assert "excludes astronomy" in sql


def test_view_does_not_change_collectors_or_eligibility():
    sql = migration_sql()
    assert "is_signal_eligible_for_persistence" not in sql
    assert "operational_sources" not in sql
    assert "donki" in OPERATIONAL_SOURCES
    assert EventStatus.CATALOG_RECORD.value == "catalog_record"
    assert EventStatus.OBSERVED_FACT.value == "observed_fact"
    assert EventStatus.FORECAST.value == "forecast"
    assert EventStatus.OFFICIAL_ALERT.value == "official_alert"
    assert EventStatus.MODEL_PROJECTION.value == "model_projection"
    assert DonkiCollector.__name__ == "DonkiCollector"


def test_030_does_not_rewrite_frozen_prior_migrations():
    climate = hashlib.sha256(CLIMATE_CURRENT.read_bytes()).hexdigest()
    ocean = hashlib.sha256(OCEAN_CURRENT.read_bytes()).hexdigest()
    atmosphere = hashlib.sha256(ATMOSPHERE_CURRENT.read_bytes()).hexdigest()
    assert climate == "793c760dd4ae311731790771a6d09c9b830f2999dd25e25da4cf16c2450d1e1d"
    assert ocean == "aa2fe7d0d7f4a3b1bb8e55ec01a7908b47e6e7b787d70aa80480298644f57c42"
    assert atmosphere == "ffef32801f6da53261ca5127a7e9a1a6c3c1dcb20be1e21ee96876c6ef8bb92d"


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
