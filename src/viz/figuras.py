# -*- coding: utf-8 -*-
"""Geração das figuras do relatório final (Figuras 1 a 13 do estudo guiado)."""

import matplotlib
matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from src.config import (CORTE_TREINO, CORTE_VALIDACAO, DIR_FIGURAS,
                        JANELA_PREDICAO_HORAS)

# Paleta do relatório (categórica em ordem fixa; sequencial azul; status)
AZUL, AQUA, AMARELO, VERDE, VIOLETA, VERMELHO = (
    "#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948")
CRITICO, SERIO = "#d03b3b", "#ec835a"
TINTA, TINTA2, TINTA3 = "#0b0b0b", "#52514e", "#898781"
GRADE, EIXO, SUPERFICIE = "#e1e0d9", "#c3c2b7", "#fcfcfb"

SEQ_AZUL = LinearSegmentedColormap.from_list("seq_azul", [
    "#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95",
    "#0d366b"])
DIV_AZUL_VERMELHO = LinearSegmentedColormap.from_list("div_ar", [
    "#0d366b", "#3987e5", "#9ec5f4", "#f0efec", "#f2a09f", "#e34948", "#8f1d1d"])

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "figure.facecolor": SUPERFICIE,
    "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
    "axes.edgecolor": EIXO, "axes.linewidth": 0.8, "axes.grid": True,
    "grid.color": GRADE, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "text.color": TINTA, "axes.labelcolor": TINTA2, "xtick.color": TINTA3,
    "ytick.color": TINTA3, "font.size": 9, "axes.titlesize": 10,
    "axes.titleweight": "bold", "axes.spines.top": False,
    "axes.spines.right": False, "legend.frameon": False,
})


def _salvar(fig, nome):
    fig.tight_layout()
    fig.savefig(DIR_FIGURAS / nome, bbox_inches="tight")
    plt.close(fig)
    print(f"  figura salva: {nome}")


def _caixa(ax, x, y, w, h, titulo, corpo, cor):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.012",
                                facecolor="white", edgecolor=cor, linewidth=1.6))
    ax.text(x + w / 2, y + h - 0.055, titulo, ha="center", va="top",
            fontsize=9.5, fontweight="bold", color=TINTA)
    ax.text(x + w / 2, y + h / 2 - 0.03, corpo, ha="center", va="center",
            fontsize=7.8, color=TINTA2)


def _seta(ax, x1, y1, x2, y2, rotulo=None):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>",
                                 mutation_scale=16, linewidth=1.4, color=TINTA2))
    if rotulo:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.035, rotulo, ha="center",
                fontsize=7.5, color=TINTA3, style="italic")


# ---------------------------------------------------------------- Figura 1
def fig01_fluxo_operacional():
    fig, ax = plt.subplots(figsize=(9.2, 3.4))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    _caixa(ax, 0.01, 0.55, 0.20, 0.34, "Ciclo de apontamento",
           "Inicio / Fim · Tag · Frota\nClasse da atividade\nOperador anonimizado", AZUL)
    _caixa(ax, 0.27, 0.55, 0.20, 0.34, "Telemetria embarcada",
           "Eventos OEM, tendências\ne sistema, com nível\n(1, 2, 3) e valor lido", AQUA)
    _caixa(ax, 0.53, 0.55, 0.20, 0.34, "Catálogo CMA\n",
           "151 regras don't go\nTIPO + EVENTO + SITUACAO\n+ QUANTIDADE + TEMPO", AMARELO)
    _caixa(ax, 0.79, 0.55, 0.20, 0.34, "Alerta don't go",
           "Equipamento não deve\noperar: Muito Alto / Alto", CRITICO)
    _caixa(ax, 0.27, 0.06, 0.20, 0.30, "Despacho (dispatcher)",
           "Redireciona produção,\nretira equipamento\nde rota", VIOLETA)
    _caixa(ax, 0.53, 0.06, 0.20, 0.30, "Manutenção",
           "Fila de inspeção,\nbox, peças e equipe", VERDE)
    _seta(ax, 0.21, 0.72, 0.27, 0.72, "opera")
    _seta(ax, 0.47, 0.72, 0.53, 0.72, "avalia")
    _seta(ax, 0.73, 0.72, 0.79, 0.72, "dispara")
    _seta(ax, 0.86, 0.55, 0.66, 0.36)
    _seta(ax, 0.84, 0.55, 0.40, 0.36)
    ax.set_title("Figura 1: Fluxo operacional: ciclo de apontamento → telemetria → alerta don't go",
                 loc="left")
    _salvar(fig, "fig01_fluxo_operacional.png")


