# Relatório Final: Desafio Análise Avançada de Dados

## Antecipação de Alertas Críticos em Frotas de Mineração

**João Pedro Costa**
pedrojoaao4@gmail.com
Programa Desenvolver, Edição 2026

---

**Resumo.** Este trabalho aborda a previsão e a prevenção de alertas críticos de condição ("don't go") em uma frota de 47 equipamentos de mina de Itabira, composta por caminhões fora de estrada CAT 793-D (frotas 2S a 5S) e escavadeiras LeTourneau L-1850, a partir de duas fontes: os apontamentos de ciclo operacional (377.907 registros) e a telemetria embarcada (37,16 milhões de eventos), cobrindo seis meses de operação (janeiro a junho de 2025). O catálogo de regras de negócio (aba CMA do arquivo Alarmes - Regra de Negocio_V2.xlsx, 151 regras definidas por TIPO, EVENTO, SITUACAO, QUANTIDADE, TEMPO e NIVEL) foi convertido em um motor de regras em Python que rotulou 1.974 alertas don't go no período; a coluna Is_Dont_Go da telemetria foi usada apenas como pré-filtro, e o rótulo oficial foi recalculado a partir das regras, que exigem uma quantidade de ocorrências dentro de uma janela de tempo em minutos. O problema foi formulado como classificação binária, prever ao fim de cada ciclo se o equipamento disparará um alerta nas 4 horas seguintes, complementada por uma formulação de sobrevivência (Weibull AFT com censura à direita) que estima o tempo até o próximo alerta. Após limpeza com controle de alterações integral, incluindo a derivação do operador por casamento temporal com a telemetria, foram construídas 50 variáveis de janelas retroativas, gerando uma tabela analítica com 343.663 pontos de decisão e prevalência de 4,89%. A validação foi estritamente temporal (treino de janeiro a abril, teste em junho, tocado uma única vez), com tuning em duas janelas independentes (abril e maio) e encodings estimados apenas em janeiro a março. Três classificadores foram comparados contra dois baselines, além do modelo de sobrevivência e de uma abordagem não supervisionada. O LightGBM venceu a seleção pré-registrada com AUC-ROC de 0,870 no teste (Random Forest: AUC-PR 0,320, empate técnico; heurística de painel: 0,750 e 0,245; Weibull AFT: C-index 0,781). O modelo opera em dois limiares escolhidos na validação: o ponto de captura (F2) antecipa 68,6% dos 229 alertas de junho com mediana de 3,4 horas de aviso, e o ponto custo-ótimo antecipa 45% com precisão de 42% e benefício líquido estimado de R$ 1,10 milhão no mês. A análise SHAP e os fatores de aceleração do modelo de sobrevivência convergem na mesma física (recorrência de alertas e rajadas de alarmes monitorados dominam o risco), e a análise de erros revelou achados acionáveis: a frota L-1850 gera 91% do volume de telemetria mas apenas 1,2% dos alertas, sendo a única 100% imprevisível, e o precursor de temperatura de freio existe no eixo dianteiro (94% de recall) mas é fraco no traseiro (cerca de 33%), um mapa direto para melhorias de instrumentação.

**Palavras-chave:** manutenção preditiva; telemetria industrial; alertas don't go; LightGBM; análise de sobrevivência; validação temporal; SHAP; mineração.

---

## 1. Introdução

Uma mina de grande porte opera como um sistema de fluxo contínuo: escavadeiras alimentam caminhões fora de estrada que ciclam entre frentes de lavra, britadores e pilhas. Cada equipamento gera dois rastros digitais permanentes, que são as fontes deste trabalho. O primeiro é o **apontamento**: o sistema de despacho registra cada ciclo de atividade com identificador, início, fim, equipamento (Tag), frota, tipo e classe da atividade. O segundo é a **telemetria embarcada**: os módulos dos fabricantes emitem eventos de condição (nível de fluido, temperatura de freio, pressão de óleo) classificados por criticidade, com o valor lido, a identificação anonimizada do operador do turno e a indicação de o alarme constar na lista de monitoramento don't go.

Sobre esse fluxo de eventos, a área de Confiabilidade (CMA) mantém um catálogo de **regras don't go**: combinações de evento, situação, quantidade e janela de tempo que, quando satisfeitas, determinam que o equipamento **não deve continuar operando**. Hoje o disparo é reativo: quando a regra fecha, a máquina precisa sair de rota imediatamente, muitas vezes carregada, em rampa, no meio do turno, e a manutenção recebe o problema sem aviso. Em linha com o foco do desafio, o objetivo central deste trabalho é a **previsão e a prevenção** desses alertas: estimar, a cada ciclo encerrado, a probabilidade de cada equipamento disparar um alerta don't go nas 4 horas seguintes, e traduzir essa probabilidade em uma fila priorizada de inspeção. A decisão baseada em dados aqui é concreta: cada hora de caminhão de grande porte parado fora de plano é produção não realizada, e cada alerta antecipado converte uma quebra em intervenção planejada.

### 1.1 Contextualização da operação (Tópico Sugerido 1.1)

**Fluxo operacional.** Cada registro de `Apontamentos` representa um ciclo de atividade de um equipamento, delimitado por `Inicio` e `Fim`, com `Id`, `Tag`, `Frota` (793-D 2S, 3S, 4S e 5S e LeTourneau L 1850), `Tipo` (Caminhao, Escavadeira) e `Classe` da atividade (Operando, Parado, Hibernando, Manutenção). Conforme o dicionário de dados revisado, o extrato de apontamentos não traz o operador; essa informação existe apenas na Telemetria e foi derivada para os ciclos por casamento temporal (seção 2.3). A base cobre **47 equipamentos** da localidade de Itabira, operando em dois turnos de 12 horas (A: 06h às 18h; B: 18h às 06h).

A tabela `Telemetria` registra os eventos embarcados: `Data_Evento`, turno, localidade, equipamento, operador anonimizado (`Nome_Operador_Anon`, `Matricula_Operador_Hash`), alarme (`Id_Alarme`, `Alarme`), criticidade (`Id_Criticidade`: 1 Crítico, 2 Não Crítico, 3 Informacional, 4 Outros), valor lido (`Valor`, com vírgula como separador decimal na origem) e a flag `Is_Dont_Go`, que indica se o nome do alarme consta na lista don't go.

**Alertas don't go.** Um alerta don't go sinaliza condição na qual o equipamento não deve operar. O impacto é triplo: segurança (um caminhão com temperatura de freio crítica descendo rampa carregado é risco inaceitável), disponibilidade de frota (a máquina sai do plano sem aviso) e custo do ativo (operar sob alarme de pressão de óleo transforma uma intervenção de horas em troca de componente de semanas).

