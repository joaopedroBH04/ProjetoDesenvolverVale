# Relatório Final — Desafio: Análise Avançada de Dados

## Antecipação de Alertas Críticos em Frotas de Mineração

**João Pedro Costa**
pedrojoaao4@gmail.com
Programa Desenvolver — Edição 2026

---

**Resumo.** Este trabalho aborda a antecipação de alertas críticos de condição ("don't go") em uma frota de 47 equipamentos de mina em Itabira — caminhões fora de estrada CAT 793-D (frotas 2S a 5S) e escavadeiras LeTourneau L-1850 — a partir de duas fontes: os apontamentos de ciclo operacional (377.907 registros) e a telemetria embarcada (37,16 milhões de eventos), cobrindo seis meses de operação (jan a jun/2025). O catálogo de regras de negócio (151 regras TIPO + EVENTO + SITUACAO + QTD + TEMPO + NIVEL) foi convertido em um motor de regras em Python que rotulou 1.974 alertas don't go no período. O problema foi formulado como classificação binária: prever, ao fim de cada ciclo de apontamento, se o equipamento disparará um alerta don't go nas 4 horas seguintes — janela definida pelo tempo necessário para o despacho retirar o equipamento de rota e a manutenção preparar box, peças e equipe. Após limpeza com controle de alterações (todas as decisões documentadas, incluindo a derivação do operador por casamento temporal com a telemetria), foram construídas 50 features de janelas retroativas (contagens de eventos por criticidade em 4/12/24/72 h, "quase-gatilhos" das regras, tempos desde o último evento crítico, utilização, encodings de frota, operador e equipamento), gerando uma tabela analítica com 343.663 pontos de decisão e prevalência de 4,89%. A validação foi estritamente temporal (treino jan–abr/2025; validação mai/2025 para tuning e limiar; teste jun/2025 tocado uma única vez). Três modelos supervisionados foram comparados contra dois baselines, além de uma abordagem não supervisionada (Isolation Forest e K-Means). O LightGBM venceu com AUC-ROC 0,864 e AUC-PR 0,317 no teste — 30% acima do AUC-PR da heurística de despacho (0,245) e 9,6 vezes a prevalência —, entregando recall de 46,3% e precisão de 24,5% no limiar operacional (F2). Em termos de negócio: 60,7% dos 229 alertas de junho foram antecipados com mediana de 3,2 h de antecedência, o equivalente a ~327 h de parada não planejada evitável e benefício líquido estimado de R$ 805 mil no mês. A análise SHAP confirmou que o modelo aprendeu a física do problema (recorrência de alertas e rajadas de alarmes monitorados em janelas curtas dominam o risco), e a análise de erros revelou dois achados centrais: a frota L-1850 gera 91% do volume de telemetria mas apenas 1,2% dos alertas — e é justamente a mais imprevisível (100% de falsos negativos) —, e o desempenho do ranking oscila com a prevalência quinzenal, reforçando a necessidade de re-treino frequente em produção.

**Palavras-chave:** manutenção preditiva; telemetria industrial; alertas don't go; LightGBM; validação temporal; SHAP; mineração.

---

## 1. Introdução

Uma mina de grande porte opera como um sistema de fluxo contínuo: escavadeiras alimentam caminhões fora de estrada que ciclam entre frentes de lavra, britadores e pilhas. Cada equipamento gera dois rastros digitais permanentes. O primeiro é o **apontamento**: o sistema de despacho registra cada ciclo de atividade com início, fim, equipamento (Tag), frota, tipo e classe da atividade. O segundo é a **telemetria embarcada**: os módulos OEM emitem eventos de condição — nível de fluido, temperatura de freio, pressão de óleo — classificados em níveis de severidade, além de tendências calculadas pela engenharia de confiabilidade e eventos de sistema, com a identificação anonimizada do operador no turno.

Sobre esse fluxo de eventos, a área de Confiabilidade (CMA) mantém um catálogo de **regras don't go**: combinações de evento, situação, quantidade e janela de tempo que, quando satisfeitas, determinam que o equipamento **não deve continuar operando**. O disparo de um don't go é, hoje, reativo: quando a regra fecha, a máquina já precisa sair de rota — muitas vezes carregada, em rampa, no meio do turno — e a manutenção recebe o problema sem aviso.

O objetivo central deste trabalho é transformar esse fluxo reativo em **antecipação**: construir um pipeline de dados completo (ETL, rotulagem via regras de negócio, engenharia de features, modelagem e avaliação) capaz de estimar, a cada ciclo encerrado, a probabilidade de cada equipamento disparar um alerta don't go nas 4 horas seguintes, e de traduzir essa probabilidade em uma fila priorizada de inspeção. A tomada de decisão baseada em dados aqui não é abstrata: cada hora de caminhão de 240 t parado fora de plano é produção não realizada, e cada alerta antecipado converte uma quebra em intervenção planejada.

## 2. Entendimento do Negócio

### 2.1 Contextualização da operação (CM 1.1)

**Fluxo operacional.** Cada registro da tabela `Apontamentos` representa um ciclo de atividade de um equipamento, delimitado por `Inicio` e `Fim`, com a identificação do equipamento (`Tag`), o modelo/frota (`Frota`: 793-D 2S/3S/4S/5S, LeTourneau L 1850), o tipo (`Tipo`: Caminhao, Escavadeira) e a classificação da atividade (`Classe`: Operando, Parado, Hibernando, Manutenção). A base analisada cobre **47 equipamentos** da localidade de Itabira, operando em dois turnos de 12 h (A: 06–18 h, B: 18–06 h). O extrato de apontamentos recebido não traz o operador; essa informação foi derivada da telemetria (seção 3.3).

A tabela `Telemetria` registra os eventos emitidos pelos módulos embarcados: `Data_Evento`, turno, localidade, equipamento, operador anonimizado (`Nome_Operador_Anon`, `Matricula_Operador_Hash`), alarme (`Id_Alarme`, `Alarme`), criticidade (`Id_Criticidade`: 1=Crítico, 2=Não Crítico, 3=Informacional, 4=Outros), valor lido pelo sensor (`Valor`, com vírgula como separador decimal) e a flag `Is_Dont_Go` indicando se o nome do alarme consta na lista don't go.

