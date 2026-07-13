# Sentinela HL

Sistema de inteligência científica que coleta, audita e valida informação de
ciência e pesquisa, promovendo apenas conhecimento rastreável e produzindo um
boletim diário. O objetivo não é resumir notícias — é **impedir overclaim,
exagero científico e perda de rastreabilidade**.

> Status: Milestone 1 (Fundação) concluída · Milestone 2 (Orquestração) em andamento
> Escopo temático: ciência e pesquisa (clima, geociências, publicações)

---

## 1. Visão Geral

O Sentinela HL recebe alegações ("claims") já classificadas provisoriamente e
**audita** se essa classificação é honesta, em vez de reclassificá-las do zero.
Cada decisão do sistema é auditável: fonte, rótulo epistêmico, confiança e
justificativa ficam registrados. A curadoria editorial final é humana
(Henrique Lobo); o sistema auxilia, nunca substitui o pesquisador.

## 2. Objetivo

- Barrar overclaim (ex.: uma hipótese de fonte única apresentada como fato).
- Garantir proveniência: a fonte realmente sustenta o que a claim afirma.
- Manter rastreabilidade e memória permanente do que foi validado.
- Entregar um boletim diário confiável.

## 3. Arquitetura

Pipeline de ponta a ponta:

```
Fontes (RSS/API) → Collector → Parser → Claim provisória
      → Agente 113 (FilterEngine + DecisionEngine)
      → Supabase (knowledge) → Boletim diário → WhatsApp
```

Detalhes e as decisões de projeto em [ARCHITECTURE.md](./ARCHITECTURE.md).

## 4. Estrutura do Projeto

```
sentinela-hl/
├── sentinela/
│   ├── core/          # contrato único: models.py (= schema SQL), contract.py, config.py
│   ├── clients/       # LLMClient (Protocol), OpenRouterClient, FakeLLMClient
│   ├── engines/       # decision.py (política pura), filter_engine.py, agent.py
│   ├── filters/       # prompt.py + tests/ + tests/fixtures/
│   │   └── tests/     # test_113.py e fixtures/ (caso_pass/escalate/reject)
│   ├── prompts/       # filter_v1.md (prompt versionado — artefato de 1ª classe)
│   └── cli/           # run_filters.py
├── supabase/
│   └── migrations/    # 001–011 (divididas, nunca monolíticas)
├── benchmarks/        # run_bench.py (fixtures × modelos)
├── docker-compose.yml # n8n + Redis + Evolution (Supabase fica fora)
├── ARCHITECTURE.md
├── CONTRIBUTING.md
└── README.md
```

## 5. Tecnologias

| Camada | Ferramenta |
|---|---|
| Banco | Supabase (PostgreSQL), gerenciado via CLI |
| Orquestração | n8n (modo single) |
| Mensageria | Evolution API + Redis |
| Linguagem | Python 3.12 + uv |
| Modelos | Pydantic v2 |
| LLM | OpenRouter (qualquer modelo, via `LLMClient`) |
| Higienização | pg_cron |

## 6. Como subir o ambiente

O Supabase roda pelo CLI, **fora** do Docker Compose.

```bash
# 1. Banco (CLI)
supabase start
supabase status                 # confirme as portas (db 54322, api 54321)
supabase db reset               # aplica migrations 001–011 num banco limpo

# 2. Orquestração (Docker)
cp .env.example .env            # preencha as chaves (openssl rand -hex 32/24)
docker compose up -d

# 3. Python
uv sync
```

De dentro dos containers, o Supabase é acessível por `host.docker.internal`
(nunca `localhost`).

## 7. Como executar os testes

```bash
uv run pytest sentinela/filters/tests/
```

Os testes rodam **offline**: o `LLMClient` é substituído pelo `FakeLLMClient`
(`sentinela/clients/fake.py`), sem gastar token nem depender de rede.

## 8. Como executar o Agente 113

```bash
export OPENROUTER_API_KEY=...
export OPENROUTER_MODEL_PRIMARY=...
uv run python -m sentinela.cli.run_filters sentinela/filters/tests/fixtures/caso_pass.json
```

Saída: um `FilterReport` em JSON com `decision` (`pass` / `escalate` / `reject`),
as classificações por filtro e `requires_human_review`.

Para calibrar o prompt contra um modelo real:

```bash
uv run python benchmarks/run_bench.py       # roda os 3 fixtures e compara com _expected
```

## 9. Fluxo completo

1. Cron (n8n) dispara a coleta.
2. Collectors buscam RSS/APIs dentro do escopo.
3. Parser normaliza; o item bruto vai para o schema `raw`.
4. A claim provisória (com rótulo e confiança) entra no **Agente 113**.
5. `FilterEngine` audita (proveniência, rótulo, calibração); `DecisionEngine`
   decide `pass` / `escalate` / `reject`.
6. O que passa vai para `knowledge`; o que escala vai para a curadoria do Henrique.
7. O boletim diário é gerado e entregue via WhatsApp.

## 10. Roadmap

O projeto evolui por **milestones** (entregas funcionais), não por documentos isolados.

| Milestone | Escopo | Status |
|---|---|---|
| M1 · Fundação | Banco, Docker, Python, contratos, Agente 113 | ✅ Concluída |
| M2 · Orquestração | Workflow n8n, coleta, parser, persistência, boletim, filtros 3 e 6 | 🔨 Em andamento |
| M3 · Inteligência | Filtro 5, embeddings, memória, busca semântica (pgvector) | ⏳ Planejada |
| M4 · Produção | Monitoramento, dashboard, deploy, backup, observabilidade | ⏳ Planejada |

## 11. Documentos implementados

| Doc | Entrega |
|---|---|
| 101 | Schema SQL (raw + knowledge, enums, RLS) |
| 102 | pgvector (opcional, fase 2) |
| 103 / 010 | Higienização automática do `raw` via pg_cron |
| 110 | Docker Compose (n8n + Redis + Evolution) |
| 111 | Estrutura Python + contratos (Pydantic v2) |
| 112A | Contrato do Agente de Filtros |
| 113 | Agente de Filtros (1, 2, 4) + OpenRouter + benchmark |

## 12. Próximos documentos

Documento 112 — Pipeline n8n (Milestone 2), em sete etapas:
112.1 estrutura do workflow · 112.2 coleta (RSS/API) · 112.3 parser ·
112.4 integração com o Agente 113 · 112.5 escrita no Supabase ·
112.6 boletim diário · 112.7 observabilidade.

---

## License

This repository is proprietary. All rights reserved.
No part of this project may be copied, modified or redistributed without prior authorization.

## Estado da implementação

### Fundação

- [x] Documento 101 — Schema PostgreSQL / Supabase
- [x] Documento 110 — Infraestrutura Docker
- [x] Documento 111 — Estrutura e contratos Python
- [x] Documento 112A — Contrato do agente
- [x] Documento 113 — Agente de filtros

### Pipeline de inteligência

- [x] Documento 112.1 — Workflow n8n
- [x] Documento 112.2A — Collector Adapter
- [x] Documento 112.2B — Pipeline Collector → Builder → Agente
- [x] Documento 112.2C — Evidence Builder
- [x] Documento 112.4 — Validação científica real
- [x] Documento 112.4 Rev 2 — Calibração e robustez
- [x] Documento 112.5 — Persistência PostgreSQL / Supabase

### Próximas etapas

- [ ] Documento 112.6 — Geração do boletim científico
- [ ] Painel privado de curadoria
- [ ] Publicação em `boletim.henriquelobo.com`
- [ ] Integração de novas fontes científicas e APIs
- [ ] Perfil de interesses e conexões temáticas