**Regras de negócio.** O arquivo `Alarmes - Regra de Negocio_V2.xlsx` tem três abas (CMA, Tendências e Eventos O&M); as regras don't go estão na aba **CMA**: 151 regras (142 ALARME OEM, 7 TENDÊNCIA e 2 SISTEMA), cada uma combinando TIPO, EVENTO, SITUACAO (por exemplo, "Mediante alarme nível 3", "Mediante cinco alarmes nivel 2 consecutivos", "Em qualquer situação"), QUANTIDADE (1 a 10 ocorrências), TEMPO (janela de 0, 360 ou 720 minutos) e NIVEL (Muito Alto ou Alto). A definição é explicitamente de contagem em janela: o alerta exige uma certa QUANTIDADE de ocorrências dentro do TEMPO, e não apenas uma combinação fixa de campos. O arquivo equivale a regras codificadas em Python, e foi exatamente assim que este trabalho o tratou (seção 2.3). Exemplos de eventos de NIVEL Muito Alto: `Low Transmission Oil Level` mediante alarme nível 3, `Engine Coolant Level - Active`, `Very Low Hydraulic Oil Level`, `Engine Overheat/Engine Coolant or Water Overheat`, `Low Engine Oil Pressure`, `High Engine Coolant Temperature`, as temperaturas de freio (`High Left/Right Front/Rear Brake Oil Temperature`), `Hydraulic Reservoir Oil Temperature Critically High (L-1850)`, `HPD Gearbox Oil Pressure Critically Low`, as tendências `MC - Tendência baixa pressão do óleo motor <250/200/150KPA` e a regra de sistema `MEMS não comunica`.

![Figura 1](figuras/fig01_fluxo_operacional.png)

### 1.2 Definição do problema analítico (Tópico Sugerido 1.2)

**Pergunta principal:**

> **Quais equipamentos têm maior risco de gerar um alerta don't go nas próximas 4 horas, considerando o padrão atual de operação?**

Perguntas de apoio respondidas ao longo do trabalho: o comportamento do operador tem correlação com a frequência de alertas em um mesmo equipamento? Qual o perfil dos equipamentos que mais geram alertas (frota, tipo, horas trabalhadas)? Os alertas se concentram em turnos, dias ou períodos do mês? Quanto tempo falta até o próximo alerta de cada equipamento (formulação de sobrevivência)? E como priorizar a fila de inspeção da manutenção a partir do score de risco?

**Métrica de sucesso.** O problema é considerado resolvido se o modelo antecipar **ao menos 60% dos alertas don't go** dentro da janela de 4 horas com **precisão mínima de 30%** (no máximo cerca de duas inspeções vazias por acerto). Como referência de valor: cada alerta antecipado converte parte de um episódio de manutenção corretiva (média de 6,7 horas na base, após reconstrução de episódios) em intervenção planejada. A aferição honesta dessa meta, com o trade-off completo, está na seção 3.6.

**Cenário de aplicação.** A cada fechamento de ciclo de apontamento (em média a cada 30 minutos por equipamento), o pipeline recalcula o score e atualiza um painel no sistema de monitoramento do despacho, em dois níveis: "atenção" (ponto de captura) e "inspecionar agora" (ponto custo-ótimo). O despachante redireciona o caminhão para rota próxima da oficina ou acopla a inspeção ao abastecimento, e a manutenção recebe a fila priorizada com as evidências que sustentam o score (via SHAP) e a estimativa de tempo até o alerta (via modelo de sobrevivência).

## 2. Metodologia

A metodologia cobre todas as etapas de uma solução de dados: análise exploratória (2.2), preparação e engenharia de variáveis (2.3), estratégia de validação (2.4), modelagem (2.5) e critérios de avaliação (2.6), sustentadas por um pipeline reprodutível (2.1). O ETL aqui é parte da solução, não o fim: garante a qualidade do insumo para a modelagem, que é o foco do desafio.

### 2.1 Visão geral da solução e ferramentas

A solução foi implementada em Python 3 (pandas, scikit-learn, LightGBM, lifelines, SHAP) e organizada em módulos de responsabilidade única, executáveis de ponta a ponta por um único comando (`executar_pipeline.py`, cerca de 8 minutos sobre os 37 milhões de eventos):

1. **Extração** (`src/etl/extracao.py`): leitura dos extratos Parquet do data lake (Apontamentos em arquivo único; Telemetria particionada por mês, 6 arquivos), com **leitura colunar seletiva**: das 18 colunas da telemetria, apenas as 10 consumidas pelo pipeline são carregadas, decisão necessária para processar 37,16 milhões de eventos em memória. Inclui a derivação do operador nos apontamentos (seção 2.3).
2. **Transformação** (`src/etl/transformacao.py`): limpeza com **controle de alterações**; cada verificação, correção ou exclusão gera registro com quantidade, tratamento e justificativa.
3. **Carga** (`src/etl/carga.py`): camada tratada em Parquet (colunar e tipado, preserva dtypes e permite reprocessamento parcial).
4. **Rotulagem** (`src/regras/motor_regras.py`): aplicação das 151 regras da aba CMA sobre a telemetria limpa.
5. **Engenharia de variáveis** (`src/features/engenharia.py`): construção da tabela analítica por varredura vetorizada com busca binária sobre arrays ordenados por equipamento.
6. **Modelagem e avaliação** (`src/modelos/`, `src/avaliacao/`): treino com tuning em duas janelas, modelo de sobrevivência, métricas, análise de erros, SHAP e impacto em dois pontos de operação. Utilitários adicionais de robustez (walk-forward mensal, sensibilidade da janela de predição, calibração e varredura completa de custo por limiar) acompanham o repositório em `src/avaliacao/robustez.py`, executáveis sobre a camada processada.
7. **Visualização** (`src/viz/figuras.py`): geração das 13 figuras deste relatório.

Critérios técnicos: separação entre camadas bruta, tratada e analítica; reprodutibilidade (semente fixa e cortes por data em configuração central; o caminho dos dados brutos é parametrizado por variável de ambiente); e um desenho de features que usa apenas ordenação temporal por equipamento, o que se traduz diretamente para janelas deslizantes em streaming no cenário de produção.

### 2.2 Entendimento dos dados (Tópicos Sugeridos 2.1, 2.2 e 2.3)

**Carregamento e inspeção inicial.**

| Tabela | Linhas | Colunas | Nulos (total) | Duplicatas | Janela temporal |
|---|---:|---:|---:|---:|---|
| Apontamentos | 377.907 | 9 (7 da origem + 2 derivadas) | 140.264 | 0 | 01/01/2025 a 30/06/2025 |
| Telemetria | 37.164.054 | 10 (de 18 na origem) | 0 | 0 | 01/01/2025 a 30/06/2025 |