**Alertas don't go.** Um alerta don't go sinaliza condição na qual o equipamento **não deve operar**. O impacto é triplo: (i) **segurança** — um caminhão com temperatura de freio crítica descendo rampa carregado é um risco inaceitável; (ii) **disponibilidade** — a máquina sai do plano de produção sem aviso; (iii) **custo do ativo** — operar sob alarme de pressão de óleo do motor transforma uma intervenção de horas em uma troca de componente de semanas.

**Regras de negócio.** O arquivo `Alarmes - Regra de Negocio.xlsx` (aba CMA — o catálogo referido no estudo guiado como Alarmes - SUL_SUDESTE.xlsx) define quando um alerta dispara: **151 regras**, cada uma combinando TIPO (142 ALARME OEM, 7 TENDÊNCIA, 2 SISTEMA), EVENTO (nome do alarme), SITUACAO (condição de disparo, ex.: "Mediante alarme nível 3", "Mediante cinco alarmes nivel 2 consecutivos", "Em qualquer situação"), QTD (1 a 10 ocorrências), TEMPO (janela de 0, 360 ou 720 minutos) e NIVEL (Muito Alto ou Alto). O arquivo é equivalente a regras codificadas — e foi exatamente assim que este trabalho o tratou, convertendo-o em um motor de regras em Python (seção 3.3).

Exemplos de eventos de NIVEL **Muito Alto** (criticidade máxima): `Low Transmission Oil Level` (mediante alarme nível 3), `Engine Coolant Level - Active`, `Very Low Hydraulic Oil Level`, `Engine Overheat/Engine Coolant or Water Overheat`, `Low Engine Oil Pressure`, `High Engine Coolant Temperature`, temperaturas de freio (`High Left/Right Front/Rear Brake Oil Temperature`), `Hydraulic Reservoir Oil Temperature Critically High (L-1850)`, `HPD Gearbox Oil Pressure Critically Low`, as tendências `MC - Tendência baixa pressão do óleo motor <250/200/150KPA` e a regra de sistema `MEMS não comunica`.

![Figura 1](figuras/fig01_fluxo_operacional.png)

### 2.2 Definição do problema analítico (CM 1.2)

**Pergunta principal:**

> **Quais equipamentos têm maior risco de gerar um alerta don't go nas próximas 4 horas, considerando o padrão atual de operação?**

Perguntas secundárias respondidas ao longo do trabalho:

* O comportamento do operador (anonimizado) tem correlação com a frequência de alertas em um mesmo equipamento? (seções 3.2 e 4.6)
* Qual é o perfil dos equipamentos que geram mais alertas don't go — frota, tipo e horas trabalhadas? (seções 3.2 e 4.6)
* Alertas críticos se concentram em determinados turnos, dias da semana ou períodos do mês? (seção 3.2)
* Como priorizar a fila de inspeção da manutenção com base no score de risco? (seção 4.5)

**Métrica de sucesso do negócio.** O problema é considerado "resolvido" se o modelo (i) **antecipar ao menos 60% dos alertas don't go** com aviso dentro da janela de 4 h e (ii) manter a carga de falsos positivos em nível absorvível pela rotina de inspeção (precisão ≥ 30%, ou seja, no máximo ~2 inspeções vazias para cada acerto). Como referência de valor: cada alerta antecipado converte parte de uma intervenção corretiva de emergência (episódio médio de 6,7 h na base) em intervenção planejada.

**Cenário de aplicação.** A cada fechamento de ciclo de apontamento (em média a cada ~30 min por equipamento), o pipeline recalcula o score de risco e atualiza um painel no sistema de monitoramento do despacho. Score acima do limiar acende um cartão "inspecionar nas próximas 4 h": o dispatcher redireciona o caminhão para uma rota próxima da oficina ou antecipa o abastecimento para coincidir com a inspeção, e a manutenção recebe a fila priorizada com o subsistema suspeito (derivado dos eventos que sustentam o score, via SHAP).

## 3. Metodologia

A metodologia segue o CRISP-DM: entendimento dos dados (3.2), preparação (3.3), modelagem (3.4–3.5) e avaliação (seção 4), sustentadas por um pipeline ETL reprodutível (3.1).

### 3.1 Arquitetura da solução e pipeline ETL

O pipeline foi implementado em Python 3 (pandas, scikit-learn, LightGBM, SHAP) e organizado em módulos com responsabilidade única, executáveis de ponta a ponta por `executar_pipeline.py`:

1. **Extração** (`src/etl/extracao.py`) — leitura dos extratos Parquet do data lake (Apontamentos em arquivo único; Telemetria particionada por mês, 6 arquivos), com tipagem explícita e **leitura colunar seletiva**: das 18 colunas da telemetria, apenas as 10 consumidas pelo pipeline são carregadas — decisão necessária para processar 37,16 milhões de eventos em memória. Inclui o enriquecimento do operador nos apontamentos por casamento temporal com a telemetria (seção 3.3).
2. **Transformação** (`src/etl/transformacao.py`) — limpeza com **controle de alterações**: cada correção ou exclusão gera uma linha de log ANTES/DEPOIS com justificativa (tabela na seção 3.3).
3. **Carga** (`src/etl/carga.py`) — materialização da camada tratada em **Parquet** (colunar, tipado; preserva dtypes entre etapas e permite reprocessamento parcial).
4. **Rotulagem** (`src/regras/motor_regras.py`) — aplicação das 151 regras do catálogo sobre a telemetria limpa.
5. **Features** (`src/features/engenharia.py`) — construção da tabela analítica (ABT) por varredura vetorizada (busca binária sobre arrays ordenados por equipamento).
6. **Modelagem e avaliação** (`src/modelos/`, `src/avaliacao/`) — treino, tuning, métricas, análise de erros, SHAP e impacto.
7. **Visualização** (`src/viz/figuras.py`) — geração das 13 figuras do relatório.

