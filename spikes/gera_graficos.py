"""Gera gráficos do relatório a partir dos dados brutos dos spikes.
Saída: docs/img/*.png — embutidos em relatorio-arquitetura.html/.pdf
"""
import json, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mt

NAVY, ACC, WARN, OK = "#16305e", "#2e6fd8", "#b8860b", "#1a6b34"
GREY = "#8a94a6"
plt.rcParams.update({
    "font.family": "Segoe UI", "font.size": 10,
    "axes.edgecolor": "#c9d2e4", "axes.linewidth": 0.8,
    "axes.grid": True, "grid.color": "#e4e9f2", "grid.linewidth": 0.7,
    "axes.axisbelow": True, "figure.facecolor": "white",
    "axes.titlesize": 11.5, "axes.titleweight": "bold",
    "axes.titlecolor": NAVY, "axes.labelcolor": "#333a4a",
})
os.makedirs("docs/img", exist_ok=True)

# ---------- fig 1: latência × tamanho do doc ----------
cpu = [json.loads(l) for l in open("spikes/p1_raw.jsonl", encoding="utf-8")]
gpu = [json.loads(l) for l in open("spikes/p1_gpu_raw.jsonl", encoding="utf-8")]
def series(rows, stride):
    r = [x for x in rows if x.get("doc_tokens") and x["stride"] == stride]
    return [x["doc_tokens"] for x in r], [x["mediana_ms"] for x in r]

x256, y256 = series(cpu, 256)
x384c, y384c = series(cpu, 384)
x384g, y384g = series(gpu, 384)

fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=160)
ax.plot(x256, y256, "o-", color=NAVY, lw=2, ms=5,
        label="CPU — stride 256 (overlap 50%)")
ax.plot(x384c, y384c, "s--", color=ACC, lw=2, ms=5,
        label="CPU — stride 384 (overlap 25%)")
ax.plot(x384g, y384g, "^-", color=OK, lw=2, ms=5,
        label="GPU RTX 5090 — stride 384")
ax.axvline(10000, color=WARN, ls=":", lw=1.6)
ax.text(10500, 400, "limiar síncrono CPU\n≈10k tokens", color=WARN,
        fontsize=8.5, va="center")
ax.set_yscale("log")
ax.set_xlabel("tamanho do documento (tokens)")
ax.set_ylabel("latência mediana (ms, escala log)")
ax.set_title("P1 — Latência do encoder Legal-BERTimbau por passe")
ax.legend(frameon=False, fontsize=8.5, loc="upper left")
fig.tight_layout(); fig.savefig("docs/img/p1_latencia.png"); plt.close(fig)

# ---------- fig 2: ms/janela CPU × GPU ----------
fig, ax = plt.subplots(figsize=(4.6, 3.0), dpi=160)
vals = [180.7, 8.9]
bars = ax.bar(["CPU (24 threads)", "GPU RTX 5090"], vals,
              color=[NAVY, OK], width=0.55)
for b, v in zip(bars, vals):
    ax.text(b.get_x()+b.get_width()/2, v*1.15, f"{v:.1f} ms",
            ha="center", fontweight="bold", fontsize=10)
ax.set_yscale("log"); ax.set_ylim(1, 500)
ax.set_ylabel("ms por janela de 512 tokens (log)")
ax.set_title("P1 — Custo por janela")
ax.text(0.5, 0.02, "≈ 12–20× de aceleração GPU", transform=ax.transAxes,
        ha="center", fontsize=8.5, color=GREY)
fig.tight_layout(); fig.savefig("docs/img/p1_janela.png"); plt.close(fig)

# ---------- fig 3: métricas v0 × gates ----------
labels = ["Validadores\nregex\n(8 tipos)", "NER stock\nsó-nomes",
          "Correferência\npairwise", "Correferência\nconsistência"]
vals   = [1.00, 0.92, 0.88, 0.87]
gates  = [1.00, 0.85, 0.90, 0.85]
colors = [OK if v >= g else WARN for v, g in zip(vals, gates)]

fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=160)
x = range(len(labels))
bars = ax.bar(x, vals, width=0.5, color=colors)
for i, (b, v, g) in enumerate(zip(bars, vals, gates)):
    ax.text(b.get_x()+b.get_width()/2, v+0.015, f"{v:.2f}",
            ha="center", fontweight="bold", fontsize=9.5)
    ax.plot([i-0.32, i+0.32], [g, g], color="#c0392b", lw=2)
    ax.text(i+0.34, g, f"gate {g:.2f}", fontsize=7.8, color="#c0392b",
            va="center")
ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=9)
ax.set_ylim(0, 1.15); ax.set_ylabel("F1 / proporção")
ax.set_title("P8 — Baseline v0 (corpus sintético) × gates N2")
ax.text(0.5, -0.32, "proxy de engenharia sobre texto limpo — "
        "gates só se declaram sobre corpus anotado real",
        transform=ax.transAxes, ha="center", fontsize=8, color=GREY)
fig.tight_layout(); fig.savefig("docs/img/p8_metricas.png"); plt.close(fig)

print("docs/img/p1_latencia.png · p1_janela.png · p8_metricas.png")
