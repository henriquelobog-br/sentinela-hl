create or replace view public.v_climate_events_monitoring
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
where scientific_area = 'climate_science'
  and event_status in ('forecast', 'official_alert');

alter view public.v_climate_events_monitoring owner to postgres;
revoke all on public.v_climate_events_monitoring from public, anon, authenticated, service_role;
grant select on public.v_climate_events_monitoring to service_role;

comment on view public.v_climate_events_monitoring is
    'Authenticated server-side climate monitoring feed. Includes forecast and official_alert climate_science events regardless of publication approval; excludes model_projection; direct browser roles have no access.';
