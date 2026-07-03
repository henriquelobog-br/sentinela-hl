-- 009_rls.sql — Sentinela HL — RLS por ultimo.
-- Fechado por padrao. service_role (n8n/backend) ignora RLS.

alter table raw.sources               enable row level security;
alter table raw.fetch_runs            enable row level security;
alter table raw.items                 enable row level security;
alter table knowledge.claims          enable row level security;
alter table knowledge.classifications enable row level security;
alter table knowledge.events          enable row level security;
alter table knowledge.contradictions  enable row level security;
alter table knowledge.bulletins       enable row level security;
alter table knowledge.bulletin_events enable row level security;

do $$ begin
  create policy "knowledge readable by authenticated"
    on knowledge.events for select to authenticated using (true);
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "bulletins readable by authenticated"
    on knowledge.bulletins for select to authenticated using (true);
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "curator updates events"
    on knowledge.events for update to authenticated using (true) with check (true);
exception when duplicate_object then null; end $$;
