# -*- coding: utf-8 -*-
"""Carga: materializa a camada tratada em Parquet.

Parquet foi escolhido por ser colunar, tipado e ~6x menor que CSV nesta base,
além de preservar dtypes (datetime, categorias) entre as etapas do pipeline.
"""

import pandas as pd

from src.config import DIR_PROCESSADOS


def salvar(df: pd.DataFrame, nome: str) -> None:
    df.to_parquet(DIR_PROCESSADOS / f"{nome}.parquet", index=False)


def ler(nome: str) -> pd.DataFrame:
    return pd.read_parquet(DIR_PROCESSADOS / f"{nome}.parquet")
