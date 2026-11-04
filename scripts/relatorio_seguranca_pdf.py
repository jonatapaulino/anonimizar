"""Relatorio tecnico da blindagem E2E e da substituicao de JWT.

Gera docs/relatorio_seguranca_e2e.pdf — mesma disciplina do
relatorio-validacao: medido x contrato x nao avaliado.
Fonte da verdade: docs/relatorio_seguranca_e2e.md.

Uso: python scripts/relatorio_seguranca_pdf.py
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "docs" / "relatorio_seguranca_e2e.pdf"


def _lat(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


class Rel(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110)
        self.cell(0, 5, _lat(
            "PIDE/FAPESPA - iSACI | Blindagem E2E + substituicao "
            "de JWT"), align="R")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(110)
        self.cell(0, 6, _lat(f"pagina {self.page_no()}"), align="C")

    def h1(self, t):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(30)
        self.cell(0, 9, _lat(t))
        self.ln(12)

    def h2(self, t):
        self.ln(3)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(0, 70, 120)
        self.cell(0, 7, _lat(t))
        self.ln(9)

    def p(self, t, indent=0):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(30)
        self.set_x(10 + indent)
        self.multi_cell(0, 5, _lat(t))
        self.ln(1)

    def bullet(self, t, indent=6):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(30)
        self.set_x(10 + indent)
        self.multi_cell(0, 5, _lat("- " + t))

    def tab(self, headers, rows, widths, fs=8.5):
        self.set_font("Helvetica", "B", fs)
        self.set_fill_color(230, 236, 242)
        self.set_text_color(30)
        for h, w in zip(headers, widths):
            self.cell(w, 6, _lat(h), border=1, fill=True)
        self.ln()
        self.set_font("Helvetica", "", fs)
        for r in rows:
            x0 = self.get_x()
            # altura da linha = maior nb de linhas das cells
            lines = []
            for c, w in zip(r, widths):
                lines.append(max(1, int(
                    self.get_string_width(_lat(c)) / (w - 2)) + 1))
            h = 5 * max(lines)
            y0 = self.get_y()
            for c, w in zip(r, widths):
                self.set_xy(x0, y0)
                self.multi_cell(w, 5, _lat(c), border=1)
                x0 += w
            self.set_xy(x0, y0 + h)


def main():
    r = Rel()
    r.set_auto_page_break(True, margin=18)
    r.add_page()

    r.h1("Relatorio Tecnico - Blindagem E2E e Substituicao de JWT")
    r.set_font("Helvetica", "I", 9)
    r.set_text_color(90)
    r.multi_cell(0, 5, _lat(
        "Data: 2026-11-04 | Commits: 6036402 (implementacao), "
        "7a7e074 (sniffer), 89ae7cb (cobertura + mTLS real) | "
        "Suite: 217 testes passando | Convencao: medido x "
        "contrato x nao avaliado"))
    r.ln(4)

    r.h2("1. Veredicto")
    r.p("O mecanismo esta provado; a arquitetura como malha de "
        "producao nao esta - e isso e o correto neste estagio. "
        "Provado em teste dinamico real: todo request /v1/ e "
        "decifrado antes da regra de negocio; toda response sai "
        "cifrada - inclusive erros 4xx/5xx; o fio so carrega "
        "quadros 0xE2; identidade vem de certificado de cliente em "
        "handshake TLS 1.3 real; broker e storage so transportam "
        "ciphertext. Contrato (config verificada estaticamente): "
        "topologia do compose, nginx.conf, URLs TLS internas, "
        "E2E_OBRIGATORIO=1. Nao avaliado: prova de NIC na rede "
        "interna com conteineres reais, latencia, rotacao de "
        "chaves, transito A<->B entre dois nos.")

    r.h2("2. Esclarecimento tecnico aplicado")
    r.p("'Hash ponta a ponta' literal nao existe: hash e "
        "irreversivel e o receptor nao recupera o dado. A "
        "propriedade pedida (claro so em memoria, ciphertext na "
        "rede) exige cifra autenticada (AEAD). Implementado "
        "ChaCha20-Poly1305 (RFC 8439): confidencialidade + "
        "integridade + deteccao de adulteracao num selo. SHA-256 "
        "segue na integridade de documento da trilha.")

    r.h2("3. Remocao completa do JWT")
    r.tab(
        ["Artefato", "Acao"],
        [["app/deps.py", "reescrito - jwt.decode/PyJWT/"
          "JWT_PUBLIC_KEY fora; identidade = X-Cliente-Orgao do "
          "terminador mTLS"],
         ["tests/jwthelper.py", "deletado - par RSA e emissor "
          "RS256 fora da suite"],
         ["test_auth_jwt.py", "substituido por test_auth_borda.py "
          "(401 opaco, oraculo fechado, 401 != 409)"],
         ["6 arquivos de teste", "tests.identidade.hdr - mesma "
          "assinatura, header em vez de token"],
         ["WWW-Authenticate: Bearer", "removido do handler 401"]],
        [55, 125])
    r.ln(2)
    r.p("Motivo: Bearer JWT vive no cliente e e exfiltravel "
        "(XSS/localStorage); certificado de cliente fica no SO/HSM "
        "do orgao. A API confia no header porque o compose garante "
        "que so o nginx alcanca a rede interna.")

    r.h2("4. Nucleo criptografico - app/crypto_e2e.py")
    for b in [
        "Quadro: 0xE2 | nonce 12B | len 4B | ciphertext+tag 16B",
        "AAD = indice do quadro: reordenacao/supressao quebra o selo",
        "Terminador 0xE2+16x00: truncamento de stream detectavel",
        "Streaming real - bloco a bloco, sem materializar em RAM",
        "Chave via E2E_CHAVE (hex 32B, Vault em runtime); ausente ="
        " bypass de dev; malformada = ErroCripto (fail closed)"]:
        r.bullet(b)

    r.h2("5. Os tres interceptadores")
    r.tab(
        ["Fronteira", "Codigo", "Comportamento provado"],
        [["HTTP", "app/middleware_e2e.py (ASGI)",
          "decifra body antes do roteador; cifra response quadro a "
          "quadro; plaintext em /v1/ = 415; selo invalido = 400"],
         ["Broker", "app/events.py + worker.py",
          "publicar sela Message.body; payload_de_mensagem decifra"
          " - RabbitMQ so carrega ciphertext"],
         ["Storage", "ArmazenamentoCifrado",
          "wrapper sobre ArmazenamentoPort - backend so persiste "
          "quadros; abrir decifra do stream"]],
        [25, 55, 100])

    r.h2("6. Configuracao - deploy/")
    for b in [
        "nginx.conf: TLS 1.3 apenas, ssl_verify_client on, CA dos"
        " pares, CN do ssl_client_s_dn -> X-Cliente-Orgao, "
        "Authorization zerado no proxy, buffering off (streaming)",
        "compose.yaml: nginx monta conf+certs :ro; api com "
        "E2E_OBRIGATORIO=1 + E2E_CHAVE passthrough do Vault",
        "gerar_certs_mtls.py: CA dev + certs por orgao (CN=id) - "
        "dev only; producao usa PKI de cada instituicao"]:
        r.bullet(b)

    r.h2("7. O que foi medido (provas executadas)")
    r.tab(
        ["#", "Prova", "Resultado"],
        [["1", "Fio so carrega ciphertext (socket real, cada byte)",
          "sentinela PII e caso_cnj ausentes de 100% do fio; dois "
          "lados = quadros 0xE2"],
         ["2", "Controle negativo (mesma app sem chave)",
          "sentinela e JSON legiveis no fio - sniffer nao e vacuoso"],
         ["3", "Cobertura de rotas (todas /v1/, todos metodos)",
          "toda resposta no fio = E2E, inclusive 4xx"],
         ["4", "Estatico: nenhuma rota escapa",
          "todo path e /v1/ ou whitelist publica"],
         ["5", "Adulteracao (bit-flip)", "ErroCripto -> 400 opaco"],
         ["6", "Chave errada", "400 opaco"],
         ["7", "Reordenacao/truncamento",
          "ErroCripto (AAD=indice + terminador)"],
         ["8", "Storage so persiste quadros",
          "sentinela ausente; adulteracao detectada; multi-quadro "
          ">64KB integro"],
         ["9", "AMQP so carrega ciphertext",
          "content-type x-e2e, magia 0xE2, roundtrip ok"],
         ["10", "mTLS real (handshake TLS 1.3 com certs do repo)",
          "CN=tjpa = identidade; sem cert rejeitado; CA forjada "
          "rejeitada"],
         ["11", "Plaintext com E2E_OBRIGATORIO=1",
          "415 opaco, antes da auth"],
         ["12", "401 opaco mantido",
          "mesma mensagem p/ ausente/vazio; sem motivo fino"],
         ["13", "Contrato estatico (test_isolamento)",
          "so nginx na borda/so 443; interna internal:true; "
          "E2E_OBRIGATORIO=1; mounts :ro"]],
        [10, 78, 92])

    r.h2("8. Limitacoes honestas (desenho, nao bugs)")
    for b in [
        "Chave simetrica por par de nos: quem vaza a chave decifra "
        "E forja trafego nos dois sentidos; sem forward secrecy "
        "(TLS de transporte mitiga o hop, a camada E2E nao tem PFS)",
        "AEAD nao impede replay de envelope integro - defesa e a "
        "idempotency_key do negocio; timestamp+janela e o "
        "endurecimento natural pendente",
        "X-Cliente-Orgao e confianca de perimetro: quem ja esta na "
        "interna pode forjar o header (ameaca interna fora do "
        "modelo de borda)",
        "XSS mitigado, nao eliminado: a credencial deixa de ser "
        "copiavel, mas um XSS ainda pode disparar requests "
        "autenticados pelo navegador",
        "abrir materializa o corpo do request: ok p/ JSON de "
        "controle; upload multipart grande atravessa num quadro "
        "(stream de ingresso e melhoria futura)"]:
        r.bullet(b)

    r.h2("9. Nao avaliado")
    for b in [
        "NIC/tcpdump na rede interna com o compose de pe - bytes do"
        " socket provam o payload; a malha conteiner-a-conteiner nao",
        "TLS dos clientes internos (amqps, sslmode, https S3) - "
        "contrato de URL, nenhum handshake medido",
        "nginx.conf executada - a primitiva foi provada; a config "
        "em si e assert estatico",
        "Transito A<->B entre nos reais - falta o lado emissor do "
        "envelope E2E no repo",
        "Latencia/overhead da cifragem - nao medida",
        "Rotacao/revogacao de E2E_CHAVE - depende do Vault (passo "
        "3) + decisao juridica de reidentificacao"]:
        r.bullet(b)

    r.h2("10. Conclusao")
    r.p("Camada de dados: invariantes mantidas e reforcadas (binario"
        " nunca em envelope/broker/DB; agora tambem nunca legivel "
        "em repouso nem no fio) - provado com medicao. Camada de "
        "transporte E2E: mecanismo provado em toda a superficie da "
        "API; falta a malha (no<->no, servicos internos, NIC). "
        "Identidade: mecanismo provado em handshake real; falta "
        "executar o nginx com certs de producao. Chamar "
        "'arquitetura validada' so depois do tcpdump na interna, "
        "dos handshakes internos medidos e do round-trip A<->B.")

    r.output(str(OUT))
    print(f"PDF: {OUT}")


if __name__ == "__main__":
    main()