Critérios de arquitetura: separação entre camadas bruta/tratada/analítica (medalhão simplificado), reprodutibilidade (semente fixa, split por data), e escalabilidade do desenho — as agregações por janela usam apenas ordenação temporal por equipamento, o que se traduz diretamente para janelas deslizantes em streaming (Spark Structured Streaming/Flink) no cenário de produção. O pipeline completo (ETL → rotulagem → ABT → treino → avaliação → figuras) roda em ~8 min sobre os 37 milhões de eventos.

### 3.2 Entendimento dos dados — EDA (CM 2.1, 2.2, 2.3)

**Carga e inspeção inicial (CM 2.1).**

| Tabela | Linhas | Colunas | Nulos (total) | Duplicatas | Janela temporal |
|---|---:|---:|---:|---:|---|
| Apontamentos | 377.907 | 9 (7 da origem + 2 derivadas) | 140.264 | 0 | 01/01/2025 00:00 — 30/06/2025 23:57 |
| Telemetria | 37.164.054 | 10 (de 18 na origem) | 0 | 0 | 01/01/2025 00:00 — 30/06/2025 23:59 |

Os 140.264 nulos dos apontamentos estão concentrados nas duas colunas de operador derivadas por casamento temporal (70.132 ciclos sem evento de telemetria do mesmo equipamento em ±6 h — majoritariamente as 15 Tags sem telemetria no período). A frequência média é de ~2.086 apontamentos/dia (≈44 ciclos por equipamento-dia) e ~205 mil eventos de telemetria/dia, estáveis ao longo do semestre (Figura 2).

Estatísticas descritivas das variáveis numéricas (antes da limpeza):

| Tabela | Feature | Tipo | % Nulos | Min | Max | Média | Mediana | Desvio Padrão |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Apontamentos | duracao_min (derivada) | float64 | 0,00 | 0,02 | **60,0** | 29,7 | 22,9 | 24,0 |
| Telemetria | Valor | float64 | 0,64 | 0,0 | 4.347 | 4,6 | 0,0 | 28,5 |
| Telemetria | Id_Criticidade | int64 | 0,00 | 1 | 4 | 2,98 | 3 | 0,15 |
| Telemetria | Is_Dont_Go | int8 | 0,00 | 0 | 1 | 0,0005 | 0 | 0,02 |
| Telemetria | Dia | int64 | 0,00 | 1 | 31 | 16,0 | 16 | 8,9 |

Dois achados estruturais orientaram a preparação: (i) a duração máxima de exatamente **60 minutos** revela que o sistema de origem **fatia atividades longas em ciclos de até 1 h** — qualquer métrica de duração de atividade (ex.: tempo de manutenção) precisa reconstruir episódios encadeando ciclos consecutivos; (ii) 98,5% dos eventos de telemetria são de criticidade 3 (informacional) e apenas 19.962 eventos (0,05%) carregam a flag `Is_Dont_Go` — o sinal relevante para as regras é uma agulha em um palheiro de 37 milhões de eventos. `Valor` usa vírgula como separador decimal na origem (tratado na transformação) e é 0 na mediana (alarmes de estado não carregam leitura).

![Figura 2](figuras/fig02_volume_temporal.png)

**Análise da variável alvo (CM 2.2).** Após a rotulagem pelo motor de regras (seção 3.3), o período contém **1.974 alertas don't go** — 10,9/dia na frota, ou 0,23 por equipamento-dia:

| TIPO | NIVEL | Alertas |
|---|---|---:|
| ALARME OEM | Muito Alto | 1.420 |
| ALARME OEM | Alto | 554 |

Nenhuma regra de TIPO TENDÊNCIA ou SISTEMA disparou no período — os eventos correspondentes não ocorrem nesta extração de telemetria, o que é em si um achado de cobertura de dados (as tendências da engenharia e os watchdogs de comunicação não estão fluindo para esta base). Os dez equipamentos mais ofensores concentram **57,8%** dos alertas (CA65926 lidera com 152; CA65930 com 141; CA65927 com 123), enquanto a mediana entre os 32 equipamentos com alerta é 59,5 — a cauda pesada é exatamente o que uma fila de inspeção priorizada explora. **Balanceamento:** nos 343.663 pontos de decisão da ABT, a classe positiva (alerta nas próximas 4 h) representa **4,89%** — desbalanceamento de ~1:19 que orientou a escolha de métricas (AUC-PR, F2) e de pesos de classe nos modelos. A série temporal diária (Figura 4) mostra regime com surtos e queda de incidência na segunda quinzena de maio, sem sazonalidade semanal relevante.

![Figura 3](figuras/fig03_alertas_tipo_nivel.png)

![Figura 4](figuras/fig04_serie_alertas.png)

**Análise de features (CM 2.3).** O heatmap de correlação de Spearman (Figura 5) entre as principais variáveis numéricas e o target mostra: (i) forte colinearidade dentro das famílias de contagem em janelas sobrepostas (esperado e tolerado, pois os modelos finais são de árvore); (ii) as correlações mais altas com `y` vêm de `n_dg_12h/24h`, `quase_gatilhos_12h` e das contagens de criticidade em janela curta; (iii) `h_desde_alerta_dg` correlaciona negativamente (alerta recente → maior risco de recorrência).

Distribuição por categoria: a taxa de don't go por 1.000 h operadas varia **16×** entre frotas — 793-D 3S com 34,5, 793-D 4S com 30,8, 793-D 5S com 30,7, 793-D 2S com 13,3 e LeTourneau L 1850 com apenas 2,1 — sendo que a L-1850 responde sozinha por **91,2% do volume de telemetria** (33,9 milhões de eventos) e apenas 1,2% dos alertas: volume de eventos não é risco. Padrões temporais: a taxa do target oscila entre 4,13% (10 h) e 5,72% (21 h), com **leve predominância noturna** — turno B (18–06 h) com 5,15% contra 4,62% do turno A (Figura 6); entre dias da semana a variação é pequena.

