from pathlib import Path
import re


MIGRATION = Path("supabase/migrations/040_precip_signal_v1.sql")


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_migration_creates_exactly_nine_precipitation_tables():
    text = sql()
    tables = re.findall(
        r"create table\s+(?:if not exists\s+)?((?:raw|knowledge)\.precip_[a-z_]+)",
        text,
    )
    assert tables == [
        "knowledge.precip_regions",
        "raw.precip_forecast_artifacts",
        "raw.precip_observation_artifacts",
        "knowledge.precip_forecasts",
        "knowledge.precip_observation_granules",
        "knowledge.precip_event_groups",
        "knowledge.precip_event_forecasts",
        "knowledge.precip_verification_expectations",
        "knowledge.precip_verification_summaries",
    ]
    assert "precip_pipeline_runs" not in text
    assert "precip_fetch_runs" not in text
    assert "precip_verification_cells" not in text


def test_identity_constraints_and_frozen_semantics_are_in_schema():
    text = sql()
    assert "unique (region_id, model, run_time, valid_from, valid_to, threshold_mm)" in text
    assert "unique (region_id, valid_from, valid_to, threshold_mm)" in text
    assert "threshold_operator = '>'" in text
    assert "decision_probability = 0.50" in text
    assert "decision_operator = '>='" in text
    assert "valid_to - valid_from = interval '24 hours'" in text
    assert "lead_hours between 0 and 240" in text
    assert "grid_resolution_deg = 0.25" in text
    assert "v_valid_to + interval '4 hours'" in text
    assert "v_valid_to + interval '8 hours'" in text
    assert "pipeline_run_id, model" not in text


def test_verification_expectations_are_forecast_scoped():
    text = sql()
    table = text.split(
        "create table knowledge.precip_verification_expectations (", 1
    )[1].split(");", 1)[0]
    assert "forecast_id         uuid not null unique" in table
    assert "references knowledge.precip_forecasts(id) on delete restrict" in table
    assert "event_group_id" not in table
    assert "on conflict (forecast_id) do nothing" in text


def test_verification_summaries_are_forecast_scoped():
    text = sql()
    table = text.split(
        "create table knowledge.precip_verification_summaries (", 1
    )[1].split(");", 1)[0]
    assert "forecast_id                     uuid not null" in table
    assert "references knowledge.precip_forecasts(id) on delete restrict" in table
    assert "unique (forecast_id, observation_granule_id)" in table
    assert "unique (event_group_id, observation_granule_id)" not in table
    assert "on conflict (forecast_id, observation_granule_id) do nothing" in text
    assert "precipitation forecast does not belong to event group" in text
    assert "where expectations.forecast_id = v_forecast_id" in text


def test_observation_versions_are_distinct_columns():
    text = sql()
    for column in (
        "filename_version",
        "internal_product_version",
        "algorithm_version",
        "revision",
        "generation_time",
        "available_at",
        "retrieved_at",
        "variable_name",
        "units",
        "fill_value",
        "source_grid",
    ):
        assert column in text
    assert "filename version such as v07c; distinct from internal_product_version such as 07b" in text


def test_all_tables_have_rls_and_no_direct_client_policy():
    text = sql()
    assert text.count(" enable row level security;") == 9
    assert "create policy" not in text


def test_rpc_security_and_transaction_contract():
    text = sql()
    for rpc in (
        "persist_precip_forecast_batch",
        "persist_precip_observation_granule",
        "persist_precip_verification",
    ):
        assert f"create function public.{rpc}" in text
        assert f"revoke all on function public.{rpc}" in text
        assert f"grant execute on function public.{rpc}" in text
    assert text.count("security definer") == 3
    assert text.count("set search_path = pg_catalog") == 3
    assert "on conflict" in text
    assert text.startswith("-- 040_precip_signal_v1.sql")
    assert "begin;" in text and text.rstrip().endswith("commit;")


def test_required_indexes_are_present():
    text = sql()
    for expression in (
        "precip_forecasts(region_id, valid_from, valid_to)",
        "precip_forecasts(run_time desc)",
        "precip_event_groups(region_id, valid_from desc)",
        "precip_verification_expectations(state, expected_at)",
        "precip_verification_expectations(state, expires_at)",
        "precip_verification_summaries(event_group_id, verification_generated_at desc)",
        "precip_observation_granules(product, revision, granule_start desc)",
    ):
        assert expression in text
