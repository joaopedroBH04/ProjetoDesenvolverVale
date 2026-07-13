# -*- coding: utf-8 -*-
"""Engenharia de features e construção da tabela analítica (ABT).

Ponto de decisão: o fim de cada apontamento fora de manutenção. A cada ciclo
encerrado o sistema recalcula o risco de alerta don't go nas próximas
JANELA_PREDICAO_HORAS horas para aquele equipamento.

Todas as features usam exclusivamente informação disponível até o instante de
decisão t (contagens em janelas retroativas, tempos "desde o último ..."),
evitando vazamento temporal. Encodings dependentes da taxa de alerta
(equipamento e operador) são estimados apenas no período de treino.

Conforme o dicionário de dados revisado, a tabela Apontamentos não carrega o
operador; o operador em turno é derivado da Telemetria, tomando o último
evento do equipamento até o instante de decisão.
"""

import numpy as np
import pandas as pd

from src.config import CORTE_TREINO, JANELA_PREDICAO_HORAS

JANELAS_H = [4, 12, 24, 72]


def _contagem_retroativa(ts_eventos: np.ndarray, ts_decisao: np.ndarray, horas: int):
    """Quantos eventos ocorreram em (t - horas, t] para cada t de decisão."""
    if len(ts_eventos) == 0:
        return np.zeros(len(ts_decisao), dtype=np.int32)
    fim = np.searchsorted(ts_eventos, ts_decisao, side="right")
    ini = np.searchsorted(ts_eventos, ts_decisao - np.timedelta64(horas, "h"), side="right")
    return (fim - ini).astype(np.int32)


def _horas_desde_ultimo(ts_eventos: np.ndarray, ts_decisao: np.ndarray, teto=240.0):
    """Horas desde o último evento antes de t (teto para 'nunca ocorreu')."""
    out = np.full(len(ts_decisao), teto, dtype=np.float32)
    if len(ts_eventos) == 0:
        return out
    idx = np.searchsorted(ts_eventos, ts_decisao, side="right") - 1
    tem = idx >= 0
    delta = (ts_decisao[tem] - ts_eventos[idx[tem]]) / np.timedelta64(1, "h")
    out[tem] = np.minimum(delta, teto)
    return out


def _quase_gatilhos(tel_dg_tag: pd.DataFrame) -> np.ndarray:
    """Instantes em que um evento do catálogo teve a 2ª ocorrência em < 6 h.

    É a materialização da 'pré-condição de regra': o equipamento repetiu um
    alarme monitorado em janela curta, ainda sem necessariamente disparar a
    regra cheia (que pode exigir 3, 5 ou 10 ocorrências).
    """
    momentos = []
    for _, grupo in tel_dg_tag.groupby("Alarme_Norm", sort=False):
        ts = grupo["Data_Evento"].sort_values().to_numpy()
        if len(ts) < 2:
            continue
        dupla = (ts[1:] - ts[:-1]) <= np.timedelta64(6, "h")
        momentos.append(ts[1:][dupla])
    if not momentos:
        return np.array([], dtype="datetime64[ns]")
    return np.sort(np.concatenate(momentos))


