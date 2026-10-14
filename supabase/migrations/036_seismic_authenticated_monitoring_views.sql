create or replace view public.v_seismic_events_monitoring
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
where scientific_area = 'seismology'
  and category = 'earthquake_detected';

alter view public.v_seismic_events_monitoring owner to postgres;
revoke all on public.v_seismic_events_monitoring from public, anon, authenticated, service_role;
grant select on public.v_seismic_events_monitoring to service_role;

create or replace view public.v_seismic_editorial_contents_monitoring
with (security_invoker = true)
as
select
    contents.event_id,
    contents.editorial_version,
    contents.locale,
    contents.editorial_title,
    contents.editorial_subtitle,
    contents.editorial_summary,
    contents.seo_title,
    contents.seo_description,
    contents.seo_keywords,
    contents.generated_at,
    events.source,
    events.event_status,
    events.country,
    events.occurred_at,
    events.category
from editorial.seismic_contents as contents
join knowledge.events as events on events.id = contents.event_id
where contents.editorial_version = 'seismic-v1'
  and contents.locale = 'pt-BR'
  and events.scientific_area = 'seismology'
  and events.category = 'earthquake_detected';

alter view public.v_seismic_editorial_contents_monitoring owner to postgres;
revoke all on public.v_seismic_editorial_contents_monitoring from public, anon, authenticated, service_role;
grant select on public.v_seismic_editorial_contents_monitoring to service_role;

comment on view public.v_seismic_events_monitoring is
    'Authenticated server-side seismic monitoring feed. Includes canonical seismic events regardless of publication approval; direct browser roles have no access.';
comment on view public.v_seismic_editorial_contents_monitoring is
    'Authenticated server-side seismic editorial monitoring feed. Includes seismic-v1 pt-BR editorial content regardless of publication approval; direct browser roles have no access.';
