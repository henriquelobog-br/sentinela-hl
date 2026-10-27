-- 040_precip_signal_v1.sql
-- Precipitation forecast, IMERG observation, and verification persistence V1.
-- Scientific identity excludes operational pipeline/fetch execution identity.

begin;

create table knowledge.precip_regions (
    id                  uuid primary key default gen_random_uuid(),
    region_key          text not null unique
        check (length(btrim(region_key)) between 1 and 160),
    name                text not null
        check (length(btrim(name)) between 1 and 240),
    roi_geojson         jsonb not null
        check (jsonb_typeof(roi_geojson) = 'object'),
    roi_sha256          text not null
        check (roi_sha256 ~ '^[0-9a-f]{64}$'),
    min_lat             double precision not null check (min_lat >= -60 and min_lat <= 60),
    max_lat             double precision not null check (max_lat >= -60 and max_lat <= 60),
    min_lon             double precision not null check (min_lon >= -180 and min_lon <= 180),
    max_lon             double precision not null check (max_lon >= -180 and max_lon <= 180),
    created_at          timestamptz not null default now(),
    check (max_lat > min_lat),
    check (max_lon > min_lon)
);

create table raw.precip_forecast_artifacts (
    id                  uuid primary key default gen_random_uuid(),
    pipeline_run_id     uuid not null references raw.pipeline_runs(id) on delete restrict,
    fetch_run_id        uuid references raw.fetch_runs(id) on delete restrict,
    artifact_sha256     text not null unique
        check (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    source_uri          text not null check (length(btrim(source_uri)) > 0),
    media_type          text not null check (length(btrim(media_type)) > 0),
    retrieved_at        timestamptz not null,
    metadata            jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object'),
    created_at          timestamptz not null default now()
);

create table raw.precip_observation_artifacts (
    id                  uuid primary key default gen_random_uuid(),
    pipeline_run_id     uuid not null references raw.pipeline_runs(id) on delete restrict,
    fetch_run_id        uuid references raw.fetch_runs(id) on delete restrict,
    artifact_sha256     text not null unique
        check (artifact_sha256 ~ '^[0-9a-f]{64}$'),
    source_uri          text not null check (length(btrim(source_uri)) > 0),
    media_type          text not null check (length(btrim(media_type)) > 0),
    retrieved_at        timestamptz not null,
    metadata            jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object'),
    created_at          timestamptz not null default now()
);

create table knowledge.precip_forecasts (
    id                       uuid primary key default gen_random_uuid(),
    pipeline_run_id          uuid not null references raw.pipeline_runs(id) on delete restrict,
    forecast_artifact_id     uuid not null
        references raw.precip_forecast_artifacts(id) on delete restrict,
    region_id                uuid not null
        references knowledge.precip_regions(id) on delete restrict,
    model                    text not null check (length(btrim(model)) > 0),
    run_time                 timestamptz not null,
    valid_from               timestamptz not null,
    valid_to                 timestamptz not null,
    threshold_mm             numeric not null
        check (threshold_mm in (1, 5, 10, 20, 25, 50, 100)),
    threshold_operator       text not null default '>' check (threshold_operator = '>'),
    probability              numeric not null check (probability >= 0 and probability <= 1),
    decision_probability     numeric not null default 0.50
        check (decision_probability = 0.50),
    decision_operator        text not null default '>=' check (decision_operator = '>='),
    lead_hours               integer not null check (lead_hours between 0 and 240),
    grid_resolution_deg      numeric not null default 0.25
        check (grid_resolution_deg = 0.25),
    grid_sha256              text not null check (grid_sha256 ~ '^[0-9a-f]{64}$'),
    forecast_field_sha256    text not null check (forecast_field_sha256 ~ '^[0-9a-f]{64}$'),
    provenance               jsonb not null default '{}'::jsonb
        check (jsonb_typeof(provenance) = 'object'),
    created_at               timestamptz not null default now(),
    unique (region_id, model, run_time, valid_from, valid_to, threshold_mm),
    check (valid_to > valid_from),
    check (valid_to - valid_from = interval '24 hours')
);

create table knowledge.precip_observation_granules (
    id                       uuid primary key default gen_random_uuid(),
    pipeline_run_id          uuid not null references raw.pipeline_runs(id) on delete restrict,
    observation_artifact_id  uuid not null
        references raw.precip_observation_artifacts(id) on delete restrict,
    product                  text not null check (length(btrim(product)) > 0),
    source_granule_id        text not null check (length(btrim(source_granule_id)) > 0),
    filename_version         text not null check (length(btrim(filename_version)) > 0),
    internal_product_version text not null check (length(btrim(internal_product_version)) > 0),
    algorithm_version        text not null check (length(btrim(algorithm_version)) > 0),
    revision                 integer not null check (revision >= 0),
    granule_start            timestamptz not null,
    granule_end              timestamptz not null,
    generation_time          timestamptz not null,
    available_at             timestamptz not null,
    retrieved_at             timestamptz not null,
    variable_name            text not null check (length(btrim(variable_name)) > 0),
    units                    text not null check (units = 'mm/h'),
    fill_value               double precision not null,
    source_grid              jsonb not null check (jsonb_typeof(source_grid) = 'object'),
    grid_sha256              text not null check (grid_sha256 ~ '^[0-9a-f]{64}$'),
    field_sha256             text not null check (field_sha256 ~ '^[0-9a-f]{64}$'),
    provenance               jsonb not null default '{}'::jsonb
        check (jsonb_typeof(provenance) = 'object'),
    created_at               timestamptz not null default now(),
    unique (
        product, source_granule_id, filename_version,
        internal_product_version, revision
    ),
    check (granule_end > granule_start),
    check (granule_end - granule_start = interval '30 minutes'),
    check (available_at >= generation_time),
    check (retrieved_at >= available_at)
);

create table knowledge.precip_event_groups (
    id                  uuid primary key default gen_random_uuid(),
    region_id           uuid not null
        references knowledge.precip_regions(id) on delete restrict,
    valid_from          timestamptz not null,
    valid_to            timestamptz not null,
    threshold_mm        numeric not null
        check (threshold_mm in (1, 5, 10, 20, 25, 50, 100)),
    threshold_operator  text not null default '>' check (threshold_operator = '>'),
    created_at          timestamptz not null default now(),
    unique (region_id, valid_from, valid_to, threshold_mm),
    check (valid_to > valid_from),
    check (valid_to - valid_from = interval '24 hours')
);

create table knowledge.precip_event_forecasts (
    event_group_id      uuid not null
        references knowledge.precip_event_groups(id) on delete restrict,
    forecast_id         uuid not null
        references knowledge.precip_forecasts(id) on delete restrict,
    created_at          timestamptz not null default now(),
    primary key (event_group_id, forecast_id),
    unique (forecast_id)
);

create table knowledge.precip_verification_expectations (
    id                  uuid primary key default gen_random_uuid(),
    forecast_id         uuid not null unique
        references knowledge.precip_forecasts(id) on delete restrict,
    state               text not null default 'AWAITING_OBSERVATION'
        check (state in (
            'AWAITING_OBSERVATION', 'PROCESSING', 'EARLY_VERIFIED',
            'EXPIRED_UNVERIFIED', 'EARLY_VERIFIED_LATE', 'FAILED_RETRYABLE'
        )),
    expected_at         timestamptz not null,
    expires_at          timestamptz not null,
    attempt_count       integer not null default 0 check (attempt_count >= 0),
    last_error          text check (char_length(coalesce(last_error, '')) <= 512),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    check (expires_at = expected_at + interval '4 hours')
);

create table knowledge.precip_verification_summaries (
    id                              uuid primary key default gen_random_uuid(),
    pipeline_run_id                 uuid not null references raw.pipeline_runs(id) on delete restrict,
    event_group_id                  uuid not null
        references knowledge.precip_event_groups(id) on delete restrict,
    forecast_id                     uuid not null
        references knowledge.precip_forecasts(id) on delete restrict,
    observation_granule_id          uuid not null
        references knowledge.precip_observation_granules(id) on delete restrict,
    verification_generated_at       timestamptz not null,
    temporal_coverage               numeric not null check (temporal_coverage >= 0 and temporal_coverage <= 1),
    spatial_coverage                numeric not null check (spatial_coverage >= 0 and spatial_coverage <= 1),
    valid_roi_cells_fraction        numeric not null check (valid_roi_cells_fraction >= 0 and valid_roi_cells_fraction <= 1),
    valid_cell_count                integer not null check (valid_cell_count >= 0),
    total_cell_count                integer not null check (total_cell_count > 0),
    valid_area_km2                  double precision not null check (valid_area_km2 >= 0),
    total_area_km2                  double precision not null check (total_area_km2 > 0),
    hit_cell_count                  integer not null check (hit_cell_count >= 0),
    hit_area_km2                    double precision not null check (hit_area_km2 >= 0),
    hit_area_fraction               numeric not null check (hit_area_fraction >= 0 and hit_area_fraction <= 1),
    miss_cell_count                 integer not null check (miss_cell_count >= 0),
    miss_area_km2                   double precision not null check (miss_area_km2 >= 0),
    miss_area_fraction              numeric not null check (miss_area_fraction >= 0 and miss_area_fraction <= 1),
    false_alarm_cell_count          integer not null check (false_alarm_cell_count >= 0),
    false_alarm_area_km2            double precision not null check (false_alarm_area_km2 >= 0),
    false_alarm_area_fraction       numeric not null check (false_alarm_area_fraction >= 0 and false_alarm_area_fraction <= 1),
    correct_negative_cell_count     integer not null check (correct_negative_cell_count >= 0),
    correct_negative_area_km2       double precision not null check (correct_negative_area_km2 >= 0),
    correct_negative_area_fraction  numeric not null check (correct_negative_area_fraction >= 0 and correct_negative_area_fraction <= 1),
    observed_max_mm                 double precision not null,
    observed_area_mean_mm           double precision not null,
    comparison_grid                 jsonb not null check (jsonb_typeof(comparison_grid) = 'object'),
    regrid_algorithm_version        text not null check (length(btrim(regrid_algorithm_version)) > 0),
    regrid_weights_sha256           text not null check (regrid_weights_sha256 ~ '^[0-9a-f]{64}$'),
    cell_result_artifact_sha256     text not null check (cell_result_artifact_sha256 ~ '^[0-9a-f]{64}$'),
    provenance                      jsonb not null check (jsonb_typeof(provenance) = 'object'),
    created_at                      timestamptz not null default now(),
    unique (forecast_id, observation_granule_id),
    check (valid_cell_count <= total_cell_count),
    check (valid_area_km2 <= total_area_km2),
    check (
        hit_cell_count + miss_cell_count + false_alarm_cell_count
            + correct_negative_cell_count = valid_cell_count
    ),
    check (
        abs(
            hit_area_km2 + miss_area_km2 + false_alarm_area_km2
                + correct_negative_area_km2 - valid_area_km2
        ) <= greatest(0.000001, valid_area_km2 * 0.000000001)
    ),
    check (
        abs(
            hit_area_fraction + miss_area_fraction + false_alarm_area_fraction
                + correct_negative_area_fraction - 1
        ) <= 0.000001
    )
);

create index precip_forecasts_region_valid_idx
    on knowledge.precip_forecasts(region_id, valid_from, valid_to);
create index precip_forecasts_run_time_idx
    on knowledge.precip_forecasts(run_time desc);
create index precip_event_groups_region_valid_idx
    on knowledge.precip_event_groups(region_id, valid_from desc);
create index precip_verification_expectations_state_expected_idx
    on knowledge.precip_verification_expectations(state, expected_at);
create index precip_verification_expectations_state_expires_idx
    on knowledge.precip_verification_expectations(state, expires_at);
create index precip_verification_summaries_event_generated_idx
    on knowledge.precip_verification_summaries(event_group_id, verification_generated_at desc);
create index precip_observation_granules_product_revision_start_idx
    on knowledge.precip_observation_granules(product, revision, granule_start desc);

create trigger trg_precip_verification_expectations_updated
    before update on knowledge.precip_verification_expectations
    for each row execute function public.set_updated_at();

alter table raw.precip_forecast_artifacts enable row level security;
alter table raw.precip_observation_artifacts enable row level security;
alter table knowledge.precip_regions enable row level security;
alter table knowledge.precip_forecasts enable row level security;
alter table knowledge.precip_observation_granules enable row level security;
alter table knowledge.precip_event_groups enable row level security;
alter table knowledge.precip_event_forecasts enable row level security;
alter table knowledge.precip_verification_expectations enable row level security;
alter table knowledge.precip_verification_summaries enable row level security;

revoke all on table raw.precip_forecast_artifacts from public, anon, authenticated, service_role;
revoke all on table raw.precip_observation_artifacts from public, anon, authenticated, service_role;
revoke all on table knowledge.precip_regions from public, anon, authenticated, service_role;
revoke all on table knowledge.precip_forecasts from public, anon, authenticated, service_role;
revoke all on table knowledge.precip_observation_granules from public, anon, authenticated, service_role;
revoke all on table knowledge.precip_event_groups from public, anon, authenticated, service_role;
revoke all on table knowledge.precip_event_forecasts from public, anon, authenticated, service_role;
revoke all on table knowledge.precip_verification_expectations from public, anon, authenticated, service_role;
revoke all on table knowledge.precip_verification_summaries from public, anon, authenticated, service_role;

create function public.persist_precip_forecast_batch(
    p_run_id uuid,
    p_items jsonb
)
returns table (
    item_index integer,
    forecast_id uuid,
    event_group_id uuid,
    disposition text
)
language plpgsql
security definer
set search_path = pg_catalog
as $$
#variable_conflict use_column
declare
    v_item jsonb;
    v_region jsonb;
    v_artifact jsonb;
    v_forecast jsonb;
    v_region_id uuid;
    v_artifact_id uuid;
    v_forecast_id uuid;
    v_group_id uuid;
    v_inserted boolean;
    v_fetch_run_id uuid;
    v_valid_from timestamptz;
    v_valid_to timestamptz;
begin
    if p_run_id is null or p_items is null or jsonb_typeof(p_items) <> 'array' then
        raise exception 'invalid precipitation forecast batch';
    end if;
    if not exists (
        select 1 from raw.pipeline_runs as runs
        where runs.id = p_run_id and runs.mode = 'persist'
    ) then
        raise exception 'precipitation persistence requires a persist pipeline run';
    end if;

    item_index := 0;
    for v_item in select value from jsonb_array_elements(p_items)
    loop
        item_index := item_index + 1;
        v_region := v_item -> 'region';
        v_artifact := v_item -> 'artifact';
        v_forecast := v_item -> 'forecast';
        if jsonb_typeof(v_region) <> 'object'
           or jsonb_typeof(v_artifact) <> 'object'
           or jsonb_typeof(v_forecast) <> 'object' then
            raise exception 'invalid precipitation forecast item %', item_index;
        end if;

        insert into knowledge.precip_regions(
            region_key, name, roi_geojson, roi_sha256,
            min_lat, max_lat, min_lon, max_lon
        ) values (
            v_region ->> 'region_key', v_region ->> 'name',
            v_region -> 'roi_geojson', v_region ->> 'roi_sha256',
            (v_region ->> 'min_lat')::double precision,
            (v_region ->> 'max_lat')::double precision,
            (v_region ->> 'min_lon')::double precision,
            (v_region ->> 'max_lon')::double precision
        )
        on conflict (region_key) do nothing
        returning id into v_region_id;

        if v_region_id is null then
            select regions.id into v_region_id
            from knowledge.precip_regions as regions
            where regions.region_key = v_region ->> 'region_key'
              and regions.roi_sha256 = v_region ->> 'roi_sha256';
            if v_region_id is null then
                raise exception 'conflicting precipitation region retry';
            end if;
        end if;

        v_fetch_run_id := nullif(v_artifact ->> 'fetch_run_id', '')::uuid;
        if v_fetch_run_id is not null and not exists (
            select 1 from raw.fetch_runs as fetches
            where fetches.id = v_fetch_run_id
              and fetches.pipeline_run_id = p_run_id
        ) then
            raise exception 'precipitation forecast fetch run mismatch';
        end if;

        insert into raw.precip_forecast_artifacts(
            pipeline_run_id, fetch_run_id, artifact_sha256, source_uri,
            media_type, retrieved_at, metadata
        ) values (
            p_run_id, v_fetch_run_id, v_artifact ->> 'artifact_sha256',
            v_artifact ->> 'source_uri', v_artifact ->> 'media_type',
            (v_artifact ->> 'retrieved_at')::timestamptz,
            coalesce(v_artifact -> 'metadata', '{}'::jsonb)
        )
        on conflict (artifact_sha256) do nothing
        returning id into v_artifact_id;
        if v_artifact_id is null then
            select artifacts.id into v_artifact_id
            from raw.precip_forecast_artifacts as artifacts
            where artifacts.artifact_sha256 = v_artifact ->> 'artifact_sha256';
        end if;

        v_valid_from := (v_forecast ->> 'valid_from')::timestamptz;
        v_valid_to := (v_forecast ->> 'valid_to')::timestamptz;
        v_forecast_id := null;
        insert into knowledge.precip_forecasts(
            pipeline_run_id, forecast_artifact_id, region_id, model, run_time,
            valid_from, valid_to, threshold_mm, probability, lead_hours,
            grid_sha256, forecast_field_sha256, provenance
        ) values (
            p_run_id, v_artifact_id, v_region_id, v_forecast ->> 'model',
            (v_forecast ->> 'run_time')::timestamptz,
            v_valid_from, v_valid_to,
            (v_forecast ->> 'threshold_mm')::numeric,
            (v_forecast ->> 'probability')::numeric,
            (v_forecast ->> 'lead_hours')::integer,
            v_forecast ->> 'grid_sha256',
            v_forecast ->> 'forecast_field_sha256',
            coalesce(v_forecast -> 'provenance', '{}'::jsonb)
        )
        on conflict (region_id, model, run_time, valid_from, valid_to, threshold_mm)
        do nothing
        returning id into v_forecast_id;
        v_inserted := v_forecast_id is not null;

        if not v_inserted then
            select forecasts.id into v_forecast_id
            from knowledge.precip_forecasts as forecasts
            where forecasts.region_id = v_region_id
              and forecasts.model = v_forecast ->> 'model'
              and forecasts.run_time = (v_forecast ->> 'run_time')::timestamptz
              and forecasts.valid_from = v_valid_from
              and forecasts.valid_to = v_valid_to
              and forecasts.threshold_mm = (v_forecast ->> 'threshold_mm')::numeric
              and forecasts.threshold_operator = '>'
              and forecasts.decision_operator = '>='
              and forecasts.decision_probability = 0.50
              and forecasts.probability = (v_forecast ->> 'probability')::numeric
              and forecasts.grid_sha256 = v_forecast ->> 'grid_sha256'
              and forecasts.forecast_field_sha256 = v_forecast ->> 'forecast_field_sha256';
            if v_forecast_id is null then
                raise exception 'conflicting precipitation forecast retry';
            end if;
        end if;

        insert into knowledge.precip_event_groups(
            region_id, valid_from, valid_to, threshold_mm
        ) values (
            v_region_id, v_valid_from, v_valid_to,
            (v_forecast ->> 'threshold_mm')::numeric
        )
        on conflict (region_id, valid_from, valid_to, threshold_mm) do nothing
        returning id into v_group_id;
        if v_group_id is null then
            select groups.id into v_group_id
            from knowledge.precip_event_groups as groups
            where groups.region_id = v_region_id
              and groups.valid_from = v_valid_from
              and groups.valid_to = v_valid_to
              and groups.threshold_mm = (v_forecast ->> 'threshold_mm')::numeric;
        end if;

        insert into knowledge.precip_event_forecasts(event_group_id, forecast_id)
        values (v_group_id, v_forecast_id)
        on conflict on constraint precip_event_forecasts_pkey do nothing;

        insert into knowledge.precip_verification_expectations(
            forecast_id, expected_at, expires_at
        ) values (
            v_forecast_id, v_valid_to + interval '4 hours',
            v_valid_to + interval '8 hours'
        )
        on conflict (forecast_id) do nothing;

        forecast_id := v_forecast_id;
        event_group_id := v_group_id;
        disposition := case when v_inserted then 'inserted' else 'existing' end;
        return next;
    end loop;
end;
$$;

create function public.persist_precip_observation_granule(
    p_run_id uuid,
    p_granule jsonb
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
    v_artifact jsonb;
    v_observation jsonb;
    v_fetch_run_id uuid;
    v_artifact_id uuid;
    v_granule_id uuid;
begin
    if p_run_id is null or p_granule is null or jsonb_typeof(p_granule) <> 'object' then
        raise exception 'invalid precipitation observation granule';
    end if;
    if not exists (
        select 1 from raw.pipeline_runs as runs
        where runs.id = p_run_id and runs.mode = 'persist'
    ) then
        raise exception 'precipitation persistence requires a persist pipeline run';
    end if;
    v_artifact := p_granule -> 'artifact';
    v_observation := p_granule -> 'observation';
    if jsonb_typeof(v_artifact) <> 'object' or jsonb_typeof(v_observation) <> 'object' then
        raise exception 'invalid precipitation observation envelope';
    end if;

    v_fetch_run_id := nullif(v_artifact ->> 'fetch_run_id', '')::uuid;
    if v_fetch_run_id is not null and not exists (
        select 1 from raw.fetch_runs as fetches
        where fetches.id = v_fetch_run_id and fetches.pipeline_run_id = p_run_id
    ) then
        raise exception 'precipitation observation fetch run mismatch';
    end if;

    insert into raw.precip_observation_artifacts(
        pipeline_run_id, fetch_run_id, artifact_sha256, source_uri,
        media_type, retrieved_at, metadata
    ) values (
        p_run_id, v_fetch_run_id, v_artifact ->> 'artifact_sha256',
        v_artifact ->> 'source_uri', v_artifact ->> 'media_type',
        (v_artifact ->> 'retrieved_at')::timestamptz,
        coalesce(v_artifact -> 'metadata', '{}'::jsonb)
    )
    on conflict (artifact_sha256) do nothing
    returning id into v_artifact_id;
    if v_artifact_id is null then
        select artifacts.id into v_artifact_id
        from raw.precip_observation_artifacts as artifacts
        where artifacts.artifact_sha256 = v_artifact ->> 'artifact_sha256';
    end if;

    insert into knowledge.precip_observation_granules(
        pipeline_run_id, observation_artifact_id, product, source_granule_id,
        filename_version, internal_product_version, algorithm_version, revision,
        granule_start, granule_end, generation_time, available_at, retrieved_at,
        variable_name, units, fill_value, source_grid, grid_sha256, field_sha256,
        provenance
    ) values (
        p_run_id, v_artifact_id, v_observation ->> 'product',
        v_observation ->> 'source_granule_id',
        v_observation ->> 'filename_version',
        v_observation ->> 'internal_product_version',
        v_observation ->> 'algorithm_version',
        (v_observation ->> 'revision')::integer,
        (v_observation ->> 'granule_start')::timestamptz,
        (v_observation ->> 'granule_end')::timestamptz,
        (v_observation ->> 'generation_time')::timestamptz,
        (v_observation ->> 'available_at')::timestamptz,
        (v_observation ->> 'retrieved_at')::timestamptz,
        v_observation ->> 'variable_name', v_observation ->> 'units',
        (v_observation ->> 'fill_value')::double precision,
        v_observation -> 'source_grid', v_observation ->> 'grid_sha256',
        v_observation ->> 'field_sha256',
        coalesce(v_observation -> 'provenance', '{}'::jsonb)
    )
    on conflict (
        product, source_granule_id, filename_version,
        internal_product_version, revision
    ) do nothing
    returning id into v_granule_id;

    if v_granule_id is null then
        select granules.id into v_granule_id
        from knowledge.precip_observation_granules as granules
        where granules.product = v_observation ->> 'product'
          and granules.source_granule_id = v_observation ->> 'source_granule_id'
          and granules.filename_version = v_observation ->> 'filename_version'
          and granules.internal_product_version = v_observation ->> 'internal_product_version'
          and granules.revision = (v_observation ->> 'revision')::integer
          and granules.algorithm_version = v_observation ->> 'algorithm_version'
          and granules.granule_start = (v_observation ->> 'granule_start')::timestamptz
          and granules.granule_end = (v_observation ->> 'granule_end')::timestamptz
          and granules.generation_time = (v_observation ->> 'generation_time')::timestamptz
          and granules.available_at = (v_observation ->> 'available_at')::timestamptz
          and granules.retrieved_at = (v_observation ->> 'retrieved_at')::timestamptz
          and granules.variable_name = v_observation ->> 'variable_name'
          and granules.units = v_observation ->> 'units'
          and granules.fill_value = (v_observation ->> 'fill_value')::double precision
          and granules.source_grid = v_observation -> 'source_grid'
          and granules.field_sha256 = v_observation ->> 'field_sha256'
          and granules.grid_sha256 = v_observation ->> 'grid_sha256'
          and granules.provenance = coalesce(v_observation -> 'provenance', '{}'::jsonb);
        if v_granule_id is null then
            raise exception 'conflicting immutable precipitation observation revision';
        end if;
    end if;
    return v_granule_id;
end;
$$;

create function public.persist_precip_verification(
    p_run_id uuid,
    p_verification jsonb
)
returns uuid
language plpgsql
security definer
set search_path = pg_catalog
as $$
declare
    v_summary_id uuid;
    v_existing knowledge.precip_verification_summaries%rowtype;
    v_event_group_id uuid;
    v_forecast_id uuid;
    v_generated_at timestamptz;
    v_inserted boolean;
begin
    if p_run_id is null or p_verification is null
       or jsonb_typeof(p_verification) <> 'object' then
        raise exception 'invalid precipitation verification';
    end if;
    if not exists (
        select 1 from raw.pipeline_runs as runs
        where runs.id = p_run_id and runs.mode = 'persist'
    ) then
        raise exception 'precipitation persistence requires a persist pipeline run';
    end if;
    if (p_verification ->> 'temporal_coverage')::numeric < 0.90
       or (p_verification ->> 'spatial_coverage')::numeric < 0.90
       or (p_verification ->> 'valid_roi_cells_fraction')::numeric < 0.90 then
        raise exception 'insufficient precipitation verification coverage';
    end if;

    v_event_group_id := (p_verification ->> 'event_group_id')::uuid;
    v_forecast_id := (p_verification ->> 'forecast_id')::uuid;
    if v_event_group_id is null or v_forecast_id is null then
        raise exception 'precipitation verification forecast and event group are required';
    end if;
    if not exists (
        select 1
        from knowledge.precip_event_forecasts as event_forecasts
        where event_forecasts.event_group_id = v_event_group_id
          and event_forecasts.forecast_id = v_forecast_id
    ) then
        raise exception 'precipitation forecast does not belong to event group';
    end if;

    v_generated_at := (p_verification ->> 'verification_generated_at')::timestamptz;
    insert into knowledge.precip_verification_summaries(
        pipeline_run_id, event_group_id, forecast_id, observation_granule_id,
        verification_generated_at, temporal_coverage, spatial_coverage,
        valid_roi_cells_fraction, valid_cell_count, total_cell_count,
        valid_area_km2, total_area_km2,
        hit_cell_count, hit_area_km2, hit_area_fraction,
        miss_cell_count, miss_area_km2, miss_area_fraction,
        false_alarm_cell_count, false_alarm_area_km2, false_alarm_area_fraction,
        correct_negative_cell_count, correct_negative_area_km2,
        correct_negative_area_fraction, observed_max_mm, observed_area_mean_mm,
        comparison_grid, regrid_algorithm_version, regrid_weights_sha256,
        cell_result_artifact_sha256, provenance
    ) values (
        p_run_id, v_event_group_id, v_forecast_id,
        (p_verification ->> 'observation_granule_id')::uuid,
        v_generated_at, (p_verification ->> 'temporal_coverage')::numeric,
        (p_verification ->> 'spatial_coverage')::numeric,
        (p_verification ->> 'valid_roi_cells_fraction')::numeric,
        (p_verification ->> 'valid_cell_count')::integer,
        (p_verification ->> 'total_cell_count')::integer,
        (p_verification ->> 'valid_area_km2')::double precision,
        (p_verification ->> 'total_area_km2')::double precision,
        (p_verification ->> 'hit_cell_count')::integer,
        (p_verification ->> 'hit_area_km2')::double precision,
        (p_verification ->> 'hit_area_fraction')::numeric,
        (p_verification ->> 'miss_cell_count')::integer,
        (p_verification ->> 'miss_area_km2')::double precision,
        (p_verification ->> 'miss_area_fraction')::numeric,
        (p_verification ->> 'false_alarm_cell_count')::integer,
        (p_verification ->> 'false_alarm_area_km2')::double precision,
        (p_verification ->> 'false_alarm_area_fraction')::numeric,
        (p_verification ->> 'correct_negative_cell_count')::integer,
        (p_verification ->> 'correct_negative_area_km2')::double precision,
        (p_verification ->> 'correct_negative_area_fraction')::numeric,
        (p_verification ->> 'observed_max_mm')::double precision,
        (p_verification ->> 'observed_area_mean_mm')::double precision,
        p_verification -> 'comparison_grid',
        p_verification ->> 'regrid_algorithm_version',
        p_verification ->> 'regrid_weights_sha256',
        p_verification ->> 'cell_result_artifact_sha256',
        p_verification -> 'provenance'
    )
    on conflict (forecast_id, observation_granule_id) do nothing
    returning id into v_summary_id;
    v_inserted := v_summary_id is not null;

    if v_summary_id is null then
        select summaries.* into v_existing
        from knowledge.precip_verification_summaries as summaries
        where summaries.forecast_id = v_forecast_id
          and summaries.observation_granule_id = (p_verification ->> 'observation_granule_id')::uuid;
        if v_existing.cell_result_artifact_sha256
               is distinct from p_verification ->> 'cell_result_artifact_sha256'
           or v_existing.regrid_weights_sha256
               is distinct from p_verification ->> 'regrid_weights_sha256'
           or v_existing.provenance is distinct from p_verification -> 'provenance' then
            raise exception 'conflicting immutable precipitation verification retry';
        end if;
        v_summary_id := v_existing.id;
    end if;

    if v_inserted then
        if not exists (
            select 1
            from knowledge.precip_verification_expectations as expectations
            where expectations.forecast_id = v_forecast_id
        ) then
            raise exception 'precipitation verification expectation not found';
        end if;
        update knowledge.precip_verification_expectations as expectations
        set state = case
                when v_generated_at <= expectations.expected_at then 'EARLY_VERIFIED'
                else 'EARLY_VERIFIED_LATE'
            end,
            attempt_count = expectations.attempt_count + 1,
            last_error = null
        where expectations.forecast_id = v_forecast_id;
    end if;

    return v_summary_id;
end;
$$;

revoke all on function public.persist_precip_forecast_batch(uuid, jsonb)
    from public, anon, authenticated;
revoke all on function public.persist_precip_observation_granule(uuid, jsonb)
    from public, anon, authenticated;
revoke all on function public.persist_precip_verification(uuid, jsonb)
    from public, anon, authenticated;

grant execute on function public.persist_precip_forecast_batch(uuid, jsonb)
    to service_role;
grant execute on function public.persist_precip_observation_granule(uuid, jsonb)
    to service_role;
grant execute on function public.persist_precip_verification(uuid, jsonb)
    to service_role;

comment on column knowledge.precip_forecasts.pipeline_run_id is
    'Operational provenance only; excluded from precipitation scientific identity.';
comment on column knowledge.precip_observation_granules.filename_version is
    'Filename version such as V07C; distinct from internal_product_version such as 07B.';
comment on table knowledge.precip_verification_summaries is
    'Immutable aggregate verification per observation revision; individual cells remain external artifacts.';

notify pgrst, 'reload schema';

commit;
