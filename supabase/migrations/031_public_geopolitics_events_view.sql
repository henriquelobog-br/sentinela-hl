-- 031_public_geopolitics_events_view.sql
-- Interface read-only minima para Events canonicos de scientific_geopolitics.
-- reported_event: registro aprovado reportado pelo provider, sem confirmacao
-- independente, alerta oficial ou previsao pelo Sentinela.

create view public.v_geopolitics_events
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
