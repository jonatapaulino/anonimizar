"""Relatorio estruturado da arquitetura iSACI — estado atual.

Gera docs/relatorio_arquitetura_v2.pdf. Sucessor do
relatorio-arquitetura.pdf (16/10/2026 — era pre-mTLS/E2E).
Cobre a arquitetura pos rodada B/C (05/11/2026): mTLS na
borda, blindagem E2E, custodia Ed25519, replay compartilhado,
malha real de dois nos provada com pcap.

Convencao do repo: medido x pos-hoc x contrato x nao avaliado.
Fontes: app/, deploy/, AGENTS.md, docs/divida-tecnica.md,
docs/adr/, provas executadas em 05/11/2026.

Uso: python scripts/relatorio_arquitetura_pdf.py
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "docs" / "relatorio_arquitetura_v2.pdf"
IMG_SIMPLES = BASE / "docs" / "img" / "fluxograma_simples.png"
IMG_DET = BASE / "docs" / "img" / "fluxograma_arquitetura.png"


def _lat(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


class Rel(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110)
        self.cell(0, 5, _lat(
            "PIDE/FAPESPA - iSACI | Relatorio de Arquitetura v2"),
            align="R")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(110)
        self.cell(0, 6, _lat(f"pagina {self.page_no()}"), align="C")

    def h1(self, t):
        if self.get_y() > self.h - 45:
            self.add_page()
        self.set_x(10)
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(30)
        self.cell(0, 9, _lat(t))
        self.ln(12)

    def h2(self, t):
        if self.get_y() > self.h - 40:
            self.add_page()
        self.set_x(10)
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
        self.set_x(10)
        self.set_font("Helvetica", "", fs)
        self.set_text_color(30)
        with self.table(
                col_widths=widths, width=sum(widths),
                line_height=5, text_align="LEFT",
                headings_style=FontFace(
                    fill_color=(230, 236, 242), emphasis="BOLD")
                ) as table:
            for row in (headers, *rows):
                tr = table.row()
                for cell in row:
                    tr.cell(_lat(cell))
        self.ln(2)


def main():
    r = Rel()
    r.set_auto_page_break(True, margin=18)
    r.add_page()

    # ============ capa / identificacao ============
    r.ln(40)
    r.set_font("Helvetica", "B", 22)
    r.set_text_color(22, 48, 94)
    r.multi_cell(0, 11, _lat(
        "Relatorio de Arquitetura\nNo Soberano iSACI"), align="C")
    r.ln(6)
    r.set_font("Helvetica", "", 12)
    r.set_text_color(74, 85, 104)
    r.multi_cell(0, 7, _lat(
        "Malha soberana de tramitacao e anonimizacao de "
        "documentos juridicos\nProjeto PIDE / FAPESPA"),
        align="C")
    r.ln(24)
    r.set_font("Helvetica", "", 10)
    r.multi_cell(0, 6, _lat(
        "Versao: 2.0 - 05 de novembro de 2026\n"
        "Sucessor do relatorio v1 (16/10/2026, era pre-mTLS/E2E)\n"
        "Commits: 75d5a64..32b5e7b (malha real + rodada B/C)\n"
        "Suite: 284 verdes, 5 skipped, 4 xfailed | Malha de 2 nos"
        ": provada com pcap"), align="C")

    # ============ 1. veredicto ============
    r.add_page()
    r.h1("1. Sumario executivo")
    r.p(
        "O iSACI e um no de borda soberano por instituicao para "
        "tramitacao e anonimizacao de documentos juridicos. Cada "
        "orgao opera a mesma imagem do servico; os papeis (origem/"
        "destino) mudam, a stack nao. O binario do documento nunca "
        "entra em banco, envelope, broker ou resposta de API - so "
        "metadados + SHA-256 circulam entre os nos (invariante T9).")
    r.p(
        "A arquitetura esta provada em execucao, nao so no papel: "
        "malha real de dois nos (tjpa x mpfpa) com TLS em todos os "
        "links internos, Vault real servindo a chave E2E do no A, "
        "round-trip A<->B atraves das bordas mTLS e captura de NIC "
        "mostrando zero payload legivel no fio. A esteira de "
        "anonimizacao e assincrona e fail-closed: outbox "
        "transacional, fila quorum + DLQ, worker com gates "
        "deterministicos e trilha de auditoria append-only "
        "encadeada por hash.")
    r.p(
        "Distincao honesta: a infraestrutura de custodia esta "
        "medida e verde; o nucleo cientifico (motor de "
        "anonimizacao) foi medido como cascata POC fora da porta "
        "MotorIA - a integracao do pipeline medido na porta e o "
        "proximo passo arquitetural.")

    # ============ 2. subsistemas ============
    r.h1("2. Os tres subsistemas")
    r.tab(
        ["Subsistema", "Onde", "Natureza"],
        [["Malha soberana de\n tramitacao",
          "app/ (api, worker,\n relay) + deploy/",
          "Producao-grade: transporte A<->B com custodia "
          "criptografica, auditoria e isolamento de rede"],
         ["Porta MotorIA",
          "anonimizar(bytes)->bytes\n + app/motor_*.py",
          "Contrato estavel, implementacao permutavel; o motor "
          "medido (cascata v2) vive fora da porta, em scripts/"],
         ["Harness cientifico",
          "corpus/, scripts/eval_*,\n metricas_prereg, spikes/",
          "Medicao pre-registrada com gabaritos, manifestos e "
          "gates - ortogonal ao runtime"]],
        [45, 50, 85])

    # ============ 3. topologia ============
    r.h1("3. Topologia e tecnologias por camada")
    r.p(
        "deploy/compose.yaml e o contrato normativo de isolamento "
        "(rede interna sem egress, nginx unico na borda, hardening "
        "de containers - verificavel estaticamente por "
        "test_isolamento.py). deploy/malha/compose.malha.yaml e a "
        "prova executavel: dois nos reais com TLS em todos os "
        "links internos.")
    r.tab(
        ["Camada", "Tecnologia", "Papel"],
        [["Borda", "nginx (TLS 1.3 + mTLS,\n limit_req, HSTS)",
          "Unico ponto exposto; identidade = CN do cert -> "
          "X-Cliente-Orgao; Authorization zerado"],
         ["Blindagem", "MiddlewareE2E — AEAD\n"
          "ChaCha20-Poly1305 (quadro\n v2: ts no AAD)",
          "Payload cifrado ponta a ponta: request decifrado antes "
          "do roteador, response cifrada; x-e2e-ct allowlist"],
         ["API", "FastAPI + Pydantic v2",
          "Validacao de contrato, erros opacos sanitizados, "
          "E2E_OBRIGATORIO=1"],
         ["Dominio", "NoTramitacao\n (app/service.py)",
          "Maquina de estados, autorizacao centralizada "
          "(participacao -> papel -> no), idempotencia"],
         ["Persistencia", "PostgreSQL 16\n (asyncpg, alembic)",
          "tramitacoes, trilha hash-chain append-only (trigger), "
          "outbox, replay_nonces, idempotencia"],
         ["Objetos", "MinIO/S3",
          "Buckets <org>-docs e <org>-docs-anonimizados; objetos "
          "= quadros AEAD (ArmazenamentoCifrado)"],
         ["Esteira", "relay + RabbitMQ (quorum\n + DLQ) + worker",
          "Outbox transacional -> claim por lease -> publish -> "
          "worker -> motor -> gates -> bucket anonimizado"],
         ["Motor", "MotorIA (porta)",
          "stub | demo | ollama | langchain (IA_ENGINE); "
          "fail-closed se ausente"],
         ["Chaves", "Cofre: env | Vault KV v2\n (AppRole, token 60s)",
          "E2E_CHAVE {atual, anteriores} com rotacao; "
          "CofrePseudonimos (ent_id -> rotulo, sem consumidor)"],
         ["Custodia", "Ed25519 (app/assinatura.py)",
          "Envelope e ack assinados; verificacao fail-closed com "
          "ORG_SIGN_*/ORGAO_PUBKEYS_*"]],
        [24, 56, 100])

    # ============ 4. fluxo A<->B ============
    r.h1("4. Jornada do documento A -> B")
    r.p(
        "Criar (metadados + hash declarado) -> upload multipart "
        "(stream com SHA-256 conferido + magic bytes, <=20 MiB) -> "
        "MinIO -> trilha + outbox numa unica transacao. Enviar "
        "emite envelope Ed25519 - o binario nao viaja nele. O "
        "destino verifica a assinatura, baixa os bytes por "
        "download autenticado, arquiva no proprio bucket e so "
        "confirma apos recomputar o SHA-256 do proprio storage. O "
        "ack volta assinado; a origem aplica e encerra.")
    r.tab(
        ["Passo", "Acao", "Garantia exercida"],
        [["1-2", "A: criar + upload", "hash declarado = medido; "
          "magic bytes; estado CRIADA"],
         ["3", "A -> B: envelope", "Ed25519 + destino enderecado; "
          "so metadados + hash"],
         ["4", "B: receber", "assinatura valida antes de tocar o "
          "banco; eco idempotente em duplicata"],
         ["5", "B: baixar bytes", "download autenticado; mesmo "
          "gate de upload"],
         ["6", "B: confirmar", "SHA-256 recomputado do storage de "
          "B; ack assinado"],
         ["7", "A: aplicar ack", "assinatura do destino exigida; "
          "CONFIRMADA/RECUSADA"]],
        [14, 55, 111])

    # ============ 5. esteira ============
    r.h1("5. Esteira de anonimizacao (assincrona)")
    r.p(
        "A garantia mora na outbox, nao no broker: o evento "
        "DocumentoProntoParaAnonimizacao e gravado na mesma "
        "transacao do upload (payload so com ids). O relay (task "
        "na API) faz claim por UPDATE condicional com lease - "
        "relays paralelos serializam na linha - e marca "
        "PROCESSADO so apos publisher-confirm; falha gera "
        "tentativas++ com backoff e ESGOTADO + falha_outbox na "
        "trilha. O worker (prefetch=1) executa download -> motor "
        "-> gates -> upload no bucket anonimizado -> ACK; "
        "delivery-limit=3 leva a DLQ, drenada com "
        "falha_anonimizacao na trilha.")
    r.h2("Gates deterministicos (nao reprocessaveis)")
    for b in [
        "saida_legivel == False -> falha_anonimizacao:{id}:"
        "saida_ilegivel",
        "residual PII > 0 -> falha_anonimizacao:{id}:residual_pii"
        " (nada e gravado no bucket anonimizado)",
        "sucesso -> objeto em <org>-docs-anonimizados + "
        "doc_anonimizado:{id}"]:
        r.bullet(b)
    r.p(
        "Logs e metricas so contam PII por tipo - nunca valores. "
        "Efeito sob at-least-once deduplicado por "
        "encadear_uma_vez sob a mesma trava consultiva da "
        "extensao da trilha.")

    # ============ 6. trilha ============
    r.h1("6. Trilha de auditoria (hash-chain append-only)")
    for b in [
        "Matematica: topo_n = sha256(topo_{n-1} || evento); "
        "cadeia global por no (intercala casos) - divergencia num "
        "elo invalida a evidencia de todos",
        "Concorrencia: pg_advisory_xact_lock serializa a extensao "
        "+ UNIQUE(hash_anterior) como backstop - bifurcacao vira "
        "409, nunca silenciosa",
        "Imutabilidade: trigger barra UPDATE/DELETE (migracao "
        "0007)",
        "Verificacao autonoma: GET /v1/tramitacoes/{id}/verificar "
        "rejoga elo a elo - nao confia no topo denormalizado",
        "Refutabilidade residual (honesta): quem escreve no PG "
        "pode reescrever+reencadear - detecta adulteracao de "
        "terceiros, nao do DBA malicioso; assinatura por linha e "
        "ancora externa sao dividas abertas"]:
        r.bullet(b)

    # ============ 7. seguranca em camadas ============
    r.h1("7. Seguranca em camadas (cada uma falha sem derrubar a "
         "outra)")
    r.tab(
        ["Camada", "Mecanismo", "Politica por canal"],
        [["Identidade", "mTLS no nginx ->\n X-Cliente-Orgao +\n "
          "BORDA_SEGREDO opcional", "JWT removido (reprovado - "
          "exfiltravel). 3 portoes 401 opacos: header, formato "
          "OrgaoID, segredo compare_digest"],
         ["Payload", "Quadro v2 AEAD:\n 0xE2|0x02|nonce|len|ts|ct",
          "HTTP: frescura 300s + replay_nonces (claim por PK, "
          "multi-replica); AMQP: so frescura (redelivery "
          "legitima); S3/DLQ: sem janela (repouso/forense)"],
         ["Custodia", "Ed25519 envelope/ack",
          "Fail-closed quando configurado; confirmar recomputa "
          "hash; upload so em CRIADA/RECEBIDA"],
         ["Evidencia", "Trilha hash-chain +\n outbox transacional",
          "Append-only por trigger; efeito deduplicado por "
          "encadear_uma_vez"],
         ["Chaves", "Vault KV v2 + AppRole",
          "No A provou E2E_FONTE=vault real; token curto 60s; "
          "rotacao sela-com-atual/abre-com-todas"],
         ["Rede", "interna internal:true",
          "Sem egress; so nginx na borda; TLS em todos os links "
          "internos (amqps, pg-ssl, minio/vault https)"]],
        [22, 62, 96])

    # ============ 8. validacao executada ============
    r.h1("8. Validacao executada (05/11/2026) - medido")
    r.tab(
        ["Prova", "Metodo", "Resultado"],
        [["Suite smoke/e2e", "pytest -q",
          "284 verdes, 5 skipped, 4 xfailed"],
         ["Migracoes 0006/0007", "alembic upgrade no Postgres 16 "
          "real da malha", "aplicadas limpas (era divida "
          "aberta)"],
         ["Round-trip A<->B", "prova_malha.py no container peer "
          "rede borda (mTLS+E2E real)",
          "criar 201, upload 201, envio 200, em_transito, "
          "recebimento B 200 com hash_cadeia"],
         ["Prova de NIC", "tcpdump no netns dos apis + "
          "prova_pcap.py",
          "interna-a: 37 registros TLS + 17 quadros E2E; "
          "interna-b: 14 + 7; ZERO bytes legiveis (sentinela, "
          "caso_cnj, JSON, credenciais)"],
         ["Trilha verificavel", "GET .../verificar no no A",
          "integro=True; 12 linhas rejogadas elo a elo; topo "
          "recomputado confere"],
         ["Cofre real", "worker-a via AppRole no Vault",
          "GET 200 no segredo isaci/e2e (E2E_FONTE=vault "
          "provado)"]],
        [34, 62, 84])
    r.ln(2)
    r.p(
        "Contrato (verificado estaticamente): topologia do "
        "compose, nginx.conf, mounts :ro, E2E_OBRIGATORIO=1. "
        "Nao avaliado nesta rodada: latencia/overhead da "
        "cifragem, carga, CRL/OCSP, backup/retencao LGPD.")

    # ============ 9. motor medido ============
    r.h1("9. Estado medido do motor (POC - fora da porta)")
    r.p(
        "O deploy usa MotorOllama single-pass (IA_ENGINE). O que "
        "foi medido e a cascata v2 no harness (det regex + spans "
        "LLM + poda de fronteira + validador CPF mod-11 + "
        "res:NOME) - ainda nao plugada na porta MotorIA. ADR-0011 "
        "(zero IA generativa) segue como regra aprovada; o LLM "
        "como extrator e desvio documentado de POC. Retorno a "
        "ADR exige NER discriminativo medido no mesmo gate.")
    r.tab(
        ["Medicao", "Resultado"],
        [["Cascata v0 (teste, 80)", "NER exact F1 0.755 < gate "
          "0.85 (FAIL); recall 356/360; reident doc 4/80"],
         ["Cascata + poda (04/11)", "exact F1 0.919 (PASS); "
          "overlap 0.972; recall 357/360; reident 3/360"],
         ["Cascata v2 (04/11)", "exact F1 0.953; overlap 1.000; "
          "recall 360/360; reident 0/360"],
         ["Coreferencia corpus_v0", "pairwise F1 1.000; "
          "consistencia 90/90; anti-merge 0/270"],
         ["Nao avaliado", "utility TAB >= 0.85; latencia; "
          "corpus real (depende de exclusao juridica)"]],
        [55, 125])

    # ============ 10. limitacoes ============
    r.h1("10. Limitacoes honestas e divida ativa")
    for b in [
        "Chave simetrica por par de nos: vazamento decifra E "
        "forja nos dois sentidos; camada E2E sem PFS (TLS do hop "
        "mitiga)",
        "Hop nginx->api e HTTP em claro na interna carregando "
        "quadros E2E (headers legiveis, payload nao - e o "
        "desenho)",
        "org e parametro confiavel dentro do servico - endpoint "
        "interno futuro e bypass potencial de autorizacao",
        "Trilha detecta adulteracao, nao impede DBA malicioso "
        "reescrever+reencadear (sem assinatura por linha/ancora "
        "externa ainda)",
        "Ack B->A tem prova de autoria (Ed25519) mas nao "
        "mecanismo de re-entrega - A pode ficar EM_TRANSITO "
        "apos B terminal",
        "Esteira de anonimizacao no no B e ambigua: upload em B "
        "dispara evento com orgao_origem=A - o worker de B busca "
        "bucket de A no MinIO de B (a corrigir/decidir)",
        "Produto especificado != implementado: sem /v1/anonymize, "
        "sem cofre HMAC/DEK por caso, modo=pseudonimizacao e "
        "metadado inerte",
        "replay_nonces.expira_ms sem indice (varredura "
        "oportunista); credencial MinIO unica para todos os "
        "buckets do no",
        "CRL/OCSP, alerta de ESGOTADO, retencao/eliminacao LGPD, "
        "backup, sandbox de parser hostil, metadados DOCX/"
        "imagem, caso_cnj em claro (decisao DPO)"]:
        r.bullet(b)

    # ============ 11. roadmap ============
    r.h1("11. Proximos passos (ordem de dependencia)")
    r.tab(
        ["#", "Item", "Estado"],
        [["1", "NER discriminativo na porta MotorIA (sair do "
          "desvio ADR-0011)", "aberto - cascata v2 medida fora da"
          " porta; portar ou treinar"],
         ["2", "Decisao juridica de reidentificacao + integracao "
          "ent_id/mapa (CofrePseudonimos)", "aberto - mecanismo "
          "pronto, sem consumidor"],
         ["3", "Corpus real (Etapa 3)", "bloqueado - depende das "
          "exclusoes juridicas"],
         ["4", "Re-entrega do ack B->A + sweeper de EM_TRANSITO",
          "aberto"],
         ["5", "Decidir papel de B na esteira de anonimizacao",
          "aberto"],
         ["6", "Gates utility TAB e latencia", "nao avaliados"],
         ["7", "Operacao: CRL/OCSP, alerta ESGOTADO, backup, "
          "retencao LGPD, assinatura por linha da trilha",
          "divida ativa"]],
        [10, 105, 65])

    # ============ 12. inventario ============
    r.h1("12. Inventario documental")
    for b in [
        "AGENTS.md - invariantes, estrutura, estado medido, "
        "proximos passos (fonte primaria)",
        "docs/divida-tecnica.md - rodada B/C detalhada",
        "docs/adr/0000..0013 - decisoes (0006 emendado: mTLS; "
        "0011: zero IA generativa)",
        "docs/relatorio_seguranca_e2e.pdf - provas da camada E2E",
        "docs/metricas.md - gates pre-registrados; "
        "relatorio_avaliacao.pdf - medicao do motor",
        "docs/relatorio-arquitetura.pdf - v1 (16/10, historico)",
        "fluxogramas: docs/img/fluxograma_simples.png "
        "(apresentacao), fluxograma_arquitetura.png (detalhado), "
        "docs/fluxograma-arquitetura.html (interativo)",
        "provas: scripts/prova_malha.py, prova_pcap.py, "
        "test_mtls_real.py, test_seguranca_b.py"]:
        r.bullet(b)

    # ============ apendices ============
    for img, h1, cap in (
        (IMG_SIMPLES, "Apendice A - jornada do documento",
         "fig. A - jornada em 7 passos (docs/img/"
         "fluxograma_simples.png)"),
        (IMG_DET, "Apendice B - stack interna detalhada",
         "fig. B - coreografia A<->B + stack interna unica "
         "(docs/img/fluxograma_arquitetura.png)"),
    ):
        if img.exists():
            r.add_page()
            r.h1(h1)
            r.image(str(img), x=10, w=190)
            r.set_font("Helvetica", "I", 8)
            r.set_text_color(110)
            r.cell(0, 5, _lat(cap), align="C")

    r.output(str(OUT))
    print(f"PDF: {OUT}")


if __name__ == "__main__":
    main()
