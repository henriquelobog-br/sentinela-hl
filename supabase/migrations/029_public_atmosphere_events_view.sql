-- 029_public_atmosphere_events_view.sql
-- Interface read-only minima para Events canonicos de atmospheric_science.
-- observed_fact: fato/resultado observacional ou de reanalise aprovado.
-- forecast: previsao aprovada.
-- catalog_record: disponibilidade de produto/granule, nao confirmacao de fenomeno.

create view public.v_atmosphere_events
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
    validated_at
from knowledge.events
where scientific_area = 'atmospheric_science'
  and event_status in ('observed_fact', 'forecast', 'catalog_record')
  and publication_approved;

alter view public.v_atmosphere_events owner to postgres;

-- public tem default privileges legados; remova-os antes do grant minimo.
revoke all on public.v_atmosphere_events from public, anon, authenticated, service_role;

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

grant select on public.v_atmosphere_events to service_role;

comment on view public.v_atmosphere_events is
    'Read-only server-side view of canonical operational atmospheric_science Events (observed_fact, forecast, and catalog_record). observed_fact is an approved observational or reanalysis result; forecast is an approved forecast; catalog_record is approved satellite product/granule availability and does not confirm an atmospheric phenomenon. Excludes model_projection and official_alert.';
