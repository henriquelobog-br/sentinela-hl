# ADR-003 — Uma única chamada de LLM por item

- **Status:** Aprovado
- **Restrição:** vinculante

## Contexto

Um classificador via LLM antes do agente significaria **duas** chamadas de LLM por
item (classificar + auditar). Com volume real (centenas a milhares de itens/dia),
metade do custo seria desperdiçada.

## Decisão

**Uma** chamada de LLM por item, concentrada no Agente 113 — um prompt único que
audita os três filtros de uma vez. O `Claim Builder` que o antecede é **mecânico**
(sinais determinísticos, sem LLM). A abstração `LLMClient` isola o provedor
(OpenRouter); a aplicação nunca conhece o nome do modelo.

## Consequências

- Custo do caminho crítico ~metade do de um pipeline com dois LLMs.
- O Builder "burro" é aceitável porque o Agente audita o rótulo provisório.
- Efeito colateral registrado (ver `docs/112.2C`): como o Builder rotula sempre
  `hypothesis`, o filtro 2 (overclaim) fica dormente até existir um classificador
  mais esperto — o agente atua sobretudo na proveniência. Escolha segura de V1.
- Um `SmartClassifier` via LLM é **opcional** e futuro (Milestone 5/6), fora do
  caminho crítico.