Hipóteses registradas na EDA: **H1** — calor da tarde eleva alertas térmicos (**não confirmada**: o pico de taxa é às 21 h e o turno noturno supera o diurno — o regime de operação pesa mais que a temperatura ambiente nesta base); **H2** — operadores diferem na taxa de alerta em equipamentos comparáveis (confirmada: entre os 124 operadores com ≥800 decisões, a taxa varia de 0% a 15,3%; ver 4.6); **H3** — frotas diferem estruturalmente na incidência (confirmada: 16× entre a 793-D 3S e a L-1850, e 2,6× dentro dos próprios caminhões 793-D); **H4** — risco cai logo após manutenção (**não confirmada com clareza**: `h_desde_manutencao` ficou fora do top-10 do SHAP); **H5** — fim de mês concentra alertas por pressão de produção (não confirmada — a variação entre quinzenas acompanha episódios específicos, não o calendário).

![Figura 5](figuras/fig05_heatmap_correlacao.png)

![Figura 6](figuras/fig06_taxa_hora_dia.png)

### 3.3 Preparação dos dados (CM 3.1, 3.2, 3.3)

**Limpeza e tratamento (CM 3.1).** Toda alteração foi registrada com ANTES/DEPOIS e justificativa (arquivo `relatorio/tabelas/controle_alteracoes.csv`):

| Tabela / Campo | Problema identificado | Qtd. | Tratamento | Justificativa |
|---|---|---:|---|---|
| Apontamentos / Operador | Extrato de origem não traz operador | 377.907 | Derivação por merge_asof com a telemetria (mesma Tag, evento mais próximo do início do ciclo, tolerância 6 h) | O comportamento do operador é uma das perguntas do desafio; a telemetria carrega o operador do turno e permite reconstruí-lo |
| Apontamentos / Operador | Ciclo sem evento de telemetria em ±6 h | 70.132 | Categoria "OP_DESCONHECIDO" | Excluir descartaria horas operadas válidas (inclui 15 Tags sem telemetria no período) |
| Apontamentos / Fim | Sobreposição de ciclos na mesma Tag | 326 | Fim truncado no início do ciclo seguinte (264 ciclos zerados removidos) | Um equipamento não executa dois apontamentos simultâneos |
| Apontamentos / Inicio, Fim | Duplicatas, inversões Inicio>Fim, duração zero ou >24 h | 0 | — (verificado) | Base de apontamentos notavelmente consistente; as verificações permanecem no pipeline como salvaguarda |
| Telemetria / Valor | Vírgula decimal e valores não numéricos ("NULL") | 237.443 | Normalização da vírgula + coerção para NaN, linha mantida | O disparo das regras depende do evento e do nível, não do Valor; imputar leitura inexistente criaria informação falsa |
| Telemetria / todas | Eventos duplicados | 0 | — (verificado) | Sem reprocessamentos do coletor nesta extração |
| Catálogo CMA / NIVEL | Grafias inconsistentes ("Muito alto"/"Muito Alto") | 6 | Padronização (title case) | Sem isso, a agregação por criticidade divide a mesma categoria em duas |

Resultado: 377.907 → **377.643** apontamentos e 37.164.054 eventos válidos (nenhum descartado). **Outliers:** optou-se por **manter** valores extremos de contagem de eventos (ex.: rajadas de milhares de eventos/dia da L-1850) — em telemetria de degradação, o outlier frequentemente **é** o sinal, e os modelos escolhidos (árvores) são robustos a caudas. A exceção documentada foi o tratamento estrutural do fatiamento de 60 min via reconstrução de episódios (usada no impacto de negócio, seção 4.6).

**Engenharia de features (CM 3.2).** 50 features em cinco famílias — todas calculadas apenas com informação anterior ao instante de decisão t:

| Feature (família) | Descrição | Fórmula / Lógica | Motivação |
|---|---|---|---|
| `n_crit{1,2,3}_{4,12,24,72}h` (12) | Contagem de eventos por criticidade em janelas retroativas | nº de eventos da Tag com Id_Criticidade=c em (t−N h, t] | A escada de severidade é o precursor físico do don't go |
| `n_dg_{4,12,24,72}h` (4) | Contagem de eventos cujo alarme consta no catálogo | idem, filtrado por Is_Dont_Go=1 | Aproximação direta das pré-condições das regras |
| `quase_gatilhos_{12,24}h` (2) | Nº de vezes em que um evento do catálogo se repetiu em < 6 h | 2ª ocorrência do mesmo EVENTO da Tag dentro de 6 h | Regras exigem QTD 2–10 na janela; a 2ª ocorrência é o "meio caminho" mensurável |
| `n_tendencia_24h` | Eventos de tendência em 24 h | contagem por nome no conjunto TENDÊNCIA | Tendências são desenhadas pela engenharia como precursoras |
| `h_desde_crit1`, `h_desde_alerta_dg` | Horas desde o último evento crítico / último alerta | t − max(timestamp ≤ t), teto 240 h | Recorrência: falha recente prediz falha próxima |
| `razao_taxa_24h_30d` | Taxa de eventos 24 h ÷ taxa média 30 d da própria Tag | n_24h / (n_720h/30) | Normaliza o "temperamento" de cada equipamento; captura anomalia relativa |
| `horas_operadas_24h`, `ciclos_24h`, `duracao_min`, `razao_duracao` | Utilização e ritmo | somas/contagens de apontamentos; duração ÷ mediana da (Tag, Classe) | Exposição ao risco e ciclos anômalos |
| `h_desde_manutencao` | Horas desde a última manutenção | idem "desde último" (a base traz classe única "Manutenção") | Saúde renovada após intervenção |
| `hora`, `hora_sin/cos`, `dia_semana`, `fim_de_semana`, `mes`, `turno_{A,B}` | Calendário e turno | extração direta + codificação cíclica; turnos de 12 h (06–18/18–06) | Padrões de regime diurno/noturno |
| `frota_*`, `tipo_*`, `classe_*` (one-hot) | Cadastro do equipamento e classe do ciclo | one-hot (cardinalidade ≤ 5) | Diferenças estruturais entre frotas (H3) |
| `tag_taxa_alerta`, `op_taxa_alerta`, `op_desconhecido` | Taxa histórica de alerta do equipamento e do operador | target encoding com suavização bayesiana (m=50), **estimado só no treino** | Cardinalidade alta (47 Tags, 396 operadores) inviabiliza one-hot; taxa histórica carrega o sinal (H2) |

