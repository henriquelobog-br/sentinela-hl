# Documento 110 — Docker Compose (desenvolvimento)

Orquestração local do Sentinela HL: **n8n + Redis + Evolution API**.
O Supabase **não** está aqui — é gerenciado só pelo CLI.

## Premissas (definitivas)

| Decisão | Escolha |
|---|---|
| Supabase | Só via CLI (`supabase start`), fora do compose |
| n8n | Modo single (sem worker) |
| Evolution API | v1.x — Redis + volume, sem Postgres próprio |
| SO alvo | macOS Apple Silicon + Docker Desktop |
| Acesso ao Supabase | `host.docker.internal` (nunca `localhost`) |
| Regra de negócio | Toda no Python; n8n só orquestra |

## O princípio que rege tudo: n8n é encanamento, não cérebro

```
Cron → chama Python → recebe JSON → persiste / notifica
```

Nunca:

```
Cron → 50 nós de IF → Claude → transformação → filtro → decisão
```

O n8n enxerga o agente como caixa-preta: `python run_filters.py` entra, JSON sai.
Ganho: teste unitário da lógica, execução por CLI, reuso sem n8n, depuração simples.

## Como subir

```bash
cp .env.example .env
# gere as chaves:
openssl rand -hex 32   # cole em N8N_ENCRYPTION_KEY
openssl rand -hex 24   # cole em EVOLUTION_API_KEY

# o Supabase sobe SEPARADO, pelo CLI:
supabase start
supabase status        # confirme as portas (db 54322, api 54321)

# depois o resto:
docker compose up -d
docker compose ps
```

Acessos: n8n em `http://localhost:5678`, Evolution em `http://localhost:8080`.

## Acessando o Supabase de dentro dos containers

O Supabase roda no **host** (via CLI). De dentro de um container, `localhost`
é o próprio container — então use **`host.docker.internal`**:

- Postgres: `host.docker.internal:54322`
- API/REST: `http://host.docker.internal:54321`

Confirme sempre as portas com `supabase status` (podem variar).

## ⚠️ Evolution API — ponto que muda entre versões

Esta é a peça de evolução mais rápida do stack. O compose usa **v1.x**, que
persiste instâncias em arquivo (volume) e roda só com Redis — batendo com a
decisão "sem Postgres na V1".

A **v2.x exige PostgreSQL (Prisma)**. Se um dia migrar para a v2:
adicione um Postgres **dedicado** à Evolution (nunca o banco do Sentinela) e
troque as variáveis de ambiente (mudam entre v1 e v2).

Antes de subir, **confirme a tag** `atendai/evolution-api:v1.8.2` no registry —
se não existir mais, ajuste para a v1.x disponível.

## Próximo passo

Documento 111 — estrutura Python (plana, por tecnologia):
`collector/ parser/ filters/ classifier/ writer/ prompts/ shared/`.
