# ADR-005 — Ciência antes da reflexão (invariante executável)

- **Status:** Aprovado
- **Restrição:** vinculante
- **Relação:** operacionaliza a regra editorial do ADR-001. O 001 define a
  *estratégia*; este define o *invariante* que o código e a arquitetura garantem.

## Contexto

A separação entre ciência e reflexão (ADR-001) precisa de uma regra que a
arquitetura **imponha**, não apenas de uma intenção editorial. Sem isso, um agente
de reflexão futuro poderia, por engano, gerar conteúdo a partir de um fato não
validado.

## Decisão

Invariante: **nenhum artefato de reflexão pode derivar de um fato que ainda não foi
validado cientificamente e curado.** Consequências técnicas:

1. O pipeline científico (Collector → Builder → Agente 113 → Curadoria) **nunca**
   emite reflexão e **não conhece** a camada privada.
2. `editorial_channel` só é gravável **após** validação + curadoria humana.
3. Qualquer agente de reflexão futuro (Reflection Editor) lê **exclusivamente** da
   base de conhecimento já validada (`knowledge.events` curados) — nunca de `raw`,
   nunca de claims não validadas.

## Consequências

- A ordem é garantida por design (isolamento de camadas), não por convenção.
- A base de conhecimento validada é a **única** fonte para qualquer camada
  editorial, científica ou reflexiva.
- Auditoria: por vir sempre de eventos validados, todo conteúdo reflexivo é
  rastreável até o fato científico que o originou.
