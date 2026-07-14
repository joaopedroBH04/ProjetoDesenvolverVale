# -*- coding: utf-8 -*-
"""Treinamento dos modelos supervisionados.

Estratégia de validação: hold-out temporal (nada de k-fold aleatório — em
séries temporais isso vaza o futuro para o treino). Treino final: jan–abr/2025;
validação: mai/2025 (escolha de limiar); teste: jun/2025 (avaliação final,
tocado uma única vez).

Tuning em DUAS janelas: cada configuração de hiperparâmetros é avaliada em
(treino jan–mar → validação abr) e (treino jan–abr → validação mai), e a
seleção usa a média do average precision das duas. Um único mês de validação
pode eleger uma configuração ajustada às idiossincrasias daquele mês (maio,
por exemplo, muda de regime na 2ª quinzena); a média de duas janelas
independentes seleciona configurações que generalizam entre regimes.

Modelos:
  * Baseline 1 — Dummy (probabilidade a priori da classe)
  * Baseline 2 — Heurística do despacho: score = nº de alarmes do catálogo
    don't go nas últimas 12 h (o que um despachante enxerga no painel)
  * Regressão Logística (linear, calibrada, interpretável)
  * Random Forest (não linear, robusto, pouco tuning)
  * LightGBM (gradient boosting, busca aleatória de hiperparâmetros)
"""

import json

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.config import (CORTE_JANELA_A, CORTE_TREINO, CORTE_VALIDACAO,
                        DIR_PROCESSADOS, SEMENTE)
from src.features.engenharia import matriz_xy, separar_conjuntos


