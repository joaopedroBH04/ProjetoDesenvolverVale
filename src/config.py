# -*- coding: utf-8 -*-
"""Configuração central do projeto: caminhos, janelas e datas de corte."""

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

DIR_BRUTOS = RAIZ / "dados" / "brutos"
DIR_NEGOCIO = RAIZ / "dados" / "negocio"
DIR_PROCESSADOS = RAIZ / "dados" / "processados"
DIR_FIGURAS = RAIZ / "relatorio" / "figuras"
DIR_TABELAS = RAIZ / "relatorio" / "tabelas"

ARQ_APONTAMENTOS = DIR_BRUTOS / "Apontamentos.csv.gz"
ARQ_TELEMETRIA = DIR_BRUTOS / "Telemetria.csv.gz"
ARQ_ALARMES = DIR_NEGOCIO / "Alarmes - SUL_SUDESTE.xlsx"
ARQ_DICIONARIO = DIR_NEGOCIO / "Dicionario_Dados.xlsx"

# Janela de antecipação do alerta don't go (horas).
# 4h = tempo hábil para o despacho redirecionar a produção e a manutenção
# preparar box, peças e equipe antes da parada.
JANELA_PREDICAO_HORAS = 4

# Cooldown entre disparos da mesma regra para o mesmo equipamento (horas).
# Evita que um único episódio físico gere dezenas de alertas duplicados.
COOLDOWN_REGRA_HORAS = 6

# Split temporal (fim exclusivo)
CORTE_TREINO = "2026-01-01"   # treino: set/2025 a dez/2025
CORTE_VALIDACAO = "2026-02-01"  # validação: jan/2026 | teste: fev/2026

SEMENTE = 42

# Mapeamento entre Id_Criticidade da telemetria e o "nível" OEM citado nas
# regras do catálogo CMA (nível 3 = mais severo).
CRITICIDADE_PARA_NIVEL = {1: 3, 2: 2, 3: 1, 4: 0}

for _d in (DIR_PROCESSADOS, DIR_FIGURAS, DIR_TABELAS):
    _d.mkdir(parents=True, exist_ok=True)
