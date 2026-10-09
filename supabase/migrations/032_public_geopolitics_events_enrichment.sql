-- Geopolitics V1 public enrichment.
--
-- Evolves public.v_geopolitics_events without changing the frozen
-- 031 migration. Existing 11 columns remain first and unchanged.
--
-- Enrichment is derived only from knowledge.events.evidence[0].
-- Missing or malformed source fields resolve to NULL.
-- reported_fatalities is source-reported evidence, not an
-- independently confirmed SentinelaHub fatality count.
--
-- No cross-source merge.
-- No source allowlist.
-- No automatic publication.
-- entities JSONB remains outside the public view contract.

-- 031_public_geopolitics_events_view.sql
-- Interface read-only minima para Events canonicos de scientific_geopolitics.
-- reported_event: registro aprovado reportado pelo provider, sem confirmacao
-- independente, alerta oficial ou previsao pelo Sentinela.

CREATE OR REPLACE VIEW public.v_geopolitics_events
with (security_invoker = true)
as
select
    id,
    title,
    summary,
    category,
    source,
    event_status,
    country,
    scientific_area,
    evidence,
    occurred_at,
    validated_at,
    NULLIF(BTRIM(evidence #>> '{0,region}'), '') AS region,
    NULLIF(BTRIM(evidence #>> '{0,actor1}'), '') AS actor1,
    NULLIF(BTRIM(evidence #>> '{0,actor2}'), '') AS actor2,
    NULLIF(BTRIM(evidence #>> '{0,location}'), '') AS location,
    CASE
      WHEN char_length((evidence #>> '{0,latitude}')) <= 32
       AND (evidence #>> '{0,latitude}') ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)$'
      THEN
        CASE
          WHEN (evidence #>> '{0,latitude}')::double precision BETWEEN -90 AND 90
          THEN (evidence #>> '{0,latitude}')::double precision
          ELSE NULL
        END
      ELSE NULL
    END AS latitude,
    CASE
      WHEN char_length((evidence #>> '{0,longitude}')) <= 32
       AND (evidence #>> '{0,longitude}') ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)$'
      THEN
        CASE
          WHEN (evidence #>> '{0,longitude}')::double precision BETWEEN -180 AND 180
          THEN (evidence #>> '{0,longitude}')::double precision
          ELSE NULL
        END
      ELSE NULL
    END AS longitude,
    CASE
        WHEN NULLIF(BTRIM(evidence #>> '{0,fatalities}'), '')
             ~ '^[0-9]+$'
         AND LENGTH(BTRIM(evidence #>> '{0,fatalities}')) <= 18
        THEN (evidence #>> '{0,fatalities}')::bigint
        ELSE NULL
    END AS reported_fatalities

from knowledge.events
where scientific_area = 'scientific_geopolitics'
  and event_status = 'reported_event'
  and publication_approved;

alter view public.v_geopolitics_events owner to postgres;

-- public tem default privileges legados; remova-os antes do grant minimo.
revoke all on public.v_geopolitics_events from public, anon, authenticated, service_role;

-- security_invoker exige acesso ao objeto subjacente. knowledge nao esta
-- exposto pela Data API, e a service_role recebe somente as colunas da view.
grant usage on schema knowledge to service_role;
grant select (
    id,
    title,
    summary,
    category,
    source,
    event_status,
    country,
    scientific_area,
    evidence,
    occurred_at,
    validated_at,
    publication_approved
) on knowledge.events to service_role;

grant select on public.v_geopolitics_events to service_role;

comment on view public.v_geopolitics_events is
    'Read-only server-side view of approved scientific_geopolitics reported_event Events. Records preserve provider provenance and do not constitute independent confirmation, official alerts, or forecasts by SentinelaHub.';
