-- 013_researcher_signal_architecture.sql
-- Contribuições estruturadas usadas pela elegibilidade, sem substituir reasons.

alter table public.researcher_signals
    add column if not exists matched_concepts jsonb not null default '[]'::jsonb;

alter table public.researcher_signals
    add column if not exists event_status text not null default 'unknown'
    check (event_status in (
        'unknown', 'observed_fact', 'official_alert', 'forecast',
        'model_projection', 'catalog_record', 'reported_event'
    ));

alter table public.researcher_signals
    add column if not exists category text,
    add column if not exists source text,
    add column if not exists supporting_sources jsonb not null default '[]'::jsonb,
    add column if not exists evidence jsonb not null default '[]'::jsonb;