def construir_abt(ap: pd.DataFrame, tel: pd.DataFrame, alertas: pd.DataFrame,
                  tendencias_nomes: set) -> pd.DataFrame:
    """Monta a tabela analítica com uma linha por ponto de decisão."""
    base = ap[~ap["Classe"].str.startswith("Manutenção")].copy()
    base = base.sort_values(["Tag", "Fim"]).reset_index(drop=True)

    mediana_classe_tag = (
        ap.groupby(["Tag", "Classe"])["duracao_min"].median().rename("dur_mediana")
    )
    base = base.join(mediana_classe_tag, on=["Tag", "Classe"])
    base["razao_duracao"] = (base["duracao_min"] / base["dur_mediana"]).clip(0, 6)

    tel = tel.sort_values(["TAG", "Data_Evento"])
    manut = ap[ap["Classe"].str.startswith("Manutenção")]

    blocos = []
    for tag, grupo in base.groupby("Tag", sort=False):
        t_dec = grupo["Fim"].to_numpy()
        tel_tag = tel[tel["TAG"] == tag]
        ts_por_crit = {
            c: tel_tag.loc[tel_tag["Id_Criticidade"] == c, "Data_Evento"].to_numpy()
            for c in (1, 2, 3)
        }
        tel_dg_tag = tel_tag[tel_tag["Is_Dont_Go"] == 1]
        ts_dg = tel_dg_tag["Data_Evento"].to_numpy()
        ts_tend = tel_tag.loc[
            tel_tag["Alarme_Norm"].isin(tendencias_nomes), "Data_Evento"
        ].to_numpy()
        ts_todos = tel_tag["Data_Evento"].to_numpy()
        ts_qg = _quase_gatilhos(tel_dg_tag)
        ts_alerta = alertas.loc[alertas["TAG"] == tag, "Data_Alerta"].sort_values().to_numpy()

        cols = {}
        for h in JANELAS_H:
            for c in (1, 2, 3):
                cols[f"n_crit{c}_{h}h"] = _contagem_retroativa(ts_por_crit[c], t_dec, h)
            cols[f"n_dg_{h}h"] = _contagem_retroativa(ts_dg, t_dec, h)
        cols["n_tendencia_24h"] = _contagem_retroativa(ts_tend, t_dec, 24)
        cols["n_eventos_24h"] = _contagem_retroativa(ts_todos, t_dec, 24)

        # operador em turno: último evento de telemetria do equipamento até t
        ops = tel_tag["Nome_Operador_Anon"].to_numpy()
        idx_op = np.searchsorted(ts_todos, t_dec, side="right") - 1
        operador = np.where(idx_op >= 0, ops[np.maximum(idx_op, 0)],
                            "OP_DESCONHECIDO")
        cols["quase_gatilhos_12h"] = _contagem_retroativa(ts_qg, t_dec, 12)
        cols["quase_gatilhos_24h"] = _contagem_retroativa(ts_qg, t_dec, 24)
        cols["h_desde_crit1"] = _horas_desde_ultimo(ts_por_crit[1], t_dec)
        cols["h_desde_alerta_dg"] = _horas_desde_ultimo(ts_alerta, t_dec)

        # taxa de eventos recente vs. linha de base do próprio equipamento (30 d)
        n_720h = _contagem_retroativa(ts_todos, t_dec, 720)
        cols["taxa_eventos_h_24h"] = cols["n_eventos_24h"] / 24.0
        cols["razao_taxa_24h_30d"] = np.where(
            n_720h > 0, cols["n_eventos_24h"] / np.maximum(n_720h / 30.0, 0.5), 1.0
        ).astype(np.float32)

        # utilização: ciclos e horas de operação nas últimas 24 h
        oper = grupo[grupo["Classe"] == "Operação"]
        ts_fim_oper = oper["Fim"].to_numpy()
        dur_oper = oper["duracao_min"].to_numpy() / 60.0
        cum = np.concatenate([[0.0], np.cumsum(dur_oper)])
        fim_idx = np.searchsorted(ts_fim_oper, t_dec, side="right")
        ini_idx = np.searchsorted(ts_fim_oper, t_dec - np.timedelta64(24, "h"), side="right")
        cols["horas_operadas_24h"] = (cum[fim_idx] - cum[ini_idx]).astype(np.float32)
        cols["ciclos_24h"] = _contagem_retroativa(grupo["Fim"].to_numpy(), t_dec, 24)

        m_tag = manut[manut["Tag"] == tag]
        cols["h_desde_manut_corretiva"] = _horas_desde_ultimo(
            m_tag.loc[m_tag["Classe"] == "Manutenção Corretiva", "Fim"].to_numpy(), t_dec)
        cols["h_desde_manut_preventiva"] = _horas_desde_ultimo(
            m_tag.loc[m_tag["Classe"] == "Manutenção Preventiva", "Fim"].to_numpy(), t_dec)

        # target: alerta don't go em (t, t + janela]
        if len(ts_alerta):
            idx = np.searchsorted(ts_alerta, t_dec, side="right")
            prox = np.where(idx < len(ts_alerta),
                            ts_alerta[np.minimum(idx, len(ts_alerta) - 1)],
                            np.datetime64("2100-01-01"))
            delta_h = (prox - t_dec) / np.timedelta64(1, "h")
            cols["y"] = (delta_h <= JANELA_PREDICAO_HORAS).astype(np.int8)
            cols["horas_ate_alerta"] = np.minimum(delta_h, 24 * 21).astype(np.float32)
        else:
            cols["y"] = np.zeros(len(t_dec), dtype=np.int8)
            cols["horas_ate_alerta"] = np.full(len(t_dec), 24 * 21, dtype=np.float32)

        bloco = grupo[["Tag", "Frota", "Tipo", "Classe",
                       "Fim", "duracao_min", "razao_duracao"]].reset_index(drop=True)
        bloco["Operador_Turno"] = operador
        blocos.append(pd.concat([bloco, pd.DataFrame(cols)], axis=1))

    abt = pd.concat(blocos, ignore_index=True).rename(columns={"Fim": "t_decisao"})

    # ------------------------------------------------------------------ tempo
    abt["hora"] = abt["t_decisao"].dt.hour.astype(np.int8)
    abt["hora_sin"] = np.sin(2 * np.pi * abt["hora"] / 24).astype(np.float32)
    abt["hora_cos"] = np.cos(2 * np.pi * abt["hora"] / 24).astype(np.float32)
    abt["dia_semana"] = abt["t_decisao"].dt.dayofweek.astype(np.int8)
    abt["fim_de_semana"] = (abt["dia_semana"] >= 5).astype(np.int8)
    abt["mes"] = abt["t_decisao"].dt.month.astype(np.int8)
    abt["turno"] = pd.cut(abt["hora"], bins=[-1, 6, 14, 22, 24],
                          labels=["C", "A", "B", "C2"]).astype(str)
    abt.loc[abt["turno"] == "C2", "turno"] = "C"

    # -------------------------------------------------- encodings categóricos
    # One-hot para baixa cardinalidade (Frota, Tipo, Classe, turno).
    abt = pd.get_dummies(
        abt, columns=["Frota", "Tipo", "Classe", "turno"], prefix=["frota", "tipo", "classe", "turno"],
        dtype=np.int8,
    )

    # Frequência/target encoding APENAS com o período de treino para Tag e
    # Operador (cardinalidade alta demais para one-hot; taxa histórica carrega
    # o sinal de "equipamento problemático" / "estilo de operação").
    corte = pd.Timestamp(CORTE_TREINO)
    treino = abt[abt["t_decisao"] < corte]
    taxa_global = treino["y"].mean()

    def _te(coluna, minimo=50):
        grp = treino.groupby(coluna)["y"].agg(["mean", "count"])
        # suavização bayesiana para categorias pouco vistas
        te = (grp["mean"] * grp["count"] + taxa_global * minimo) / (grp["count"] + minimo)
        return te

    abt["tag_taxa_alerta"] = abt["Tag"].map(_te("Tag")).fillna(taxa_global).astype(np.float32)
    abt["op_taxa_alerta"] = (
        abt["Operador_Turno"].map(_te("Operador_Turno"))
        .fillna(taxa_global).astype(np.float32)
    )
    abt["op_desconhecido"] = (abt["Operador_Turno"] == "OP_DESCONHECIDO").astype(np.int8)

    # nomes de coluna sem espaços/acentos (compatibilidade com LightGBM)
    tabela = str.maketrans("áàâãéêíóôõúç ", "aaaaeeiooouc_", "()-°")
    abt.columns = [c.translate(tabela) if c not in COLUNAS_NAO_FEATURE else c
                   for c in abt.columns]
    return abt


def separar_conjuntos(abt: pd.DataFrame, corte_treino: str, corte_validacao: str):
    treino = abt[abt["t_decisao"] < corte_treino]
    valid = abt[(abt["t_decisao"] >= corte_treino) & (abt["t_decisao"] < corte_validacao)]
    teste = abt[abt["t_decisao"] >= corte_validacao]
    return treino, valid, teste


COLUNAS_NAO_FEATURE = ["Tag", "Operador_Turno", "t_decisao", "y", "horas_ate_alerta"]


def matriz_xy(df: pd.DataFrame):
    X = df.drop(columns=COLUNAS_NAO_FEATURE)
    return X, df["y"].to_numpy()
