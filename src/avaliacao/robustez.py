# -*- coding: utf-8 -*-
"""Análises de robustez complementares (execução opcional, após o pipeline).

Uso: python -m src.avaliacao.robustez
Requer a camada processada gerada por executar_pipeline.py (ABT e scores).

1. Walk-forward: re-treina o campeão em janelas expansivas mensais e avalia
   sempre no mês seguinte, verificando se o desempenho depende do corte.
2. Sensibilidade da janela de predição: repete o treino com alvos de 2 h e
   8 h para sustentar a escolha operacional de 4 h.
3. Calibração de probabilidade: confiabilidade por decis e escore de Brier,
   com e sem calibração isotônica ajustada na validação.
4. Varredura limiar x custo: converte cada limiar possível em benefício
   líquido (R$), materializando a curva completa entre os pontos F2 e
   custo-ótimo já reportados pelo pipeline.
5. Antecipação por subsistema: em qual família física o modelo enxerga ou
   não o alerta que está por vir.
"""

import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from src.config import (CORTE_TREINO, CORTE_VALIDACAO, DIR_PROCESSADOS,
                        DIR_TABELAS, JANELA_PREDICAO_HORAS, SEMENTE)
from src.features.engenharia import matriz_xy

from src.avaliacao.avaliar import (CUSTO_HORA_PARADA, CUSTO_INSPECAO,
                                   REDUCAO_PARADA_ANTECIPADA,
                                   _duracao_episodio_manutencao, limiar_f2)

SUBSISTEMAS = [
    ("Arrefecimento/Motor", ["COOLANT", "OVERHEAT", "AFTERCOOLER", "EXPANSION TANK"]),
    ("Lubrificação do motor", ["ENGINE OIL", "OIL LEVEL", "OIL PRESSURE", "ÓLEO MOTOR",
                               "OLEO MOTOR", "CRANKCASE", "RIFLE"]),
    ("Transmissão", ["TRANSMISSION", "TORQUE CONVERTER", "GEARBOX"]),
    ("Freios", ["BRAKE", "FREIO"]),
    ("Hidráulico/Direção", ["HYDRAULIC", "STEERING"]),
    ("Escape/Turbo", ["EXHAUST", "TURBO", "CYLINDER"]),
    ("Pneus", ["TIRE"]),
    ("Elétrico/Gerador", ["GRID BLOWER", "GENERATOR"]),
    ("Lubrificação automática", ["LUBE", "LUBRICATION"]),
    ("Sistema/Comunicação", ["MINECARE", "MEMS"]),
]


def _classifica_subsistema(evento: str) -> str:
    ev = evento.upper()
    for nome, chaves in SUBSISTEMAS:
        if any(c in ev for c in chaves):
            return nome
    return "Outros"


def _params_campeao() -> dict:
    with open(DIR_PROCESSADOS / "lightgbm_params.json") as f:
        p = json.load(f)
    n = max(int(p.pop("n_arvores", 200)), 3)
    return dict(n_estimators=n, random_state=SEMENTE, n_jobs=-1, verbose=-1, **p)


def walk_forward(abt: pd.DataFrame) -> pd.DataFrame:
    """Janela expansiva: treina até o fim de um mês, avalia no mês seguinte."""
    params = _params_campeao()
    cortes = ["2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01", "2025-06-01"]
    linhas = []
    for corte in cortes:
        fim_aval = (pd.Timestamp(corte) + pd.offsets.MonthBegin(1))
        tr = abt[abt["t_decisao"] < corte]
        av = abt[(abt["t_decisao"] >= corte) & (abt["t_decisao"] < fim_aval)]
        if tr.empty or av.empty or av["y"].nunique() < 2:
            continue
        X_tr, y_tr = matriz_xy(tr)
        X_av, y_av = matriz_xy(av)
        gbm = lgb.LGBMClassifier(**params).fit(X_tr, y_tr)
        score = gbm.predict_proba(X_av)[:, 1]
        linhas.append(dict(
            Treino_ate=str(pd.Timestamp(corte).date() - pd.Timedelta(days=1)),
            Mes_avaliado=pd.Timestamp(corte).strftime("%b/%Y"),
            N_treino=len(tr), N_aval=len(av),
            Prevalencia=round(float(y_av.mean()), 4),
            AUC_ROC=round(roc_auc_score(y_av, score), 4),
            AUC_PR=round(average_precision_score(y_av, score), 4),
            AUC_PR_heuristica=round(
                average_precision_score(y_av, X_av["n_dg_12h"]), 4),
        ))
    tab = pd.DataFrame(linhas)
    tab.to_csv(DIR_TABELAS / "walk_forward.csv", index=False)
    return tab


