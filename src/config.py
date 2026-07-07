# -*- coding: utf-8 -*-
"""Configuração central do projeto: caminhos, janelas e datas de corte."""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Parquets brutos ficam fora do repositório (37 M de eventos); o caminho pode
# ser sobrescrito pela variável de ambiente DADOS_BRUTOS_DIR.
DIR_BRUTOS = Path(os.environ.get(
    "DADOS_BRUTOS_DIR", r"C:/Users/costa/OneDrive/Área de Trabalho/datasets"))
DIR_NEGOCIO = RAIZ / "dados" / "negocio"
DIR_PROCESSADOS = RAIZ / "dados" / "processados"
DIR_FIGURAS = RAIZ / "relatorio" / "figuras"
DIR_TABELAS = RAIZ / "relatorio" / "tabelas"

ARQ_APONTAMENTOS = DIR_BRUTOS / "apontamentos" / "desenvolver_apontamentos.parquet"
DIR_TELEMETRIA = DIR_BRUTOS / "telemetria"
ARQS_TELEMETRIA = sorted(DIR_TELEMETRIA.glob("telemetry_*.parquet"))
ARQ_ALARMES = DIR_NEGOCIO / "Alarmes - Regra de Negocio.xlsx"
ARQ_DICIONARIO = DIR_NEGOCIO / "Dicionario_Dados.xlsx"

# Janela de antecipação do alerta don't go (horas).
# 4h = tempo hábil para o despacho redirecionar a produção e a manutenção
# preparar box, peças e equipe antes da parada.
JANELA_PREDICAO_HORAS = 4

# Cooldown entre disparos da mesma regra para o mesmo equipamento (horas).
# Evita que um único episódio físico gere dezenas de alertas duplicados.
COOLDOWN_REGRA_HORAS = 6

# Split temporal (fim exclusivo)
# Dados disponíveis: jan/2025 a jun/2025.
# Treino: jan–abr/2025 | validação: mai/2025 | teste: jun/2025.
# O tuning usa DUAS janelas de validação (abr e mai) para não eleger
# hiperparâmetros ajustados às idiossincrasias de um único mês; os target
# encodings são estimados apenas em jan–mar, anteriores a ambas as janelas.
CORTE_JANELA_A = "2025-04-01"
CORTE_TREINO = "2025-05-01"
CORTE_VALIDACAO = "2025-06-01"

SEMENTE = 42

# Mapeamento entre Id_Criticidade da telemetria e o "nível" OEM citado nas
# regras do catálogo CMA (nível 3 = mais severo).
CRITICIDADE_PARA_NIVEL = {1: 3, 2: 2, 3: 1, 4: 0}

for _d in (DIR_PROCESSADOS, DIR_FIGURAS, DIR_TABELAS):
    _d.mkdir(parents=True, exist_ok=True)