# ---------------------------------------------------------------- Figura 2
def fig02_volume_temporal(ap, tel):
    fig, axes = plt.subplots(2, 1, figsize=(9.2, 4.6), sharex=True)
    d1 = ap.set_index("Inicio").resample("D").size()
    axes[0].fill_between(d1.index, d1.values, color=AZUL, alpha=0.25, linewidth=0)
    axes[0].plot(d1.index, d1.values, color=AZUL, linewidth=1.6)
    axes[0].set_ylabel("Apontamentos/dia")
    axes[0].set_title("Figura 2: Volume diário de registros (set/2025 a fev/2026)", loc="left")
    d2 = tel.set_index("Data_Evento").resample("D").size()
    axes[1].fill_between(d2.index, d2.values, color=AQUA, alpha=0.25, linewidth=0)
    axes[1].plot(d2.index, d2.values, color=AQUA, linewidth=1.6)
    axes[1].set_ylabel("Eventos de telemetria/dia")
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
    _salvar(fig, "fig02_volume_temporal.png")


# ---------------------------------------------------------------- Figura 3
def fig03_alertas_tipo_nivel(alertas):
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6),
                             gridspec_kw={"width_ratios": [1, 1.9]})
    por_tipo = alertas.groupby(["TIPO", "NIVEL"]).size().unstack(fill_value=0)
    por_tipo = por_tipo.loc[por_tipo.sum(axis=1).sort_values().index]
    esq = np.zeros(len(por_tipo))
    for nivel, cor in (("Muito Alto", CRITICO), ("Alto", SERIO)):
        if nivel in por_tipo:
            axes[0].barh(por_tipo.index, por_tipo[nivel], left=esq, color=cor,
                         height=0.55, label=nivel, edgecolor=SUPERFICIE, linewidth=1.5)
            esq += por_tipo[nivel].values
    for i, total in enumerate(por_tipo.sum(axis=1)):
        axes[0].text(total + 12, i, f"{total:,.0f}".replace(",", "."),
                     va="center", fontsize=8, color=TINTA2)
    axes[0].set_title("Alertas por TIPO e NIVEL", loc="left")
    axes[0].legend(loc="lower right", fontsize=8)
    axes[0].set_xlim(0, por_tipo.sum(axis=1).max() * 1.18)

    top = (alertas.groupby(["EVENTO", "NIVEL"]).size().rename("n").reset_index()
           .sort_values("n", ascending=False).head(10))
    top["rotulo"] = top["EVENTO"].str.slice(0, 38)
    cores = top["NIVEL"].map({"Muito Alto": CRITICO, "Alto": SERIO})
    axes[1].barh(top["rotulo"][::-1], top["n"][::-1], color=cores[::-1], height=0.6,
                 edgecolor=SUPERFICIE, linewidth=1.5)
    axes[1].set_title("10 eventos que mais dispararam alertas", loc="left")
    axes[1].tick_params(axis="y", labelsize=7.2)
    fig.suptitle("Figura 3: Distribuição dos alertas don't go por tipo e criticidade",
                 x=0.01, ha="left", fontsize=10, fontweight="bold")
    _salvar(fig, "fig03_alertas_tipo_nivel.png")


