-- 012_researcher_signals.sql
-- Persistência da projeção ResearcherSignal (saída do pipeline 112.7).
-- A tabela reflete exatamente os campos atuais de ResearcherSignal;
-- created_at/updated_at são apenas controle de persistência do banco.

create table if not exists public.researcher_signals (
    -- identidade estável (SHA-256 hex de pesquisador + evento + versões)
    id                        text primary key,
    researcher_id             text not null,
    research_profile_version  text not null,

    -- evento (UUID canônico em forma textual, conforme contrato Python)
    event_id                  text not null,
    representative_event_id   text not null,
    member_event_ids          jsonb not null default '[]'::jsonb,

    title                     text not null,
    summary                   text,
    occurred_at               timestamptz,
    validated_at              timestamptz,

    -- priorização (valores copiados, nunca recalculados no banco)
    priority_score            double precision not null
        check (priority_score between 0.0 and 1.0),
    priority_level            text not null
        check (priority_level in ('low', 'moderate', 'high', 'urgent')),
    relevance_score           double precision not null
        check (relevance_score between 0.0 and 1.0),
    significance_score        double precision not null
        check (significance_score between 0.0 and 1.0),
    significance_level        text not null
        check (significance_level in ('low', 'moderate', 'high', 'critical')),

    reasons                   jsonb not null default '[]'::jsonb,
    requires_human_review     boolean not null,

    -- proveniência de versões
    taxonomy_version          text not null,
    algorithm_version         text not null,
    config_version            text not null,

    -- controle de persistência (banco)
    created_at                timestamptz not null default now(),
    updated_at                timestamptz not null default now()
);

create index if not exists researcher_signals_researcher_id_idx
    on public.researcher_signals (researcher_id);

create index if not exists researcher_signals_event_id_idx
    on public.researcher_signals (event_id);

create index if not exists researcher_signals_priority_level_idx
    on public.researcher_signals (priority_level);

create index if not exists researcher_signals_occurred_at_idx
    on public.researcher_signals (occurred_at desc);

-- ---------------------------------------------------------------------
-- RLS
--
-- Leitura pública DESABILITADA: RLS habilitado sem nenhuma policy de
-- SELECT, portanto o default-deny se aplica a anon e authenticated.
--
-- BLOQUEADO: a policy de leitura pelo próprio pesquisador exige o
-- mapeamento researcher_id ↔ auth.uid(), que ainda não existe em
-- nenhum contrato do projeto. Inventar essa associação aqui seria
-- fabricar contrato. Quando o mapeamento for definido, criar policy
-- de SELECT restrita ao pesquisador autenticado.
--
-- A escrita via service role (backend) bypassa RLS e permanece
-- funcional para o upsert idempotente pela coluna id.
-- ---------------------------------------------------------------------

alter table public.researcher_signals enable row level security;
