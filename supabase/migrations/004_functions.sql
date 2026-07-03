-- 004_functions.sql — Sentinela HL
-- Funcao util de updated_at. create or replace = idempotente.
create or replace function public.set_updated_at()
returns trigger language plpgsql as $func$
begin
  new.updated_at = now();
  return new;
end;
$func$;