# ---------------------------------------------------------------- Figura 4
def fig04_serie_alertas(alertas):
    fig, ax = plt.subplots(figsize=(9.2, 3.2))
    d = alertas.set_index("Data_Alerta").resample("D").size()
    ax.plot(d.index, d.values, color=EIXO, linewidth=0.9, label="Alertas/dia")
    mm = d.rolling(7, center=True).mean()
    ax.plot(mm.index, mm.values, color=CRITICO, linewidth=2.0, label="Média móvel 7 dias")
    ax.axvline(pd.Timestamp(CORTE_TREINO), color=TINTA3, linewidth=1, linestyle="--")
    ax.axvline(pd.Timestamp(CORTE_VALIDACAO), color=TINTA3, linewidth=1, linestyle="--")
    ax.text(pd.Timestamp(CORTE_TREINO), d.max() * 0.97, " corte treino/validação",
            fontsize=7.3, color=TINTA3)
    ax.text(pd.Timestamp(CORTE_VALIDACAO), d.max() * 0.88, " corte validação/teste",
            fontsize=7.3, color=TINTA3)
    ax.set_ylabel("Alertas don't go/dia")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
    ax.legend(loc="upper left", fontsize=8)
    ax.set_title("Figura 4: Frequência diária de alertas don't go no período analisado",
                 loc="left")
    _salvar(fig, "fig04_serie_alertas.png")


# ---------------------------------------------------------------- Figura 5
def fig05_heatmap_correlacao(abt):
    cols = ["y", "n_crit1_24h", "n_crit2_12h", "n_crit2_24h", "n_crit3_24h",
            "n_dg_12h", "n_dg_24h", "n_tendencia_24h", "quase_gatilhos_12h",
            "n_eventos_24h", "razao_taxa_24h_30d", "h_desde_crit1",
            "h_desde_alerta_dg", "horas_operadas_24h", "ciclos_24h",
            "h_desde_manut_preventiva", "duracao_min"]
    corr = abt[cols].corr(method="spearman")
    fig, ax = plt.subplots(figsize=(7.6, 6.4))
    im = ax.imshow(corr, cmap=DIV_AZUL_VERMELHO, vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)), cols, rotation=52, ha="right", fontsize=7.2)
    ax.set_yticks(range(len(cols)), cols, fontsize=7.2)
    ax.grid(False)
    for i in range(len(cols)):
        for j in range(len(cols)):
            v = corr.iloc[i, j]
            if abs(v) >= 0.35 and i != j:
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=5.8,
                        color="white" if abs(v) > 0.62 else TINTA)
    fig.colorbar(im, ax=ax, shrink=0.75, label="Correlação de Spearman")
    ax.set_title("Figura 5: Correlação entre features numéricas e o target (y)",
                 loc="left")
    _salvar(fig, "fig05_heatmap_correlacao.png")


# ---------------------------------------------------------------- Figura 6
def fig06_taxa_hora_dia(abt):
    tab = abt.pivot_table(index="dia_semana", columns="hora", values="y", aggfunc="mean") * 100
    dias = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    fig, ax = plt.subplots(figsize=(9.2, 3.4))
    im = ax.imshow(tab, cmap=SEQ_AZUL, aspect="auto")
    ax.set_yticks(range(7), dias, fontsize=8)
    ax.set_xticks(range(0, 24, 2), range(0, 24, 2), fontsize=8)
    ax.set_xlabel("Hora do dia"); ax.grid(False)
    for lim in (6.5, 14.5, 22.5):
        ax.axvline(lim, color=SUPERFICIE, linewidth=2)
    ax.text(10.5, -0.85, "Turno A (07–15)", ha="center", fontsize=7.4, color=TINTA3)
    ax.text(18.5, -0.85, "Turno B (15–23)", ha="center", fontsize=7.4, color=TINTA3)
    ax.text(3, -0.85, "Turno C (23–07)", ha="center", fontsize=7.4, color=TINTA3)
    fig.colorbar(im, ax=ax, shrink=0.85, label="Taxa de alerta em 4 h (%)")
    ax.set_title("Figura 6: Taxa de alertas por hora do dia e dia da semana",
                 loc="left", pad=26)
    _salvar(fig, "fig06_taxa_hora_dia.png")