Os 140.264 nulos dos apontamentos concentram-se nas duas colunas de operador derivadas por casamento temporal (70.132 ciclos sem evento de telemetria do mesmo equipamento em uma janela de 6 horas, majoritariamente de 15 Tags sem telemetria no período). A frequência média é de 2.086 apontamentos/dia (cerca de 44 ciclos por equipamento-dia) e cerca de 205 mil eventos de telemetria/dia, estáveis ao longo do semestre (Figura 2).

Estatísticas descritivas das variáveis numéricas, antes da limpeza:

| Tabela | Feature | Tipo | % Nulos | Min | Max | Média | Mediana | Desvio Padrão |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Apontamentos | duracao_min (derivada) | float64 | 0,00 | 0,02 | **60,0** | 29,7 | 22,9 | 24,0 |
| Telemetria | Valor | float64 | 0,64 | 0,0 | 4.347 | 4,6 | 0,0 | 28,5 |
| Telemetria | Id_Criticidade | int64 | 0,00 | 1 | 4 | 2,98 | 3 | 0,15 |
| Telemetria | Is_Dont_Go | int8 | 0,00 | 0 | 1 | 0,0005 | 0 | 0,02 |
| Telemetria | Dia | int64 | 0,00 | 1 | 31 | 16,0 | 16 | 8,9 |

Dois achados estruturais orientaram a preparação: (i) a duração máxima de exatamente **60 minutos** revela que o sistema de origem fatia atividades longas em ciclos de até 1 hora; qualquer métrica de duração (por exemplo, tempo de manutenção) precisa reconstruir episódios encadeando ciclos consecutivos; (ii) 98,5% dos eventos são de criticidade 3 (informacional) e apenas 19.962 eventos (0,05%) carregam a flag `Is_Dont_Go`: o sinal relevante para as regras é uma agulha em um palheiro de 37 milhões de eventos. `Valor` usa vírgula decimal na origem (tratado na transformação) e é zero na mediana, pois alarmes de estado não carregam leitura.

![Figura 2](figuras/fig02_volume_temporal.png)

**Análise da variável alvo.** Após a rotulagem pelo motor de regras (seção 2.3), o período contém **1.974 alertas don't go**, ou 10,9 por dia na frota (0,23 por equipamento-dia):

| TIPO | NIVEL | Alertas |
|---|---|---:|
| ALARME OEM | Muito Alto | 1.420 |
| ALARME OEM | Alto | 554 |

Nenhuma regra de TIPO TENDÊNCIA ou SISTEMA disparou no período: os eventos correspondentes não ocorrem nesta extração de telemetria, o que é em si um achado de cobertura de dados (as tendências da engenharia e os watchdogs de comunicação não estão fluindo para esta base). Os dez equipamentos mais ofensores concentram **57,8%** dos alertas (CA65926 lidera com 152; CA65930 tem 141; CA65927, 123), enquanto a mediana entre os 32 equipamentos com alerta é 59,5: essa cauda pesada é exatamente o que uma fila de inspeção priorizada explora. **Balanceamento:** nos 343.663 pontos de decisão da tabela analítica, a classe positiva (alerta nas 4 horas seguintes) representa **4,89%**, desbalanceamento de cerca de 1:19 que orientou a escolha de métricas (AUC-PR e F2) e o tratamento de pesos nos modelos. A série temporal diária (Figura 4) mostra regime com surtos e queda de incidência na segunda quinzena de maio, sem sazonalidade semanal relevante.

![Figura 3](figuras/fig03_alertas_tipo_nivel.png)

![Figura 4](figuras/fig04_serie_alertas.png)

**Análise de features.** O heatmap de correlação de Spearman (Figura 5) mostra três padrões: colinearidade forte dentro das famílias de contagem em janelas sobrepostas (esperada e tolerada, pois os modelos finais são de árvore); correlações mais altas com o alvo nas contagens de alarmes monitorados em janelas curtas (`n_dg_12h`, `n_dg_24h`, `quase_gatilhos_12h`); e correlação negativa de `h_desde_alerta_dg` (alerta recente eleva o risco de recorrência).

Distribuição por categoria: a taxa de don't go por 1.000 horas operadas varia **16 vezes** entre frotas: 793-D 3S com 34,5; 793-D 4S com 30,8; 793-D 5S com 30,7; 793-D 2S com 13,3; e LeTourneau L 1850 com apenas 2,1. A L-1850 responde sozinha por **91,2% do volume de telemetria** (33,9 milhões de eventos) e por apenas 1,2% dos alertas: volume de eventos não é risco. Padrões temporais: a taxa do alvo oscila entre 4,13% (10h) e 5,72% (21h), com leve predominância noturna: turno B (18h às 06h) com 5,15% contra 4,62% do turno A (Figura 6); entre dias da semana a variação é pequena.

Hipóteses registradas na EDA: **H1**, calor da tarde eleva alertas térmicos (**não confirmada**: o pico de taxa é às 21h e o turno noturno supera o diurno; o regime de operação pesa mais que a temperatura ambiente nesta base); **H2**, operadores diferem na taxa de alerta em equipamentos comparáveis (confirmada: entre os 124 operadores com pelo menos 800 decisões, a taxa varia de 0% a 15,3%; seção 3.7); **H3**, frotas diferem estruturalmente (confirmada: 16 vezes entre a 793-D 3S e a L-1850, e 2,6 vezes dentro dos próprios 793-D); **H4**, risco cai logo após manutenção (**não confirmada com clareza**: `h_desde_manutencao` ficou fora do topo do SHAP, e o modelo de sobrevivência sugere leitura mais sutil, seção 3.4); **H5**, fim de mês concentra alertas (não confirmada: a variação entre quinzenas acompanha episódios específicos, não o calendário).

![Figura 5](figuras/fig05_heatmap_correlacao.png)

![Figura 6](figuras/fig06_taxa_hora_dia.png)

### 2.3 Preparação dos dados (Tópicos Sugeridos 3.1, 3.2 e 3.3)

**Limpeza e tratamento.** Toda verificação e alteração foi registrada com quantidade, tratamento e justificativa (arquivo `relatorio/tabelas/controle_alteracoes.csv`):

