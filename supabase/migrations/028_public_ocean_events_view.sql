-- 028_public_ocean_events_view.sql
-- Interface read-only minima para Events canonicos oceanograficos operacionais.
-- Inclui observacao e previsao aprovadas; exclui projecao e outras areas.

create view public.v_ocean_events
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
where scientific_area = 'oceanography'
  and event_status in ('observed_fact', 'forecast')
  and publication_approved;

alter view public.v_ocean_events owner to postgres;

-- public tem default privileges legados; remova-os antes do grant minimo.
revoke all on public.v_ocean_events from public, anon, authenticated, service_role;

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

grant select on public.v_ocean_events to service_role;

comment on view public.v_ocean_events is
    'Read-only server-side view of canonical operational oceanography Events (observed_fact and forecast). Excludes model_projection.';
