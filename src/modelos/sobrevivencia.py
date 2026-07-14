# -*- coding: utf-8 -*-
"""Abordagem 3 — análise de sobrevivência (Weibull AFT).

Em vez de "haverá alerta nas próximas 4 h?" (binário), o modelo de tempo de
falha acelerado (Accelerated Failure Time) pergunta "quanto tempo até o
próximo alerta?". Cada ponto de decisão vira uma observação com duração T
(horas até o próximo alerta don't go do equipamento) e indicador de evento E:

  * E=1 — o alerta foi observado (T exato);
  * E=0 — censura à direita: o horizonte de observação terminou (fim da base
    em 30/06) ou o próximo alerta está além do teto de 21 dias registrado na
    ABT. Ignorar a censura enviesaria o modelo para baixo — é exatamente o
    problema que a formulação de sobrevivência resolve.

Saídas:
  * risco em 4 h = 1 − S(4 | x): probabilidade acumulada de alerta na janela
    operacional — diretamente comparável aos classificadores (AUC-ROC/PR);
  * C-index no teste: qualidade do ranqueamento de tempos;
  * fatores de aceleração exp(coef) por desvio-padrão de cada feature: quanto
    cada variável ENCURTA (fator < 1) ou alonga o tempo até o alerta.

Features contínuas padronizadas no treino (fatores lidos "por 1 desvio-padrão").
"""

import numpy as np
import pandas as pd
from lifelines import WeibullAFTFitter
from lifelines.utils import concordance_index
from sklearn.preprocessing import StandardScaler

from src.config import CORTE_TREINO, CORTE_VALIDACAO, DIR_PROCESSADOS, DIR_TABELAS
from src.features.engenharia import separar_conjuntos

TETO_H = 24 * 21  # teto de horas_ate_alerta registrado na ABT

FEATURES_AFT = [
    "h_desde_alerta_dg", "h_desde_crit1", "n_dg_4h", "n_dg_12h", "n_dg_24h",
    "n_dg_72h", "quase_gatilhos_24h", "n_crit1_72h", "n_crit2_4h",
    "n_crit2_12h", "razao_taxa_24h_30d", "horas_operadas_24h", "ciclos_24h",
    "h_desde_manutencao", "tag_taxa_alerta", "op_taxa_alerta",
]


def _duracao_evento(df: pd.DataFrame, fim_dados: pd.Timestamp):
    """T = horas até o alerta (ou até a censura); E = alerta observado."""
    h_fim = ((fim_dados - df["t_decisao"]).dt.total_seconds() / 3600).to_numpy()
    h_alerta = df["horas_ate_alerta"].to_numpy()
    evento = (h_alerta < np.minimum(h_fim, TETO_H - 1e-6))
    T = np.where(evento, h_alerta, np.minimum(h_fim, TETO_H))
    return np.maximum(T, 1e-3), evento.astype(int)


def weibull_aft(abt: pd.DataFrame):
    fim_dados = abt["t_decisao"].max()
    treino, _, teste = separar_conjuntos(abt, CORTE_TREINO, CORTE_VALIDACAO)

    scaler = StandardScaler().fit(treino[FEATURES_AFT])

    def _monta(df):
        base = pd.DataFrame(scaler.transform(df[FEATURES_AFT]),
                            columns=FEATURES_AFT)
        base["T"], base["E"] = _duracao_evento(df, fim_dados)
        return base

    df_tr, df_te = _monta(treino), _monta(teste)

    aft = WeibullAFTFitter(penalizer=0.01)
    aft.fit(df_tr, duration_col="T", event_col="E")

    # risco na janela operacional: P(alerta <= 4 h | x) = 1 - S(4)
    s4 = aft.predict_survival_function(df_te[FEATURES_AFT], times=[4.0])
    risco_4h = 1.0 - s4.iloc[0].to_numpy()

    # C-index no teste: tempos menores devem receber medianas menores
    mediana = aft.predict_median(df_te[FEATURES_AFT])
    c_index = concordance_index(df_te["T"], mediana, df_te["E"])

    # fatores de aceleração (escala lambda_), sem o intercepto
    resumo = aft.summary.loc["lambda_"].drop(index="Intercept", errors="ignore")
    fatores = (resumo[["coef", "exp(coef)", "p"]]
               .rename(columns={"coef": "coef_por_dp",
                                "exp(coef)": "razao_tempo_por_dp",
                                "p": "p_valor"})
               .sort_values("coef_por_dp")
               .round(4)
               .reset_index(names="Feature"))
    fatores.to_csv(DIR_TABELAS / "aft_fatores_aceleracao.csv", index=False)

    saida = pd.DataFrame({
        "t_decisao": teste["t_decisao"].values, "Tag": teste["Tag"].values,
        "y": teste["y"].values, "WeibullAFT": risco_4h,
    })
    saida.to_parquet(DIR_PROCESSADOS / "scores_weibull_aft.parquet", index=False)
    print(f"  Weibull AFT: C-index teste={c_index:.4f} | "
          f"eventos treino={int(df_tr['E'].sum()):,} de {len(df_tr):,}")
    return aft, saida, c_index, fatores
