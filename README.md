# Antecipação de Alertas Críticos em Frotas de Mineração

Trabalho final do **Desafio: Análise Avançada de Dados** (Programa Desenvolver, Edição 2026), alinhado à versão revisada do material de apoio.

O foco é a previsão e a prevenção de alertas **don't go** (condições em que o equipamento não deve operar) em uma frota de 50 equipamentos de mina (caminhões CAT 793-D, 793-F e 789-C, Komatsu 930-E, carregadeiras LeTourneau L-1850 e escavadeiras PC5500): a cada ciclo de apontamento encerrado, o pipeline estima a probabilidade de alerta nas **4 horas seguintes** e prioriza a fila de inspeção.

## Resultados principais (teste cego, fev/2026)

| Indicador | Valor |
|---|---|
| AUC-ROC / AUC-PR (LightGBM) | 0,869 / 0,391 (heurística de painel: 0,825 / 0,238) |
| Recall / Precisão no limiar operacional (F2) | 63,7% / 33,7% |
| Alertas do mês antecipados | 136 de 188 (**72,3%**), mediana de 3,5 h de aviso |
| Robustez | walk-forward em 5 dobras: AUC-PR de 0,358 a 0,426, sempre 1,6 a 1,9x a heurística |
| Calibração | Brier 0,0155 (base: 0,0205) |
| Benefício líquido estimado | cerca de R$ 1,39 milhão/mês (premissas documentadas no relatório) |

Relatório completo em [`relatorio/Relatorio_Final.md`](relatorio/Relatorio_Final.md) (versão para entrega: `relatorio/Relatorio_Final.docx`).

## Estrutura

```
dados/
  brutos/        Apontamentos.parquet e Telemetria.parquet (set/2025 a fev/2026)
  negocio/       Alarmes - Regra de Negocio_V2.xlsx (regras na aba CMA) e Dicionario_Dados.xlsx
  processados/   camada tratada em Parquet (gerada pelo pipeline; fora do versionamento)
src/
  etl/           extração, transformação (com controle de alterações) e carga
  regras/        motor de regras don't go (TIPO + EVENTO + SITUACAO + QUANTIDADE + TEMPO + NIVEL)
  features/      engenharia de variáveis e tabela analítica (operador derivado da Telemetria)
  modelos/       baselines, Regressão Logística, Random Forest, LightGBM,
                 Isolation Forest e K-Means
  avaliacao/     métricas, limiar F2, análise de erros, drift, impacto e robustez
                 (walk-forward, sensibilidade de janela, calibração, custo por limiar)
  viz/           figuras do relatório
relatorio/
  Relatorio_Final.md / .docx, figuras/ (15 figuras) e tabelas/ (21 tabelas em CSV)
executar_pipeline.py   pipeline completo, da extração ao material do relatório
```

## Como executar

```bash
pip install -r requirements.txt
python executar_pipeline.py
```

O pipeline roda de ponta a ponta em cerca de 5 minutos (ETL, rotulagem via regras, tabela analítica com 56 variáveis, treino e tuning, avaliação, robustez, figuras e tabelas). Semente fixa e cortes temporais em `src/config.py`.

## Decisões metodológicas centrais

* **Rótulo**: a coluna `Is_Dont_Go` da telemetria não é usada como rótulo oficial; ela apenas indica que o alarme consta na lista monitorada. O rótulo é recalculado pelo motor de regras a partir da aba CMA, que exige uma QUANTIDADE de ocorrências dentro de uma janela de TEMPO (em minutos). Interpretações e salvaguardas (cooldown de 6 h, colapso de disparos simultâneos) estão documentadas em `src/regras/motor_regras.py` e na seção 2.3 do relatório.
* **Validação temporal**: treino de set a dez/2025, validação em jan/2026 (tuning e limiar), teste em fev/2026 avaliado uma única vez; robustez confirmada por walk-forward mensal. Nada de k-fold aleatório em série temporal.
* **Métricas**: AUC-PR e F2 como primárias, dada a classe positiva rara (2,37%) e o custo assimétrico dos erros (falso negativo gera parada não planejada; falso positivo custa cerca de 1 h de inspeção). O limiar F2 ficou a 4% do ótimo da curva de benefício líquido em reais.
