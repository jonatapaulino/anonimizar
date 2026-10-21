"""Demo E2E da esteira soberana — T13.

Uso:  python scripts/demo_e2e.py
Requer a infra de dev de pé:  docker compose up -d

O script sobe a API (uvicorn, thread) e o worker de IA (thread)
IN-PROCESS contra Postgres + RabbitMQ + MinIO reais — nada é
mockado exceto o motor, que roda em modo `demo` (regex LGPD,
zero tokens). O HTTP passa por socket de verdade.

Fluxo: JWT(A) -> cria -> upload PDF -> outbox/relay -> worker IA
-> JWT(B) consulta trilha encadeada -> B baixa o anonimizado.
"""
import hashlib
import os
import socket
import subprocess
import sys
import threading
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

# console Windows legado é cp1252 — sem isso, ✓/─/… explodem
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------- ambiente do nó A (dev) ----------
DB_URL = ("postgresql+asyncpg://edvar:edvar_dev"
          "@localhost:5432/tramitacao")
os.environ["DATABASE_URL"] = DB_URL
os.environ["MINIO_URL"] = "http://localhost:9000"
os.environ["MINIO_USER"] = "edvar"
os.environ["MINIO_PASS"] = "edvar_dev_minio"
os.environ["RABBITMQ_URL"] = "amqp://edvar:edvar_dev@localhost:5672/"
os.environ["IA_ENGINE"] = "demo"      # regex LGPD — zero tokens

import tests.jwthelper as idp   # noqa: E402 — IdP offline (RSA)
                                 # importar já exporta
                                 # JWT_PUBLIC_KEY p/ a API

from rich.console import Console  # noqa: E402
from rich.panel import Panel      # noqa: E402
from rich.table import Table      # noqa: E402

con = Console()
API = "http://127.0.0.1:8000"

DOC = (
    "Documento confidencial do processo CNJ "
    "5614226-41.2021.8.14.2679.\n"
    "Outorgante: João da Silva, CPF 123.456.789-00.\n"
    "Endereço: Rua das Flores, 123 — Belém/PA.\n"
    "Contato: joao.silva@email.com — (91) 99999-0000.\n"
    "Objeto: dano moral em decorrência de extravio de autos."
).encode()
CASO = "5614226-41.2021.8.14.2679"
HASH_DOC = hashlib.sha256(DOC).hexdigest()


def _preflight():
    """As 3 portas de infra respondem? Mensagem clara se não."""
    servicos = [(5432, "PostgreSQL"), (5672, "RabbitMQ"),
                (9000, "MinIO")]
    mortos = []
    for porta, nome in servicos:
        try:
            socket.create_connection(("localhost", porta), 1).close()
        except OSError:
            mortos.append(f"{nome} (:{porta})")
    if mortos:
        con.print(Panel(
            "[bold red]Infra fora do ar:[/] "
            + ", ".join(mortos)
            + "\n\nSuba o ambiente antes de rodar a demo:\n"
              "  [bold]docker compose up -d[/]",
            title="demo_e2e — abortado", border_style="red"))
        sys.exit(1)


def _migrar():
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=os.environ, capture_output=True, text=True)
    if r.returncode != 0:
        con.print(f"[red]alembic falhou:[/]\n{r.stderr or r.stdout}")
        sys.exit(1)


def _subir_stack():
    """API (uvicorn thread) + worker IA (thread) in-process."""
    import asyncio
    import uvicorn
    from app.main import create_app
    from app import worker
    from sqlalchemy.ext.asyncio import (async_sessionmaker,
                                        create_async_engine)
    from app.repository import RepositorioSQL

    async def repo_factory():
        e = create_async_engine(DB_URL)
        return e, RepositorioSQL(
            async_sessionmaker(e, expire_on_commit=False))

    app = create_app("tjpa", repo_factory=repo_factory)
    srv = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=8000, log_level="warning"))
    t_api = threading.Thread(target=srv.run, daemon=True)
    t_api.start()

    def _worker():
        asyncio.run(worker.main())
    t_wk = threading.Thread(target=_worker, daemon=True)
    t_wk.start()

    import httpx
    for _ in range(100):
        try:
            httpx.get(f"{API}/healthz", timeout=0.3)
            return srv
        except Exception:
            time.sleep(0.1)
    con.print("[red]API não subiu em 10s[/]")
    sys.exit(1)


def passo(n, titulo):
    con.print(f"\n[bold cyan]── Passo {n} — {titulo} ──[/]")


