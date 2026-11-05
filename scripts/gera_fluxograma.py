"""Fluxograma da arquitetura do nó soberano iSACI.

Saída: docs/img/fluxograma_arquitetura.png — minimalista, fundo
branco, paleta clara (sem preto). Dois blocos conceituais:

  - faixa superior: coreografia A↔B (dois nós são a MESMA imagem
    — só mudam os papéis; passos numerados nas setas)
  - bloco inferior: a stack interna única que ambos rodam

Uso: python scripts/gera_fluxograma.py
"""
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

# ---------- paleta (clara, sem preto) ----------
NAVY = "#16305e"
TXT = "#3c4761"
ZONE_F, ZONE_E = "#f7f9fc", "#c9d2e4"
PROC_F, PROC_E, PROC_T = "#e8eefb", "#7b9bd6", "#1f3a66"
DATA_F, DATA_E, DATA_T = "#eff2f7", "#9aa8c0", "#3a4560"
ASYNC_F, ASYNC_E, ASYNC_T = "#e9f4ee", "#7fb890", "#1d5638"
KEY_F, KEY_E, KEY_T = "#fdf3e3", "#d9a94f", "#7a5410"
ACTOR_F, ACTOR_E = "#eef1f6", "#9aa8c0"
ARROW = "#5b6b8c"
CROSS = "#2e6fd8"
ACK = "#7b5fc9"
BADGE = "#2e6fd8"

plt.rcParams.update({"font.family": "Segoe UI"})

fig, ax = plt.subplots(figsize=(15, 10.6), dpi=160)
ax.set_xlim(0, 100)
ax.set_ylim(0, 66)
ax.axis("off")
fig.patch.set_facecolor("white")


def box(x, y, w, h, titulo, sub, st, fs_t=8.4, fs_s=6.4):
    f, e, t = st
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.55",
        fc=f, ec=e, lw=1.0, zorder=2))
    ax.text(x + w / 2, y + h - 0.55, titulo, ha="center", va="top",
            fontsize=fs_t, weight="bold", color=t, zorder=3)
    if sub:
        ax.text(x + w / 2, y + 0.45, sub, ha="center", va="bottom",
                fontsize=fs_s, color=TXT, zorder=3, linespacing=1.3)


def arr(x1, y1, x2, y2, color=ARROW, lw=1.1):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=9,
        color=color, lw=lw, shrinkA=1, shrinkB=1, zorder=4))


def badge(x, y, n):
    ax.add_patch(Circle((x, y), 0.95, fc=BADGE, ec="white",
                        lw=0.9, zorder=6))
    ax.text(x, y, str(n), ha="center", va="center", fontsize=7.4,
            color="white", weight="bold", zorder=7)


# ---------- título ----------
ax.text(50, 64.6, "iSACI — nó soberano: coreografia A↔B e stack "
        "interna", ha="center", va="center", fontsize=13.5,
        weight="bold", color=NAVY)

# ============================================================
# FAIXA SUPERIOR — coreografia entre nós (a mesma imagem, dois
# papéis; passos numerados nas setas)
# ============================================================
ax.text(50, 61.9, "coreografia entre nós — a mesma stack, dois "
        "papéis", ha="center", va="center", fontsize=8.6,
        weight="bold", color=NAVY)

# atores (clientes) — os passos que cada lado dispara
box(8, 56.8, 24, 3.6, "sistemas do órgão A",
    "(1) criar   (2) upload   (3) envio", (ACTOR_F, ACTOR_E, TXT),
    fs_t=8.0, fs_s=6.6)
box(68, 56.8, 24, 3.6, "sistemas do órgão B",
    "(5) download+upload   (6) confirmar+acks",
    (ACTOR_F, ACTOR_E, TXT), fs_t=8.0, fs_s=6.6)
arr(20, 56.8, 20, 55.3, color=CROSS, lw=1.3)
arr(80, 56.8, 80, 55.3, color=CROSS, lw=1.3)

# cartões dos nós — projeções de estado sob o mesmo tid
box(8, 45.5, 24, 9.4, "NÓ A — origem (tjpa)",
    "projeção local\nCRIADA → EM_TRANSITO\n→ CONFIRMADA / RECUSADA\n"
    "mesmo tid nos dois nós", (ZONE_F, ZONE_E, NAVY), fs_t=8.6,
    fs_s=6.4)
box(68, 45.5, 24, 9.4, "NÓ B — destino (mpfpa)",
    "projeção local\nRECEBIDA\n→ CONFIRMADA / RECUSADA\n"
    "mesmo tid nos dois nós", (ZONE_F, ZONE_E, NAVY), fs_t=8.6,
    fs_s=6.4)

# 3/4: envelope assinado A→B
arr(32, 51.6, 68, 51.6, color=CROSS, lw=1.6)
badge(35, 51.6, 3)
badge(65, 51.6, 4)
ax.text(50, 52.0, "envelope Ed25519 — só metadados + SHA-256\n"
        "POST /v1/envio → POST /v1/recebimentos → RECEBIDA · eco "
        "idempotente", ha="center", va="bottom", fontsize=6.9,
        color=CROSS, linespacing=1.3)

# 5: bytes A→B
arr(32, 48.4, 68, 48.4, color=CROSS, lw=1.6)
badge(50, 48.4, 5)
ax.text(50, 49.6, "bytes do documento\nGET /v1/documentos/{id}/"
        "download (A) → upload em B · hash + magic bytes",
        ha="center", va="bottom", fontsize=6.9, color=CROSS,
        linespacing=1.3)

