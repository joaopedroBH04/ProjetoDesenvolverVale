# Antecipação de Alertas Críticos em Frotas de Mineração

Trabalho final do **Desafio: Análise Avançada de Dados** (Programa Desenvolver — Edição 2026).

O objetivo é antecipar alertas **don't go** — condições em que o equipamento não deve operar — em uma frota de 47 equipamentos de mina em Itabira (caminhões CAT 793-D, frotas 2S a 5S, e escavadeiras LeTourneau L-1850), prevendo, ao fim de cada ciclo de apontamento, a probabilidade de alerta nas **4 horas seguintes**. Base: 377.907 apontamentos e 37,16 milhões de eventos de telemetria (jan a jun/2025).

## Resultados principais (teste cego, jun/2025)

| Indicador | Valor |
|---|---|
| AUC-ROC (LightGBM) / AUC-PR (RF) | 0,870 / 0,320 (heurística de despacho: 0,750 / 0,245) |
| Weibull AFT (sobrevivência) | C-index 0,781; risco em 4 h com AUC-ROC 0,841 |
| Ponto de captura (limiar F2) | 68,6% dos 229 alertas antecipados, mediana 3,4 h de aviso |
| Ponto custo-ótimo (limiar em R$) | precisão 41,9%, ~45 cartões/dia, **benefício líquido ~R$ 1,10 mi/mês** |

Relatório completo em [`relatorio/Relatorio_Final.md`](relatorio/Relatorio_Final.md) (versão para entrega: `relatorio/Relatorio_Final.docx`).

## Estrutura

```
dados/
  (externos)     parquets brutos: apontamentos/desenvolver_apontamentos.parquet e
                 telemetria/telemetry_{jan..jun}.parquet — caminho em
                 src/config.py, sobrescrevível pela env DADOS_BRUTOS_DIR
  negocio/       Alarmes - Regra de Negocio.xlsx (catálogo don't go, aba CMA)
                 e Dicionario_Dados.xlsx (versionados)
  processados/   camada tratada em Parquet (gerada pelo pipeline; fora do versionamento)
src/
  etl/           extração (leitura colunar dos 37 M de eventos, derivação do
                 operador por merge_asof), transformação (com controle de
                 alterações) e carga
  regras/        motor de regras don't go (aplica o catálogo CMA à telemetria)
  features/      engenharia de features e tabela analítica (ABT)
  modelos/       baselines, Regressão Logística, Random Forest, LightGBM,
                 Weibull AFT (sobrevivência), Isolation Forest e K-Means
  avaliacao/     métricas, limiares F2 e custo-ótimo, análise de erros, drift
                 e impacto de negócio
  viz/           figuras do relatório
relatorio/
  Relatorio_Final.md / .docx, figuras/ (13 figuras) e tabelas/ (17 tabelas em CSV)
executar_pipeline.py   pipeline completo, da extração ao material do relatório
```

## Como executar

```bash
pip install -r requirements.txt
python executar_pipeline.py
```

Aponte a variável de ambiente `DADOS_BRUTOS_DIR` (ou o default em `src/config.py`) para a pasta com os parquets brutos. O pipeline roda de ponta a ponta em ~8 min (ETL → rotulagem via regras → ABT com 50 features → treino e tuning → avaliação → figuras e tabelas). Semente fixa e cortes temporais em `src/config.py`.

## Decisões metodológicas centrais

* **Rotulagem**: as 151 regras do catálogo CMA (TIPO + EVENTO + SITUACAO + QTD + TEMPO + NIVEL) foram compiladas em um motor de regras; interpretações e simplificações estão documentadas em `src/regras/motor_regras.py` e na seção 3.3 do relatório. Resultado: 1.974 alertas rotulados no semestre.
* **Operador**: o extrato de apontamentos não traz operador; ele é derivado da telemetria por casamento temporal (`merge_asof`, tolerância 6 h) — decisão documentada no controle de alterações.
* **Validação temporal**: treino jan–abr/2025, teste jun/2025 tocado uma única vez; **tuning em duas janelas** walk-forward (abr e mai) e target encodings estimados só em jan–mar — nenhuma estatística vê dados de validação. Nada de k-fold aleatório em série temporal.
* **Métricas e limiares**: AUC-PR e F2 como primárias — classe positiva rara (4,89%) e custo assimétrico. Dois pontos de operação escolhidos na validação: captura (F2) e custo-ótimo (maximiza benefício líquido em R$ sob premissas explícitas).
* **Sobrevivência**: Weibull AFT com censura à direita estima o tempo até o próximo alerta; fatores de aceleração convergem com o SHAP do classificador.
* **Episódios de manutenção**: a base fatia atividades em ciclos de ≤60 min; durações reais são reconstruídas encadeando ciclos consecutivos (gap < 30 min) — essencial para o cálculo de impacto.