**Encoding categórico — justificativa:** one-hot para baixa cardinalidade (Frota 5, Tipo 2, Classe 3, turno 2) por ser lossless e interpretável; target encoding suavizado para `Tag` e `Operador` (alta cardinalidade), estimado exclusivamente no período de treino para evitar vazamento; `OP_DESCONHECIDO` mantido como categoria com flag própria.

**Definição da variável alvo (CM 3.3).** A rotulagem aplica as 151 regras do catálogo sobre a telemetria limpa. Interpretações registradas (controle de decisões metodológicas):

* Equivalência de níveis: "alarme nível 3" ≡ Id_Criticidade 1 (Crítico); "nível 2" ≡ 2 (Não Crítico); "nível 1" ≡ 3 (Informacional).
* "N alarmes consecutivos" foi aproximado por "QTD ocorrências dentro de TEMPO minutos" — sem o estado intermediário do alarme não é possível verificar interrupções; a aproximação nunca dispara com menos eventos que o exigido.
* Regras SISTEMA (Minecare/MEMS) disparariam na ocorrência do evento; nesta extração esses eventos não ocorrem.
* **Cooldown de 6 h** por (equipamento, regra) e colapso de disparos da mesma (Tag, EVENTO) em 30 min (prevalece o de maior NIVEL): um episódio físico único não deve virar dezenas de alertas. Resultado: **1.974 alertas** don't go consolidados.

**Estratégia do target:** classificação binária — `y=1` se existe alerta don't go do equipamento em (t, t+4 h], onde t é o fim de cada apontamento fora de manutenção. **Justificativa da janela de 4 h:** é o tempo operacional mínimo para ação corretiva sem caos — o despacho completa o ciclo corrente (~30 min), redireciona a máquina para rota próxima da oficina e a manutenção prepara box/peças/equipe (2–3 h); janelas maiores (8 h+) diluem a precisão e viram "previsão de turno", janelas menores (1–2 h) não dão tempo de agir. A formulação por regressão do tempo-até-alerta foi considerada e descartada nesta fase: 95,1% dos pontos não têm alerta em horizonte curto (censura pesada), e a decisão operacional é binária (inspecionar ou não).

![Figura 7](figuras/fig07_janela_predicao.png)

### 3.4 Estratégia de validação (CM 4.1)

Dados temporais não podem ser divididos aleatoriamente: um k-fold padrão colocaria a tarde de uma degradação no treino e a manhã da mesma degradação no teste — o modelo "preveria" um episódio que já viu pela metade, inflando todas as métricas (data leakage). Além disso, os encodings de taxa histórica (Tag/operador) seriam contaminados com informação do futuro.

Adotou-se **hold-out temporal** com cortes fixos (Figura 8): **treino = 01/01/2025 a 30/04/2025** (230.009 pontos, 66,9%, prevalência 5,72%); **validação = mai/2025** (58.954 pontos, 17,2%, 3,14%) — usada para tuning de hiperparâmetros e escolha de limiar; **teste = jun/2025** (54.700 pontos, 15,9%, 3,29%) — avaliado **uma única vez**, com limiar congelado. Nenhuma estatística (encodings, escalas, hiperparâmetros) foi estimada fora do treino.

![Figura 8](figuras/fig08_validacao_temporal.png)

### 3.5 Baseline e modelagem principal (CM 4.2, 4.3)

**Baselines (CM 4.2).** (1) **Dummy** — probabilidade a priori da classe (piso estatístico: AUC-PR = prevalência = 0,033 no teste). (2) **Heurística do despacho** — score = nº de alarmes do catálogo don't go nas últimas 12 h: é a melhor aproximação do que um despachante atento faz hoje olhando o painel, e o baseline honesto a ser batido (teste: AUC-ROC 0,750, AUC-PR 0,245).

**Abordagem 1 — supervisionada (classificação).** Três famílias com complexidade crescente:

* **Regressão Logística** (StandardScaler + class_weight=balanced; C ∈ {0,01; 0,1; 1; 10} escolhido na validação → C=0,01). Papel: fronteira linear interpretável.
* **Random Forest** (400 árvores, max_features=√p, class_weight=balanced_subsample; min_samples_leaf ∈ {5, 20, 60} → 60). Papel: não linearidades sem tuning pesado.
* **LightGBM** — **busca aleatória com 30 configurações** sobre num_leaves {15–127}, learning_rate log-uniforme [0,01; 0,2], min_child_samples {10–200}, feature_fraction e bagging_fraction [0,6; 1,0], regularizações L1/L2 log-uniformes e scale_pos_weight {1, √16,5; 16,5}, com early stopping (60 rodadas) monitorando average precision na validação. Configuração vencedora: num_leaves=63, learning_rate=0,011, min_child_samples=10, feature_fraction=0,73, bagging_fraction=0,66, scale_pos_weight=√16,5≈4,1 e apenas **3 árvores** — o early stopping interrompeu cedo porque a validação (maio) sofre queda de prevalência na 2ª quinzena (seção 4.2), e modelos maiores se ajustavam a padrões que não persistem. O modelo final é compacto mas foi o melhor da busca tanto na validação quanto, verificado a posteriori, no teste. A seleção por AUC-PR (e não accuracy/AUC-ROC) é deliberada: com ~5% de positivos, é a métrica que discrimina modelos na região operacional.

