# -*- coding: utf-8 -*-
"""Avaliação: métricas, limiar operacional, análise de erros e impacto.

O limiar de operação é escolhido na VALIDAÇÃO maximizando F2 (recall pesa o
dobro da precisão): na mina, o falso negativo vira parada não planejada com
equipamento possivelmente comprometido, enquanto o falso positivo custa uma
inspeção de ~1 h. O teste (jun/2025) é tocado uma única vez, já com o limiar
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
    for nome, sc in (("mai/2025 (validação)", sc_va), ("jun/2025 (teste)", sc_te)):
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


def _duracao_episodio_manutencao(ap: pd.DataFrame) -> float:
    """Duração média (h) do EPISÓDIO de manutenção.

    A base registra classe única "Manutenção" e fatia atividades longas em
    ciclos de no máximo 60 min; a duração real da intervenção é a do episódio:
    apontamentos consecutivos da mesma Tag com intervalo < 30 min."""
    manut = ap[ap["Classe"] == "Manutenção"].sort_values(["Tag", "Inicio"]).copy()
    fim_anterior = manut.groupby("Tag")["Fim"].shift()
    novo_episodio = (manut["Inicio"] - fim_anterior > pd.Timedelta("30min")) | fim_anterior.isna()
    manut["_ep"] = novo_episodio.cumsum()
    episodios = manut.groupby("_ep").agg(ini=("Inicio", "min"), fim=("Fim", "max"))
    return float(((episodios["fim"] - episodios["ini"])
                  .dt.total_seconds() / 3600).mean())


def _resultado_operacional(sc, alertas, limiar, dur_corretiva_h, campeao="LightGBM"):
    """Antecipação, falsos positivos e benefício líquido de um limiar."""
    pred = sc[campeao] >= limiar
    al = alertas[alertas["Data_Alerta"] >= sc["t_decisao"].min()]
    al = al[al["Data_Alerta"] <= sc["t_decisao"].max()
            + pd.Timedelta(hours=JANELA_PREDICAO_HORAS)]
    tp = sc[(sc["y"] == 1) & pred]
    janela = pd.Timedelta(hours=JANELA_PREDICAO_HORAS)
    antecipados, antecedencias = 0, []
    for linha in al.itertuples(index=False):
        acertos = tp[(tp["Tag"] == linha.TAG)
                     & (tp["t_decisao"] >= linha.Data_Alerta - janela)
                     & (tp["t_decisao"] < linha.Data_Alerta)]
        if len(acertos):
            antecipados += 1
            antecedencias.append(
                (linha.Data_Alerta - acertos["t_decisao"].min()).total_seconds() / 3600)
    fp = int((~sc["y"].astype(bool) & pred).sum())
    horas_evitadas = antecipados * dur_corretiva_h * REDUCAO_PARADA_ANTECIPADA
    beneficio = horas_evitadas * CUSTO_HORA_PARADA
    custo_fp = fp * CUSTO_INSPECAO
    return dict(
        alertas=len(al), antecipados=antecipados,
        taxa=antecipados / max(len(al), 1),
        antecedencia_mediana=float(np.median(antecedencias)) if antecedencias else np.nan,
        horas_evitadas=horas_evitadas, fp=fp,
        beneficio=beneficio, custo_fp=custo_fp, liquido=beneficio - custo_fp,
    )


def limiar_custo_otimo(sc_va, alertas, dur_corretiva_h, campeao="LightGBM"):
    """Limiar que maximiza o benefício líquido estimado NA VALIDAÇÃO.

    O F2 maximiza captura sob custo assimétrico genérico; este ponto usa as
    premissas financeiras explícitas do negócio. Escolhido na validação e
    congelado antes de tocar o teste, como o limiar F2."""
    candidatos = np.unique(np.quantile(sc_va[campeao], np.linspace(0.70, 0.999, 120)))
    melhor_t, melhor_b = candidatos[0], -np.inf
    for t in candidatos:
        r = _resultado_operacional(sc_va, alertas, t, dur_corretiva_h, campeao)
        if r["liquido"] > melhor_b:
            melhor_b, melhor_t = r["liquido"], t
    return float(melhor_t)


def impacto_negocio(sc_va, sc_te, alertas, ap, limiar_f2, campeao="LightGBM"):
    """Converte os dois pontos de operação (F2 e custo-ótimo) em horas e R$."""
    dur_corretiva_h = _duracao_episodio_manutencao(ap)
    limiar_rs = limiar_custo_otimo(sc_va, alertas, dur_corretiva_h, campeao)
    r_f2 = _resultado_operacional(sc_te, alertas, limiar_f2, dur_corretiva_h, campeao)
    r_rs = _resultado_operacional(sc_te, alertas, limiar_rs, dur_corretiva_h, campeao)

    linhas = [
        ("Limiar (escolhido na validação)", round(limiar_f2, 4), round(limiar_rs, 4)),
        ("Alertas don't go no teste (jun/2025)", r_f2["alertas"], r_rs["alertas"]),
        ("Alertas antecipados (≥1 acerto nas 4 h anteriores)",
         r_f2["antecipados"], r_rs["antecipados"]),
        ("Taxa de antecipação", round(r_f2["taxa"], 3), round(r_rs["taxa"], 3)),
        ("Antecedência mediana do 1º aviso (h)",
         round(r_f2["antecedencia_mediana"], 2), round(r_rs["antecedencia_mediana"], 2)),
        ("Duração média do episódio de manutenção (h)",
         round(dur_corretiva_h, 2), round(dur_corretiva_h, 2)),
        ("Horas de parada não planejada evitadas (premissa 35%)",
         round(r_f2["horas_evitadas"], 1), round(r_rs["horas_evitadas"], 1)),
        ("Falsos positivos no mês (inspeções vazias)", r_f2["fp"], r_rs["fp"]),
        ("Benefício bruto estimado (R$)", round(r_f2["beneficio"], 0), round(r_rs["beneficio"], 0)),
        ("Custo das inspeções vazias (R$)", round(r_f2["custo_fp"], 0), round(r_rs["custo_fp"], 0)),
        ("Benefício líquido estimado no mês (R$)",
         round(r_f2["liquido"], 0), round(r_rs["liquido"], 0)),
    ]
    tab = pd.DataFrame(linhas,
                       columns=["Indicador", "Ponto F2 (captura)", "Ponto custo-ótimo (R$)"])
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
