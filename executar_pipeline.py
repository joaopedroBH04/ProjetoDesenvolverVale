# -*- coding: utf-8 -*-
"""Pipeline completo do desafio — executa da extração ao material do relatório.

Etapas:
  1. Extração dos dados brutos e do catálogo de regras
  2. Transformação (limpeza com controle de alterações) e carga em Parquet
  3. Rotulagem don't go via motor de regras (catálogo CMA)
  4. Engenharia de features e construção da ABT
  5. Treinamento (baselines + supervisionados + não supervisionados)
  6. Avaliação, análise de erros e impacto de negócio
  7. Figuras e tabelas do relatório

Uso: python executar_pipeline.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from src.avaliacao import avaliar
from src.config import (CORTE_TREINO, CORTE_VALIDACAO, DIR_PROCESSADOS,
                        DIR_TABELAS)
from src.etl import carga, extracao, transformacao
from src.features import engenharia
from src.modelos import nao_supervisionado, sobrevivencia, treinar
from src.regras import motor_regras
from src.viz import figuras


def tabelas_eda(ap_bruto, tel_bruto, ap, tel, alertas, abt):
    """Tabelas exigidas pela EDA (CM 2.1 a 2.3)."""
    # inspeção inicial
    linhas = []
    for nome, df, col_dt in (("Apontamentos", ap_bruto, "Inicio"),
                             ("Telemetria", tel_bruto, "Data_Evento")):
        linhas.append(dict(
            Tabela=nome, Linhas=len(df), Colunas=df.shape[1],
            Nulos_total=int(df.isna().sum().sum()),
            Duplicatas=int(df.duplicated().sum()),
            Data_min=str(df[col_dt].min()), Data_max=str(df[col_dt].max()),
        ))
    pd.DataFrame(linhas).to_csv(DIR_TABELAS / "inspecao_inicial.csv", index=False)

    # estatísticas descritivas das variáveis numéricas
    stats = []
    ap_num = ap_bruto.assign(
        duracao_min=(ap_bruto["Fim"] - ap_bruto["Inicio"]).dt.total_seconds() / 60)
    fontes = [("Apontamentos", ap_num, ["duracao_min"]),
              ("Telemetria", tel_bruto.assign(
                  Valor=pd.to_numeric(
                      tel_bruto["Valor"].astype(str).str.replace(",", ".", regex=False),
                      errors="coerce")),
               ["Valor", "Id_Criticidade", "Is_Dont_Go", "Dia"])]
    for tabela, df, cols in fontes:
        for c in cols:
            s = df[c]
            stats.append(dict(
                Tabela=tabela, Feature=c, Tipo=str(s.dtype),
                Pct_Nulos=round(100 * s.isna().mean(), 2),
                Min=round(float(s.min()), 2), Max=round(float(s.max()), 2),
                Media=round(float(s.mean()), 2), Mediana=round(float(s.median()), 2),
                Desvio_Padrao=round(float(s.std()), 2),
            ))
    pd.DataFrame(stats).to_csv(DIR_TABELAS / "estatisticas_descritivas.csv", index=False)

    # distribuição de alertas
    motor_regras.resumo_alertas(alertas).to_csv(
        DIR_TABELAS / "alertas_por_tipo_nivel.csv", index=False)
    alertas["TAG"].value_counts().head(15).rename_axis("TAG").rename(
        "Qtd_Alertas").reset_index().to_csv(
        DIR_TABELAS / "alertas_top_equipamentos.csv", index=False)

    # taxa de alerta por frota (pontos de decisão positivos e por 1.000 h operadas)
    frota_cols = [c for c in abt.columns if c.startswith("frota_")]
    fr = abt[["Tag", "y", "horas_operadas_24h"]].copy()
    fr["Frota"] = abt[frota_cols].idxmax(axis=1).str.replace("frota_", "", regex=False)
    horas_op = ap[ap["Classe"] == "Operando"].groupby("Tag")["duracao_min"].sum() / 60
    mapa_frota = fr.drop_duplicates("Tag").set_index("Tag")["Frota"]
    al = alertas.copy()
    al["Frota"] = al["TAG"].map(mapa_frota)
    horas_frota = horas_op.groupby(mapa_frota).sum()
    tab_frota = pd.DataFrame({
        "Pontos_decisao": fr.groupby("Frota").size(),
        "Taxa_target_pct": (fr.groupby("Frota")["y"].mean() * 100).round(2),
        "Alertas": al.groupby("Frota").size(),
        "Horas_operadas": horas_frota.round(0),
    })
    tab_frota["Alertas_por_1000h"] = (1000 * tab_frota["Alertas"]
                                      / tab_frota["Horas_operadas"]).round(2)
    tab_frota.reset_index().to_csv(DIR_TABELAS / "taxa_alerta_por_frota.csv", index=False)

    # comportamento do operador: taxa de alerta por operador (mín. 800 decisões)
    op = (abt.groupby("Nome_Operador_Anon")
          .agg(decisoes=("y", "size"), taxa_pct=("y", lambda s: 100 * s.mean()))
          .query("decisoes >= 800").sort_values("taxa_pct", ascending=False)
          .round(3).reset_index())
    op.to_csv(DIR_TABELAS / "taxa_alerta_por_operador.csv", index=False)

    # turno (dois turnos de 12 h nesta operação)
    turnos = []
    for t in ("A", "B"):
        col = f"turno_{t}"
        sub = abt[abt[col] == 1]
        turnos.append(dict(Turno=t, Pontos=len(sub),
                           Taxa_target_pct=round(100 * sub["y"].mean(), 2)))
    pd.DataFrame(turnos).to_csv(DIR_TABELAS / "taxa_alerta_por_turno.csv", index=False)


def main():
    t0 = time.time()

    print("[1/7] Extração")
    ap_bruto = extracao.carregar_apontamentos()
    tel_bruto = extracao.carregar_telemetria()
    ap_bruto = extracao.enriquecer_apontamentos_com_operador(ap_bruto, tel_bruto)
    cma = extracao.carregar_catalogo_alarmes()

    print("[2/7] Transformação e carga")
    ap = transformacao.limpar_apontamentos(ap_bruto)
    tel = transformacao.limpar_telemetria(tel_bruto)
    cma_n = transformacao.normalizar_catalogo(cma)
    carga.salvar(ap, "apontamentos_limpos")
    carga.salvar(tel, "telemetria_limpa")
    transformacao.tabela_controle_alteracoes().to_csv(
        DIR_TABELAS / "controle_alteracoes.csv", index=False)

    print("[3/7] Motor de regras don't go")
    regras = motor_regras.compilar_regras(cma_n)
    alertas = motor_regras.aplicar_regras(tel, regras)
    carga.salvar(alertas, "alertas_dont_go")
    print(f"  {len(alertas):,} alertas rotulados")

    print("[4/7] Engenharia de features")
    tend_nomes = set(cma_n.loc[cma_n["TIPO"] == "TENDÊNCIA", "EVENTO_Norm"])
    abt = engenharia.construir_abt(ap, tel, alertas, tend_nomes)
    carga.salvar(abt, "abt")
    print(f"  ABT: {abt.shape[0]:,} pontos de decisão × {abt.shape[1]} colunas | "
          f"prevalência do target: {abt['y'].mean() * 100:.2f}%")

    print("[5/7] Treinamento")
    modelos, scores = treinar.treinar_todos(abt)
    aft, saida_aft, c_index, _ = sobrevivencia.weibull_aft(abt)
    iso, saida_iso = nao_supervisionado.isolation_forest(abt)
    km, perfil = nao_supervisionado.perfis_kmeans(abt)
    perfil.to_csv(DIR_TABELAS / "perfis_kmeans.csv", index=False)

    print("[6/7] Avaliação")
    sc_va = scores["valid"]
    sc_te = scores["teste"]
    from sklearn.metrics import average_precision_score, roc_auc_score
    tab = avaliar.tabela_comparativa(sc_va, sc_te)
    aft_linha = pd.DataFrame([dict(
        Modelo="Weibull AFT (sobrevivência, risco em 4 h)", Conjunto="teste",
        Precision=np.nan, Recall=np.nan, F1=np.nan, F2=np.nan,
        AUC_ROC=round(roc_auc_score(saida_aft["y"], saida_aft["WeibullAFT"]), 4),
        AUC_PR=round(average_precision_score(saida_aft["y"], saida_aft["WeibullAFT"]), 4),
        Limiar=np.nan)])
    iso_linha = pd.DataFrame([dict(
        Modelo="IsolationForest (não supervisionado)", Conjunto="teste",
        Precision=np.nan, Recall=np.nan, F1=np.nan, F2=np.nan,
        AUC_ROC=round(roc_auc_score(saida_iso["y"], saida_iso["IsolationForest"]), 4),
        AUC_PR=round(average_precision_score(saida_iso["y"], saida_iso["IsolationForest"]), 4),
        Limiar=np.nan)])
    pd.concat([tab, aft_linha, iso_linha], ignore_index=True).to_csv(
        DIR_TABELAS / "comparativo_modelos.csv", index=False)
    mc, limiar = avaliar.matriz_confusao_campeao(sc_va, sc_te)
    avaliar.analise_falsos_negativos(sc_te, alertas, abt, limiar)
    avaliar.degradacao_temporal(sc_va, sc_te)
    avaliar.impacto_negocio(sc_va, sc_te, alertas, ap, limiar)
    avaliar.fila_inspecao(sc_te)

    print("[7/7] Figuras e tabelas")
    tabelas_eda(ap_bruto, tel_bruto, ap, tel, alertas, abt)
    figuras.fig01_fluxo_operacional()
    figuras.fig02_volume_temporal(ap, tel)
    figuras.fig03_alertas_tipo_nivel(alertas)
    figuras.fig04_serie_alertas(alertas)
    figuras.fig05_heatmap_correlacao(abt)
    figuras.fig06_taxa_hora_dia(abt)
    figuras.fig07_janela_predicao()
    figuras.fig08_validacao_temporal()
    figuras.fig09_roc_pr(sc_te)
    figuras.fig10_matriz_confusao(mc)
    _, _, teste = engenharia.separar_conjuntos(abt, CORTE_TREINO, CORTE_VALIDACAO)
    X_te, _ = engenharia.matriz_xy(teste)
    figuras.fig11_12_shap(modelos["LightGBM"], X_te.reset_index(drop=True), sc_te)
    figuras.fig13_baseline_vs_modelos(tab)

    print(f"\nPipeline concluído em {time.time() - t0:.0f}s")
    print(f"Figuras em relatorio/figuras | tabelas em relatorio/tabelas | "
          f"camada tratada em {DIR_PROCESSADOS}")


if __name__ == "__main__":
    main()
