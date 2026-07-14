# -*- coding: utf-8 -*-
"""Extração: leitura dos dados brutos e dos arquivos de negócio.

As fontes chegam como extrações Parquet do data lake (Apontamentos em um único
arquivo, Telemetria particionada por mês) e planilhas Excel de negócio
(catálogo de alarmes don't go e dicionário de dados). Aqui só se faz leitura,
tipagem e enriquecimento de campos ausentes na origem — nenhuma limpeza.

Nota metodológica: o extrato de Apontamentos entregue nesta base não contém
`Nome_Operador_Anon`/`Matricula_Operador_Hash`. Como a modelagem usa a taxa
histórica de alerta por operador, esses campos são derivados por casamento
temporal entre cada ciclo e o evento de telemetria mais próximo do mesmo
equipamento (tolerância de 6 h). Ciclos sem match ficam com "OP_DESCONHECIDO".
"""

import pandas as pd

from src.config import (ARQ_ALARMES, ARQ_APONTAMENTOS, ARQ_DICIONARIO,
                        ARQS_TELEMETRIA)


def carregar_apontamentos() -> pd.DataFrame:
    df = pd.read_parquet(ARQ_APONTAMENTOS)
    df["Id"] = df["Id"].astype("int64")
    df["Inicio"] = pd.to_datetime(df["Inicio"])
    df["Fim"] = pd.to_datetime(df["Fim"])
    return df


# Colunas de telemetria consumidas pelo pipeline (o extrato bruto tem 18;
# as demais — turno, localidade, nome da criticidade — são redundantes com
# campos já derivados e ficam fora da carga para caber em memória: 37 M linhas)
COLS_TELEMETRIA = [
    "Id_Eventos_Telemetria", "Data_Evento", "Dia", "TAG",
    "Nome_Operador_Anon", "Matricula_Operador_Hash", "Alarme",
    "Id_Criticidade", "Valor", "Is_Dont_Go",
]


def carregar_telemetria() -> pd.DataFrame:
    partes = []
    for arq in ARQS_TELEMETRIA:
        p = pd.read_parquet(arq, columns=COLS_TELEMETRIA)
        partes.append(p)
    df = pd.concat(partes, ignore_index=True)
    # normaliza a resolução para ns (o extrato vem em us; apontamentos em ns)
    df["Data_Evento"] = pd.to_datetime(df["Data_Evento"]).astype("datetime64[ns]")
    df["Valor"] = df["Valor"].astype("object")
    df["Is_Dont_Go"] = df["Is_Dont_Go"].astype("int8")
    return df


def enriquecer_apontamentos_com_operador(
    ap: pd.DataFrame, tel: pd.DataFrame
) -> pd.DataFrame:
    """Deriva Nome_Operador_Anon e Matricula_Operador_Hash em Apontamentos a
    partir da telemetria (evento mais próximo do mesmo equipamento, tolerância
    de 6 h). Estratégia:

      * Junção por Tag = TAG e Inicio ≈ Data_Evento (merge_asof direção
        `nearest`);
      * Ciclos sem casamento no intervalo → categoria 'OP_DESCONHECIDO'.
    """
    # merge_asof exige ordenação global pela chave temporal
    op = (
        tel[["TAG", "Data_Evento", "Nome_Operador_Anon", "Matricula_Operador_Hash"]]
        .rename(columns={"TAG": "Tag", "Data_Evento": "_ts_tel"})
        .dropna(subset=["Tag"])
        .sort_values("_ts_tel")
        .reset_index(drop=True)
    )
    ap_ord = ap.sort_values("Inicio").reset_index()
    fundido = pd.merge_asof(
        ap_ord, op, by="Tag", left_on="Inicio", right_on="_ts_tel",
        direction="nearest", tolerance=pd.Timedelta("6h"),
    )
    fundido = fundido.set_index("index").sort_index()
    ap = ap.copy()
    ap["Nome_Operador_Anon"] = fundido["Nome_Operador_Anon"].values
    ap["Matricula_Operador_Hash"] = fundido["Matricula_Operador_Hash"].values
    return ap


def carregar_catalogo_alarmes() -> pd.DataFrame:
    """Catálogo CMA: cada linha é uma regra TIPO + EVENTO + SITUACAO +
    QUANTIDADE + TEMPO + NIVEL que constitui um alerta don't go (uma certa
    QUANTIDADE de ocorrências dentro de uma janela de TEMPO, em minutos). O
    arquivo tem três abas (CMA, Tendências e Eventos O&M); as regras don't go
    estão na aba CMA."""
    return pd.read_excel(ARQ_ALARMES, sheet_name="CMA")


def carregar_tendencias() -> pd.DataFrame:
    return pd.read_excel(ARQ_ALARMES, sheet_name="Tendências")


def carregar_dicionario() -> dict:
    xl = pd.ExcelFile(ARQ_DICIONARIO)
    return {aba: xl.parse(aba) for aba in xl.sheet_names}
