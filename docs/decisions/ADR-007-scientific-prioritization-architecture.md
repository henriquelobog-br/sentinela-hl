ADR-007 — Scientific Prioritization Architecture
Status: Aprovado
Data: Julho/2026

Contexto
O Sentinela HL nasceu como um sistema de coleta, validação e organização de conhecimento científico.
A arquitetura inicial (Documentos 101–112.6A) resolveu com sucesso as primeiras etapas do pipeline:
Collector
        ↓
Evidence Builder
        ↓
Agente 113
        ↓
Knowledge Base
        ↓
Bulletin Engine
Essa arquitetura garante que apenas conhecimento cientificamente validado seja persistido e organizado.
Entretanto, durante a validação real (112.4) surgiu uma nova necessidade.
O volume de eventos científicos cresce continuamente.
Mesmo depois de filtrados pelo Agente 113, ainda existem muitos eventos corretos que possuem importância diferente para diferentes pesquisadores.
O problema deixa de ser:
"Este evento é cientificamente válido?"
e passa a ser:
"Este evento altera significativamente alguma linha de pesquisa deste pesquisador?"
Esse problema não pode ser resolvido apenas por palavras-chave.
Também não deve depender de novas chamadas de LLM.
Foi avaliada uma série de arquiteturas:
Matching por palavras-chave.
Research Profile simples.
Hipóteses estruturadas desde o primeiro dia.
Knowledge Graph completo.
Sistema híbrido.
A decisão abaixo consolida as melhores características observadas durante esse processo.

Decisão
A arquitetura de priorização científica passa a ser composta pelas seguintes camadas.

1. Scientific Taxonomy
Primeira camada.
Responsável por definir um vocabulário científico controlado.
Ela contém:
domínios científicos;
conceitos;
fenômenos;
instrumentos;
regiões;
sinônimos;
relações semânticas leves.
A Taxonomia representa conhecimento científico estável.
Ela não conhece pesquisadores.

2. Research Profile
Representa a agenda científica de um pesquisador.
Contém:
áreas prioritárias;
linhas de pesquisa;
regiões de interesse;
fontes preferidas;
pesos;
exclusões.
O perfil não classifica eventos.
Ele apenas declara prioridades.

3. Event Radar
Nem todo acontecimento relevante pode ser previsto pelo perfil.
O Event Radar identifica eventos cuja importância é intrínseca.
Exemplos:
guerras;
grandes terremotos;
erupções vulcânicas;
falhas de satélites;
eventos extremos;
descobertas científicas de grande impacto.
Seu objetivo é reduzir pontos cegos do sistema.

4. Concept Fingerprint
Cada evento validado recebe uma representação determinística baseada na Taxonomia.
Essa representação é composta por conceitos, relações e pesos explicáveis.
Ela NÃO utiliza LLM.
Ela NÃO utiliza embeddings online.
Ela deve ser completamente reproduzível.

5. Interest Engine
Recebe:
Concept Fingerprint;
Research Profile;
Event Radar.
Calcula:
relevância;
significância;
prioridade.
A saída NÃO reutiliza PASS / ESCALATE / REJECT.
Esses estados pertencem exclusivamente ao Agente 113.
O Interest Engine responde apenas:
"Quanto este evento importa para esta agenda científica?"

6. Research Questions
Uma agenda científica não é composta apenas por tópicos.
Ela é composta por perguntas.
Cada pergunta representa uma hipótese ou linha de investigação.
Eventos passam a ser relacionados às perguntas que podem fortalecer, enfraquecer ou complementar.

7. Scientific Memory
O sistema deixa de organizar apenas eventos.
Passa a organizar conhecimento acumulado.
Cada pergunta científica mantém:
evidências favoráveis;
evidências contrárias;
lacunas;
evolução temporal.
Essa memória constitui o histórico científico do pesquisador.

8. Knowledge Graph
O Knowledge Graph NÃO faz parte do MVP.
Ele será implementado somente quando houver volume suficiente de conceitos, relações e evidências validadas.
Seu papel será ampliar conexões indiretas entre eventos e linhas de pesquisa.

Invariantes
As seguintes restrições permanecem obrigatórias.
Uma única chamada LLM por item
Nenhuma camada posterior pode realizar novas inferências generativas sobre cada evento.

Determinismo
Todos os componentes desta arquitetura devem produzir resultados reproduzíveis.

Auditabilidade
Todo score deve possuir explicação.
Toda decisão deve ser rastreável.
Nenhum peso oculto é permitido.

Ciência antes da apresentação
A priorização científica ocorre antes de qualquer adaptação para:
HTML;
WordPress;
WhatsApp;
API;
PDF.
A apresentação permanece desacoplada da lógica científica.

Evolução incremental
Cada camada pode ser implementada independentemente.
Nenhuma camada exige a existência da seguinte.

Roadmap
Esta decisão estabelece a seguinte sequência de implementação.
112.7A
Scientific Taxonomy

↓

112.7B
Research Profile

↓

112.7C
Event Radar

↓

112.7D
Concept Fingerprint

↓

112.7E
Interest Engine

↓

112.7F
Research Questions

↓

112.8
Scientific Memory

↓

112.9
Knowledge Graph

Consequências
O Sentinela deixa de ser apenas um sistema que coleta e valida eventos científicos.
Passa a evoluir para uma plataforma de Inteligência Científica Assistida, cujo objetivo não é responder:
"O que aconteceu hoje?"
Mas sim:
"O que aconteceu hoje que pode alterar, fortalecer ou enfraquecer uma linha de pesquisa científica?"
A Taxonomia fornece significado.
O Research Profile fornece contexto.
O Event Radar protege contra acontecimentos inesperados.
O Concept Fingerprint representa conhecimento.
O Interest Engine estabelece prioridades.
As Research Questions organizam hipóteses.
A Scientific Memory preserva a evolução do conhecimento.
O Knowledge Graph amplia, futuramente, a capacidade de descoberta de relações indiretas.

Consideração final
Henrique, há uma frase que eu acrescentaria ao final deste ADR, porque ela sintetiza tudo o que construímos desde o Documento 101:
"O Sentinela HL não foi concebido para informar pesquisadores sobre eventos científicos. Foi concebido para ajudá-los a perceber conexões que dificilmente seriam observadas apenas pela leitura individual de artigos, comunicados e bases de dados."
Na minha opinião, essa frase define a identidade do projeto. Ela explica por que estamos investindo em Taxonomia, Research Profile, Event Radar, Fingerprints e Memória Científica. O objetivo nunca foi substituir a leitura da NASA, da Nature ou da USGS; foi criar uma camada de inteligência capaz de conectar evidências dispersas e acelerar o raciocínio científico. Essa passa a ser, para mim, a missão arquitetural do Sentinela HL.