# ---------------------------------------------------------------- Figura 7
def fig07_janela_predicao():
    fig, ax = plt.subplots(figsize=(9.2, 2.7))
    ax.set_xlim(0, 24); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(plt.Rectangle((0.5, 0.42), 13.5, 0.16, color="#9ec5f4"))
    ax.add_patch(plt.Rectangle((14.0, 0.42), 4.0, 0.16, color=AMARELO, alpha=0.85))
    ax.add_patch(plt.Rectangle((18.0, 0.42), 5.5, 0.16, color=GRADE))
    ax.plot([14, 14], [0.30, 0.72], color=TINTA, linewidth=2)
    ax.text(14, 0.78, "instante de decisão t\n(fim do ciclo de apontamento)",
            ha="center", fontsize=8, color=TINTA)
    ax.annotate("", xy=(18, 0.34), xytext=(14, 0.34),
                arrowprops=dict(arrowstyle="-|>", color=TINTA2, lw=1.4))
    ax.text(16, 0.22, f"janela de predição\n(t, t + {JANELA_PREDICAO_HORAS} h]",
            ha="center", fontsize=8, color=TINTA2)
    ax.plot([16.9], [0.5], marker="v", markersize=10, color=CRITICO)
    ax.text(16.9, 0.64, "alerta don't go\n(y = 1)", ha="center", fontsize=8, color=CRITICO)
    ax.text(7, 0.50, "histórico usado nas features\n(janelas de 4 h a 72 h)", ha="center",
            fontsize=8, color=TINTA2)
    ax.text(20.7, 0.50, "futuro não observado", ha="center", fontsize=7.6, color=TINTA3)
    ax.set_title("Figura 7: Janela de predição: decisão → antecipação → evento alvo",
                 loc="left")
    _salvar(fig, "fig07_janela_predicao.png")


# ---------------------------------------------------------------- Figura 8
def fig08_validacao_temporal():
    fig, ax = plt.subplots(figsize=(9.2, 2.4))
    ax.set_xlim(0, 12); ax.set_ylim(0, 1); ax.axis("off")
    seg = [("Treino: set a dez/2025 (67%)", 0, 8, AZUL),
           ("Validação: jan/2026 (17%)", 8, 2, AMARELO),
           ("Teste: fev/2026 (16%)", 10, 2, VERMELHO)]
    for rotulo, x, w, cor in seg:
        ax.add_patch(plt.Rectangle((x + 0.03, 0.38), w - 0.06, 0.24, color=cor,
                                   alpha=0.85))
        ax.text(x + w / 2, 0.50, rotulo, ha="center", va="center", fontsize=8,
                color="white", fontweight="bold")
    for x, txt in ((0, "01/09/2025"), (8, "01/01/2026"), (10, "01/02/2026"),
                   (12, "28/02/2026")):
        ax.plot([x, x], [0.30, 0.70], color=TINTA3, linewidth=0.8, linestyle=":")
        ax.text(x, 0.20, txt, ha="center", fontsize=7.6, color=TINTA3)
    ax.text(6, 0.82, "tuning de hiperparâmetros e escolha de limiar usam apenas a validação;"
                     " o teste é avaliado uma única vez", ha="center", fontsize=8,
            color=TINTA2, style="italic")
    ax.set_title("Figura 8: Estratégia de validação: hold-out temporal (sem embaralhar o tempo)",
                 loc="left")
    _salvar(fig, "fig08_validacao_temporal.png")


# ---------------------------------------------------------------- Figura 9
def fig09_roc_pr(sc_te):
    from sklearn.metrics import (auc, average_precision_score,
                                 precision_recall_curve, roc_curve)
    modelos = [("Heuristica", TINTA3), ("RegressaoLogistica", AMARELO),
               ("RandomForest", AQUA), ("LightGBM", AZUL)]
    rotulos = {"Heuristica": "Heurística (nº alarmes 12 h)",
               "RegressaoLogistica": "Regressão Logística",
               "RandomForest": "Random Forest", "LightGBM": "LightGBM"}
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.0))
    for m, cor in modelos:
        fpr, tpr, _ = roc_curve(sc_te["y"], sc_te[m])
        axes[0].plot(fpr, tpr, color=cor, linewidth=1.8,
                     label=f"{rotulos[m]} (AUC={auc(fpr, tpr):.3f})")
        prec, rec, _ = precision_recall_curve(sc_te["y"], sc_te[m])
        ap = average_precision_score(sc_te["y"], sc_te[m])
        axes[1].plot(rec, prec, color=cor, linewidth=1.8,
                     label=f"{rotulos[m]} (AP={ap:.3f})")
    axes[0].plot([0, 1], [0, 1], color=GRADE, linewidth=1, linestyle="--")
    axes[0].set_xlabel("Taxa de falsos positivos"); axes[0].set_ylabel("Recall")
    axes[0].set_title("Curva ROC no teste (fev/2026)", loc="left")
    axes[0].legend(fontsize=7.2, loc="lower right")
    axes[1].axhline(sc_te["y"].mean(), color=GRADE, linewidth=1, linestyle="--")
    axes[1].text(0.02, sc_te["y"].mean() + 0.012, "prevalência (aleatório)",
                 fontsize=7, color=TINTA3)
    axes[1].set_xlabel("Recall"); axes[1].set_ylabel("Precision")
    axes[1].set_title("Curva Precision-Recall no teste", loc="left")
    axes[1].legend(fontsize=7.2, loc="upper right")
    fig.suptitle("Figura 9: Curvas ROC e Precision-Recall dos modelos avaliados",
                 x=0.01, ha="left", fontsize=10, fontweight="bold")
    _salvar(fig, "fig09_roc_pr.png")


