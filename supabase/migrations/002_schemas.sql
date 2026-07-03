-- 002_schemas.sql — Sentinela HL
-- raw       = banco bruto (descartável, auditoria de curto prazo)
-- knowledge = banco de conhecimento (memória permanente, só validado)
create schema if not exists raw;
create schema if not exists knowledge;

comment on schema raw is 'Banco bruto: coletas originais, logs e auditoria. Nao e conhecimento validado.';
comment on schema knowledge is 'Banco de conhecimento: apenas eventos que passaram filtros e curadoria.';
