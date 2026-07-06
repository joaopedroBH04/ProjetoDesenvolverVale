# -*- coding: utf-8 -*-
"""Abordagem não supervisionada.

1) Isolation Forest — detector de anomalia treinado só com operação normal
   (registros de treino sem alerta nas 4 h seguintes). Os alertas don't go do
   período de teste servem apenas como ground truth de validação: o modelo
   nunca os vê no treino. A pergunta: desvios do padrão normal antecedem os
   alertas críticos?

2) K-Means — perfis de comportamento equipamento-dia. Não prevê nada; agrupa
   dias de operação e mede a incidência de alertas por cluster, revelando os
   perfis de risco da frota.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from src.config import CORTE_TREINO, CORTE_VALIDACAO, DIR_PROCESSADOS, SEMENTE
from src.features.engenharia import matriz_xy, separar_conjuntos

# Sem encodings supervisionados (taxas históricas de alerta) — a abordagem
# deve permanecer cega ao rótulo.
COLS_SUPERVISIONADAS = ["tag_taxa_alerta", "op_taxa_alerta"]


def isolation_forest(abt: pd.DataFrame):
    treino, valid, teste = separar_conjuntos(abt, CORTE_TREINO, CORTE_VALIDACAO)
    X_tr, y_tr = matriz_xy(treino)
    X_te, y_te = matriz_xy(teste)
    X_tr = X_tr.drop(columns=COLS_SUPERVISIONADAS)
    X_te = X_te.drop(columns=COLS_SUPERVISIONADAS)

    normal = X_tr[y_tr == 0]
    iso = IsolationForest(
        n_estimators=300, max_samples=0.5, contamination="auto",
        random_state=SEMENTE, n_jobs=-1,
    ).fit(normal)

    # score_samples: quanto menor, mais anômalo -> inverte para "risco"
    score_teste = -iso.score_samples(X_te)
    saida = pd.DataFrame({
        "t_decisao": teste["t_decisao"].values, "Tag": teste["Tag"].values,
        "y": y_te, "IsolationForest": score_teste,
    })
    saida.to_parquet(DIR_PROCESSADOS / "scores_isolation_forest.parquet", index=False)
    return iso, saida


def perfis_kmeans(abt: pd.DataFrame, k: int = 4):
    """Agrega o comportamento por equipamento-dia e clusteriza."""
    df = abt.copy()
    df["data"] = df["t_decisao"].dt.floor("D")
    agg = df.groupby(["Tag", "data"]).agg(
        eventos_24h=("n_eventos_24h", "max"),
        crit2_24h=("n_crit2_24h", "max"),
        dg_24h=("n_dg_24h", "max"),
        quase_gatilhos=("quase_gatilhos_24h", "max"),
        horas_operadas=("horas_operadas_24h", "max"),
        ciclos=("ciclos_24h", "max"),
        teve_alerta=("y", "max"),
    ).reset_index()

    feats = ["eventos_24h", "crit2_24h", "dg_24h", "quase_gatilhos",
             "horas_operadas", "ciclos"]
    Xz = StandardScaler().fit_transform(agg[feats])
    km = KMeans(n_clusters=k, n_init=10, random_state=SEMENTE).fit(Xz)
    agg["cluster"] = km.labels_

    perfil = agg.groupby("cluster").agg(
        dias=("Tag", "size"),
        **{f: (f, "mean") for f in feats},
        taxa_alerta=("teve_alerta", "mean"),
    ).round(2).reset_index()
    agg.to_parquet(DIR_PROCESSADOS / "clusters_equipamento_dia.parquet", index=False)
    return km, perfil