**Abordagem 2 — não supervisionada.** (a) **Isolation Forest** (300 árvores, max_samples=0,5) treinado **apenas com operação normal** (pontos de treino sem alerta nas 4 h seguintes) e sem os encodings supervisionados; os alertas do teste servem só como ground truth de validação. Pergunta: o desvio do padrão normal antecede o don't go mesmo sem rótulo? (b) **K-Means** (k=4, features padronizadas) sobre agregados equipamento-dia, para descobrir perfis de comportamento e sua associação com a incidência de alertas.

## 4. Resultados e Discussões

### 4.1 Seleção de métricas e comparação de modelos (CM 5.1)

Com prevalência de 3,3% no teste, accuracy é inútil (o Dummy "acerta" 96,7%). As métricas primárias são **AUC-PR** (qualidade do ranking na região rara), **Recall** e **Precision** no limiar operacional e **AUC-ROC** como visão complementar. O **custo dos erros é assimétrico**: um falso negativo é uma parada não planejada (horas de máquina, risco de dano secundário e de segurança); um falso positivo é ~1 h de inspeção. Por isso o limiar de operação foi escolhido na validação **maximizando F2** (recall pesa o dobro da precisão) — o ponto da curva Precision-Recall coerente com esse custo.

| Modelo | Conjunto | Precision | Recall | F1 | F2 | AUC-ROC | AUC-PR | Observações |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Dummy | teste | 0,033 | 1,000 | 0,064 | 0,145 | 0,500 | 0,033 | piso estatístico |
| Heurística (alarmes 12 h) | teste | 0,147 | 0,590 | 0,235 | 0,368 | 0,750 | 0,245 | prática atual do painel |
| Regressão Logística | teste | 0,098 | 0,658 | 0,171 | 0,307 | 0,840 | 0,269 | C=0,01, balanced |
| Random Forest | teste | 0,156 | 0,671 | 0,253 | 0,404 | 0,863 | 0,310 | leaf=60; maior recall/F2 |
| **LightGBM (campeão)** | **teste** | **0,245** | **0,463** | **0,320** | **0,393** | **0,864** | **0,317** | limiar F2=0,066 |
| Isolation Forest (não superv.) | teste | — | — | — | — | 0,560 | 0,174 | sem rótulo no treino |

Na validação os números são consistentes (LightGBM: AUC-PR 0,198; RF 0,189; RL 0,105; Heurística 0,102), sem inversão de ranking entre validação e teste — indício de tuning sem overfitting à validação. O LightGBM domina em AUC-PR e precisão; o **Random Forest é a alternativa recall-orientada** (67,1% de recall e o maior F2, 0,404, ao custo de 2,4× mais falsos positivos por acerto) — a escolha entre os dois é uma decisão de capacidade da equipe de inspeção, não de estatística. As curvas ROC e PR (Figura 9) mostram que a vantagem do LightGBM se concentra na região de precisão 0,2–0,4.

![Figura 9](figuras/fig09_roc_pr.png)

### 4.2 Análise de erros (CM 5.2)

**Matriz de confusão (teste, limiar F2 = 0,066):**

| | Previsto: sem alerta | Previsto: alerta |
|---|---:|---:|
| **Real: sem alerta** | VN = 50.335 | FP = 2.566 |
| **Real: alerta** | FN = 967 | VP = 832 |

Tradução operacional: em junho, o modelo teria emitido 3.398 cartões de inspeção (~113/dia na frota de 47, ~2,4 por equipamento-dia); 832 antecederam alerta real. Os 2.566 falsos positivos custam ~86 verificações/dia distribuídas na frota — uma carga alta, parcialmente absorvível porque a inspeção visual agrega valor mesmo sem falha iminente; a alternativa de operar com precisão ≥30% (limiar 0,070) reduziria o recall para 38,8% e é discutida em 4.6. Os 967 falsos negativos são o custo residual: paradas que continuariam chegando sem aviso.

**Casos extremos — onde o modelo sistematicamente falha (Figura 10 e tabelas de FN):**

* **Frota LeTourneau L 1850: 100% de FN** (7 positivos, todos perdidos). É a frota com os alertas mais raros (2,1/1.000 h — 16× menos que os caminhões) e as regras dos seus eventos (`Hydraulic Reservoir Oil Temperature Critically High`) são de disparo imediato, com pouca escada precursora; paradoxalmente, é também a frota que gera 91% do volume de telemetria — quase todo informacional.
* **Assimetria entre subsistemas de freio:** `Right Front Brake Temperature - Active` tem apenas 12,9% de FN (480 positivos — o modelo domina o padrão), enquanto as temperaturas de freio **traseiras** têm ~80% de FN (168 positivos). O precursor existe no eixo dianteiro e é mais fraco no traseiro — pista concreta para investigação de instrumentação.
* **`Aftercooler Level - Active`: 87,6% de FN** (121 positivos) e **`Transmission Oil Level - Active`: 64,8%** (586 positivos — o evento mais frequente do teste): perdas de nível podem ser abruptas (vazamento), sem rampa de eventos anterior.
* A frota 793-D 4S tem 33% de FN contra 69% da 5S — a 4S dispara mais "escada" de eventos nível 2 antes do alerta.

**Degradação temporal (drift).** AUC-ROC por quinzena: mai 0,866 → 0,765; jun 0,860 → 0,868. AUC-PR: mai 0,283 → **0,091**; jun 0,278 → 0,350. A queda abrupta na 2ª quinzena de maio acompanha a queda de prevalência (3,85% → 2,51%) e explica por que o early stopping selecionou um modelo compacto (seção 3.5); em junho o desempenho se recupera e se mantém estável. Não há tendência monotônica de queda — o padrão é de **sensibilidade a regime** (surtos vs. calmaria), não de concept drift acumulado, e a recomendação operacional é re-treino frequente (semanal) com monitoramento de prevalência.

![Figura 10](figuras/fig10_matriz_confusao.png)

### 4.3 Interpretabilidade (CM 5.3)

O SHAP summary (Figura 11) valida o modelo contra a intuição operacional — as seis features mais importantes têm leitura física direta:

