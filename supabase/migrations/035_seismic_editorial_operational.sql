-- 035_seismic_editorial_operational.sql
-- Narrow service-role RPC boundary for hourly Seismic Editorial v1 persistence
-- and an explicit, non-scheduled backfill reader.

create or replace function public.persist_seismic_editorial_batch(
    p_records jsonb
)
returns table (
    item_index integer,
    event_id uuid,
    disposition text
)
language plpgsql
security definer
set search_path = pg_catalog, pg_temp
as $$
declare
    v_item jsonb;
    v_index integer;
    v_event_id uuid;
    v_editorial_version text;
    v_locale text;
    v_editorial_title text;
    v_editorial_subtitle text;
    v_editorial_summary text;
    v_seo_title text;
    v_seo_description text;
    v_seo_keywords text[];
    v_input_facts_signature text;
    v_generated_at timestamptz;
    v_existing editorial.seismic_contents%rowtype;
    v_disposition text;
begin
    if p_records is null or jsonb_typeof(p_records) <> 'array' then
        raise exception 'p_records must be a JSON array' using errcode = '22023';
    end if;

    for v_item, v_index in
        select value, (ordinality - 1)::integer
        from jsonb_array_elements(p_records) with ordinality
    loop
        if jsonb_typeof(v_item) <> 'object' then
            raise exception 'record % must be a JSON object', v_index using errcode = '22023';
        end if;
        if jsonb_typeof(coalesce(v_item->'seo_keywords', 'null'::jsonb)) <> 'array' then
            raise exception 'record % seo_keywords must be an array', v_index using errcode = '22023';
        end if;

        v_event_id := (v_item->>'event_id')::uuid;
        v_editorial_version := btrim(v_item->>'editorial_version');
        v_locale := btrim(v_item->>'locale');
        v_editorial_title := v_item->>'editorial_title';
        v_editorial_subtitle := v_item->>'editorial_subtitle';
        v_editorial_summary := v_item->>'editorial_summary';
        v_seo_title := v_item->>'seo_title';
        v_seo_description := v_item->>'seo_description';
        select coalesce(array_agg(keyword order by ordinality), '{}'::text[])
          into v_seo_keywords
          from jsonb_array_elements_text(v_item->'seo_keywords')
               with ordinality as keywords(keyword, ordinality);
        v_input_facts_signature := v_item->>'input_facts_signature';
        v_generated_at := (v_item->>'generated_at')::timestamptz;

        if v_editorial_version is null or v_editorial_version = ''
           or v_locale is null or v_locale = ''
           or v_editorial_title is null
           or v_editorial_subtitle is null
           or v_editorial_summary is null
           or v_seo_title is null
           or v_seo_description is null
           or v_input_facts_signature is null
           or v_input_facts_signature !~ '^[0-9a-f]{64}$'
           or v_generated_at is null then
            raise exception 'record % violates seismic editorial contract', v_index
                using errcode = '22023';
        end if;

        select esc.*
          into v_existing
          from editorial.seismic_contents as esc
         where esc.event_id = v_event_id
           and esc.editorial_version = v_editorial_version
           and esc.locale = v_locale
         for update;

        if not found then
            insert into editorial.seismic_contents (
                event_id,
                editorial_version,
                locale,
                editorial_title,
                editorial_subtitle,
                editorial_summary,
                seo_title,
                seo_description,
                seo_keywords,
                input_facts_signature,
                generated_at
            ) values (
                v_event_id,
                v_editorial_version,
                v_locale,
                v_editorial_title,
                v_editorial_subtitle,
                v_editorial_summary,
                v_seo_title,
                v_seo_description,
                v_seo_keywords,
                v_input_facts_signature,
                v_generated_at
            );
            v_disposition := 'inserted';
        elsif v_existing.input_facts_signature is distinct from v_input_facts_signature
           or v_existing.editorial_title is distinct from v_editorial_title
           or v_existing.editorial_subtitle is distinct from v_editorial_subtitle
           or v_existing.editorial_summary is distinct from v_editorial_summary
           or v_existing.seo_title is distinct from v_seo_title
           or v_existing.seo_description is distinct from v_seo_description
           or v_existing.seo_keywords is distinct from v_seo_keywords then
            update editorial.seismic_contents as esc
               set editorial_title = v_editorial_title,
                   editorial_subtitle = v_editorial_subtitle,
                   editorial_summary = v_editorial_summary,
                   seo_title = v_seo_title,
                   seo_description = v_seo_description,
                   seo_keywords = v_seo_keywords,
                   input_facts_signature = v_input_facts_signature,
                   generated_at = v_generated_at
             where esc.id = v_existing.id;
            v_disposition := 'updated';
        else
            v_disposition := 'unchanged';
        end if;

        item_index := v_index;
        event_id := v_event_id;
        disposition := v_disposition;
        return next;
    end loop;
end;
$$;

revoke all on function public.persist_seismic_editorial_batch(jsonb)
from public, anon, authenticated;
grant execute on function public.persist_seismic_editorial_batch(jsonb)
to service_role;

drop function if exists public.list_seismic_editorial_events(integer, integer);

create or replace function public.list_seismic_editorial_events(
    p_limit integer default 250
)
returns table (
    id uuid,
    primary_claim_id uuid,
    title text,
    summary text,
    epistemic_status public.epistemic_status,
    event_status text,
    confidence_score numeric,
    category text,
    source text,
    supporting_sources text[],
    country text,
    scientific_area text,
    entities jsonb,
    keywords text[],
    evidence jsonb,
    occurred_at timestamptz,
    pipeline_status public.pipeline_status,
    requires_human_review boolean,
    review_decision public.review_decision,
    validated_by text,
    validated_at timestamptz
)
language plpgsql
stable
security definer
set search_path = pg_catalog, pg_temp
as $$
begin
    if p_limit is null or p_limit < 1 or p_limit > 1000 then
        raise exception 'p_limit must be between 1 and 1000'
            using errcode = '22023';
    end if;

    return query
    select
        e.id,
        e.primary_claim_id,
        e.title,
        e.summary,
        e.epistemic_status,
        e.event_status,
        e.confidence_score,
        e.category,
        e.source,
        e.supporting_sources,
        e.country,
        e.scientific_area,
        e.entities,
        e.keywords,
        e.evidence,
        e.occurred_at,
        e.pipeline_status,
        e.requires_human_review,
        e.review_decision,
        e.validated_by,
        e.validated_at
    from knowledge.events as e
    where e.source = 'USGS'
      and e.category = 'earthquake_detected'
      and e.scientific_area = 'seismology'
      and not exists (
          select 1
          from editorial.seismic_contents as esc
          where esc.event_id = e.id
            and esc.editorial_version = 'seismic-v1'
            and esc.locale = 'pt-BR'
      )
    order by e.occurred_at desc nulls last, e.id
    limit p_limit;
end;
$$;

revoke all on function public.list_seismic_editorial_events(integer)
from public, anon, authenticated;
grant execute on function public.list_seismic_editorial_events(integer)
to service_role;

comment on function public.list_seismic_editorial_events(integer) is
    'Service-role-only pending reader used solely by explicit Seismic Editorial backfill.';
