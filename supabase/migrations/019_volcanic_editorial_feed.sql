-- 019_volcanic_editorial_feed.sql
-- Read-only server-side contract for the approved Volcanic Editorial v1.

create or replace view public.v_volcanic_editorial_contents
with (security_invoker = true)
as
select
    contents.editorial_group_id,
    contents.representative_event_id,
    contents.member_event_ids,
    contents.volcano_name,
    contents.volcano_number,
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
    events.occurred_at,
    events.category
from editorial.volcanic_contents as contents
join knowledge.events as events on events.id = contents.representative_event_id
where contents.editorial_version = 'volcanic-v1'
  and contents.locale = 'pt-BR'
  and events.scientific_area = 'volcanology';

alter view public.v_volcanic_editorial_contents owner to postgres;

revoke all on public.v_volcanic_editorial_contents
from public, anon, authenticated, service_role;

grant select on public.v_volcanic_editorial_contents to service_role;

comment on view public.v_volcanic_editorial_contents is
    'Sanitized server-side feed for approved Volcanic Editorial v1 content.';
