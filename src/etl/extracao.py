# -*- coding: utf-8 -*-
"""Extração: leitura dos dados brutos e dos arquivos de negócio.

As fontes chegam como extrações CSV compactadas do data lake (Apontamentos e
Telemetria) e planilhas Excel de negócio (catálogo de alarmes don't go e
dicionário de dados). Aqui só se faz leitura e tipagem — nenhuma limpeza.
"""

import pandas as pd

from src.config import ARQ_ALARMES, ARQ_APONTAMENTOS, ARQ_DICIONARIO, ARQ_TELEMETRIA


def carregar_apontamentos() -> pd.DataFrame:
    df = pd.read_csv(ARQ_APONTAMENTOS, parse_dates=["Inicio", "Fim"])
    df["Id"] = df["Id"].astype("int64")
    return df


def carregar_telemetria() -> pd.DataFrame:
    df = pd.read_csv(
        ARQ_TELEMETRIA,
        parse_dates=["Data_Evento"],
        dtype={"Valor": "object", "Is_Dont_Go": "int8"},
    )
    return df


def carregar_catalogo_alarmes() -> pd.DataFrame:
    """Catálogo CMA: cada linha é uma regra TIPO + EVENTO + SITUACAO + QTD +
    TEMPO + NIVEL que constitui um alerta don't go."""
    return pd.read_excel(ARQ_ALARMES, sheet_name="CMA")


def carregar_tendencias() -> pd.DataFrame:
    return pd.read_excel(ARQ_ALARMES, sheet_name="Tendências")


def carregar_dicionario() -> dict:
    xl = pd.ExcelFile(ARQ_DICIONARIO)
    return {aba: xl.parse(aba) for aba in xl.sheet_names}
