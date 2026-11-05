"""Fluxograma SIMPLES da arquitetura iSACI — para explicar.

Saída: docs/img/fluxograma_simples.png — a jornada de um
documento em 7 passos entre dois nós soberanos, mais uma
faixa com as 4 garantias que sustentam a confiança.

Versão de apresentação (pouco texto, fontes grandes).
Detalhe fino: docs/img/fluxograma_arquitetura.png
(scripts/gera_fluxograma.py).

Uso: python scripts/gera_fluxograma_simples.py
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

# ---------- paleta (clara, sem preto) ----------
NAVY = "#16305e"
TXT = "#3c4761"
MUTED = "#8a94a6"
CARD_F, CARD_E = "#f7f9fc", "#c9d2e4"
CHIP_F, CHIP_E, CHIP_T = "#eef1f8", "#a8b4cc", "#1f3a66"
GUAR_F, GUAR_E = "#f4f7fb", "#d6dfeb"
CROSS = "#2e6fd8"
ACK = "#7b5fc9"
BADGE = "#2e6fd8"

plt.rcParams.update({"font.family": "Segoe UI"})

fig, ax = plt.subplots(figsize=(14.5, 8.6), dpi=160)
ax.set_xlim(0, 100)
ax.set_ylim(0, 60)
ax.axis("off")
fig.patch.set_facecolor("white")


def box(x, y, w, h, fc, ec, lw=1.0, rs=0.55):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=%f" % rs,
        fc=fc, ec=ec, lw=lw, zorder=2))


def arr(x1, y1, x2, y2, color=CROSS, lw=1.7):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=12,
        color=color, lw=lw, shrinkA=1, shrinkB=1, zorder=4))


def badge(x, y, n):
    ax.add_patch(Circle((x, y), 1.15, fc=BADGE, ec="white",
                        lw=1.0, zorder=6))
    ax.text(x, y, str(n), ha="center", va="center", fontsize=8.6,
            color="white", weight="bold", zorder=7)


def step_badge(x, y, n):
    ax.add_patch(Circle((x, y), 1.0, fc="white", ec=BADGE,
                        lw=1.1, zorder=6))
    ax.text(x, y, str(n), ha="center", va="center", fontsize=7.6,
            color=BADGE, weight="bold", zorder=7)


# ---------- título ----------
ax.text(50, 58.2, "iSACI — como um documento tramita entre órgãos",
        ha="center", va="center", fontsize=15, weight="bold",
        color=NAVY)
ax.text(50, 56.5, "dois nós soberanos idênticos — só muda o papel",
        ha="center", va="center", fontsize=9.5, color=MUTED)

# ---------- cartões dos nós ----------
CY, CH = 32, 21          # cartões y=32..53
for x, titulo, org in ((4, "ÓRGÃO A — origem", "ex.: TJPA"),
                       (68, "ÓRGÃO B — destino", "ex.: MPFPA")):
    box(x, CY, 28, CH, CARD_F, CARD_E, lw=1.2, rs=0.8)
    ax.text(x + 14, CY + CH - 1.6, titulo, ha="center", va="top",
            fontsize=11.5, weight="bold", color=NAVY, zorder=3)
    ax.text(x + 14, CY + CH - 4.4, org + " · nó soberano iSACI",
            ha="center", va="top", fontsize=8.2, color=MUTED,
            zorder=3, style="italic")

# passos do nó A
for n, y, txt in (
    (1, CY + 13.0, "cadastra o caso\n(metadados + hash do documento)"),
    (2, CY + 8.0,  "sobe o documento\n(hash conferido → storage)"),
    (7, CY + 3.0,  "aplica a confirmação\n— ciclo encerrado"),
):
    step_badge(6.6, y, n)
    ax.text(9.0, y, txt, ha="left", va="center", fontsize=8.0,
            color=TXT, zorder=3, linespacing=1.35)

# passos do nó B
for n, y, txt in (
    (4, CY + 13.0, "confere a assinatura e\nregistra o recebimento"),
    (5, CY + 8.0,  "baixa o documento de A e\nguarda no próprio storage"),
    (6, CY + 3.0,  "recomputa o hash e devolve\nconfirmação assinada"),
):
    step_badge(70.6, y, n)
    ax.text(73.0, y, txt, ha="left", va="center", fontsize=8.0,
            color=TXT, zorder=3, linespacing=1.35)

# ---------- setas entre os nós ----------
# 3: envelope A→B
arr(32, CY + 16.5, 68, CY + 16.5)
badge(50, CY + 16.5, 3)
ax.text(50, CY + 18.0, "envelope assinado —\nsó metadados + hash",
        ha="center", va="bottom", fontsize=8.4, color=CROSS,
        linespacing=1.3)

# 5: bytes A→B (B baixa)
arr(32, CY + 10.0, 68, CY + 10.0)
badge(50, CY + 10.0, 5)
ax.text(50, CY + 11.4, "documento (bytes) —\ndownload autenticado",
        ha="center", va="bottom", fontsize=8.4, color=CROSS,
        linespacing=1.3)

# 6: confirmação B→A
arr(68, CY + 3.8, 32, CY + 3.8, color=ACK)
badge(50, CY + 3.8, 6)
ax.text(50, CY + 5.0, "confirmação assinada",
        ha="center", va="bottom", fontsize=8.4, color=ACK)

# nota T9
ax.text(50, CY - 2.2,
        "o binário nunca entra no envelope, na fila, no banco ou na API\n"
        "— só metadados + SHA-256 circulam entre os nós",
        ha="center", va="top", fontsize=8.6, color=NAVY,
        style="italic", linespacing=1.4)

# ---------- faixa de garantias ----------
GY, GH = 4.5, 20.0
box(4, GY, 92, GH, GUAR_F, GUAR_E, lw=1.0, rs=0.8)
ax.text(50, GY + GH - 1.4, "dentro de cada nó — o que sustenta a "
        "confiança (a mesma stack nos dois lados)",
        ha="center", va="top", fontsize=10, weight="bold",
        color=NAVY, zorder=3)

CHIPS = (
    ("canal selado", "mTLS na borda + payload\ncifrado ponta a ponta —\n"
     "nada legível no fio"),
    ("auditoria inviolável", "cada evento gravado numa\ntrilha "
     "encadeada por hash\n(append-only)"),
    ("documento soberano", "bytes ficam no storage\ndo órgão — nunca "
     "em\nenvelope, fila ou banco"),
    ("anonimização assíncrona", "fila → worker → motor de IA\n"
     "→ checagens → documento\nlimpo em bucket próprio"),
)
for i, (t, s) in enumerate(CHIPS):
    x = 7 + i * 23
    box(x, GY + 1.8, 20.5, 12.0, CHIP_F, CHIP_E, lw=0.9, rs=0.6)
    ax.text(x + 10.25, GY + 12.0, t, ha="center", va="top",
            fontsize=8.8, weight="bold", color=CHIP_T, zorder=3)
    ax.text(x + 10.25, GY + 10.2, s, ha="center", va="top",
            fontsize=7.6, color=TXT, zorder=3, linespacing=1.45)

os.makedirs("docs/img", exist_ok=True)
fig.savefig("docs/img/fluxograma_simples.png",
            bbox_inches="tight", facecolor="white")
print("docs/img/fluxograma_simples.png")