| Tabela / Campo | Problema identificado | Qtd. | Tratamento | Justificativa |
|---|---|---:|---|---|
| Apontamentos / Operador | Extrato de origem não traz operador (dicionário revisado) | 377.907 | Derivação por merge_asof com a telemetria (mesma Tag, evento mais próximo do início do ciclo, tolerância de 6 h) | O comportamento do operador é uma das perguntas do desafio; a telemetria carrega o operador do turno e permite reconstruí-lo |
| Apontamentos / Operador | Ciclo sem evento de telemetria em 6 h | 70.132 | Categoria "OP_DESCONHECIDO" | Excluir descartaria horas operadas válidas (inclui 15 Tags sem telemetria no período) |
| Apontamentos / Fim | Sobreposição de ciclos na mesma Tag | 326 | Fim truncado no início do ciclo seguinte (264 ciclos zerados removidos) | Um equipamento não executa dois apontamentos simultâneos |
| Apontamentos / Inicio, Fim | Duplicatas, inversões, duração zero ou acima de 24 h | 0 | Verificado, nada a corrigir | Base de apontamentos consistente; as verificações permanecem no pipeline como salvaguarda |
| Telemetria / Valor | Vírgula decimal e valores não numéricos ("NULL") | 237.443 | Normalização da vírgula e coerção para NaN, linha mantida | O disparo das regras depende do evento e do nível, não do Valor; imputar leitura inexistente criaria informação falsa |
| Telemetria / todas | Eventos duplicados | 0 | Verificado, nada a corrigir | Sem reprocessamentos do coletor nesta extração |
| Catálogo CMA / NIVEL | Grafias inconsistentes ("Muito alto"/"Muito Alto") | 6 | Padronização (title case) | Sem isso, a agregação por criticidade divide a mesma categoria em duas |

Resultado: 377.907 apontamentos tornam-se **377.643** válidos, e os 37.164.054 eventos de telemetria seguem íntegros (nenhum descartado). **Outliers:** optou-se por manter valores extremos de contagem de eventos (como as rajadas de milhares de eventos/dia da L-1850), porque em telemetria de degradação o outlier frequentemente é o próprio sinal, e os modelos escolhidos (árvores) são robustos a caudas. A exceção documentada foi o tratamento estrutural do fatiamento de 60 minutos, resolvido com reconstrução de episódios (usada no impacto de negócio, seção 3.6).

**Engenharia de variáveis.** Foram construídas 50 variáveis em cinco famílias, todas calculadas exclusivamente com informação anterior ao instante de decisão t:

| Feature (família) | Descrição | Fórmula / Lógica | Motivação |
|---|---|---|---|
| `n_crit{1,2,3}_{4,12,24,72}h` (12) | Contagem de eventos por criticidade em janelas retroativas | eventos da Tag com criticidade c em (t-N h, t] | A escada de severidade é o precursor físico do don't go |
| `n_dg_{4,12,24,72}h` (4) | Contagem de eventos cujo alarme consta no catálogo | idem, filtrado por Is_Dont_Go = 1 | Aproximação direta das pré-condições das regras |
| `quase_gatilhos_{12,24}h` (2) | Vezes em que um evento do catálogo se repetiu em menos de 6 h | 2ª ocorrência do mesmo EVENTO da Tag dentro de 6 h | As regras exigem QUANTIDADE de 2 a 10 na janela; a 2ª ocorrência é o meio do caminho mensurável |
| `n_tendencia_24h` | Eventos de tendência em 24 h | contagem por nome no conjunto TENDÊNCIA | Tendências são desenhadas pela engenharia como precursoras |
| `h_desde_crit1`, `h_desde_alerta_dg` | Horas desde o último evento crítico e o último alerta | t menos o último timestamp anterior, teto de 240 h | Recorrência: falha recente prediz falha próxima |
| `razao_taxa_24h_30d` | Taxa de eventos em 24 h dividida pela taxa média de 30 dias da própria Tag | n_24h / (n_720h/30) | Normaliza o temperamento de cada equipamento; captura anomalia relativa |
| `horas_operadas_24h`, `ciclos_24h`, `duracao_min`, `razao_duracao` | Utilização e ritmo | somas e contagens de apontamentos; duração dividida pela mediana da (Tag, Classe) | Exposição ao risco; ciclo anômalo é sintoma |
| `h_desde_manutencao` | Horas desde a última manutenção | idem "desde o último" (a base traz classe única "Manutenção") | Saúde renovada após intervenção |
| `hora`, `hora_sin/cos`, `dia_semana`, `fim_de_semana`, `mes`, `turno_{A,B}` | Calendário e turno | extração direta e codificação cíclica; turnos de 12 h (06h/18h) | Padrões de regime diurno e noturno |
| `frota_*`, `tipo_*`, `classe_*` (one-hot) | Cadastro do equipamento e classe do ciclo | one-hot (cardinalidade até 5) | Diferenças estruturais entre frotas (H3) |
| `tag_taxa_alerta`, `op_taxa_alerta`, `op_desconhecido` | Taxas históricas de alerta | target encoding com suavização bayesiana (m = 50), **estimado só em jan a mar** (anterior a todas as janelas de validação) | Cardinalidade alta (47 Tags, 396 operadores) inviabiliza one-hot; a taxa histórica carrega o sinal (H2) |

**Encoding categórico, com justificativa:** one-hot para baixa cardinalidade (Frota 5, Tipo 2, Classe 3, turno 2), por ser sem perda e interpretável; target encoding suavizado para `Tag` e operador (alta cardinalidade), estimado exclusivamente em janeiro a março de 2025, período anterior às duas janelas de tuning e ao teste, para eliminar vazamento; "OP_DESCONHECIDO" mantido como categoria com flag própria.

**Definição da variável alvo.** Ponto tratado de forma explícita, conforme o material revisado: **a coluna Is_Dont_Go não foi usada como rótulo oficial**. Ela indica apenas que o nome do alarme consta na lista monitorada, e uma ocorrência isolada de um evento listado não constitui alerta quando a regra exige repetição dentro da janela. O rótulo foi **recalculado** pelo motor de regras: para cada linha da CMA, o disparo acontece quando a QUANTIDADE de ocorrências do EVENTO, no nível exigido pela SITUACAO, acontece dentro de TEMPO minutos para o mesmo equipamento. Is_Dont_Go atua como pré-filtro de elegibilidade e como insumo de features. Interpretações registradas como decisões metodológicas: equivalência entre criticidade e nível OEM (Crítico equivale a nível 3, Não Crítico a nível 2, Informacional a nível 1); "N alarmes consecutivos" aproximado por "QUANTIDADE de ocorrências dentro de TEMPO minutos", aproximação conservadora que nunca dispara com menos eventos que o exigido; regras SISTEMA disparariam na ocorrência do evento, mas esses eventos não existem nesta extração; **cooldown de 6 horas** por (equipamento, regra) e colapso de disparos da mesma (Tag, EVENTO) em 30 minutos, prevalecendo o de maior NIVEL, para que um episódio físico único não vire dezenas de alertas. Resultado: **1.974 alertas** consolidados.

