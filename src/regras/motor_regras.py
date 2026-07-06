# -*- coding: utf-8 -*-
"""Motor de regras don't go.

Aplica o catálogo CMA (Alarmes - SUL_SUDESTE.xlsx) sobre a telemetria limpa.
Cada regra é uma combinação TIPO + EVENTO + SITUACAO + QTD + TEMPO + NIVEL:
o alerta dispara quando QTD ocorrências do EVENTO, no nível exigido pela
SITUACAO, acontecem dentro de TEMPO minutos para o mesmo equipamento.

Interpretação adotada (registrada como decisão metodológica):
  * "Mediante alarme nível 3"            -> eventos com Id_Criticidade = 1
  * "... alarmes nivel 2 consecutivos"   -> QTD eventos nível 2 dentro de TEMPO
  * "... nível 1 e 2"                    -> Id_Criticidade em {2, 3}
  * "... alarmes de tendência"           -> ocorrências do próprio evento TENDÊNCIA
  * "Em qualquer situação"               -> qualquer criticidade conta
  * Regras SISTEMA (Minecare/MEMS)       -> disparo imediato na ocorrência
  * TEMPO = 0 com QTD = 1                -> disparo imediato
A consecutividade é aproximada por "QTD ocorrências dentro da janela TEMPO";
sem o estado intermediário do alarme não há como verificar interrupções, e a
aproximação é conservadora (nunca dispara com menos eventos que o exigido).

Após disparar, a mesma regra fica em cooldown de 6 h para o mesmo equipamento,
evitando que um único episódio físico gere dezenas de alertas repetidos.
"""

import re

import numpy as np
import pandas as pd

from src.config import COOLDOWN_REGRA_HORAS, CRITICIDADE_PARA_NIVEL


def _niveis_da_situacao(situacao: str) -> set:
    """Traduz o texto da SITUACAO para o conjunto de níveis OEM que contam."""
    s = situacao.lower()
    if "nível 3" in s or "nivel 3" in s:
        return {3}
    if ("nível 1 e 2" in s) or ("nivel 1 e 2" in s):
        return {1, 2}
    if "nível 2" in s or "nivel 2" in s:
        return {2}
    if "nível 1" in s or "nivel 1" in s:
        return {1}
    # "Em qualquer situação", tendências e regras de sistema: qualquer nível
    return {0, 1, 2, 3}


def compilar_regras(cma: pd.DataFrame) -> pd.DataFrame:
    regras = cma.copy()
    regras["niveis"] = regras["SITUACAO"].map(_niveis_da_situacao)
    regras["janela_min"] = regras["TEMPO"].astype(int)
    regras["qtd_min"] = regras["QTD"].astype(int).clip(lower=1)
    return regras


def aplicar_regras(tel: pd.DataFrame, regras: pd.DataFrame) -> pd.DataFrame:
    """Varre a telemetria e materializa os alertas don't go.

    Retorna um DataFrame com um registro por disparo: equipamento, instante,
    regra, evento e nível de criticidade do alerta.
    """
    # Só eventos cujo nome consta no catálogo podem disparar regra
    tel_dg = tel[tel["Is_Dont_Go"] == 1].copy()
    tel_dg["nivel_oem"] = tel_dg["Id_Criticidade"].map(CRITICIDADE_PARA_NIVEL)

    cooldown = pd.Timedelta(hours=COOLDOWN_REGRA_HORAS)
    disparos = []

    for regra in regras.itertuples(index=False):
        eventos = tel_dg[tel_dg["Alarme_Norm"] == regra.EVENTO_Norm]
        eventos = eventos[eventos["nivel_oem"].isin(regra.niveis)]
        if eventos.empty:
            continue
        janela = pd.Timedelta(minutes=max(regra.janela_min, 1))
        for tag, grupo in eventos.groupby("TAG", sort=False):
            ts = grupo["Data_Evento"].sort_values().to_numpy()
            if regra.qtd_min == 1:
                gatilhos = ts
            else:
                # instante em que a QTD-ésima ocorrência cai dentro da janela
                k = regra.qtd_min - 1
                dentro = (ts[k:] - ts[:-k]) <= np.timedelta64(int(janela.total_seconds()), "s")
                gatilhos = ts[k:][dentro]
            ultimo = None
            for t in gatilhos:
                if ultimo is None or (t - ultimo) > cooldown:
                    disparos.append((tag, t, regra.Id_Regra, regra.TIPO,
                                     regra.EVENTO, regra.SITUACAO, regra.NIVEL))
                    ultimo = t

    alertas = pd.DataFrame(
        disparos,
        columns=["TAG", "Data_Alerta", "Id_Regra", "TIPO", "EVENTO", "SITUACAO", "NIVEL"],
    )
    if alertas.empty:
        return alertas
    alertas = alertas.sort_values(["TAG", "Data_Alerta"]).reset_index(drop=True)

    # Colapsa disparos simultâneos de regras distintas do mesmo evento físico:
    # mantém o de maior criticidade dentro de uma janela de 30 min por TAG+EVENTO.
    prioridade = alertas["NIVEL"].map({"Muito Alto": 0, "Alto": 1}).fillna(2)
    alertas = alertas.assign(_prio=prioridade)
    alertas["_grupo"] = (
        alertas.groupby(["TAG", "EVENTO"])["Data_Alerta"].diff()
        .gt(pd.Timedelta(minutes=30)).fillna(True).groupby(
            [alertas["TAG"], alertas["EVENTO"]]).cumsum()
    )
    alertas = (
        alertas.sort_values(["TAG", "EVENTO", "_grupo", "_prio", "Data_Alerta"])
        .groupby(["TAG", "EVENTO", "_grupo"], as_index=False).first()
        .drop(columns=["_grupo", "_prio"])
        .sort_values(["TAG", "Data_Alerta"])
        .reset_index(drop=True)
    )
    return alertas


def resumo_alertas(alertas: pd.DataFrame) -> pd.DataFrame:
    return (
        alertas.groupby(["TIPO", "NIVEL"])
        .size()
        .rename("Qtd_Alertas")
        .reset_index()
        .sort_values("Qtd_Alertas", ascending=False)
    )
