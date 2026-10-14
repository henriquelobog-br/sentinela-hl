from __future__ import annotations

from pathlib import Path


MIGRATION = Path("supabase/migrations/037_climate_authenticated_monitoring_view.sql")
PUBLIC_VIEW = Path("supabase/migrations/027_public_climate_events_view.sql")


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def normalized() -> str:
    return " ".join(migration_sql().lower().split())


def test_037_is_next_free_migration_after_036():
    names = [path.name for path in sorted(Path("supabase/migrations").glob("*.sql"))]
    assert "037_climate_authenticated_monitoring_view.sql" in names
    assert names.index("037_climate_authenticated_monitoring_view.sql") == (
        names.index("036_seismic_authenticated_monitoring_views.sql") + 1
    )


def test_monitoring_view_security_contract():
    sql = normalized()
    assert "create or replace view public.v_climate_events_monitoring" in sql
    assert "with (security_invoker = true)" in sql
    assert "alter view public.v_climate_events_monitoring owner to postgres" in sql
    assert (
        "revoke all on public.v_climate_events_monitoring from public, anon, authenticated, service_role"
        in sql
    )
    assert "grant select on public.v_climate_events_monitoring to service_role" in sql
    assert "to anon" not in sql.replace(
        "from public, anon, authenticated, service_role", ""
    )
    assert "to authenticated" not in sql.replace(
        "from public, anon, authenticated, service_role", ""
    )
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "create function" not in sql
    assert "create policy" not in sql
    assert "pg_cron" not in sql
    assert "cron.schedule" not in sql


def test_monitoring_view_includes_unapproved_operational_climate_only():
    sql = normalized()
    view_body = sql.split(
        "create or replace view public.v_climate_events_monitoring", 1
    )[1].split("alter view public.v_climate_events_monitoring", 1)[0]
    assert "scientific_area = 'climate_science'" in sql
    assert "event_status in ('forecast', 'official_alert')" in sql
    assert "publication_approved" not in view_body
    assert "model_projection" not in view_body
    assert "excludes model_projection" in sql
    assert "regardless of publication approval" in sql
    assert "v_climate_events " not in sql.replace("v_climate_events_monitoring", "")


def test_public_climate_view_remains_publication_gated():
    public_sql = PUBLIC_VIEW.read_text(encoding="utf-8").lower()
    assert "create view public.v_climate_events" in public_sql
    assert "publication_approved" in public_sql
    assert "v_climate_events_monitoring" not in public_sql