# ---------------------------------------------------------------- Figura 10
def fig10_matriz_confusao(mc):
    tn, fp, fn, tp = mc.ravel()
    fig, ax = plt.subplots(figsize=(6.6, 4.6))
    ax.imshow(np.log1p(mc), cmap=SEQ_AZUL); ax.grid(False)
    rotulos = [
        [f"VN = {tn:,}".replace(",", "."), f"FP = {fp:,}".replace(",", ".")],
        [f"FN = {fn:,}".replace(",", "."), f"VP = {tp:,}".replace(",", ".")],
    ]
    notas = [["operação normal\nmantida", "inspeção vazia\n(~1 h de verificação)"],
             ["alerta perdido →\nparada não planejada", "parada antecipada →\nintervenção planejada"]]
    for i in range(2):
        for j in range(2):
            cor = "white" if (i, j) == (0, 0) else TINTA
            ax.text(j, i - 0.10, rotulos[i][j], ha="center", fontsize=12,
                    fontweight="bold", color=cor)
            ax.text(j, i + 0.16, notas[i][j], ha="center", fontsize=8, color=cor)
    ax.set_xticks([0, 1], ["Previsto: sem alerta", "Previsto: alerta"], fontsize=9)
    ax.set_yticks([0, 1], ["Real:\nsem alerta", "Real:\nalerta"], fontsize=9)
    ax.set_title("Figura 10: Matriz de confusão no teste (LightGBM, limiar F2)",
                 loc="left")
    _salvar(fig, "fig10_matriz_confusao.png")


# ---------------------------------------------------------------- Figuras 11 e 12
def fig11_12_shap(modelo, X_te, sc_te):
    import shap
    amostra = X_te.sample(min(3000, len(X_te)), random_state=42)
    explainer = shap.TreeExplainer(modelo)
    sv = explainer(amostra)
    plt.figure(figsize=(8.4, 6.0))
    shap.summary_plot(sv, amostra, max_display=14, show=False, plot_size=None)
    plt.gcf().suptitle("Figura 11: SHAP summary plot (LightGBM, amostra do teste)",
                       x=0.01, ha="left", fontsize=10, fontweight="bold")
    plt.tight_layout()
    plt.savefig(DIR_FIGURAS / "fig11_shap_summary.png", bbox_inches="tight")
    plt.close("all")
    print("  figura salva: fig11_shap_summary.png")

    # verdadeiro positivo com maior score
    pos = sc_te[sc_te["y"] == 1].nlargest(1, "LightGBM")
    idx = pos.index[0]
    sv1 = explainer(X_te.loc[[idx]])
    plt.figure(figsize=(8.4, 5.2))
    shap.plots.waterfall(sv1[0], max_display=12, show=False)
    plt.gcf().suptitle("Figura 12: SHAP waterfall: decomposição de uma predição\n"
                       f"(equipamento {pos['Tag'].iloc[0]}, "
                       f"{pos['t_decisao'].iloc[0]:%d/%m/%Y %H:%M}, alerta real em < 4 h)",
                       x=0.01, ha="left", fontsize=9.5, fontweight="bold")
    plt.tight_layout()
    plt.savefig(DIR_FIGURAS / "fig12_shap_waterfall.png", bbox_inches="tight")
    plt.close("all")
    print("  figura salva: fig12_shap_waterfall.png")


