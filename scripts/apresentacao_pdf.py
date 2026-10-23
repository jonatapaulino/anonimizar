"""Apresentacao da arquitetura para docentes/alunos.

Gera docs/apresentacao_arquitetura.pdf — mesmo conteudo de
apresentacao_arquitetura.html, com o diagrama desenhado em
primitivas fpdf (caixas + setas).

Uso: python scripts/apresentacao_pdf.py
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "docs" / "apresentacao_arquitetura.pdf"


def _lat(s):
    return s.encode("latin-1", "replace").decode("latin-1")


class Rel(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110)
        self.cell(0, 5, _lat("PIDE/FAPESPA - iSACI | Arquitetura "
                             "do no soberano"), align="R")
        self.ln(7)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(110)
        self.cell(0, 6, _lat(f"pagina {self.page_no()}"),
                  align="C")

    def h1(self, t):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(13, 59, 102)
        self.cell(0, 11, _lat(t))
        self.ln(13)

    def h2(self, t):
        self.set_font("Helvetica", "B", 12.5)
        self.set_text_color(13, 59, 102)
        self.cell(0, 8, _lat(t))
        self.ln(9)

    def h3(self, t):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(27, 108, 168)
        self.cell(0, 7, _lat(t))
        self.ln(7)

    def p(self, t):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(20)
        self.multi_cell(0, 5, _lat(t))
        self.ln(2)

    def bullet(self, t):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(20)
        self.multi_cell(0, 5, _lat("- " + t))
        self.ln(0.5)

    def tabela(self, cab, linhas, larguras, negrito_col=None):
        def _nlinhas(txt, w):
            # ~0.19mm por caractere em 8.5pt Helvetica
            return max(1, -(-int(len(txt) * 1.9) // int(w * 10)))

        self.set_font("Helvetica", "B", 8.5)
        self.set_fill_color(13, 59, 102)
        self.set_text_color(255)
        x0 = self.l_margin
        for i, c in enumerate(cab):
            self.cell(larguras[i], 6, _lat(str(c)), border=1,
                      fill=True, align="L")
        self.ln()
        self.set_text_color(20)
        for ln in linhas:
            h = max(5.0, 5.0 * max(
                _nlinhas(str(c), larguras[i] / 10)
                for i, c in enumerate(ln)))
            if self.get_y() + h > 272:
                self.add_page()
                x0 = self.l_margin
            y0 = self.get_y()
            x = x0
            for i, c in enumerate(ln):
                self.rect(x, y0, larguras[i], h)
                if i == negrito_col:
                    self.set_font("Helvetica", "B", 8.5)
                    self.set_text_color(13, 59, 102)
                else:
                    self.set_font("Helvetica", "", 8.5)
                    self.set_text_color(20)
                self.set_xy(x, y0 + 0.3)
                self.multi_cell(larguras[i], 4.5, _lat(str(c)))
                x += larguras[i]
            self.set_xy(x0, y0 + h)
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(20)
        self.ln(3)

    def box(self, x, y, w, h, titulo, linhas, cor=(27, 108, 168),
            fill=(255, 255, 255)):
        self.set_fill_color(*fill)
        self.set_draw_color(*cor)
        self.set_line_width(0.5)
        self.rect(x, y, w, h, "DF")
        self.set_xy(x, y + 2)
        self.set_font("Helvetica", "B", 8.5)
        self.set_text_color(13, 59, 102)
        self.cell(w, 4, _lat(titulo), align="C")
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(70)
        for l in linhas:
            self.set_xy(x, self.get_y() + 3.5)
            self.cell(w, 3.5, _lat(l), align="C")

    def seta(self, x1, y1, x2, y2, cor=(27, 108, 168), texto=None):
        self.set_draw_color(*cor)
        self.set_line_width(0.4)
        self.line(x1, y1, x2, y2)
        # ponta
        import math
        a = math.atan2(y2 - y1, x2 - x1)
        for da in (2.6, -2.6):
            self.line(x2, y2, x2 - 5 * math.cos(a + da),
                      y2 - 5 * math.sin(a + da))
        if texto:
            self.set_font("Helvetica", "", 7)
            self.set_text_color(90)
            self.text((x1 + x2) / 2 - 8, (y1 + y2) / 2 - 1.5,
                      _lat(texto))


def diagrama(pdf):
    pdf.add_page(orientation="L")
    pdf.h2("Desenho da arquitetura")
    # moldura do no
    pdf.set_draw_color(13, 59, 102)
    pdf.set_line_width(0.6)
    pdf.set_fill_color(247, 249, 252)
    pdf.rect(12, 30, 250, 150, "DF")
    pdf.set_dash_pattern(dash=2, gap=2)
    pdf.set_draw_color(180, 84, 30)
    pdf.line(264, 32, 264, 178)
    pdf.set_dash_pattern()
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(13, 59, 102)
    pdf.text(18, 38, _lat("NO DA INSTITUICAO (orgao A) - soberano"))
    pdf.set_text_color(180, 84, 30)
    pdf.text(268, 38, _lat("fronteira: so metadados"))

    pdf.box(18, 46, 52, 20, "API FastAPI",
            ["upload/recebimento", "JWT offline"])
    pdf.box(18, 74, 52, 22, "PostgreSQL",
            ["tramitacao + outbox", "trilha hash-chain"])
    pdf.box(18, 102, 52, 20, "MinIO (S3)",
            ["<org>-docs", "<org>-docs-anon"])
    pdf.box(90, 46, 44, 18, "Relay", ["outbox->envelopes"])
    pdf.box(160, 46, 62, 18, "RabbitMQ",
            ["quorum + DLX + backoff"])
    pdf.box(90, 76, 44, 20, "Worker IA", ["prefetch=1", "assincrono"])
    pdf.box(160, 74, 62, 24, "MotorIA (porta)",
            ["cascata: regex + LLM", "local qwen2.5 + guarda"])
    pdf.box(160, 104, 62, 18, "Gate residual PII",
            ["regex + contexto"], cor=(180, 84, 30),
            fill=(255, 247, 237))

    pdf.seta(44, 66, 44, 74)                 # api -> pg
    pdf.seta(44, 96, 44, 102)                # pg -> minio
    pdf.seta(70, 84, 90, 55)                 # pg outbox -> relay
    pdf.seta(134, 55, 160, 55)               # relay -> mq
    pdf.seta(112, 64, 112, 76)               # relay->worker
    pdf.seta(134, 86, 160, 86)               # worker -> motor
    pdf.seta(190, 98, 190, 104)              # motor -> gate
    pdf.seta(160, 112, 70, 112)              # gate -> minio anon
    pdf.seta(70, 50, 90, 50)                 # api -> relay? (outbox)
    pdf.seta(112, 96, 70, 110)               # worker lê bruto

    # falha residual (laranja)
    pdf.set_draw_color(180, 84, 30)
    pdf.set_line_width(0.4)
    x1, y1, x2, y2 = 172, 113, 58, 96
    pdf.line(x1, y1, x2, y2)
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    for da in (2.6, -2.6):
        pdf.line(x2, y2, x2 - 5 * math.cos(a + da),
                 y2 - 5 * math.sin(a + da))
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(180, 84, 30)
    pdf.text(120, 135, _lat(
        "residual>0 -> falha_anonimizacao na trilha "
        "(nada vai ao bucket)"))

    # no B
    pdf.box(268, 46, 40, 22, "NO B", ["mesmo desenho", "idempotente"])
    pdf.seta(222, 52, 268, 54, texto="envelope")
    pdf.seta(268, 64, 222, 76, texto="confirmacao")

    # invariantes
    pdf.box(18, 140, 244, 38, "INVARIANTES DE PRIVACIDADE", [
        "binario nunca entra no PostgreSQL, envelopes, broker "
        "nem respostas de API;",
        "upload -> SHA-256 verificado -> storage por-orgao -> "
        "evento auditavel;",
        "trilha append-only encadeada por hash; outbox "
        "transacional (evento+estado no mesmo COMMIT);",
        "idempotencia por (orgao, chave); JWT validado offline; "
        "mTLS planejado na fronteira."],
        cor=(216, 224, 234))


def main():
    pdf = Rel()
    pdf.set_auto_page_break(True, 18)
    pdf.add_page()
    pdf.h1("iSACI - no soberano de anonimizacao e tramitacao")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 5, _lat(
        "PIDE / FAPESPA - POC de arquitetura - documento de "
        "apresentacao"))
    pdf.ln(4)
    pdf.p("Principio estruturante: cada instituicao roda um no "
          "de borda soberano - guarda, processa e assina os "
          "proprios documentos. O que atravessa a fronteira "
          "entre organizacoes sao apenas envelopes de "
          "metadados (hashes, IDs, estado); nunca o documento "
          "binario nem texto extraido.")

    diagrama(pdf)

    pdf.add_page()
    pdf.h2("O fluxo, em algoritmo")
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 4.5, _lat(
        "O mesmo desenho, lido como sequencia de passos."))
    pdf.ln(2)
    algoritmo = [
        ("UPLOAD (no A)", [
            "1  recebe metadados + SHA-256 do documento",
            "2  se (orgao, chave) ja existe -> devolve resultado",
            "   cometido            // idempotente: reenvio = eco",
            "3  recebe binario (multipart) -> verifica SHA-256",
            "4  hash confere? nao -> rejeita; sim -> grava em",
            "   <org>-docs",
            "5  num unico COMMIT: trilha += doc_arquivado:{id}",
            "                  outbox += ia.anonimizacao:{id}",
            "      // evento e estado vivem ou morrem juntos",
        ]),
        ("ANONIMIZACAO (worker, fila ia.anonimizacao)", [
            "6  baixa o bruto -> MotorIA.anonimizar(bytes)",
            "   // cascata: regex -> spans LLM -> so-nomes ->",
            "   // guarda -> substituicao por codigo",
            "7  saida ilegivel? -> trilha += falha; NACK;",
            "   FIM",
            "8  pii_residual(saida) > 0? ->",
            "   trilha += falha:residual_pii; sem gravacao;",
            "   // fail-closed",
            "   ACK; FIM",
            "9  grava em <org>-docs-anonimizados;",
            "   trilha += doc_anonimizado:{id}; ACK",
        ]),
        ("TRAMITACAO A -> B", [
            "10 trilha += criada:{id}; outbox += envelope",
            "   // envelope = so metadados + hash; nunca binario",
            "11 relay publica com retry limitado -> EM_TRANSITO",
            "12 B recebe (idempotente) -> RECEBIDA; 1o ingresso",
            "   traz hash_cadeia",
            "13 B decide -> CONFIRMADA | RECUSADA | CANCELADA",
            "14 esgotou retry? -> estado EXAUSTO (visivel,",
            "   auditado)",
            "15 reconciliador varre EM_TRANSITO antigos ->",
            "   reencaminha   // 'perdido em transito' nao vira",
            "   // buraco",
        ]),
    ]
    for titulo, linhas in algoritmo:
        pdf.set_fill_color(15, 36, 56)
        w = 190
        x = pdf.l_margin
        y0 = pdf.get_y()
        h = 5 + 4.6 * len(linhas)
        if y0 + h > 272:
            pdf.add_page()
            y0 = pdf.get_y()
        pdf.rect(x, y0, w, h, "F")
        pdf.set_xy(x + 3, y0 + 2)
        pdf.set_font("Courier", "B", 9)
        pdf.set_text_color(143, 208, 160)
        pdf.cell(0, 5, _lat(titulo))
        pdf.ln(5.5)
        pdf.set_font("Courier", "", 8.5)
        pdf.set_text_color(214, 230, 245)
        for l in linhas:
            pdf.set_x(x + 3)
            pdf.cell(0, 4.2, _lat(l))
            pdf.ln(4.2)
        pdf.set_y(y0 + h + 4)

    if pdf.get_y() > 200:
        pdf.add_page()
    pdf.h3("Quem liga com quem (o diagrama em texto)")
    conexoes = [
        "API FastAPI -> PostgreSQL: estado da tramitacao, evento "
        "de trilha e evento de outbox numa unica transacao.",
        "PostgreSQL -> MinIO: binario (SHA-256 verificado) vai "
        "para <org>-docs; a coluna da esquerda encadeia upload -> "
        "registro -> objeto.",
        "PostgreSQL -> Relay: o relay le os eventos pendentes da "
        "tabela outbox.",
        "Relay -> RabbitMQ: publica o envelope (so metadados + "
        "hash).",
        "Relay -> Worker IA: sinaliza o processamento assincrono "
        "pendente.",
        "RabbitMQ -> No B: o envelope atravessa a fronteira "
        "(linha tracejada) - e a unica coisa que sai do no.",
        "No B -> RabbitMQ: a confirmacao (RECEBIDA/hash_cadeia) "
        "volta pelo mesmo caminho.",
        "Worker IA -> API/PostgreSQL (retorno superior): grava "
        "doc_anonimizado:{id} ou falhas na trilha.",
        "Worker IA -> MinIO (retorno inferior): baixa o bruto de "
        "<org>-docs.",
        "Worker IA -> MotorIA: entrega os bytes para "
        "anonimizar().",
        "MotorIA -> Gate residual PII: o texto anonimizado desce "
        "para validacao.",
        "Gate residual -> MinIO: se residual=0, grava em "
        "<org>-docs-anonimizados.",
        "Gate residual -> PostgreSQL (seta laranja): se "
        "residual>0, NADA e gravado - a falha falha_anonimizacao:"
        "{id}:residual_pii vai para a trilha.",
    ]
    for c in conexoes:
        pdf.bullet(c)

    glossario = [
        ("PII (Personally Identifiable Information)",
         "dado que identifica uma pessoa (nome, CPF, RG, e-mail, "
         "telefone, endereco). Objeto de protecao da LGPD e alvo "
         "da anonimizacao."),
        ("No soberano / fronteira",
         "cada instituicao roda o proprio no e guarda os proprios "
         "documentos; entre nos circulam so envelopes de metadados "
         "(ID, hash, estado) - nunca binario nem texto extraido. "
         "Nao existe ponto central onde o PII se concentre."),
        ("Envelope e hash",
         "mensagem A->B com identificadores e o SHA-256 do "
         "documento; o hash e a impressao digital que prova "
         "correspondencia entre o declarado e o recebido."),
        ("Outbox transacional",
         "o evento e gravado na mesma transacao da mudanca de "
         "estado: se o commit falha, nada e publicado - elimina o "
         "'mudou e ninguem foi avisado'. Um relay drena e publica."),
        ("Trilha de auditoria (hash-chain)",
         "log append-only onde cada evento carrega o hash do "
         "anterior: alterar um evento antigo invalida os "
         "seguintes - adulteracao e detectavel por verificacao."),
        ("Idempotencia e at-least-once",
         "o broker pode entregar 2x; o no B reconhece duplicata "
         "pela chave e devolve o resultado ja cometido - reenvio e "
         "eco, nao novo efeito."),
        ("Quorum + DLX",
         "filas replicadas toleram replica morta; mensagem que "
         "falha alem do delivery-limit vai para a fila-morta (DLQ) "
         "- erro permanente vira estado visivel, nao loop."),
        ("MotorIA - porta permutavel",
         "contrato anonimizar(bytes)->bytes: stub, demo-regex, "
         "Ollama e o futuro NER discriminativo implementam a mesma "
         "interface; trocar o motor nao toca o pipeline."),
        ("Cascata det + LLM",
         "regex pega CPF/RG/e-mail/telefone/endereco; LLM local "
         "extrai spans semanticos; guarda protege CNJ/VALOR; a "
         "substituicao e feita por codigo - o LLM aponta, o "
         "codigo apaga."),
        ("PII residual e o gate de saida",
         "PII residual = dado pessoal que sobrou no texto ja "
         "anonimizado. Se residual>0, o gate bloqueia a gravacao "
         "no bucket e encadeia falha_anonimizacao:{id}:residual_"
         "pii na trilha, contando so quantidades - falha vira "
         "evento auditavel, nao vazamento silencioso (fail-"
         "closed)."),
        ("NER exact x overlap",
         "exact exige fronteira identica ao gabarito; overlap "
         "aceita sobreposicao parcial. Teste: exact F1 0,755 "
         "(gate 0,85 reprovou) x overlap F1 0,938 - o motor "
         "encontra quase tudo, mas delimita mal."),
        ("Reidentificacao por mencao x documento",
         "4/360 entidades (1,1%) x 4/80 documentos (5,0%). A "
         "unidade de risco LGPD e o documento - um doc com um "
         "nome residual ja expoe uma pessoa."),
        ("ADR-0011 - zero IA generativa",
         "decisao registrada: processamento local "
         "deterministico/discriminativo. O LLM da cascata e "
         "desvio documentado da POC; voltar a ADR = NER "
         "discriminativo treinado medido no mesmo gate. Aceitar "
         "o desvio e decisao do requisitante."),
    ]
    pdf.add_page()
    pdf.h2("Conceitos-chave")
    for termo, texto in glossario:
        if pdf.get_y() > 262:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(13, 59, 102)
        pdf.write(5, _lat(termo + ": "))
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(20)
        pdf.write(5, _lat(texto))
        pdf.ln(7)

    pdf.add_page()
    pdf.h2("O que cada tecnologia decide")
    pdf.tabela(
        ["Tecnologia", "Papel", "O que influencia / garante"],
        [
            ["FastAPI + pydantic", "contrato HTTP do no",
             "validacao de envelope na borda; nada de binario "
             "em resposta"],
            ["PostgreSQL + SQLAlchemy + Alembic",
             "estado, outbox, trilha",
             "outbox transacional (evento gravado na mesma "
             "transacao do estado: se o commit falhar, nada e "
             "publicado); trilha hash-chain verificavel"],
            ["RabbitMQ (quorum + DLX)",
             "envelopes e fila de anonimizacao",
             "quorum tolera replica morta; DLX + delivery-limit "
             "isolam mensagem envenenada; prefetch=1"],
            ["MinIO (S3)", "objetos por orgao",
             "buckets <org>-docs/-anonimizados: isolamento "
             "fisico; binario fora do banco e do broker"],
            ["Worker (aio-pika)", "esteira IA assincrona",
             "ACK so apos upload+trilha (at-least-once); falha "
             "-> NACK+requeue; desacopla latencia do modelo"],
            ["Relay", "drenador do outbox",
             "retry/backoff limitado + exaustao explicita + "
             "reconciliador de 'perdidos em transito'"],
            ["MotorIA (porta)", "anonimizar(bytes)->bytes",
             "contrato permutavel (stub/demo/Ollama): a "
             "arquitetura nao depende do motor"],
            ["Ollama + qwen2.5 7B/14B", "detector semantico local",
             "processamento on-prem, temperature=0; "
             "experimento documentado (desvio da ADR-0011, "
             "decisao do requisitante)"],
            ["pii_residual", "gate de saida",
             "residual>0 -> falha_anonimizacao:residual_pii na "
             "trilha; nada vai ao bucket anonimizado"],
            ["JWT offline + HMAC", "autenticacao/integridade",
             "validacao sem IdP online (soberania); mTLS "
             "planejado na fronteira entre nos"],
            ["Docker Compose", "empacotamento do no",
             "no reproduzivel por instituicao: api+db+broker+"
             "minio+worker+relay"],
            ["pytest (smoke e2e)", "verificacao",
             "upload dedup, reconciliacao, outbox retry, DLQ, "
             "gate residual - a suite e o contrato"],
            ["fpdf2 / pypdf", "corpus e relatorio",
             "geracao de PDF sem quebrar entidade e relatorio "
             "de avaliacao - medicao, nao pipeline"],
        ],
        [46, 44, 100], negrito_col=2)

    pdf.add_page()
    pdf.h2("Fluxos essenciais")
    pdf.h3("Upload e registro")
    pdf.bullet("metadados + SHA-256 registrados; idempotencia "
               "por (orgao, chave);")
    pdf.bullet("upload multipart -> hash verificado -> objeto "
               "em <org>-docs;")
    pdf.bullet("doc_arquivado:{id} na trilha + evento outbox na "
               "mesma transacao.")
    pdf.h3("Tramitacao A -> B")
    pdf.bullet("criada:{id}; outbox publica envelope (metadados, "
               "nunca binario);")
    pdf.bullet("B recebe idempotentemente; 1o ingresso retorna "
               "hash_cadeia; duplicata devolve o resultado ja "
               "cometido;")
    pdf.bullet("estados CRIADA -> EM_TRANSITO -> RECEBIDA -> "
               "CONFIRMADA / RECUSADA / CANCELADA;")
    pdf.bullet("relay multi-replica com backoff limitado; "
               "reconciliador reencaminha perdidos; exaustao e "
               "estado explicito.")
    pdf.h3("Anonimizacao (esteira IA)")
    pdf.bullet("outbox ia.anonimizacao -> worker (prefetch=1);")
    pdf.bullet("bruto -> MotorIA.anonimizar (cascata: regex + "
               "spans LLM + passada so-nomes + guarda CNJ/"
               "VALOR + substituicao por codigo);")
    pdf.bullet("gate de legibilidade: saida ilegivel -> falha na "
               "trilha, sem gravacao;")
    pdf.bullet("gate residual: PII residual -> falha_"
               "anonimizacao:{id}:residual_pii, sem gravacao;")
    pdf.bullet("sucesso -> <org>-docs-anonimizados + "
               "doc_anonimizado:{id} -> ACK.")

    pdf.h2("O que a avaliacao mediu")
    pdf.p("Cascata na particao teste (80 docs, held-out): "
          "recall agregado 356/360 (98,9%); excesso em "
          "preservados 0/305; reidentificacao por mencao "
          "4/360 (1,1%, dentro do gate <=0,05) e por documento "
          "4/80 (5,0%, limite dentro do IC). NER exact F1 "
          "0,755 - abaixo do gate 0,85 (fronteiras frouxas dos "
          "spans LLM). Detalhe: docs/relatorio_avaliacao.pdf.")
    pdf.p("Leitura honesta: a arquitetura esta validada como "
          "desenho; o motor e candidato de POC, nao aprovado "
          "para producao - o gate NER exact reprovou e o uso de "
          "LLM generativo local e desvio documentado da "
          "ADR-0011, cuja aceitacao cabe ao requisitante.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"gerado: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
