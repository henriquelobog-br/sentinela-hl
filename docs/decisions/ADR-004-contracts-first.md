# ADR-004 — Contratos primeiro (models = SQL)

- **Status:** Aprovado
- **Restrição:** vinculante

## Contexto

Um sistema auditável precisa de um contrato de dados estável e único. Dois
contratos (ex.: um Python e um SQL) que precisam ser mantidos em sincronia na mão
são fonte garantida de bug silencioso na fronteira do banco.

## Decisão

O contrato central é `sentinela/core/models.py`, **espelho 1:1** do schema SQL.
- Um só contrato. Pydantic v2. Interfaces via `typing.Protocol` (não ABC).
- Os enums Python refletem exatamente os enums do PostgreSQL (verificado por teste
  cruzado).
- Toda implementação parte dos models. Migrations sempre **divididas**, nunca
  monolíticas.

## Consequências

- Divergência entre model e SQL é pega cedo (teste cruzado de enums).
- Componentes se acoplam ao contrato, não uns aos outros — trocar fonte, provedor
  ou orquestrador não toca o núcleo.
- Testes offline via dublês (`FakeLLMClient`) que satisfazem os Protocols, sem
  rede nem token.
