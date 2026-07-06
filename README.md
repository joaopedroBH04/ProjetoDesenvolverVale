# Antecipação de Alertas Críticos em Frotas de Mineração

Trabalho final do **Desafio: Análise Avançada de Dados** (Programa Desenvolver — Edição 2026).

O objetivo é antecipar alertas **don't go** — condições em que o equipamento não deve operar — em uma frota de 50 equipamentos de mina (caminhões CAT 793-D/793-F/789-C e Komatsu 930-E, carregadeiras LeTourneau L-1850 e escavadeiras PC5500), prevendo, ao fim de cada ciclo de apontamento, a probabilidade de alerta nas **4 horas seguintes**.

## Resultados principais (teste cego, fev/2026)

| Indicador | Valor |
|---|---|
| AUC-ROC / AUC-PR (LightGBM) | 0,871 / 0,398 (heurística de despacho: 0,825 / 0,239) |
| Recall / Precisão no limiar operacional (F2) | 60,1% / 35,0% |
| Alertas do mês antecipados | 133 de 188 (**70,7%**), mediana de 3,4 h de aviso |
| Benefício líquido estimado | ~R$ 1,40 mi/mês (premissas no relatório) |

Relatório completo em [`relatorio/Relatorio_Final.md`](relatorio/Relatorio_Final.md) (versão para entrega: `relatorio/Relatorio_Final.docx`).

## Estrutura

```
dados/
  brutos/        Apontamentos.csv.gz e Telemetria.csv.gz (set/2025 a fev/2026)
  negocio/       Alarmes - SUL_SUDESTE.xlsx (catálogo don't go) e Dicionario_Dados.xlsx
  processados/   camada tratada em Parquet (gerada pelo pipeline; fora do versionamento)
src/
  etl/           extração, transformação (com controle de alterações) e carga
  regras/        motor de regras don't go (aplica o catálogo CMA à telemetria)
  features/      engenharia de features e tabela analítica (ABT)
  modelos/       baselines, Regressão Logística, Random Forest, LightGBM,
                 Isolation Forest e K-Means
  avaliacao/     métricas, limiar F2, análise de erros, drift e impacto de negócio
  viz/           figuras do relatório
relatorio/
  Relatorio_Final.md / .docx, figuras/ (13 figuras) e tabelas/ (16 tabelas em CSV)
executar_pipeline.py   pipeline completo, da extração ao material do relatório
```

## Como executar

```bash
pip install -r requirements.txt
python executar_pipeline.py
```

O pipeline roda de ponta a ponta em ~3 min (ETL → rotulagem via regras → ABT com 56 features → treino e tuning → avaliação → figuras e tabelas). Semente fixa e cortes temporais em `src/config.py`.

## Decisões metodológicas centrais

* **Rotulagem**: as 151 regras do catálogo CMA (TIPO + EVENTO + SITUACAO + QTD + TEMPO + NIVEL) foram compiladas em um motor de regras; interpretações e simplificações estão documentadas em `src/regras/motor_regras.py` e na seção 3.3 do relatório.
* **Validação temporal**: treino set–dez/2025, validação jan/2026 (tuning + limiar), teste fev/2026 tocado uma única vez. Nada de k-fold aleatório em série temporal.
* **Métricas**: AUC-PR e F2 como primárias — classe positiva rara (2,36%) e custo assimétrico (falso negativo = parada não planejada; falso positivo = ~1 h de inspeção).
