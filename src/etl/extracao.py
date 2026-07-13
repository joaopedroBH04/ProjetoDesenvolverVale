# -*- coding: utf-8 -*-
"""Extração: leitura dos dados brutos e dos arquivos de negócio.

As fontes chegam como Parquet do data lake (Apontamentos e Telemetria) e
planilhas Excel de negócio (catálogo de regras "Alarmes - Regra de
Negocio_V2.xlsx" e dicionário de dados). Aqui só se faz leitura e tipagem;
nenhuma limpeza.
"""

import pandas as pd

from src.config import ARQ_ALARMES, ARQ_APONTAMENTOS, ARQ_DICIONARIO, ARQ_TELEMETRIA


def carregar_apontamentos() -> pd.DataFrame:
    df = pd.read_parquet(ARQ_APONTAMENTOS)
    df["Inicio"] = pd.to_datetime(df["Inicio"])
    df["Fim"] = pd.to_datetime(df["Fim"])
    df["Id"] = df["Id"].astype("int64")
    return df


def carregar_telemetria() -> pd.DataFrame:
    df = pd.read_parquet(ARQ_TELEMETRIA)
    df["Data_Evento"] = pd.to_datetime(df["Data_Evento"])
    df["Is_Dont_Go"] = df["Is_Dont_Go"].astype("int8")
    return df


def carregar_catalogo_alarmes() -> pd.DataFrame:
    """Catálogo CMA: cada linha é uma regra TIPO + EVENTO + SITUACAO +
    QUANTIDADE + TEMPO + NIVEL que constitui um alerta don't go. O arquivo
    tem três abas (CMA, Tendências e Eventos O&M); as regras estão na CMA."""
    return pd.read_excel(ARQ_ALARMES, sheet_name="CMA")


def carregar_tendencias() -> pd.DataFrame:
    return pd.read_excel(ARQ_ALARMES, sheet_name="Tendências")


def carregar_dicionario() -> dict:
    xl = pd.ExcelFile(ARQ_DICIONARIO)
    return {aba: xl.parse(aba) for aba in xl.sheet_names}
