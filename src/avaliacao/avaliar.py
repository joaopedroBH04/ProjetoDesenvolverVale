# -*- coding: utf-8 -*-
"""Avaliação: métricas, limiar operacional, análise de erros e impacto.

O limiar de operação é escolhido na VALIDAÇÃO maximizando F2 (recall pesa o
dobro da precisão): na mina, o falso negativo vira parada não planejada com
equipamento possivelmente comprometido, enquanto o falso positivo custa uma
inspeção de ~1 h. O teste (fev/2026) é tocado uma única vez, já com o limiar
congelado.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, confusion_matrix,
                             fbeta_score, precision_score, recall_score,
                             roc_auc_score)

from src.config import DIR_PROCESSADOS, DIR_TABELAS, JANELA_PREDICAO_HORAS

MODELOS = ["Dummy", "Heuristica", "RegressaoLogistica", "RandomForest", "LightGBM"]

# Premissas de negócio (documentadas no relatório)
CUSTO_HORA_PARADA = 6_000.0      # R$/h de indisponibilidade de caminhão fora de plano
REDUCAO_PARADA_ANTECIPADA = 0.35  # fração do tempo de corretiva evitada quando há antecipação
CUSTO_INSPECAO = 450.0            # R$ por inspeção disparada por alerta do modelo


def limiar_f2(y, score):
    """Limiar que maximiza F2 na validação."""
    candidatos = np.unique(np.quantile(score, np.linspace(0.5, 0.999, 300)))
    melhor_f2, melhor_t = -1.0, candidatos[0]
    for t in candidatos:
        f2 = fbeta_score(y, score >= t, beta=2, zero_division=0)
        if f2 > melhor_f2:
            melhor_f2, melhor_t = f2, t
    return melhor_t


def tabela_comparativa(sc_va: pd.DataFrame, sc_te: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for m in MODELOS:
        t = limiar_f2(sc_va["y"], sc_va[m])
        for nome_cj, sc in (("validação", sc_va), ("teste", sc_te)):
            pred = sc[m] >= t
            linhas.append(dict(
                Modelo=m, Conjunto=nome_cj,
                Precision=precision_score(sc["y"], pred, zero_division=0),
                Recall=recall_score(sc["y"], pred, zero_division=0),
                F1=fbeta_score(sc["y"], pred, beta=1, zero_division=0),
                F2=fbeta_score(sc["y"], pred, beta=2, zero_division=0),
                AUC_ROC=roc_auc_score(sc["y"], sc[m]) if sc[m].nunique() > 1 else 0.5,
                AUC_PR=average_precision_score(sc["y"], sc[m]),
                Limiar=t,
            ))
    tab = pd.DataFrame(linhas).round(4)
    tab.to_csv(DIR_TABELAS / "comparativo_modelos.csv", index=False)
    return tab


def matriz_confusao_campeao(sc_va, sc_te, campeao="LightGBM"):
    t = limiar_f2(sc_va["y"], sc_va[campeao])
    pred = sc_te[campeao] >= t
    mc = confusion_matrix(sc_te["y"], pred)
    pd.DataFrame(mc, index=["Real 0", "Real 1"], columns=["Pred 0", "Pred 1"]).to_csv(
        DIR_TABELAS / "matriz_confusao_teste.csv")
    return mc, t


def analise_falsos_negativos(sc_te, alertas, abt, limiar, campeao="LightGBM"):
    """Que tipo de alerta o modelo sistematicamente perde?"""
    sc = sc_te.copy()
    sc["fn"] = (sc["y"] == 1) & (sc[campeao] < limiar)
    positivos = sc[sc["y"] == 1].copy()

    al = alertas.sort_values("Data_Alerta")
    janela = pd.Timedelta(hours=JANELA_PREDICAO_HORAS)
    assoc = pd.merge_asof(
        positivos.sort_values("t_decisao"),
        al.rename(columns={"TAG": "Tag"})[["Tag", "Data_Alerta", "EVENTO", "TIPO", "NIVEL"]],
        left_on="t_decisao", right_on="Data_Alerta", by="Tag",
        direction="forward", tolerance=janela,
    )
    frota = abt[["Tag"]].join(
        abt.filter(like="frota_")).drop_duplicates("Tag").set_index("Tag")
    frota_nome = frota.idxmax(axis=1).str.replace("frota_", "", regex=False)
    assoc["Frota"] = assoc["Tag"].map(frota_nome)

    resumo = (assoc.groupby(["TIPO", "EVENTO"])
              .agg(positivos=("fn", "size"), fn=("fn", "sum"))
              .assign(taxa_fn=lambda d: (d["fn"] / d["positivos"]).round(3))
              .sort_values("fn", ascending=False).reset_index())
    resumo.to_csv(DIR_TABELAS / "falsos_negativos_por_evento.csv", index=False)

    por_frota = (assoc.groupby("Frota")
                 .agg(positivos=("fn", "size"), fn=("fn", "sum"))
                 .assign(taxa_fn=lambda d: (d["fn"] / d["positivos"]).round(3))
                 .sort_values("taxa_fn", ascending=False).reset_index())
    por_frota.to_csv(DIR_TABELAS / "falsos_negativos_por_frota.csv", index=False)
    return resumo, por_frota


def degradacao_temporal(sc_va, sc_te, campeao="LightGBM"):
    """AUC por quinzena para verificar estabilidade (drift)."""
    linhas = []
    for nome, sc in (("jan/2026 (validação)", sc_va), ("fev/2026 (teste)", sc_te)):
        sc = sc.copy()
        sc["quinzena"] = np.where(sc["t_decisao"].dt.day <= 15, "1ª quinzena", "2ª quinzena")
        for q, g in sc.groupby("quinzena"):
            linhas.append(dict(
                Periodo=f"{nome} — {q}", N=len(g), Prevalencia=g["y"].mean(),
                AUC_ROC=roc_auc_score(g["y"], g[campeao]),
                AUC_PR=average_precision_score(g["y"], g[campeao]),
            ))
    tab = pd.DataFrame(linhas).round(4)
    tab.to_csv(DIR_TABELAS / "degradacao_temporal.csv", index=False)
    return tab


def impacto_negocio(sc_te, alertas, ap, limiar, campeao="LightGBM"):
    """Converte a matriz de confusão do teste em horas e R$ estimados."""
    sc = sc_te.copy()
    sc["pred"] = sc[campeao] >= limiar

    # alertas de fev/2026 antecipados: com ao menos um TP nas 4 h anteriores
    al_teste = alertas[alertas["Data_Alerta"] >= sc["t_decisao"].min()].copy()
    tp = sc[(sc["y"] == 1) & sc["pred"]]
    janela = pd.Timedelta(hours=JANELA_PREDICAO_HORAS)
    antecipados = 0
    antecedencias = []
    for linha in al_teste.itertuples(index=False):
        acertos = tp[(tp["Tag"] == linha.TAG)
                     & (tp["t_decisao"] >= linha.Data_Alerta - janela)
                     & (tp["t_decisao"] < linha.Data_Alerta)]
        if len(acertos):
            antecipados += 1
            antecedencias.append(
                (linha.Data_Alerta - acertos["t_decisao"].min()).total_seconds() / 3600)

    dur_corretiva_h = ap.loc[ap["Classe"] == "Manutenção Corretiva", "duracao_min"].mean() / 60
    horas_evitadas = antecipados * dur_corretiva_h * REDUCAO_PARADA_ANTECIPADA
    fp = int((~sc["y"].astype(bool) & sc["pred"]).sum())
    beneficio = horas_evitadas * CUSTO_HORA_PARADA
    custo_fp = fp * CUSTO_INSPECAO

    tab = pd.DataFrame([
        ("Alertas don't go no teste (fev/2026)", len(al_teste)),
        ("Alertas antecipados pelo modelo (≥1 acerto nas 4 h anteriores)", antecipados),
        ("Taxa de antecipação", round(antecipados / max(len(al_teste), 1), 3)),
        ("Antecedência mediana do 1º aviso (h)", round(float(np.median(antecedencias)), 2)),
        ("Duração média da manutenção corretiva (h)", round(dur_corretiva_h, 2)),
        ("Horas de parada não planejada evitadas (premissa 35%)", round(horas_evitadas, 1)),
        ("Falsos positivos no mês (inspeções vazias)", fp),
        ("Benefício bruto estimado (R$)", round(beneficio, 0)),
        ("Custo das inspeções vazias (R$)", round(custo_fp, 0)),
        ("Benefício líquido estimado no mês (R$)", round(beneficio - custo_fp, 0)),
    ], columns=["Indicador", "Valor"])
    tab.to_csv(DIR_TABELAS / "impacto_negocio.csv", index=False)
    return tab


def fila_inspecao(sc_te, campeao="LightGBM", topo=15):
    """Priorização da manutenção: score máximo por equipamento no último dia."""
    ultimo_dia = sc_te["t_decisao"].dt.floor("D").max()
    dia = sc_te[sc_te["t_decisao"].dt.floor("D") == ultimo_dia]
    fila = (dia.groupby("Tag")[campeao].max().sort_values(ascending=False)
            .head(topo).rename("score_risco").reset_index())
    fila["posicao"] = np.arange(1, len(fila) + 1)
    fila.to_csv(DIR_TABELAS / "fila_inspecao_ultimo_dia.csv", index=False)
    return fila