# 6: ack B→A
arr(68, 45.1, 32, 45.1, color=ACK, lw=1.6)
badge(50, 45.1, 6)
ax.text(50, 44.7, "POST /{id}/confirmacao — B recomputa SHA-256 "
        "do próprio storage\nack Ed25519 → POST /{tid}/acks em A → "
        "CONFIRMADA / RECUSADA", ha="center", va="top", fontsize=6.9,
        color=ACK, linespacing=1.3)

# ============================================================
# BLOCO INFERIOR — a stack interna única (ambos os nós rodam)
# ============================================================
ax.text(50, 41.9, "dentro de cada nó — mesma stack soberana",
        ha="center", va="center", fontsize=8.6, weight="bold",
        color=NAVY)
ax.text(50, 41.1, "azul caminho HTTP · cinza dados · verde "
        "esteira de IA · âmbar chaves e gates", ha="center",
        va="center", fontsize=6.4, color="#8a94a6")

PROC = (PROC_F, PROC_E, PROC_T)
DATA = (DATA_F, DATA_E, DATA_T)
ASYNC = (ASYNC_F, ASYNC_E, ASYNC_T)
KEY = (KEY_F, KEY_E, KEY_T)

X0, W, HW, GAP = 30, 40, 19.2, 1.6
CX, LX, RX = X0 + W / 2, X0 + HW / 2, X0 + HW + GAP + HW / 2

STACK = (  # (titulo, sub, y, h, col, estilo)
    ("nginx — terminador TLS",
     ":443 · TLS 1.3 + mTLS\nCN→X-Cliente-Orgao · limit_req · HSTS",
     36.4, 3.7, 0, PROC),
    ("MiddlewareE2E — blindagem do payload",
     "quadros AEAD ChaCha20-Poly1305\njanela 300 s + nonce "
     "anti-replay (replay_nonces)", 31.5, 3.7, 0, PROC),
    ("FastAPI — /v1/*",
     "validação Pydantic · erros opacos\nE2E_OBRIGATORIO=1",
     26.6, 3.7, 0, PROC),
    ("NoTramitacao — domínio",
     "máquina de estados · autorização\n404→papel→nó · idempotência",
     21.7, 3.7, 0, PROC),
    ("Postgres",
     "tramitacoes · trilha hash-chain\n(append-only) · outbox ·\n"
     "replay_nonces · idempotencia", 16.2, 4.4, 1, DATA),
    ("MinIO",
     "<org>-docs ·\n<org>-docs-anonimizados\n(objetos = quadros "
     "AEAD)", 16.2, 4.4, 2, DATA),
    ("relay (task na API)",
     "outbox→broker · claim por\nlease + backoff → ESGOTADO\n"
     "→ falha_outbox na trilha", 10.7, 4.4, 1, ASYNC),
    ("RabbitMQ",
     "fila quorum\nia.anonimizacao + DLQ\n(payload = quadro AEAD)",
     10.7, 4.4, 2, ASYNC),
    ("MotorIA — porta permutável",
     "anonimizar(bytes)→bytes\nstub | demo | ollama |\n"
     "langchain (IA_ENGINE)", 5.2, 4.4, 1, ASYNC),
    ("worker — esteira",
     "download → motor → gates →\nupload-anon · feedback na\n"
     "trilha · DLQ → falha_", 5.2, 4.4, 2, ASYNC),
    ("Vault — cofre de chaves",
     "KV v2 · AppRole (token 60 s)\nE2E_CHAVE {atual,\n"
     "anteriores} — rotação", 0.1, 4.6, 1, KEY),
    ("gates determinísticos",
     "saída legível +\nresidual_pii = 0\nsenão falha_"
     "anonimizacao", 0.1, 4.6, 2, KEY),
)
for titulo, sub, y, h, col, st in STACK:
    x = X0 if col == 0 else X0 if col == 1 else X0 + HW + GAP
    w = W if col == 0 else HW
    box(x, y, w, h, titulo, sub, st)

# setas internas
arr(CX, 36.4, CX, 35.2)                      # nginx→e2e
arr(CX, 31.5, CX, 30.3)                      # e2e→api
arr(CX, 26.6, CX, 25.4)                      # api→dominio
arr(CX - 4, 21.7, LX, 20.6)                  # dominio→pg
arr(CX + 4, 21.7, RX, 20.6)                  # dominio→minio
arr(LX, 16.2, LX, 15.1)                      # pg→relay (outbox)
arr(X0 + HW, 12.9, X0 + HW + GAP, 12.9)      # relay→rabbit
arr(RX, 10.7, RX, 9.6)                       # rabbit→worker
arr(X0 + HW + GAP, 7.4, X0 + HW, 7.4)        # worker→motor
arr(RX, 5.2, RX, 4.7)                        # worker→gates
ax.text(LX + 0.6, 15.65, "outbox\n(tx única)", fontsize=5.8,
        color=ARROW, ha="left", va="center", style="italic",
        linespacing=1.15)
ax.text(CX, 13.55, "publish", fontsize=5.8, color=ARROW,
        ha="center", va="bottom", style="italic")
ax.text(CX, 8.15, "bytes→bytes", fontsize=5.8, color=ARROW,
        ha="center", va="bottom", style="italic")

os.makedirs("docs/img", exist_ok=True)
fig.savefig("docs/img/fluxograma_arquitetura.png",
            bbox_inches="tight", facecolor="white")
print("docs/img/fluxograma_arquitetura.png")