def treinar_todos(abt: pd.DataFrame) -> dict:
    treino, valid, teste = separar_conjuntos(abt, CORTE_TREINO, CORTE_VALIDACAO)
    X_tr, y_tr = matriz_xy(treino)
    X_va, y_va = matriz_xy(valid)
    X_te, y_te = matriz_xy(teste)

    # janela extra de tuning: treino jan–mar, validação abr
    tr_a = abt[abt["t_decisao"] < CORTE_JANELA_A]
    va_a = abt[(abt["t_decisao"] >= CORTE_JANELA_A)
               & (abt["t_decisao"] < CORTE_TREINO)]
    X_ta, y_ta = matriz_xy(tr_a)
    X_vaa, y_vaa = matriz_xy(va_a)

    janelas = [(X_ta, y_ta, X_vaa, y_vaa),   # A: jan–mar → abr
               (X_tr, y_tr, X_va, y_va)]     # B: jan–abr → mai (fit final)

    scores = {
        "valid": pd.DataFrame({"t_decisao": valid["t_decisao"].values,
                               "Tag": valid["Tag"].values, "y": y_va}),
        "teste": pd.DataFrame({"t_decisao": teste["t_decisao"].values,
                               "Tag": teste["Tag"].values, "y": y_te}),
    }
    modelos = {}

    # ---------------------------------------------------------------- dummies
    dummy = DummyClassifier(strategy="prior").fit(X_tr, y_tr)
    scores["valid"]["Dummy"] = dummy.predict_proba(X_va)[:, 1]
    scores["teste"]["Dummy"] = dummy.predict_proba(X_te)[:, 1]

    # Heurística do despacho: contagem de alarmes monitorados nas últimas 12 h
    scores["valid"]["Heuristica"] = X_va["n_dg_12h"].to_numpy(dtype=float)
    scores["teste"]["Heuristica"] = X_te["n_dg_12h"].to_numpy(dtype=float)

    # ---------------------------------------------------- regressão logística
    melhor_ap, melhor_C = -1.0, None
    for C in (0.01, 0.1, 1.0, 10.0):
        aps, fit_b = [], None
        for X_t, y_t, X_v, y_v in janelas:
            rl = make_pipeline(
                StandardScaler(),
                LogisticRegression(C=C, class_weight="balanced", max_iter=3000,
                                   random_state=SEMENTE),
            ).fit(X_t, y_t)
            aps.append(average_precision_score(y_v, rl.predict_proba(X_v)[:, 1]))
            fit_b = rl
        ap = float(np.mean(aps))
        if ap > melhor_ap:
            melhor_ap, melhor_C, melhor_rl = ap, C, fit_b
    modelos["RegressaoLogistica"] = melhor_rl
    scores["valid"]["RegressaoLogistica"] = melhor_rl.predict_proba(X_va)[:, 1]
    scores["teste"]["RegressaoLogistica"] = melhor_rl.predict_proba(X_te)[:, 1]
    print(f"  RegLog: C={melhor_C} (AP médio abr+mai={melhor_ap:.4f})")

    # ------------------------------------------------------------ random forest
    melhor_ap, melhor_leaf = -1.0, None
    for leaf in (5, 20, 60):
        aps, fit_b = [], None
        for X_t, y_t, X_v, y_v in janelas:
            rf = RandomForestClassifier(
                n_estimators=400, min_samples_leaf=leaf, max_features="sqrt",
                class_weight="balanced_subsample", n_jobs=-1, random_state=SEMENTE,
            ).fit(X_t, y_t)
            aps.append(average_precision_score(y_v, rf.predict_proba(X_v)[:, 1]))
            fit_b = rf
        ap = float(np.mean(aps))
        if ap > melhor_ap:
            melhor_ap, melhor_leaf, melhor_rf = ap, leaf, fit_b
    modelos["RandomForest"] = melhor_rf
    scores["valid"]["RandomForest"] = melhor_rf.predict_proba(X_va)[:, 1]
    scores["teste"]["RandomForest"] = melhor_rf.predict_proba(X_te)[:, 1]
    print(f"  RF: min_samples_leaf={melhor_leaf} (AP médio abr+mai={melhor_ap:.4f})")

    # ---------------------------------------------------------------- lightgbm
    rng = np.random.default_rng(SEMENTE)
    pos_weight = (y_tr == 0).sum() / max((y_tr == 1).sum(), 1)
    melhor_ap, melhor_params = -1.0, None
    for i in range(30):
        params = dict(
            num_leaves=int(rng.choice([15, 31, 63, 95, 127])),
            learning_rate=float(10 ** rng.uniform(-2.0, -0.7)),
            min_child_samples=int(rng.choice([10, 30, 60, 120, 200])),
            feature_fraction=float(rng.uniform(0.6, 1.0)),
            bagging_fraction=float(rng.uniform(0.6, 1.0)),
            bagging_freq=1,
            reg_alpha=float(10 ** rng.uniform(-3, 1)),
            reg_lambda=float(10 ** rng.uniform(-3, 1)),
            scale_pos_weight=float(rng.choice([1.0, np.sqrt(pos_weight), pos_weight])),
        )
        aps, fit_b = [], None
        for X_t, y_t, X_v, y_v in janelas:
            gbm = lgb.LGBMClassifier(
                n_estimators=1500, random_state=SEMENTE, n_jobs=-1, verbose=-1,
                **params)
            gbm.fit(X_t, y_t, eval_set=[(X_v, y_v)],
                    eval_metric="average_precision",
                    callbacks=[lgb.early_stopping(60, verbose=False)])
            aps.append(average_precision_score(y_v, gbm.predict_proba(X_v)[:, 1]))
            fit_b = gbm
        ap = float(np.mean(aps))
        if ap > melhor_ap:
            melhor_ap, melhor_params, melhor_gbm = ap, params, fit_b
    modelos["LightGBM"] = melhor_gbm
    scores["valid"]["LightGBM"] = melhor_gbm.predict_proba(X_va)[:, 1]
    scores["teste"]["LightGBM"] = melhor_gbm.predict_proba(X_te)[:, 1]
    print(f"  LightGBM: AP médio abr+mai={melhor_ap:.4f} | params={melhor_params} "
          f"| n_arvores={melhor_gbm.best_iteration_}")

    # persistência
    joblib.dump(modelos, DIR_PROCESSADOS / "modelos_supervisionados.joblib")
    scores["valid"].to_parquet(DIR_PROCESSADOS / "scores_validacao.parquet", index=False)
    scores["teste"].to_parquet(DIR_PROCESSADOS / "scores_teste.parquet", index=False)
    with open(DIR_PROCESSADOS / "lightgbm_params.json", "w") as f:
        json.dump({**melhor_params, "n_arvores": int(melhor_gbm.best_iteration_ or 0)}, f,
                  indent=2)

    for nome in ("Dummy", "Heuristica", "RegressaoLogistica", "RandomForest", "LightGBM"):
        auc = roc_auc_score(y_va, scores["valid"][nome])
        ap = average_precision_score(y_va, scores["valid"][nome])
        print(f"  [validação] {nome:20s} AUC-ROC={auc:.4f} AUC-PR={ap:.4f}")
    return modelos, scores