1. **`h_desde_alerta_dg`** (impacto médio 0,027) — pouco tempo desde o último alerta → recorrência provável: a feature mais forte do modelo. Manutenção que não elimina a causa raiz devolve a máquina para a mesma fila.
2. **`h_desde_crit1`** (0,019) — proximidade do último evento crítico, o degrau final da escada de severidade.
3. **`n_dg_4h`** (0,017) e **`n_dg_12h`** (0,012) — rajada de alarmes do catálogo em janela curta: a matéria-prima das regras.
4. **`tag_taxa_alerta`** (0,014) e **`op_taxa_alerta`** (0,010) — o "quem": equipamento cronicamente ofensor e operador com histórico elevado (H2 e H3 confirmadas dentro do modelo).

Nenhuma feature importante carece de explicação operacional — critério de validação de sentido atendido. O waterfall (Figura 12) decompõe a predição de maior score entre os verdadeiros positivos (CA65926 — justamente o equipamento mais ofensor do semestre —, 12/06/2025 20:53): **13 alarmes do catálogo nas últimas 4 h** (18 em 12 h), **alerta anterior há apenas 4,2 h**, 120 eventos críticos em 72 h e 19 quase-gatilhos em 24 h somam +0,39 em log-odds sobre a base E[f(X)] = −2,75, levando o equipamento ao topo do ranking do dia; ele disparou novo alerta dentro da janela de 4 h. É o caso de uso do painel: o cartão de inspeção viria com essas três evidências listadas.

![Figura 11](figuras/fig11_shap_summary.png)

![Figura 12](figuras/fig12_shap_waterfall.png)

### 4.4 Abordagem não supervisionada — o que ela adiciona

O **Isolation Forest**, sem nunca ver um rótulo, alcança AUC-ROC 0,560 e AUC-PR 0,174 no teste — acima do acaso (0,033 de prevalência), mas muito abaixo do supervisionado: nesta base, "estar anômalo" não é um bom preditor de don't go, em grande parte porque a frota L-1850 produz anomalias de volume de eventos (tempestades de telemetria) que não terminam em alerta. O detector permanece útil como **cerca de segurança para modos de falha novos** que ainda não têm regra no catálogo, mas não substitui o modelo supervisionado.

O **K-Means** (k=4) sobre agregados equipamento-dia encontrou uma partição com leitura operacional imediata:

| Cluster | Dias | Eventos/24h | Nível 2/24h | Alarmes catálogo/24h | Quase-gatilhos | Horas operadas | Taxa de alerta |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 — **pré-falha** | 19 (0,2%) | 3.582 | 981 | 439 | 437 | 19,7 | **84%** |
| 1 — operação plena | 4.546 (45%) | 9.455 | 132 | 4,9 | 4,2 | 20,3 | 24% |
| 0 — dia parado/ocioso | 2.714 (27%) | 158 | 5,8 | 0,3 | 0,2 | 0,5 | 2% |
| 3 — tempestade de telemetria | 2 | 1.334.184 | 282 | 0 | 0 | 19,4 | 0% |

O cluster 2 é raro (19 equipamento-dias) mas quase determinístico: 84% de chance de alerta — um "estado da máquina" exibível como semáforo no painel do despacho. O cluster 3 é um achado de qualidade de dados: dois dias em que um único equipamento emitiu **mais de 1,3 milhão de eventos** em 24 h sem nenhum alerta — flooding do coletor, não degradação física.

### 4.5 Priorização da fila de inspeção

O score ordena a fila de manutenção: no último dia do teste (30/06), os cinco primeiros da fila (CA65927, CA65909, CA65926, CA65924, CA65935) concentravam os maiores riscos residuais da frota — quatro deles estão entre os dez maiores ofensores do semestre. Ao longo de junho, seguir a fila do modelo teria colocado a equipe de inspeção na máquina certa antes do alerta em 6 de cada 10 disparos (taxa de antecipação de 60,7%).

### 4.6 Impacto de negócio e insights (CM 6.1)

**Comparação com baseline.** O LightGBM supera a heurística do despacho em **+30% de AUC-PR** (0,317 vs 0,245) e **+67% de precisão** (0,245 vs 0,147) no ponto operacional; sobre o Dummy, o lift de precisão é 7,4×. Em termos práticos: para cada 100 cartões de inspeção, a heurística acerta 15 e o modelo 25 — com a heurística capturando mais alertas (59% vs 46%) ao custo de quase o dobro de inspeções vazias por acerto. O Random Forest oferece o meio-termo (recall 67%, precisão 16%).

**Tradução para impacto (jun/2025, premissas explícitas: custo de indisponibilidade R$ 6.000/h, inspeção R$ 450, 35% da duração da corretiva economizável quando a intervenção é antecipada; duração média do episódio de manutenção reconstruído por encadeamento de ciclos: 6,72 h):**

| Indicador | Valor |
|---|---:|
| Alertas don't go no mês | 229 |
| Alertas antecipados (≥1 predição correta nas 4 h anteriores) | 139 (**60,7%**) |
| Antecedência mediana do primeiro aviso | 3,2 h |
| Duração média do episódio de manutenção | 6,72 h |
| Horas de parada não planejada evitáveis | **326,7 h** |
| Benefício bruto estimado | R$ 1,96 mi |
| Custo das 2.566 inspeções vazias | R$ 1,15 mi |
| **Benefício líquido estimado no mês** | **R$ 805 mil** |

**Aferição da métrica de sucesso (CM 1.2):** a meta de antecipação foi atingida (60,7% ≥ 60%); a meta de precisão **não** foi atingida no limiar F2 (24,5% < 30%). Operar no limiar de precisão 30% é possível (limiar 0,070), mas derruba o recall para 38,8% e a antecipação abaixo da meta — com esta base, as duas metas não são atingíveis simultaneamente, e o ponto F2 é o que maximiza o benefício líquido estimado. Registra-se a meta como **parcialmente atingida**, com o trade-off quantificado para decisão do negócio.

**Insights não óbvios:**

