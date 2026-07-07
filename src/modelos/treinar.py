# -*- coding: utf-8 -*-
"""Treinamento dos modelos supervisionados.

Estratégia de validação: hold-out temporal (nada de k-fold aleatório — em
séries temporais isso vaza o futuro para o treino). Treino: jan–abr/2025;
validação: mai/2025 (tuning e escolha de limiar); teste: jun/2025 (avaliação
final, tocado uma única vez).

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

from src.config import CORTE_TREINO, CORTE_VALIDACAO, DIR_PROCESSADOS, SEMENTE
from src.features.engenharia import matriz_xy, separar_conjuntos


def treinar_todos(abt: pd.DataFrame) -> dict:
    treino, valid, teste = separar_conjuntos(abt, CORTE_TREINO, CORTE_VALIDACAO)
    X_tr, y_tr = matriz_xy(treino)
    X_va, y_va = matriz_xy(valid)
    X_te, y_te = matriz_xy(teste)

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
        rl = make_pipeline(
            StandardScaler(),
            LogisticRegression(C=C, class_weight="balanced", max_iter=3000,
                               random_state=SEMENTE),
        ).fit(X_tr, y_tr)
        ap = average_precision_score(y_va, rl.predict_proba(X_va)[:, 1])
        if ap > melhor_ap:
            melhor_ap, melhor_C, melhor_rl = ap, C, rl
    modelos["RegressaoLogistica"] = melhor_rl
    scores["valid"]["RegressaoLogistica"] = melhor_rl.predict_proba(X_va)[:, 1]
    scores["teste"]["RegressaoLogistica"] = melhor_rl.predict_proba(X_te)[:, 1]
    print(f"  RegLog: C={melhor_C} (AP validação={melhor_ap:.4f})")

    # ------------------------------------------------------------ random forest
    melhor_ap, melhor_leaf = -1.0, None
    for leaf in (5, 20, 60):
        rf = RandomForestClassifier(
            n_estimators=400, min_samples_leaf=leaf, max_features="sqrt",
            class_weight="balanced_subsample", n_jobs=-1, random_state=SEMENTE,
        ).fit(X_tr, y_tr)
        ap = average_precision_score(y_va, rf.predict_proba(X_va)[:, 1])
        if ap > melhor_ap:
            melhor_ap, melhor_leaf, melhor_rf = ap, leaf, rf
    modelos["RandomForest"] = melhor_rf
    scores["valid"]["RandomForest"] = melhor_rf.predict_proba(X_va)[:, 1]
    scores["teste"]["RandomForest"] = melhor_rf.predict_proba(X_te)[:, 1]
    print(f"  RF: min_samples_leaf={melhor_leaf} (AP validação={melhor_ap:.4f})")

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
        gbm = lgb.LGBMClassifier(
            n_estimators=1500, random_state=SEMENTE, n_jobs=-1, verbose=-1, **params
        )
        gbm.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], eval_metric="average_precision",
                callbacks=[lgb.early_stopping(60, verbose=False)])
        ap = average_precision_score(y_va, gbm.predict_proba(X_va)[:, 1])
        if ap > melhor_ap:
            melhor_ap, melhor_params, melhor_gbm = ap, params, gbm
    modelos["LightGBM"] = melhor_gbm
    scores["valid"]["LightGBM"] = melhor_gbm.predict_proba(X_va)[:, 1]
    scores["teste"]["LightGBM"] = melhor_gbm.predict_proba(X_te)[:, 1]
    print(f"  LightGBM: AP validação={melhor_ap:.4f} | params={melhor_params} "
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
