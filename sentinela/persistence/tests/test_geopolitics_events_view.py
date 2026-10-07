from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sentinela.cli.generate_real_signals import OPERATIONAL_SOURCES
from sentinela.core.models import EventStatus
from sentinela.real_signals.acled import AcledCollector
from sentinela.real_signals.volcano_geopolitics import GdeltCollector


MIGRATION = Path("supabase/migrations/031_public_geopolitics_events_view.sql")
SPACE_WEATHER_CURRENT = Path("supabase/migrations/030_public_space_weather_events_view.sql")
ATMOSPHERE_CURRENT = Path("supabase/migrations/029_public_atmosphere_events_view.sql")
OCEAN_CURRENT = Path("supabase/migrations/028_public_ocean_events_view.sql")


def migration_text() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def migration_sql() -> str:
    return migration_text().lower()


def _view_body(sql: str) -> str:
    start = sql.index("create view public.v_geopolitics_events")
    return sql[start : sql.index("alter view public.v_geopolitics_events", start)]


def _public_columns(select_sql: str) -> list[str]:
    select = select_sql.split("select", 1)[1].split("from knowledge.events", 1)[0]
    return [line.strip(" ,") for line in select.splitlines() if line.strip(" ,")]


def test_031_exists_after_030():
    names = [path.name for path in sorted(Path("supabase/migrations").glob("*.sql"))]
    assert "031_public_geopolitics_events_view.sql" in names
    assert names.index("031_public_geopolitics_events_view.sql") == (
        names.index("030_public_space_weather_events_view.sql") + 1
    )


def test_view_creates_only_geopolitics_events_contract():
    sql = migration_sql()
    assert sql.count("create view public.v_geopolitics_events") == 1
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


def test_view_matches_prior_public_columns_and_security():
    geopolitics = _view_body(migration_sql())
    space_weather = SPACE_WEATHER_CURRENT.read_text(encoding="utf-8").lower()
    prior_view = space_weather.split("create view public.v_space_weather_events", 1)[1].split(
        "alter view public.v_space_weather_events", 1
    )[0]
    assert _public_columns(geopolitics) == _public_columns(prior_view)
    assert _public_columns(geopolitics) == [
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
    assert "with (security_invoker = true)" in geopolitics
    sql = migration_sql()
    assert "alter view public.v_geopolitics_events owner to postgres" in sql
    assert (
        "revoke all on public.v_geopolitics_events from public, anon, authenticated, service_role"
        in sql
    )
    assert "grant select on public.v_geopolitics_events to service_role" in sql
    assert "grant usage on schema knowledge to service_role" in sql
    assert "to anon" not in sql.replace("from public, anon, authenticated, service_role", "")
    assert "to authenticated" not in sql.replace(
        "from public, anon, authenticated, service_role", ""
    )
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "grant truncate" not in sql
    assert "grant references" not in sql
    assert "grant trigger" not in sql


def test_view_includes_scientific_geopolitics_reported_event_only():
    where = _view_body(migration_sql()).split("where", 1)[1]
    assert "scientific_area = 'scientific_geopolitics'" in where
    assert "event_status = 'reported_event'" in where
    assert "publication_approved" in where
    assert "scientific_area = 'geopolitics'" not in where
    assert "climate_science" not in where
    assert "atmospheric_science" not in where
    assert "oceanography" not in where
    assert "space_weather" not in where
    assert "observed_fact" not in where
    assert "forecast" not in where
    assert "official_alert" not in where
    assert "catalog_record" not in where
    assert "model_projection" not in where


def test_view_has_no_source_or_category_allowlist():
    where = _view_body(migration_sql()).split("where", 1)[1]
    assert "source in" not in where
    assert "source =" not in where
    assert "category in" not in where
    assert "category =" not in where
    assert "gdelt" not in where
    assert "acled" not in where


def test_view_preserves_reported_provider_semantics():
    sql = migration_sql()
    assert "preserve provider provenance" in sql
    assert "do not constitute independent confirmation" in sql
    assert "official alerts" in sql
    assert "forecasts" in sql


def test_view_does_not_change_collectors_or_eligibility():
    sql = migration_sql()
    assert "is_signal_eligible_for_persistence" not in sql
    assert "operational_sources" not in sql
    assert "gdelt" in OPERATIONAL_SOURCES
    assert "acled" in OPERATIONAL_SOURCES
    assert EventStatus.REPORTED_EVENT.value == "reported_event"
    assert EventStatus.OBSERVED_FACT.value == "observed_fact"
    assert EventStatus.FORECAST.value == "forecast"
    assert EventStatus.OFFICIAL_ALERT.value == "official_alert"
    assert EventStatus.CATALOG_RECORD.value == "catalog_record"
    assert EventStatus.MODEL_PROJECTION.value == "model_projection"
    assert GdeltCollector.__name__ == "GdeltCollector"
    assert AcledCollector.__name__ == "AcledCollector"


def test_031_does_not_rewrite_frozen_prior_migrations():
    ocean = hashlib.sha256(OCEAN_CURRENT.read_bytes()).hexdigest()
    atmosphere = hashlib.sha256(ATMOSPHERE_CURRENT.read_bytes()).hexdigest()
    space_weather = hashlib.sha256(SPACE_WEATHER_CURRENT.read_bytes()).hexdigest()
    assert ocean == "aa2fe7d0d7f4a3b1bb8e55ec01a7908b47e6e7b787d70aa80480298644f57c42"
    assert atmosphere == "ffef32801f6da53261ca5127a7e9a1a6c3c1dcb20be1e21ee96876c6ef8bb92d"
    assert space_weather == "408314f31d91c739c33ffad9364d747de0d9ef4b4546932935d37b748803c0d2"


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
