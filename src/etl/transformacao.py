# -*- coding: utf-8 -*-
"""Transformação: limpeza e padronização com controle de alterações.

Toda exclusão ou correção de registro é registrada em um log ANTES/DEPOIS
(tabela de controle de alterações exigida pelo estudo guiado), com a
justificativa da decisão.
"""

import numpy as np
import pandas as pd

REGISTRO_ALTERACOES = []


def _log(tabela, campo, problema, qtd, tratamento, justificativa):
    REGISTRO_ALTERACOES.append(
        dict(Tabela=tabela, Campo=campo, Problema=problema, Qtd_Registros=int(qtd),
             Tratamento=tratamento, Justificativa=justificativa)
    )


def limpar_apontamentos(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 1) Duplicatas exatas (reenvio do sistema de despacho)
    qtd = df.duplicated().sum()
    df = df.drop_duplicates(keep="first")
    _log("Apontamentos", "todas", "Registro duplicado (reenvio do despacho)", qtd,
         "Remoção (mantida 1ª ocorrência)",
         "Linhas idênticas em todos os campos, inclusive Id; não agregam informação.")

    # 2) Inicio > Fim: inversão de campos no envio — troca e mantém
    invertidos = df["Inicio"] > df["Fim"]
    qtd = invertidos.sum()
    df.loc[invertidos, ["Inicio", "Fim"]] = df.loc[invertidos, ["Fim", "Inicio"]].values
    _log("Apontamentos", "Inicio/Fim", "Inicio posterior ao Fim", qtd,
         "Troca dos campos",
         "Padrão consistente com inversão de colunas na origem; duração resultante "
         "fica dentro da distribuição normal da classe.")

    # 3) Duração nula
    dur = (df["Fim"] - df["Inicio"]).dt.total_seconds()
    qtd = (dur == 0).sum()
    df = df[dur > 0]
    _log("Apontamentos", "Inicio/Fim", "Ciclo com duração zero", qtd,
         "Remoção",
         "Sem conteúdo operacional; não representam atividade nem parada.")

    # 4) Duração extrema (> 24 h) — erro de digitação de data no fechamento
    dur = (df["Fim"] - df["Inicio"]).dt.total_seconds() / 3600
    qtd = (dur > 24).sum()
    df = df[dur <= 24]
    _log("Apontamentos", "Fim", "Duração > 24 h (data de fechamento incorreta)", qtd,
         "Remoção",
         "Acima do turno máximo possível; corrigir a data seria especulativo e o "
         "volume é irrelevante (<0,1%).")

    # 5) Sobreposição de ciclos do mesmo equipamento — ajusta o fim do anterior
    df = df.sort_values(["Tag", "Inicio"]).reset_index(drop=True)
    prox_inicio = df.groupby("Tag")["Inicio"].shift(-1)
    sobrepoe = (df["Fim"] > prox_inicio) & prox_inicio.notna()
    qtd = sobrepoe.sum()
    df.loc[sobrepoe, "Fim"] = prox_inicio[sobrepoe]
    dur = (df["Fim"] - df["Inicio"]).dt.total_seconds()
    df = df[dur > 0]
    _log("Apontamentos", "Fim", "Sobreposição de ciclos na mesma Tag", qtd,
         "Fim truncado no início do ciclo seguinte",
         "Um equipamento não executa dois apontamentos simultâneos; assume-se "
         "atraso no fechamento do ciclo anterior.")

    # 6) Operador ausente — mantém o registro (as horas operadas importam)
    qtd = df["Nome_Operador_Anon"].isna().sum()
    df["Nome_Operador_Anon"] = df["Nome_Operador_Anon"].fillna("OP_DESCONHECIDO")
    df["Matricula_Operador_Hash"] = df["Matricula_Operador_Hash"].fillna("desconhecido")
    _log("Apontamentos", "Nome_Operador_Anon", "Operador não informado", qtd,
         "Imputação com categoria 'OP_DESCONHECIDO'",
         "Excluir descartaria horas de operação válidas; a ausência vira categoria "
         "própria e o modelo decide sua relevância.")

    df["duracao_min"] = (df["Fim"] - df["Inicio"]).dt.total_seconds() / 60
    return df.sort_values(["Tag", "Inicio"]).reset_index(drop=True)


def limpar_telemetria(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 1) Duplicatas exatas
    qtd = df.duplicated().sum()
    df = df.drop_duplicates(keep="first")
    _log("Telemetria", "todas", "Evento duplicado (reprocessamento do coletor)", qtd,
         "Remoção (mantida 1ª ocorrência)",
         "Mesma chave Id_Eventos_Telemetria e mesmo conteúdo; contagem dupla "
         "distorceria as regras de QTD do catálogo.")

    # 2) Valor não numérico ("N/A", vazio) — converte para NaN e mantém a linha
    valor_num = pd.to_numeric(df["Valor"], errors="coerce")
    qtd = (df["Valor"].notna() & valor_num.isna()).sum() + df["Valor"].isna().sum()
    df["Valor"] = valor_num
    _log("Telemetria", "Valor", "Valor ausente ou não numérico ('N/A')", qtd,
         "Coerção para NaN, linha mantida",
         "O disparo das regras depende do evento e do nível, não do Valor; "
         "imputar leitura de sensor inexistente criaria informação falsa.")

    # 3) Operador ausente
    qtd = df["Nome_Operador_Anon"].isna().sum()
    df["Nome_Operador_Anon"] = df["Nome_Operador_Anon"].fillna("OP_DESCONHECIDO")
    df["Matricula_Operador_Hash"] = df["Matricula_Operador_Hash"].fillna("desconhecido")
    _log("Telemetria", "Nome_Operador_Anon", "Operador não informado", qtd,
         "Imputação com categoria 'OP_DESCONHECIDO'",
         "Mesmo critério adotado nos apontamentos.")

    # 4) Normalização do nome do evento para casar com o catálogo CMA
    df["Alarme_Norm"] = df["Alarme"].str.strip().str.upper()

    return df.sort_values(["TAG", "Data_Evento"]).reset_index(drop=True)


def normalizar_catalogo(cma: pd.DataFrame) -> pd.DataFrame:
    """Padroniza o catálogo de regras (grafia de NIVEL, espaços, chave do evento)."""
    cma = cma.copy()
    nivel_padrao = cma["NIVEL"].str.strip().str.title()  # "Muito alto" -> "Muito Alto"
    qtd = (cma["NIVEL"] != nivel_padrao).sum()
    cma["NIVEL"] = nivel_padrao
    _log("Catálogo CMA", "NIVEL", "Grafias inconsistentes ('Muito alto'/'Muito Alto')",
         qtd,
         "Padronização para title case",
         "As 3 grafias distintas de NIVEL viram 2 categorias reais (Muito Alto, Alto); "
         "sem isso a agregação por criticidade dupla conta os mesmos eventos.")
    cma["EVENTO_Norm"] = cma["EVENTO"].str.strip().str.upper()
    cma["Id_Regra"] = np.arange(1, len(cma) + 1)
    return cma


def tabela_controle_alteracoes() -> pd.DataFrame:
    return pd.DataFrame(REGISTRO_ALTERACOES)
