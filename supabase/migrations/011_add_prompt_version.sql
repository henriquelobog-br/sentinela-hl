-- =====================================================================
-- 011_add_prompt_version.sql
-- Ajuste 2 (Doc 113): versionar o prompt que produziu cada classificação.
-- Migration separada (nunca monolítica) — segue o padrão 001–010.
--
-- Responde, seis meses depois: "esse veredito saiu de qual versão do prompt?"
-- =====================================================================

alter table knowledge.classifications
  add column if not exists prompt_version text;

comment on column knowledge.classifications.prompt_version is
  'Versão do prompt (ex.: filter_v1) que gerou este veredito. Auditoria.';

create index if not exists idx_classifications_prompt_version
  on knowledge.classifications(prompt_version);
