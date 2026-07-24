# ADR-006 — Boletim é modelo de conhecimento, não conteúdo de canal

- **Status:** Aprovado
- **Restrição:** vinculante

## Contexto

O boletim precisará alimentar múltiplos canais: HTML (painel), WordPress
(publicação científica pública), WhatsApp (camada privada), e potencialmente PDF,
e-mail ou API. Se o boletim nascer acoplado a um canal, cada novo destino exigiria
reimplementar a lógica científica de seleção, ordenação e agrupamento.

## Decisão

O boletim é um **modelo de conhecimento** (`BulletinModel`), não conteúdo de canal.

- O `BulletinEngine` produz **estrutura**, nunca apresentação.
- O `BulletinModel` **não tem campos visuais** — nada de HTML, CSS, emoji,
  formatação ou limite de caracteres.
- Cada canal é um **renderizador** que consome o mesmo modelo.

```
BulletinModel ──┬── HTML (painel)
                ├── WordPress (público)
                ├── WhatsApp (privado)
                └── PDF / e-mail / API
```

## Consequências

- Adicionar um canal é escrever um adapter — a lógica científica não é tocada.
- A separação editorial do ADR-001 é preservada: o mesmo conhecimento validado
  alimenta a camada pública (ciência) e, opcionalmente, a privada — sem que o
  pipeline conheça a camada privada.
- `requires_review` viaja no modelo: a **curadoria** decide o que publica, em que
  canal. O engine não decide publicação (ADR-001, ADR-005).
- O engine permanece determinístico e testável sem banco, sem rede, sem LLM.
