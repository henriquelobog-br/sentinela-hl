-- 015_public_seismic_events_view.sql
-- Interface read-only minima para Events canonicos de sismologia.
-- Os Events atuais satisfazem ambos os campos; AND evita incluir registros
-- classificados como sismologia ou terremoto por apenas um criterio.

create view public.v_seismic_events
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

alter view public.v_seismic_events owner to postgres;

-- public tem default privileges legados; remova-os antes do grant minimo.
revoke all on public.v_seismic_events from public, anon, authenticated, service_role;

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
    validated_at
) on knowledge.events to service_role;

grant select on public.v_seismic_events to service_role;

comment on view public.v_seismic_events is
    'Read-only server-side view of canonical seismology earthquake Events.';
