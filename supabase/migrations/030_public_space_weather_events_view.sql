-- 030_public_space_weather_events_view.sql
-- Interface read-only minima para Events canonicos de space_weather.
-- catalog_record: registro aprovado de atividade espacial (NASA DONKI).
-- Nao confirma impacto terrestre, previsao ou alerta oficial.

create view public.v_space_weather_events
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
where scientific_area = 'space_weather'
  and event_status = 'catalog_record'
  and publication_approved;

alter view public.v_space_weather_events owner to postgres;

-- public tem default privileges legados; remova-os antes do grant minimo.
revoke all on public.v_space_weather_events from public, anon, authenticated, service_role;

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

grant select on public.v_space_weather_events to service_role;

comment on view public.v_space_weather_events is
    'Read-only server-side view of canonical operational space_weather Events (catalog_record). catalog_record is an approved NASA DONKI activity record and does not confirm terrestrial impact, forecast, or official alert. Excludes astronomy, observed_fact, forecast, official_alert, and model_projection.';
