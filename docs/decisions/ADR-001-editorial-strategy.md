# ADR-001 — Posicionamento editorial do Sentinela HL

- **Status:** Aprovado
- **Restrição:** vinculante para todos os componentes futuros

## Contexto

O Sentinela HL precisa definir, de forma definitiva, o que publica e como separa
conteúdo científico de conteúdo reflexivo. Sem essa fronteira, o rigor científico
do sistema fica exposto a contaminação por opinião, religião ou filosofia.

## Decisão

**Missão.** O Sentinela HL é uma plataforma de inteligência científica: coleta,
valida, organiza e publica informação científica de interesse público, com rigor
metodológico, rastreabilidade de fontes e transparência sobre o nível de evidência.
A ciência é o eixo central.

**Princípio fundamental.** Tudo o que o sistema publica é baseado em evidência.
**Nenhum componente do pipeline** produz interpretação religiosa, opinião pessoal
ou conclusão filosófica. O pipeline produz somente conhecimento científico
estruturado.

**Camada pública** (`boletim.henriquelobo.com`): publicação científica — clima,
geociências, oceanografia, astronomia, transporte atmosférico, análise factual,
artigos, boletins. Linguagem técnica, fontes citadas, rastreabilidade, neutralidade.
**Sem conteúdo religioso nesta camada.**

**Camada privada** (inicialmente WhatsApp; futuramente área de membros): reflexões
cristãs baseadas em fatos **já validados cientificamente**. Privada e opcional.

**Regra editorial.** A reflexão nunca gera a ciência; a ciência sempre precede a
reflexão. Fluxo obrigatório: fato → coleta → validação científica → curadoria →
publicação científica → (opcional) reflexão. Inverter esta ordem é proibido.
(Ver ADR-005 para o invariante executável.)

**Isolamento.** Nenhum componente do pipeline conhece a camada privada.

**Destino editorial.** Todo conteúdo aprovado terá um campo `editorial_channel`
(`science_public` | `reflection_private` | `both`), **definido na curadoria por
um humano** — nunca pelo Builder nem pelo Agente.

**Painel de curadoria** (`boletim.henriquelobo.com`): ambiente operacional (não é
blog) para revisar coletas, validar decisões do Agente 113, aprovar/editar claims,
definir o destino editorial e publicar.

**WordPress:** CMS exclusivo de publicação científica. Não valida, não executa IA;
apenas recebe conteúdo já aprovado.

## Consequências

- O pipeline atual permanece science-only e **não muda** — a decisão é confirmada,
  não uma reescrita.
- `editorial_channel` é campo **futuro**: entra em `knowledge.events` quando o
  painel de curadoria existir (Milestone 3/4), com default nulo e escrita humana.
  Adicioná-lo antes disso seria YAGNI.
- Restrições permanentes: não misturar ciência e reflexão no boletim público; não
  gerar interpretação religiosa automaticamente pelo pipeline; não publicar
  conteúdo científico sem curadoria.
- Agentes futuros (Scientific Editor, Reflection Editor) leem da mesma base de
  conhecimento validada, com responsabilidades distintas.
