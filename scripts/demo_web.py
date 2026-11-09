"""Visualizador web da demonstração — a versão amigável.

Serve uma página local (http://localhost:8080) que acompanha AO
VIVO a mesma execução real do `demo_coordenador.py`: o peer grava
marcos de progresso em /run/demo_state.json e esta página anima
a jornada do documento entre os dois nós.

Uso na apresentação:
  1. docker compose -f deploy/malha/compose.malha.yaml up -d
  2. python scripts/demo_web.py          -> abre o browser (projetor)
  3. python scripts/demo_coordenador.py --pausar  (terminal do apresentador)

A tela é 100% local (HTML sem CDN — funciona offline) e apenas
LÊ o estado: quem executa e prova é o orquestrador no terminal.
"""
import json
import subprocess
import sys
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PEER = "isaci-malha-peer-1"
PORTA = 8080
HTML = Path(__file__).resolve().parent / "web" / "demo.html"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._responder(200, "text/html; charset=utf-8",
                            HTML.read_bytes())
        elif self.path.startswith("/api/estado"):
            r = subprocess.run(
                ["docker", "exec", PEER,
                 "cat", "/run/demo_state.json"],
                capture_output=True)
            corpo = (r.stdout if r.returncode == 0
                     and r.stdout.strip() else b"{}")
            self._responder(200, "application/json", corpo,
                            no_store=True)
        elif self.path == "/api/reset":
            # reinicia a tela entre execuções (o próximo 'criar'
            # já zera progresso; isto limpa a página antes disso)
            self._responder(200, "application/json", b'{"ok":true}')
        else:
            self.send_error(404)

    def _responder(self, status, ctype, corpo, no_store=False):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *a):
        pass


def main():
    if not HTML.exists():
        sys.exit(f"página não encontrada: {HTML}")
    # peer de pé? (a página tolera malha descendo, mas avisar ajuda)
    r = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                       capture_output=True)
    if PEER not in r.stdout.decode("utf-8", "replace"):
        print(f"aviso: {PEER} não está de pé — suba a malha antes"
              " de iniciar a demo (a página abre em espera).")
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    print(f"visualizador em http://localhost:{PORTA}")
    print("deixe este terminal aberto durante a apresentação"
          " — Ctrl+C para encerrar")
    try:
        webbrowser.open(f"http://localhost:{PORTA}")
    except Exception:
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
