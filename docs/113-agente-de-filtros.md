# Documento 113 — Agente de Filtros

O núcleo de inteligência do Sentinela HL: recebe uma claim já classificada,
audita-a nos filtros 1 (proveniência), 2 (rótulo epistemológico) e 4
(calibração) via um único LLM, e devolve um `FilterReport`.

Desacoplado de qualquer provedor: fala só com `LLMClient`. Trocar o modelo é
mudar uma variável de ambiente.

## Árvore

```
sentinela/
├── core/
│   ├── models.py      # contrato (101/111) — não tocado
│   └── contract.py    # envelope (112A) + erros (llm_timeout, llm_error)
├── clients/
│   ├── base.py        # LLMClient (Protocol) + LLMError/LLMTimeout
│   ├── openrouter.py  # OpenRouterClient (modelo por env, fallback)
│   └── fake.py        # dublê de teste
├── engines/
│   ├── decision.py    # DecisionEngine — função pura (política 112A)
│   ├── filter_engine.py  # monta prompt, chama LLM, → Classification[]
│   └── agent.py       # orquestra + mapeia erros → FilterReport
├── filters/
│   └── prompt.py      # o prompt único (o produto real do 113)
├── cli/
│   └── run_filters.py # uv run python -m sentinela.cli.run_filters ...
├── fixtures/          # caso_pass / caso_escalate / caso_reject
└── tests/
    └── test_113.py    # DecisionEngine + pipeline + erros
```

## Fluxo

```
FilterAgentInput
   ↓  FilterEngine: monta prompt único → LLMClient → JSON
Classification[]        (avaliação — sem política)
   ↓  DecisionEngine: função pura
(decision, requires_human_review)   (política — sem IA)
   ↓
FilterReport
```

`FilterEngine` avalia; `DecisionEngine` decide. Mudar a regra ("dois flags →
reject") toca só o `DecisionEngine`, nunca os filtros nem o prompt.

## Rodar

```bash
export OPENROUTER_API_KEY=...
export OPENROUTER_MODEL_PRIMARY=...      # ex.: um modelo forte
export OPENROUTER_MODEL_FALLBACK=...     # opcional

uv run python -m sentinela.cli.run_filters sentinela/fixtures/caso_pass.json
```

Saída: `FilterAgentOutput` em JSON — `{ok, report}` no sucesso, `{ok:false,
error}` em falha. Exit code 0 = pass/escalate; 1 = reject ou erro.

## Testes

```bash
uv run pytest sentinela/tests/test_113.py
```

Rodam **offline** com `FakeLLMClient` injetado pelo Protocol — sem token, sem
rede. Cobrem: DecisionEngine puro, os três fixtures ponta a ponta, e os erros
(missing_source, invalid_json, llm_timeout).

## Duas emendas ao 112A (exigidas pela decisão do OpenRouter)

A decisão de desacoplar via OpenRouter veio depois do 112A e forçou ajustar o
enum de erros:

- `claude_timeout` → **`llm_timeout`** (manter "claude" contradiz o desacoplamento)
- **`llm_error`** adicionado — falha de provedor que não é timeout (4xx/5xx, rede)

## Limite honesto desta entrega

Os testes provam a **plumbing**: parsing da resposta, conversão em
`Classification[]`, `DecisionEngine`, orquestração e mapa de erros — tudo com
um LLM simulado que devolve o veredito "certo".

O que **não** foi testado aqui (não dá, offline): se o prompt real, contra um
modelo real, de fato detecta o overclaim do `caso_escalate` e a contradição do
`caso_reject`. Isso é a parte difícil e subjetiva do 113 — a qualidade do
`filters/prompt.py`. A primeira coisa a fazer com uma `OPENROUTER_API_KEY` real
é rodar os três fixtures contra o modelo escolhido e conferir se os vereditos
batem com os `_expected`. Se não baterem, o ajuste é no prompt, não no código.

## Próximo

Documento 112 — pipeline n8n, encadeando este agente (já validado) como
caixa-preta: `cron → coleta → parser → run_filters → knowledge → boletim`.

---

## Revisão pós-113 — ajustes aplicados (antes do congelamento)

Sete ajustes propostos; aplicados os que têm payoff real agora, deferidos os especulativos.

| # | ajuste | decisão |
|---|---|---|
| 1 | prompt em arquivo | **feito** — `prompts/filter_v1.md` + `PromptLoader` (sem Jinja2: system é estático) |
| 2 | versionar prompt | **feito** — `prompt_version` no `Classification` + migration `011` |
| 3 | params extras no client | **feito como passthrough** — `extra: dict` (não 5 params enumerados) |
| 4 | JSON Schema | **pronto, não forçado** — `RESPONSE_SCHEMA` + via `extra`; ligar quando o modelo suportar |
| 5 | benchmark runner | **feito** — `benchmarks/run_bench.py` compara fixtures × `_expected`, mede latência |
| 6 | run_id | **feito** — `FilterAgentOutput.run_id` |
| 7 | métricas (tokens/custo) | **deferido** — benchmark mede latência; tokens/custo é específico do provedor, prematuro |

Ligar Structured Outputs (Ajuste 4), quando escolherem o modelo:

```python
from sentinela.filters.prompt import RESPONSE_SCHEMA
FilterEngine(client, extra={"response_format": {"type": "json_schema", "json_schema": RESPONSE_SCHEMA}})
```

O prompt agora é artefato de primeira classe (`prompts/filter_v1.md`), versionado
como o schema SQL e os models — que era o único motivo do 9,8 não ser 10.
