-- 001_extensions.sql — Projeto Sentinela HL
-- Extensões necessárias. gen_random_uuid() é nativo no PG13+, mas
-- pgcrypto garante compatibilidade e não custa nada.
create extension if not exists pgcrypto;