def sensibilidade_janela(abt: pd.DataFrame) -> pd.DataFrame:
    """Re-treina o campeão com alvos de 2 h, 4 h e 8 h."""
    params = _params_campeao()
    linhas = []
    for h in (2, JANELA_PREDICAO_HORAS, 8):
        df = abt.copy()
        df["y"] = (df["horas_ate_alerta"] <= h).astype(np.int8)
        tr = df[df["t_decisao"] < CORTE_TREINO]
        va = df[(df["t_decisao"] >= CORTE_TREINO) & (df["t_decisao"] < CORTE_VALIDACAO)]
        te = df[df["t_decisao"] >= CORTE_VALIDACAO]
        X_tr, y_tr = matriz_xy(tr)
        X_va, y_va = matriz_xy(va)
        X_te, y_te = matriz_xy(te)
        gbm = lgb.LGBMClassifier(**params).fit(X_tr, y_tr)
        s_va = gbm.predict_proba(X_va)[:, 1]
        s_te = gbm.predict_proba(X_te)[:, 1]
        t = limiar_f2(y_va, s_va)
        pred = s_te >= t
        vp = int(((y_te == 1) & pred).sum())
        linhas.append(dict(
            Janela_h=h, Prevalencia_teste=round(float(y_te.mean()), 4),
            AUC_ROC=round(roc_auc_score(y_te, s_te), 4),
            AUC_PR=round(average_precision_score(y_te, s_te), 4),
            Recall=round(vp / max(int((y_te == 1).sum()), 1), 4),
            Precision=round(vp / max(int(pred.sum()), 1), 4),
        ))
    tab = pd.DataFrame(linhas)
    tab.to_csv(DIR_TABELAS / "sensibilidade_janela.csv", index=False)
    return tab


def calibracao(sc_va: pd.DataFrame, sc_te: pd.DataFrame, campeao="LightGBM"):
    """Confiabilidade por decil e Brier, antes e depois da isotônica."""
    iso = IsotonicRegression(out_of_bounds="clip").fit(sc_va[campeao], sc_va["y"])
    bruto = sc_te[campeao].to_numpy()
    calibrado = iso.predict(bruto)
    y = sc_te["y"].to_numpy()

    resumo = dict(
        brier_bruto=float(brier_score_loss(y, np.clip(bruto, 0, 1))),
        brier_calibrado=float(brier_score_loss(y, calibrado)),
        base=float(brier_score_loss(y, np.full_like(calibrado, y.mean()))),
    )
    bins = pd.qcut(bruto, 10, duplicates="drop")
    tab = pd.DataFrame({
        "score_medio_bruto": pd.Series(bruto).groupby(bins, observed=True).mean().values,
        "score_medio_calibrado": pd.Series(calibrado).groupby(bins, observed=True).mean().values,
        "taxa_observada": pd.Series(y).groupby(bins, observed=True).mean().values,
        "n": pd.Series(y).groupby(bins, observed=True).size().values,
    }).round(5)
    tab.to_csv(DIR_TABELAS / "calibracao_decis.csv", index=False)
    return tab, resumo