**Estratégia do target:** classificação binária, com y = 1 se existe alerta don't go do equipamento em (t, t + 4 h], sendo t o fim de cada apontamento fora de manutenção; complementada pela formulação de **sobrevivência** (tempo até o próximo alerta, com censura à direita), descrita na seção 2.5. **Justificativa da janela de 4 horas:** é o tempo operacional mínimo para ação corretiva ordenada: o despacho completa o ciclo corrente (cerca de 30 minutos), redireciona a máquina, e a manutenção prepara box, peças e equipe em 2 a 3 horas. Janelas maiores (8 horas ou mais) diluem a precisão e viram previsão de turno; janelas menores (1 a 2 horas) não dão tempo de agir. A regressão direta do tempo até o alerta sem tratamento de censura foi descartada: 95,1% dos pontos não têm alerta em horizonte curto, e ignorar a censura enviesaria o modelo, exatamente o problema que a formulação de sobrevivência resolve.

![Figura 7](figuras/fig07_janela_predicao.png)

### 2.4 Estratégia de validação (Tópico Sugerido 4.1)

Dados temporais não podem ser divididos aleatoriamente. Um k-fold padrão colocaria a tarde de uma degradação no treino e a manhã da mesma degradação no teste: o modelo "preveria" um episódio que já viu pela metade, inflando todas as métricas (vazamento temporal), além de contaminar os encodings de taxa histórica com informação do futuro.

Adotou-se **hold-out temporal** com cortes fixos (Figura 8): treino final de 01/01/2025 a 30/04/2025 (230.009 pontos, 66,9%, prevalência 5,72%); validação em maio/2025 (58.954 pontos, 17,2%, prevalência 3,14%), usada para a escolha dos limiares de operação; teste em junho/2025 (54.700 pontos, 15,9%, prevalência 3,29%), avaliado **uma única vez**, com limiares congelados.

**Tuning em duas janelas.** Um único mês de validação pode eleger hiperparâmetros ajustados às idiossincrasias daquele mês, e maio muda de regime na segunda quinzena (a prevalência cai de 3,9% para 2,5%; seção 3.2). Por isso cada configuração candidata foi avaliada em **duas janelas walk-forward independentes**, (treino jan a mar, validação abr) e (treino jan a abr, validação mai), e a seleção usou a **média do average precision** das duas. Para eliminar vazamento nas duas janelas, os target encodings foram estimados apenas em janeiro a março. Nenhuma estatística (encodings, escalas, hiperparâmetros, limiares) viu dados de validação ou de teste.

![Figura 8](figuras/fig08_validacao_temporal.png)

### 2.5 Baselines e modelagem principal (Tópicos Sugeridos 4.2 e 4.3)

**Baselines.** (1) **Dummy**: probabilidade a priori da classe, piso estatístico (AUC-PR igual à prevalência, 0,033 no teste). (2) **Heurística do despacho**: score igual ao número de alarmes do catálogo don't go nas últimas 12 horas. É a melhor aproximação do que um despachante atento faz hoje olhando o painel e, portanto, o baseline honesto a ser batido (teste: AUC-ROC 0,750, AUC-PR 0,245).

**Abordagem 1, supervisionada (classificação).** Três famílias com complexidade crescente, todas selecionadas pela média de AP nas duas janelas de tuning:

* **Regressão Logística** (StandardScaler, class_weight balanced; C entre 0,01 e 10; vencedor C = 0,1). Papel: fronteira linear interpretável.
* **Random Forest** (400 árvores, max_features raiz quadrada, class_weight balanced_subsample; min_samples_leaf entre 5, 20 e 60; vencedor 60). Papel: não linearidades sem tuning pesado.
* **LightGBM** com **busca aleatória de 30 configurações** sobre num_leaves (15 a 127), learning_rate (log-uniforme entre 0,01 e 0,2), min_child_samples (10 a 200), feature_fraction e bagging_fraction (0,6 a 1,0), regularizações L1 e L2 e scale_pos_weight (1, raiz de 16,5 ou 16,5), com early stopping monitorando average precision. Configuração vencedora (AP médio 0,223): num_leaves 31, learning_rate 0,011, min_child_samples 10, feature_fraction 0,75, bagging_fraction 0,93, reg_alpha 1,71, scale_pos_weight 4,1 e apenas **3 árvores**. Mesmo com duas janelas, a busca convergiu para um modelo compacto: com features de janela retroativa muito informativas, poucas árvores capturam o sinal estável entre regimes, e modelos maiores se ajustam a padrões que não persistem de um mês para o outro. A seleção por AUC-PR (e não por accuracy ou AUC-ROC) é deliberada: com cerca de 5% de positivos, é a métrica que discrimina modelos na região operacional.