1. **Volume de telemetria não é risco.** A frota L-1850 gera 91,2% dos 37 milhões de eventos (98,5% informacionais) e apenas 1,2% dos alertas — e é a única frota 100% imprevisível para o modelo. O caminho para ela é curadoria de eventos e sensorização dirigida, não mais dados brutos.
2. **Recorrência é o padrão dominante.** As duas features mais fortes do SHAP são "tempo desde o último alerta/evento crítico": parte relevante dos don't go é a mesma causa raiz mal resolvida voltando — um indicador de qualidade de manutenção, não só de condição.
3. **O operador importa.** Entre 124 operadores com ≥800 decisões, a taxa varia de 0% a 15,3% e `op_taxa_alerta` está no top-6 do SHAP. Há um programa de treinamento escondido nesses dados.
4. **O precursor depende do subsistema, não só do evento.** Temperatura de freio dianteiro direito: 87% de recall; freios traseiros: ~20%. Mesma física, instrumentação/dinâmica diferentes — mapa direto para priorizar melhorias de sensores.
5. **A base fatia atividades em ciclos de 60 min.** Qualquer análise de duração (inclusive o próprio impacto financeiro) exige reconstrução de episódios — a duração média "por registro" de manutenção é 0,5 h; por episódio real, 6,7 h. Ignorar isso subestimaria o benefício em ~8×.

![Figura 13](figuras/fig13_baseline_vs_modelos.png)

## 5. Conclusão e Trabalhos Futuros

### 5.1 Resposta à pergunta analítica (CM 6.2)

**"Quais equipamentos têm maior risco de gerar um alerta don't go nas próximas 4 horas?"** — a pergunta foi respondida com um pipeline reprodutível que, a cada fechamento de ciclo, ranqueia a frota por probabilidade de alerta: no teste cego (jun/2025), o ranking tem AUC-ROC 0,864/AUC-PR 0,317 (9,6× a prevalência), antecipou **60,7% dos alertas** com mediana de 3,2 h de aviso e precisão de 24,5% no limiar F2 — atingindo a meta de antecipação e ficando aquém da meta de precisão, com o trade-off entre os dois pontos de operação quantificado (seção 4.6). O modelo aprendeu mecanismos com respaldo físico (recorrência, rajadas de alarmes monitorados, efeito equipamento e operador), verificados por SHAP.

**Limitações (honestas):** (i) seis meses de dados — a sazonalidade anual completa (estação chuvosa vs. seca) não está coberta; (ii) o rótulo deriva do catálogo CMA — regras erradas ou incompletas propagam para o target ("consecutivos" foi aproximado por janela, decisão documentada), e as regras de TENDÊNCIA/SISTEMA não têm eventos correspondentes nesta extração; (iii) o operador dos apontamentos foi **derivado** da telemetria (tolerância de 6 h) — 18,6% dos ciclos ficaram sem operador, concentrados em 15 Tags sem telemetria, cujas decisões nunca podem ser positivas (viés estrutural documentado); (iv) telemetria agregada em eventos, sem as séries contínuas de sensores, que elevariam o teto de desempenho; (v) o campeão é um modelo deliberadamente compacto (3 árvores) selecionado sob drift de prevalência em maio — com re-treino mensal, modelos maiores tendem a se sustentar; (vi) premissas financeiras (R$ 6.000/h, 35% de economia) são estimativas de ordem de grandeza a calibrar com a área de planejamento; (vii) generalização para outras localidades exige re-treino — os padrões aprendidos são específicos desta frota e catálogo.

### 5.2 Trabalhos futuros (CM 6.3)

1. **Novos dados:** integrar ordens de serviço do ERP de manutenção (causa raiz real, componente trocado, horímetro) para separar "alerta antecipável" de "manutenção mal executada" — o peso da recorrência no SHAP sugere que parte do problema é de qualidade de intervenção; além de dados climáticos horários e séries contínuas de sensores via historiador (crucial para os eventos de nível sem rampa, como `Transmission Oil Level`).
2. **Novas features / formulação:** duas cabeças complementares — regressão/sobrevivência (Weibull AFT ou Cox com censura, tempo-até-alerta por subsistema) para priorização fina além do binário 4 h; e classificação multi-rótulo do **tipo** de alerta (freio vs. nível vs. arrefecimento), entregando à manutenção o subsistema suspeito junto com o cartão.
3. **Abordagens alternativas:** aprendizado online (re-treino incremental semanal com monitoramento de prevalência e AUC-PR móvel — a rotina de degradação temporal da seção 4.2 já é o embrião, e a queda da 2ª quinzena de maio mostra por que é necessária) e custo-sensível explícito (otimizar diretamente o benefício líquido em R$ em vez de F2).
4. **Integração operacional:** publicar o score via API no sistema de despacho com atualização por evento (a arquitetura de janelas ordenadas migra direto para streaming), cartões com as evidências SHAP, semáforo do K-Means como camada de leitura rápida (o cluster pré-falha tem 84% de acerto), watchdog de flooding de telemetria (cluster 3), e ciclo de feedback do inspetor (achou/não achou problema) realimentando o treino — transformando cada falso positivo em rótulo novo.

---

## Referências e Recursos

* `Alarmes - Regra de Negocio.xlsx` — catálogo de regras de negócio para alertas don't go (aba CMA).
* `Dicionario_Dados.xlsx` — dicionário das tabelas Apontamentos e Telemetria.
* Estudo Guiado — Desafio: Análise Avançada de Dados, Programa Desenvolver, Edição 2026.
* scikit-learn — https://scikit-learn.org
* LightGBM — https://lightgbm.readthedocs.io
* SHAP — https://shap.readthedocs.io
* Ke, G. et al. *LightGBM: A Highly Efficient Gradient Boosting Decision Tree*. NeurIPS, 2017.
* Lundberg, S.; Lee, S.-I. *A Unified Approach to Interpreting Model Predictions*. NeurIPS, 2017.
* Provost, F.; Fawcett, T. *Data Science para Negócios*. Alta Books, 2016.
