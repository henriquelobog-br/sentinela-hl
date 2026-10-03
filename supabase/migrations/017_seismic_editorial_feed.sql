-- 017_seismic_editorial_feed.sql
-- Read-only server-side contract for the approved Seismic Editorial v1.

create view public.v_seismic_editorial_contents
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

alter view public.v_seismic_editorial_contents owner to postgres;

revoke all on public.v_seismic_editorial_contents
from public, anon, authenticated, service_role;

grant usage on schema editorial to service_role;
grant select (
    event_id,
    editorial_version,
    locale,
    editorial_title,
    editorial_subtitle,
    editorial_summary,
    seo_title,
    seo_description,
    seo_keywords,
    generated_at
) on editorial.seismic_contents to service_role;

grant usage on schema knowledge to service_role;
grant select (
    id,
    source,
    event_status,
    country,
    occurred_at,
    category,
    scientific_area
) on knowledge.events to service_role;

grant select on public.v_seismic_editorial_contents to service_role;

comment on view public.v_seismic_editorial_contents is
    'Sanitized server-side feed for approved Seismic Editorial v1 content.';