**Abordagem 2, sobrevivência (Weibull AFT).** Em vez de "haverá alerta em 4 horas?", o modelo de tempo de falha acelerado pergunta **"quanto tempo até o próximo alerta?"**. Cada ponto de decisão vira uma observação com duração T (horas até o próximo don't go) e indicador de evento; pontos sem alerta observado são **censurados à direita** (fim da base em 30/06 ou teto de 21 dias). Implementação: `WeibullAFTFitter` (lifelines, penalizer 0,01) sobre as 16 variáveis de maior sinal, padronizadas no treino; 155.754 eventos observados em 230.009 observações de treino. O modelo produz duas saídas: o **risco acumulado em 4 horas** (1 menos S(4|x)), diretamente comparável aos classificadores, e os **fatores de aceleração** por desvio-padrão, interpretabilidade nativa (seção 3.4).

**Abordagem 3, não supervisionada.** (a) **Isolation Forest** (300 árvores, max_samples 0,5), treinado apenas com operação normal e sem os encodings supervisionados; os alertas do teste servem somente como ground truth de validação. (b) **K-Means** (k = 4, variáveis padronizadas) sobre agregados equipamento-dia, para descobrir perfis de comportamento e sua associação com a incidência de alertas.

### 2.6 Critérios de avaliação e pontos de operação (Tópico Sugerido 5.1)

Com prevalência de 3,3% no teste, accuracy é inútil (o Dummy "acerta" 96,7%). As métricas primárias são **AUC-PR**, **Recall** e **Precision** no limiar operacional, com **AUC-ROC** como visão complementar e o C-index para o modelo de sobrevivência. O custo dos erros é assimétrico: um falso negativo é uma parada não planejada (horas de máquina, risco de dano secundário e de segurança); um falso positivo custa cerca de 1 hora de inspeção. O campeão opera em **dois limiares escolhidos na validação e congelados antes do teste**: o ponto F2 (recall pesa o dobro da precisão, prioriza captura) e o ponto **custo-ótimo**, que maximiza o benefício líquido estimado em reais sob as premissas financeiras explícitas (seção 3.6).

## 3. Resultados e Discussões

### 3.1 Comparação de modelos

| Modelo | Conjunto | Precision | Recall | F1 | F2 | AUC-ROC | AUC-PR | Observações |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Dummy | teste | 0,033 | 1,000 | 0,064 | 0,145 | 0,500 | 0,033 | piso estatístico |
| Heurística (alarmes 12 h) | teste | 0,147 | 0,590 | 0,235 | 0,368 | 0,750 | 0,245 | prática atual de painel |
| Regressão Logística | teste | 0,107 | 0,624 | 0,183 | 0,318 | 0,847 | 0,279 | C = 0,1, balanced |
| Random Forest | teste | 0,161 | 0,664 | 0,259 | 0,409 | 0,868 | **0,320** | leaf = 60; maior AUC-PR |
| **LightGBM (campeão)** | **teste** | **0,187** | **0,595** | **0,284** | **0,414** | **0,870** | 0,296 | limiar F2 = 0,062 |
| Weibull AFT (risco em 4 h) | teste | n/a | n/a | n/a | n/a | 0,841 | 0,266 | C-index 0,781 |
| Isolation Forest (não supervisionado) | teste | n/a | n/a | n/a | n/a | 0,560 | 0,174 | sem rótulo no treino |

A seleção do campeão seguiu o critério pré-registrado, a média de AP nas duas janelas de tuning: LightGBM 0,223, Random Forest 0,216, Regressão Logística 0,119, heurística 0,102. No teste o resultado é um **empate técnico entre os dois modelos de árvore**: o LightGBM lidera em AUC-ROC (0,870) e F2 (0,414); o Random Forest, em AUC-PR (0,320). A diferença entre eles é menor que a oscilação quinzenal do próprio teste (seção 3.2), e ambos superam a heurística com folga. Mantém-se o LightGBM como campeão pelo critério definido antes de tocar o teste: trocar de modelo depois de ver o teste seria exatamente o vício metodológico que o desenho evita. O Weibull AFT, com formulação completamente diferente (tempo até o evento, com censura), confirma o mesmo ranking de risco (AUC-ROC 0,841): três famílias de modelo concordando é evidência de sinal real, não de artefato. As curvas ROC e Precision-Recall estão na Figura 9.

![Figura 9](figuras/fig09_roc_pr.png)

### 3.2 Análise de erros (Tópico Sugerido 5.2)

**Matriz de confusão (teste, ponto F2, limiar 0,062):**

| | Previsto: sem alerta | Previsto: alerta |
|---|---:|---:|
| **Real: sem alerta** | VN = 48.246 | FP = 4.655 |
| **Real: alerta** | FN = 729 | VP = 1.070 |

Tradução operacional: no ponto F2, o modelo teria emitido 5.725 cartões de inspeção em junho (cerca de 191/dia na frota de 47), carga desenhada para capturar o máximo de alertas e adequada apenas se a inspeção for barata e acoplada à rotina (verificação visual no abastecimento, por exemplo). No **ponto custo-ótimo** (limiar 0,074), os cartões caem para 1.340 no mês (cerca de 45/dia, aproximadamente 1 por equipamento-dia), com precisão de 41,9%, quase um acerto a cada dois cartões. A escolha entre os dois pontos é uma decisão de capacidade da equipe, e a seção 3.6 quantifica o valor de cada um. Os falsos negativos (729 no ponto F2) são o custo residual: paradas que continuariam chegando sem aviso.

**Casos extremos, onde o modelo sistematicamente falha (Figura 10 e tabelas de FN, no ponto F2):**

* **Frota LeTourneau L 1850: 100% de falso negativo** (7 positivos, todos perdidos). É a frota com os alertas mais raros (2,1 por 1.000 h, 16 vezes menos que os caminhões) e regras de disparo imediato (`Hydraulic Reservoir Oil Temperature Critically High`), com pouca escada precursora; paradoxalmente, é também a frota que gera 91% do volume de telemetria, quase todo informacional.
* **Assimetria entre subsistemas de freio:** `Right Front Brake Temperature - Active` tem apenas 5,8% de FN (480 positivos, o modelo domina o padrão), enquanto as temperaturas de freio **traseiras** têm cerca de 67% de FN (168 positivos). O precursor existe no eixo dianteiro e é fraco no traseiro, pista concreta para investigação de instrumentação.
* **`Aftercooler Level - Active` (74,4% de FN, 121 positivos)** e **`Engine Coolant Flow - Active` (78,3%, 46)**: perdas de nível e de fluxo podem ser abruptas (vazamento), sem rampa prévia de eventos. Já `Transmission Oil Level - Active`, o evento mais frequente do teste (586 positivos), tem 46,8% de FN: o modelo captura a maioria.
* A frota 793-D 4S tem 26% de FN contra 50% da 5S: a 4S dispara mais escada de eventos nível 2 antes do alerta.

**Degradação temporal (drift).** AUC-ROC por quinzena: maio 0,866 e 0,758; junho 0,863 e 0,876. AUC-PR: maio 0,293 e **0,089**; junho 0,245 e 0,337. A queda abrupta na segunda quinzena de maio acompanha a queda de prevalência (3,85% para 2,51%), e foi exatamente esse comportamento que motivou o tuning em duas janelas (seção 2.4); em junho o desempenho se recupera e cresce ao longo do mês. Não há tendência monotônica de queda: o padrão é de **sensibilidade a regime** (surtos contra calmaria), não de concept drift acumulado, e a recomendação operacional é re-treino frequente (semanal) com monitoramento de prevalência.

![Figura 10](figuras/fig10_matriz_confusao.png)

### 3.3 Interpretabilidade (Tópico Sugerido 5.3)

O SHAP summary (Figura 11) valida o modelo contra a intuição operacional; as seis variáveis mais importantes têm leitura física direta:

1. **`h_desde_alerta_dg`** (impacto médio 0,027): pouco tempo desde o último alerta indica recorrência provável; é a variável mais forte do modelo. Manutenção que não elimina a causa raiz devolve a máquina para a mesma fila.
2. **`h_desde_crit1`** (0,020): proximidade do último evento crítico, o degrau final da escada de severidade.
3. **`n_dg_4h`** (0,019) e **`n_dg_12h`** (0,013): rajada de alarmes do catálogo em janela curta, a matéria-prima das regras.
4. **`tag_taxa_alerta`** (0,013) e **`op_taxa_alerta`** (0,008): o "quem"; equipamento cronicamente ofensor e operador com histórico elevado (H2 e H3 dentro do modelo).

Nenhuma variável importante carece de explicação operacional, critério de validação de sentido atendido. O waterfall (Figura 12) decompõe a predição de maior score entre os verdadeiros positivos (CA65926, justamente o equipamento mais ofensor do semestre, em 28/06/2025 03:00): **77 alarmes do catálogo nas últimas 4 horas** (236 em 12 horas), **alerta anterior há 3,4 horas** e **evento crítico há cerca de 1 minuto** somam +0,38 em log-odds sobre a base de -2,75, levando o equipamento ao topo do ranking do dia; ele disparou novo alerta dentro da janela. É o caso de uso do painel: o cartão de inspeção viria com essas três evidências listadas.

![Figura 11](figuras/fig11_shap_summary.png)

![Figura 12](figuras/fig12_shap_waterfall.png)

### 3.4 Abordagens complementares: sobrevivência e não supervisionada

O **Weibull AFT** responde uma pergunta que o classificador não alcança: quanto tempo até o próximo alerta. Com C-index de 0,781 no teste, o ranqueamento de tempos é sólido, e os **fatores de aceleração** (razão de tempo por +1 desvio-padrão, todos com p < 0,05) contam a mesma história física do SHAP por outro caminho:

| Feature | Razão de tempo (por +1 dp) | Leitura |
|---|---:|---|
| `tag_taxa_alerta` | **0,60** | equipamento cronicamente ofensor encurta o tempo até o alerta em 40% |
| `horas_operadas_24h` | 0,79 | uso intenso acelera a falha (exposição) |
| `op_taxa_alerta` | 0,82 | o operador acelera ou adia o alerta |
| `n_dg_24h` | 0,85 | rajada de alarmes do catálogo encurta o relógio |
| `h_desde_manutencao` | 1,67 | máquina há muito sem intervenção e ainda sem alarmes tende a seguir saudável |
| `h_desde_alerta_dg` | **1,86** | quanto mais longe do último alerta, mais longo o tempo até o próximo (recorrência) |

Convergência entre formulações independentes, classificação (SHAP) e sobrevivência (AFT), é o teste de robustez mais forte deste trabalho: o sinal de recorrência, rajada e "quem" (equipamento e operador) domina nos dois. Como risco em 4 horas, o AFT alcança AUC-ROC 0,841 e AUC-PR 0,266, abaixo dos modelos de árvore (que capturam interações não lineares), mas acima da Regressão Logística e da heurística, entregando de brinde a estimativa de tempo que a manutenção usa para sequenciar a fila.

O **Isolation Forest**, sem nunca ver um rótulo, alcança AUC-ROC de 0,560 e AUC-PR de 0,174 no teste: acima do acaso, mas muito abaixo do supervisionado. Nesta base, "estar anômalo" não é bom preditor de don't go, em grande parte porque a L-1850 produz anomalias de volume (tempestades de telemetria) que não terminam em alerta. O detector permanece útil como cerca de segurança para modos de falha novos, ainda sem regra no catálogo, mas não substitui o modelo supervisionado.

O **K-Means** (k = 4) sobre agregados equipamento-dia encontrou uma partição com leitura operacional imediata:

| Perfil | Dias | Eventos/24h | Nível 2/24h | Alarmes catálogo/24h | Quase-gatilhos | Horas operadas | Taxa de alerta |
|---|---:|---:|---:|---:|---:|---:|---:|
| Pré-falha | 19 (0,2%) | 3.582 | 981 | 439 | 437 | 19,7 | **84%** |
| Operação plena | 4.546 (45%) | 9.455 | 132 | 4,9 | 4,2 | 20,3 | 24% |
| Dia parado ou ocioso | 2.714 (27%) | 158 | 5,8 | 0,3 | 0,2 | 0,5 | 2% |
| Tempestade de telemetria | 2 | 1.334.184 | 282 | 0 | 0 | 19,4 | 0% |

O perfil pré-falha é raro (19 equipamento-dias) mas quase determinístico: 84% de chance de alerta, um "estado da máquina" exibível como semáforo no painel do despacho. O quarto perfil é um achado de qualidade de dados: dois dias em que um único equipamento emitiu **mais de 1,3 milhão de eventos** em 24 horas sem nenhum alerta, flooding do coletor, não degradação física, que merece um watchdog próprio.

### 3.5 Priorização da fila de inspeção

O score ordena a fila de manutenção continuamente. No último dia do teste (30/06), os cinco primeiros da fila (CA65926, CA65927, CA65909, CA65924 e CA65935) concentravam os maiores riscos residuais da frota, e quatro deles estão entre os dez maiores ofensores do semestre. Ao longo de junho, seguir a fila do modelo no ponto de captura teria colocado a equipe de inspeção na máquina certa antes do alerta em quase 7 de cada 10 disparos (antecipação de 68,6%).

### 3.6 Impacto de negócio (Tópico Sugerido 6.1)

**Comparação com baseline.** No ranking, os modelos de árvore superam a heurística do despacho em **31% de AUC-PR** (Random Forest 0,320 contra 0,245) e **16 pontos de AUC-ROC** (LightGBM 0,870 contra 0,750); sobre o Dummy, o ganho de AUC-PR é de 9 vezes. No ponto de operação custo-ótimo o contraste é direto: a cada 100 cartões de inspeção, a heurística acerta 15 e o modelo **42**, quase o triplo de aproveitamento da equipe.

**Dois pontos de operação, ambos escolhidos na validação e congelados antes do teste.** Premissas explícitas, a calibrar com o planejamento: custo de indisponibilidade de R$ 6.000/h, inspeção de R$ 450, 35% da duração economizável quando a intervenção é antecipada, episódio médio de manutenção de 6,72 horas reconstruído por encadeamento de ciclos (seção 2.2):

| Indicador (teste, jun/2025) | Ponto F2 (captura) | Ponto custo-ótimo (R$) |
|---|---:|---:|
| Limiar | 0,062 | 0,074 |
| Precisão / Recall | 18,7% / 59,5% | 41,9% / 31,2% |
| Alertas antecipados (de 229) | 157 (**68,6%**) | 103 (45,0%) |
| Antecedência mediana do 1º aviso | 3,4 h | 3,1 h |
| Cartões de inspeção no mês | 5.725 (cerca de 191/dia) | 1.340 (cerca de 45/dia) |
| Horas de parada evitáveis | 369,0 h | 242,1 h |
| Benefício bruto | R$ 2,21 milhões | R$ 1,45 milhão |
| Custo das inspeções vazias | R$ 2,09 milhões | R$ 0,35 milhão |
| **Benefício líquido no mês** | R$ 119 mil | **R$ 1,10 milhão** |

A leitura é operacional: com equipe de inspeção folgada (ou inspeções acopladas ao abastecimento), o ponto F2 captura mais alertas e ainda se paga; com equipe restrita, o ponto custo-ótimo entrega R$ 1,10 milhão líquido por mês com um cartão por equipamento-dia. O painel pode expor os dois níveis como "atenção" (F2) e "inspecionar agora" (custo-ótimo): o mesmo score, duas ações.

**Aferição da métrica de sucesso (seção 1.2):** as duas metas não são atingíveis simultaneamente com esta base. O ponto F2 atinge a meta de antecipação (68,6%, acima de 60%) mas não a de precisão (18,7%, abaixo de 30%); o ponto custo-ótimo atinge a de precisão (41,9%) mas não a de antecipação (45,0%). Registra-se a meta como **parcialmente atingida em cada ponto**, com o trade-off completo quantificado em reais para decisão do negócio, o que é mais útil que um único número que esconderia a escolha.

![Figura 13](figuras/fig13_baseline_vs_modelos.png)

### 3.7 Insights não óbvios

1. **Volume de telemetria não é risco.** A frota L-1850 gera 91,2% dos 37 milhões de eventos (98,5% informacionais) e apenas 1,2% dos alertas, e é a única frota 100% imprevisível para o modelo. O caminho para ela é curadoria de eventos e sensorização dirigida, não mais dados brutos.
2. **Recorrência é o padrão dominante.** As duas variáveis mais fortes do SHAP são os tempos desde o último alerta e desde o último evento crítico, e o AFT confirma pela via independente (razões de tempo 1,86 e 1,67). Parte relevante dos don't go é a mesma causa raiz mal resolvida voltando: um indicador de qualidade de manutenção, não só de condição do ativo.
3. **O operador importa.** Entre 124 operadores com pelo menos 800 decisões, a taxa varia de 0% a 15,3%, e `op_taxa_alerta` aparece no topo do SHAP e nos fatores do AFT. Há um programa de treinamento operacional escondido nesses dados.
4. **O precursor depende do subsistema, não só do evento.** Temperatura de freio dianteiro direito: 94% de recall; freios traseiros: cerca de 33%. Mesma física, instrumentação e dinâmica diferentes, um mapa direto para priorizar melhorias de sensores.
5. **A base fatia atividades em ciclos de 60 minutos.** Qualquer análise de duração (inclusive o próprio impacto financeiro) exige reconstrução de episódios: a duração média por registro de manutenção é 0,5 hora; por episódio real, 6,7 horas. Ignorar isso subestimaria o benefício em cerca de 8 vezes.

## 4. Conclusão e Trabalhos Futuros

### 4.1 Conclusão (Tópico Sugerido 6.2)

Retomando a pergunta da seção 1.2: **quais equipamentos têm maior risco de gerar um alerta don't go nas próximas 4 horas?** A pergunta foi respondida com uma solução completa e reprodutível que, a cada fechamento de ciclo, ranqueia a frota por probabilidade de alerta. No teste cego (junho/2025), o ranking tem AUC-ROC de 0,870 (Random Forest: AUC-PR 0,320, 9 vezes a prevalência) e opera em dois pontos escolhidos na validação: captura (68,6% dos alertas antecipados, mediana de 3,4 horas de aviso) e custo-ótimo (precisão de 41,9% e benefício líquido de R$ 1,10 milhão no mês). O modelo aprendeu mecanismos com respaldo físico (recorrência, rajadas de alarmes monitorados, efeito do equipamento e do operador), verificados por duas vias independentes: SHAP no classificador e fatores de aceleração no modelo de sobrevivência.

**Limitações, com honestidade:** (i) seis meses de dados não cobrem a sazonalidade anual completa (estação chuvosa contra seca); (ii) o rótulo deriva do catálogo CMA, e imprecisões nas regras propagam para o alvo ("consecutivos" foi aproximado por contagem em janela, decisão documentada), sendo que as regras de TENDÊNCIA e SISTEMA não têm eventos correspondentes nesta extração; (iii) o operador dos apontamentos foi **derivado** da telemetria (tolerância de 6 horas): 18,6% dos ciclos ficaram sem operador, concentrados em 15 Tags sem telemetria, cujas decisões nunca podem ser positivas (viés estrutural documentado); (iv) a telemetria é de eventos, sem as séries contínuas de sensores, que elevariam o teto de desempenho; (v) o campeão é um modelo deliberadamente compacto (3 árvores), com score granular (533 valores distintos no teste), suficiente para fila e limiares, mas não para probabilidades finamente calibradas; (vi) as premissas financeiras são estimativas de ordem de grandeza, e o limiar custo-ótimo herda essa incerteza; (vii) generalização para outras localidades exige re-treino, pois os padrões aprendidos são específicos desta frota e catálogo.

### 4.2 Trabalhos futuros (Tópico Sugerido 6.3)

1. **Novos dados:** integrar as ordens de serviço do ERP de manutenção (causa raiz real, componente trocado, horímetro) para separar alerta antecipável de manutenção mal executada, hipótese sustentada pelo peso da recorrência no SHAP e no AFT; incorporar dados climáticos horários; e conectar as séries contínuas do historiador de sensores, cruciais para os eventos de nível sem rampa, como `Aftercooler Level`.
2. **Novas formulações:** evoluir o Weibull AFT para **sobrevivência por subsistema** (riscos competitivos: freio, nível, arrefecimento, qual falha vem primeiro?) e classificação multirrótulo do tipo de alerta, entregando à manutenção o subsistema suspeito junto com o cartão; sensorização dirigida para os pontos cegos mapeados (freios traseiros e frota L-1850).
3. **Abordagens alternativas de operação:** aprendizado online com re-treino semanal e monitoramento de prevalência e de AUC-PR móvel (a rotina de degradação temporal da seção 3.2 é o embrião, e a queda da segunda quinzena de maio mostra por que é necessária); calibração isotônica sobre o score granular; e as rotinas de robustez já incluídas no repositório (walk-forward mensal, sensibilidade da janela de predição e varredura completa de custo por limiar) incorporadas ao ciclo de re-treino.
4. **Integração operacional:** publicar o score via API no sistema de despacho com atualização por evento (o desenho de janelas ordenadas migra direto para streaming), cartões em dois níveis ("atenção" e "inspecionar agora") com as evidências SHAP, semáforo dos perfis K-Means como leitura rápida (o perfil pré-falha tem 84% de acerto), watchdog de flooding de telemetria (perfil "tempestade") e ciclo de feedback do inspetor (achou ou não achou problema) realimentando o treino, transformando cada falso positivo em rótulo novo.

---

## Referências e Recursos

* Alarmes - Regra de Negocio_V2.xlsx: catálogo de regras de negócio para alertas don't go, aba CMA (pasta `dados/negocio/`).
* Dicionario_Dados.xlsx: dicionário das tabelas Apontamentos e Telemetria.
* Estudo Guiado e Notas de Revisão do Material de Apoio, Desafio Análise Avançada de Dados, Programa Desenvolver, Edição 2026.
* scikit-learn: https://scikit-learn.org
* LightGBM: https://lightgbm.readthedocs.io
* SHAP: https://shap.readthedocs.io
* lifelines (análise de sobrevivência): https://lifelines.readthedocs.io
* Ke, G. et al. LightGBM: A Highly Efficient Gradient Boosting Decision Tree. NeurIPS, 2017.
* Lundberg, S.; Lee, S.-I. A Unified Approach to Interpreting Model Predictions. NeurIPS, 2017.
* Provost, F.; Fawcett, T. Data Science para Negócios. Alta Books, 2016.
