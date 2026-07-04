# ADR-002 — n8n como orquestrador fino

- **Status:** Aprovado
- **Restrição:** vinculante

## Contexto

O n8n orquestra o pipeline. Há tentação recorrente de colocar lógica de decisão
nele (nós de IF, transformações), o que dispersaria a inteligência do sistema e a
tornaria não-testável.

## Decisão

O n8n é **apenas** encanamento: `Cron → chama Python → recebe JSON → roteia`.
- O nó `Execute Command` chama o agente como caixa-preta, via **stdin/stdout**.
- O único roteamento permitido é um `Switch` lendo `report.decision`.
- **Proibido** qualquer `IF` sobre `confidence_score`, `reliability`,
  `epistemic_status` ou similar. Toda decisão já foi tomada no Python.

## Consequências

- A lógica vive no Python: testável por unidade, executável por CLI, reutilizável
  sem n8n.
- O contrato `Execute Command` (stdin entra, stdout sai, erro estruturado + exit
  code) fica congelado — qualquer orquestrador serve, hoje ou amanhã.
- Trocar a fonte do dado (fixture → collector → outra API) não altera o workflow.
