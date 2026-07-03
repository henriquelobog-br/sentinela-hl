-- 008_triggers.sql — Sentinela HL — todos os triggers de updated_at.
-- create or replace trigger = idempotente (PG14+).
create or replace trigger trg_items_updated before update on raw.items
  for each row execute function public.set_updated_at();
create or replace trigger trg_claims_updated before update on knowledge.claims
  for each row execute function public.set_updated_at();
create or replace trigger trg_events_updated before update on knowledge.events
  for each row execute function public.set_updated_at();
create or replace trigger trg_bulletins_updated before update on knowledge.bulletins
  for each row execute function public.set_updated_at();