def _max_score_por_alerta(sc_te: pd.DataFrame, alertas: pd.DataFrame,
                          campeao="LightGBM") -> pd.DataFrame:
    """Maior score emitido nas N horas anteriores a cada alerta do teste."""
    janela = pd.Timedelta(hours=JANELA_PREDICAO_HORAS)
    al = alertas[(alertas["Data_Alerta"] >= sc_te["t_decisao"].min())
                 & (alertas["Data_Alerta"] <= sc_te["t_decisao"].max() + janela)].copy()
    maximos = []
    for linha in al.itertuples(index=False):
        pontos = sc_te[(sc_te["Tag"] == linha.TAG)
                       & (sc_te["t_decisao"] >= linha.Data_Alerta - janela)
                       & (sc_te["t_decisao"] < linha.Data_Alerta)]
        maximos.append(float(pontos[campeao].max()) if len(pontos) else np.nan)
    al["max_score_previo"] = maximos
    return al


def custo_limiar(sc_te: pd.DataFrame, alertas: pd.DataFrame, ap: pd.DataFrame,
                 campeao="LightGBM"):
    """Benefício líquido mensal (R$) em função do limiar de decisão."""
    al = _max_score_por_alerta(sc_te, alertas, campeao)
    dur_episodio_h = _duracao_episodio_manutencao(ap)
    ganho_por_alerta = dur_episodio_h * REDUCAO_PARADA_ANTECIPADA * CUSTO_HORA_PARADA

    score = sc_te[campeao].to_numpy()
    y = sc_te["y"].to_numpy()
    grade = np.unique(np.quantile(score, np.linspace(0.50, 0.9995, 220)))
    linhas = []
    for t in grade:
        antecipados = int((al["max_score_previo"] >= t).sum())
        fp = int(((y == 0) & (score >= t)).sum())
        beneficio = antecipados * ganho_por_alerta - fp * CUSTO_INSPECAO
        linhas.append((t, antecipados, fp, beneficio))
    tab = pd.DataFrame(linhas, columns=["limiar", "alertas_antecipados",
                                        "falsos_positivos", "beneficio_liquido"])
    tab.to_csv(DIR_TABELAS / "custo_por_limiar.csv", index=False)
    otimo = tab.loc[tab["beneficio_liquido"].idxmax()]
    return tab, float(otimo["limiar"]), float(otimo["beneficio_liquido"])


def antecipacao_por_subsistema(sc_te: pd.DataFrame, alertas: pd.DataFrame,
                               limiar: float, campeao="LightGBM") -> pd.DataFrame:
    """Taxa de antecipação por família física de falha (nível de alerta)."""
    al = _max_score_por_alerta(sc_te, alertas, campeao)
    al["Subsistema"] = al["EVENTO"].map(_classifica_subsistema)
    al["antecipado"] = al["max_score_previo"] >= limiar
    tab = (al.groupby("Subsistema")
           .agg(alertas=("antecipado", "size"), antecipados=("antecipado", "sum"))
           .assign(taxa_antecipacao=lambda d: (d["antecipados"] / d["alertas"]).round(3))
           .sort_values("alertas", ascending=False).reset_index())
    tab.to_csv(DIR_TABELAS / "antecipacao_por_subsistema.csv", index=False)
    return tab


if __name__ == "__main__":
    from src.etl import carga

    abt = carga.ler("abt")
    sc_va = pd.read_parquet(DIR_PROCESSADOS / "scores_validacao.parquet")
    sc_te = pd.read_parquet(DIR_PROCESSADOS / "scores_teste.parquet")
    alertas = carga.ler("alertas_dont_go")
    ap = carga.ler("apontamentos_limpos")

    print(walk_forward(abt).to_string(index=False))
    print(sensibilidade_janela(abt).to_string(index=False))
    _, resumo = calibracao(sc_va, sc_te)
    print(f"Brier: bruto {resumo['brier_bruto']:.4f} | "
          f"isotônica {resumo['brier_calibrado']:.4f} | base {resumo['base']:.4f}")
    _, limiar_otimo, beneficio = custo_limiar(sc_te, alertas, ap)
    print(f"Ótimo financeiro: limiar {limiar_otimo:.4f} (R$ {beneficio:,.0f})")
    lim_f2 = limiar_f2(sc_va["y"], sc_va["LightGBM"])
    print(antecipacao_por_subsistema(sc_te, alertas, lim_f2).to_string(index=False))