def main():
    import httpx

    con.rule("[bold]DEMO E2E — esteira soberana de anonimização[/]")
    _preflight()
    con.print("[green]✓[/] infra: Postgres, RabbitMQ e MinIO de pé")
    _migrar()
    con.print("[green]✓[/] schema migrado (alembic head)")
    srv = _subir_stack()
    con.print("[green]✓[/] API :8000 + worker IA (IA_ENGINE=demo)")

    h = lambda org: {"Authorization":
                     f"Bearer {idp.token_para(org)}"}  # noqa: E731

    passo(1, "Autenticação — JWT RS256 offline do Órgão A (TJPA)")
    con.print(f"[green]✓[/] token tjpa assinado pelo IdP local "
              f"({len(h('tjpa')['Authorization']) - 7} chars)")

    passo(2, "Criação — POST /v1/tramitacoes (metadados + hash)")
    r = httpx.post(f"{API}/v1/tramitacoes", headers=h("tjpa"),
                   json=dict(
                       caso_cnj=CASO, destino="prodepa",
                       modo="pseudonimizacao",
                       hash_documento_sha256=HASH_DOC,
                       metadados={"assunto": "dano moral",
                                  "demo": "t13"},
                       idempotency_key=f"demo-{int(time.time())}",
                       requer_anonimizacao_lgpd=True))
    if r.status_code != 201:
        con.print(f"[red]falhou: {r.status_code} {r.text}[/]")
        sys.exit(1)
    tid = r.json()["id"]
    con.print(f"[green]✓[/] 201 — tramitação {tid}")
    con.print(f"    sha256 declarado: [dim]{HASH_DOC}[/]")

    passo(3, "Upload — POST /v1/documentos/{id}/upload (PDF)")
    r = httpx.post(f"{API}/v1/documentos/{tid}/upload",
                   headers=h("tjpa"),
                   files={"arquivo": ("peticao.pdf", DOC,
                                      "application/pdf")})
    if r.status_code != 201:
        con.print(f"[red]falhou: {r.status_code} {r.text}[/]")
        sys.exit(1)
    up = r.json()
    con.print(f"[green]✓[/] 201 — hash conferido, "
              f"{up['tamanho']} bytes em tjpa-docs (MinIO)")
    con.print(f"    sha256 medido:    [dim]{up['sha256']}[/]")

    passo(4, "Outbox → Relay → RabbitMQ (at-least-once)")
    con.print("    relay lê outbox PENDENTE, publica com "
              "publisher-confirm e marca PROCESSADO...")

    passo(5, "Processamento IA — worker consome e anonimiza")
    t0 = time.time()
    d = {}
    while time.time() - t0 < 5:
        d = httpx.get(f"{API}/v1/tramitacoes/{tid}",
                      headers=h("tjpa")).json()
        if d.get("anonimizacao_concluida"):
            break
        time.sleep(0.3)
    if not d.get("anonimizacao_concluida"):
        con.print("[red]timeout 5s — worker não concluiu[/]")
        sys.exit(1)
    con.print(f"[green]✓[/] doc_anonimizado gravado na trilha "
              f"({time.time() - t0:.1f}s)")

    passo(6, "Consulta pelo Órgão B (PRODEPA) — GET por CNJ")
    r = httpx.get(f"{API}/v1/tramitacoes/{CASO}",
                  headers=h("prodepa"))
    if r.status_code != 200:
        con.print(f"[red]falhou: {r.status_code} {r.text}[/]")
        sys.exit(1)
    d = r.json()
    con.print(f"[green]✓[/] 200 — status=[bold]{d['status']}[/]  "
              f"anonimizacao_concluida={d['anonimizacao_concluida']}")

    tab = Table(title="trilha_auditoria — hash-chain",
                show_lines=False)
    for col in ("seq", "evento", "hash_anterior", "hash_cadeia"):
        tab.add_column(col, style="dim" if col != "evento" else "")
    ok = True
    prev = None
    for ev in d["trilha"]:
        elo = (prev is None or ev["hash_anterior"] == prev)
        ok &= elo
        tab.add_row(str(ev["seq"]), ev["evento"],
                    ev["hash_anterior"][:12] + "…",
                    ev["hash_cadeia"][:12] + "…"
                    + (" [green]✓[/]" if elo else " [red]✗[/]"))
        prev = ev["hash_cadeia"]
    con.print(tab)
    con.print("[green]✓ cadeia íntegra[/]" if ok else
              "[red]✗ CADEIA QUEBRADA[/]")

    passo(7, "Download anonimizado — Órgão B baixa a versão LGPD")
    r = httpx.get(f"{API}/v1/documentos/{tid}/download-anonimizado",
                  headers=h("prodepa"))
    if r.status_code != 200:
        con.print(f"[red]falhou: {r.status_code} {r.text}[/]")
        sys.exit(1)
    corpo = r.content.decode()
    achou = "[ANONIMIZADO_LGPD]" in corpo
    con.print(Panel(corpo.strip(), title="documento sanitizado",
                    border_style="green" if achou else "red"))
    if not achou:
        con.print("[red]✗ tag [ANONIMIZADO_LGPD] ausente[/]")
        sys.exit(1)
    assert "123.456.789-00" not in corpo          # CPF original fora
    con.print("[green]✓[/] tag presente, CPF original ausente")

    con.rule("[bold green]DEMO CONCLUÍDA — fluxo íntegro[/]")
    srv.should_exit = True
    sys.exit(0)


if __name__ == "__main__":
    main()