# ---------------------------------------------------------------- Figura 14
def fig14_calibracao(tab_calib, resumo):
    fig, ax = plt.subplots(figsize=(6.2, 4.6))
    lim = max(tab_calib["taxa_observada"].max(),
              tab_calib["score_medio_bruto"].max()) * 1.15
    ax.plot([0, lim], [0, lim], color=GRADE, linewidth=1.2, linestyle="--")
    ax.plot(tab_calib["score_medio_bruto"], tab_calib["taxa_observada"],
            marker="o", markersize=6, linewidth=1.6, color=AZUL,
            label=f"Score bruto (Brier {resumo['brier_bruto']:.4f})")
    ax.plot(tab_calib["score_medio_calibrado"], tab_calib["taxa_observada"],
            marker="s", markersize=5, linewidth=1.6, color=AQUA,
            label=f"Isotônica (Brier {resumo['brier_calibrado']:.4f})")
    ax.set_xlabel("Probabilidade prevista (média do decil)")
    ax.set_ylabel("Taxa de alerta observada")
    ax.legend(fontsize=8, loc="upper left")
    ax.set_title("Figura 14: Calibração de probabilidade no teste (decis de score)",
                 loc="left")
    _salvar(fig, "fig14_calibracao.png")


# ---------------------------------------------------------------- Figura 15
def fig15_custo_limiar(tab_custo, limiar_f2, limiar_otimo):
    fig, ax = plt.subplots(figsize=(9.2, 3.8))
    ax.plot(tab_custo["limiar"], tab_custo["beneficio_liquido"] / 1e6,
            color=AZUL, linewidth=2.0)
    ax.axhline(0, color=EIXO, linewidth=0.8)
    for x, rotulo, cor in ((limiar_f2, "limiar F2 (operacional)", VERMELHO),
                           (limiar_otimo, "ótimo financeiro", VERDE)):
        ax.axvline(x, color=cor, linewidth=1.3, linestyle="--")
        y_txt = ax.get_ylim()[1] * (0.88 if cor == VERMELHO else 0.72)
        ax.text(x * 1.05, y_txt, rotulo, fontsize=8, color=cor)
    ax.set_xscale("log")
    ax.set_xlabel("Limiar de decisão (escala log)")
    ax.set_ylabel("Benefício líquido no mês (R$ milhões)")
    ax.set_title("Figura 15: Benefício líquido estimado em função do limiar de decisão",
                 loc="left")
    _salvar(fig, "fig15_custo_limiar.png")


# ---------------------------------------------------------------- Figura 13
def fig13_baseline_vs_modelos(tab):
    t = tab[tab["Conjunto"] == "teste"].set_index("Modelo")
    ordem = ["Dummy", "Heuristica", "RegressaoLogistica", "RandomForest", "LightGBM"]
    rotulos = ["Dummy\n(classe majoritária)", "Heurística\n(alarmes 12 h)",
               "Regressão\nLogística", "Random\nForest", "LightGBM\n(campeão)"]
    t = t.loc[ordem]
    x = np.arange(len(t))
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6))
    for ax, met, titulo in ((axes[0], "AUC_PR", "AUC-PR (average precision)"),
                            (axes[1], "Recall", "Recall no limiar F2")):
        cores = [GRADE, TINTA3, AMARELO, AQUA, AZUL]
        barras = ax.bar(x, t[met], color=cores, width=0.58)
        for b, v in zip(barras, t[met]):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.012, f"{v:.3f}",
                    ha="center", fontsize=8.2, color=TINTA2)
        ax.set_xticks(x, rotulos, fontsize=7.4)
        ax.set_ylim(0, min(1.0, t[met].max() * 1.25))
        ax.set_title(titulo, loc="left")
    fig.suptitle("Figura 13: Baseline vs. modelos desenvolvidos (teste, fev/2026)",
                 x=0.01, ha="left", fontsize=10, fontweight="bold")
    _salvar(fig, "fig13_baseline_vs_modelos.png")
