-- 014_canonical_events.sql
-- Alinha knowledge.events ao Event canônico usado pelos coletores direct-source.
-- Migration estritamente aditiva; não altera researcher_signals nem linhas existentes.

alter table knowledge.events
    add column if not exists event_status text not null default 'unknown'
    check (event_status in (
        'unknown', 'observed_fact', 'official_alert', 'forecast',
        'model_projection', 'catalog_record', 'reported_event'
    )),
    add column if not exists source text,
    add column if not exists supporting_sources text[] not null default '{}';
