-- 003_enums.sql — Sentinela HL
-- TODOS os enums, criados ANTES de qualquer tabela.
-- Ordem exata da especificacao. Cada um e idempotente (re-execucao segura).

do $$ begin
  create type public.source_kind as enum ('rss','api','scraper','newsletter','manual');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.reliability_tier as enum ('high','medium','low','unknown');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.fetch_status as enum ('running','success','partial','error');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.pipeline_status as enum (
    'collected','normalized','duplicate','discarded',
    'in_filter','escalated','validated','rejected','promoted','archived'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.epistemic_status as enum (
    'confirmed_fact','hypothesis','interpretation','practical_application'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.filter_key as enum (
    'provenance','epistemic_label','source_independence',
    'calibration','contradiction','extraordinariness'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.filter_result as enum ('pass','flag','fail');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.review_decision as enum ('pending','approved','rejected','edited');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.bulletin_status as enum ('draft','in_review','approved','sent','failed');
exception when duplicate_object then null; end $$;
