"""Relatorio de tecnologias — o papel de cada uma na arquitetura.

Gera docs/relatorio_tecnologias.pdf: para cada tecnologia da
stack, o que e, o papel que exerce na arquitetura do no soberano,
por que foi escolhida, onde encontrar no codigo — e uma RESPOSTA
EM UMA FRASE para quando perguntarem na apresentacao.

Uso: python scripts/relatorio_tecnologias_pdf.py
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "docs" / "relatorio_tecnologias.pdf"


def _lat(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


class Rel(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110)
        self.cell(0, 5, _lat(
            "PIDE/FAPESPA | Relatorio de Tecnologias da "
            "Arquitetura"), align="R")
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

    def resp(self, t, indent=6):
        """Resposta em uma frase — destaque para a pergunta."""
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(0, 100, 60)
        self.set_x(10 + indent)
        self.multi_cell(0, 5, _lat(">> " + t))
        self.ln(1)

    def tec(self, nome, papel, oq, pq, onde, frase):
        """Bloco de uma tecnologia."""
        self.h2(nome)
        self.p(f"Papel na arquitetura: {papel}")
        self.p(f"O que e: {oq}")
        self.p(f"Por que ela: {pq}")
        self.p(f"Onde ver: {onde}")
        self.resp(frase)


def main():
    r = Rel()
    r.set_auto_page_break(True, margin=18)
    r.add_page()

    # ============ capa ============
    r.ln(45)
    r.set_font("Helvetica", "B", 21)
    self_title = ("Relatorio de Tecnologias\n"
                  "No Soberano - PIDE / FAPESPA")
    r.set_text_color(22, 48, 94)
    r.multi_cell(0, 11, _lat(self_title), align="C")
    r.ln(8)
    r.set_font("Helvetica", "", 11.5)
    r.set_text_color(74, 85, 104)
    r.multi_cell(0, 7, _lat(
        "o papel de cada tecnologia na arquitetura\n"
        "e a resposta em uma frase para cada 'o que isso faz?'"),
        align="C")
    r.ln(20)
    r.set_font("Helvetica", "", 10)
    r.multi_cell(0, 6, _lat(
        "Stack real da malha de dois nos (deploy/malha/) —\n"
        "a mesma imagem em cada instituicao; muda o papel,\n"
        "nao a stack."), align="C")

    # ============ visao geral ============
    r.add_page()
    r.h1("1. Visao geral da stack")
    r.p(
        "Cada no soberano e a MESMA composicao de servicos. O que "
        "muda entre instituicoes e o papel na tramitacao (origem "
        "ou destino), nunca a stack. Esta e a arquitetura-alvo: "
        "cada orgao opera esta composicao na propria "
        "infraestrutura.")
    r.ln(3)
    r.tab(
        ("Camada", "Tecnologia", "Funcao no no"),
        [
            ("API", "FastAPI (Python)", "tramitacoes, upload, "
             "recebimentos, acks, verificacao"),
            ("Banco", "PostgreSQL", "metadados, trilha "
             "hash-chain, outbox, replay_nonces — SEM bytes"),
            ("Fila", "RabbitMQ (TLS)", "esteira assincrona de "
             "anonimizacao — quorum + DLQ"),
            ("Storage", "MinIO (HTTPS)", "objetos — sempre "
             "ciphertext E2E em repouso"),
            ("Borda", "nginx + mTLS", "identidade institucional "
             "por certificado de cliente"),
            ("Segredos", "Vault", "custodia da chave E2E — "
             "AppRole, rotacao, revogacao"),
            ("Worker", "Python + MotorIA", "anonimizacao via "
             "porta permutavel"),
            ("Relay", "Python", "outbox -> broker"),
            ("Cripto", "ChaCha20-Poly1305, Ed25519, SHA-256",
             "E2E nos 3 pontos de I/O; assinaturas; integridade"),
            ("Plataforma", "Docker Compose, Alembic, pytest",
             "malha de 2 nos; migracoes; suite smoke/e2e"),
        ],
        (26, 62, 102), fs=8)
    r.p(
        "Regra que atravessa tudo: o binario do documento NUNCA "
        "entra em banco, envelope, broker ou resposta de API — "
        "so metadados + SHA-256 circulam entre os nos.")

    # ============ servicos do no ============
    r.add_page()
    r.h1("2. Os servicos do no — um a um")

    r.tec(
        "FastAPI (a API)",
        "a superficie publica do no — todas as operacoes de "
        "tramitacao passam por ela.",
        "framework web Python assincrono. Recebe criacao de "
        "tramitacao, upload multipart, recebimento de envelope, "
        "acks e o endpoint de verificacao da cadeia.",
        "mesma linguagem do worker e do motor — uma base so de "
        "codigo; async aguenta I/O concorrente sem complexidade.",
        "app/main.py, app/service.py, app/deps.py.",
        "e a porta do no: tudo que a instituicao ou outra "
        "instituicao pede ao sistema entra pela API — e ela "
        "aplica as regras antes de tocar storage ou banco.")

    r.tec(
        "PostgreSQL (o banco)",
        "guarda so metadados e evidencias — nunca o documento.",
        "registros de tramitacao, trilha de auditoria (hash-"
        "chain), outbox de eventos, replay_nonces e o cofre de "
        "pseudonimos.",
        "transacoes: o upload grava objeto + trilha + outbox numa "
        "UNICA transacao — nao existe 'arquivou mas nao "
        "registrou'. E o trigger append-only barra UPDATE/DELETE "
        "na trilha no nivel do banco.",
        "alembic/versions/ (migracoes — 0007 = append-only); "
        "app/repository.py.",
        "o banco e o livro-razao: metadados, hashes e a corrente "
        "de auditoria — e por desenho nao existe sequer coluna "
        "para guardar bytes de documento.")

    r.tec(
        "RabbitMQ (a fila)",
        "a esteira assincrona — desacopla a API do processamento "
        "pesado de anonimizacao.",
        "broker de mensagens so em TLS (porta 5671). Fila quorum "
        "com DLQ: evento de 'documento arquivado' dispara o "
        "worker sem a chamada de upload ficar esperando.",
        "anonimizacao pode demorar — a API responde na hora e o "
        "processamento continua em segundo plano. Fila quorum "
        "sobrevive a restart; DLQ guarda o que falhar de vez.",
        "deploy/malha/rabbitmq.conf (TLS-only); app/worker.py "
        "(consumidor); app/relay.py (produtor via outbox).",
        "e a correia interna do no: o evento sai da API, viaja "
        "cifrado pela fila e acorda o worker — tudo dentro do "
        "dominio da instituicao.")

    r.tec(
        "MinIO (o storage)",
        "o cofre de objetos da instituicao — guarda o documento "
        "e depois o anonimizado.",
        "object storage compativel com S3, servido em HTTPS. "
        "Dois buckets por no: <org>-docs e <org>-docs-"
        "anonimizados.",
        "soberania fisica: cada instituicao e dona do proprio "
        "storage. E em repouso so existe ciphertext — o objeto "
        "cru comeca com a magia E2 (0xE2 0x02), legivel so "
        "dentro do processo.",
        "app/storage.py (ArmazenamentoCifrado); prova no "
        "terminal: 'objeto cru no MinIO' na demo.",
        "e o cofre da instituicao: quem olha o MinIO por dentro "
        "ve so ciphertext — o documento em claro nunca repousa "
        "em lugar nenhum.")

    r.tec(
        "nginx + mTLS (a borda)",
        "a fronteira institucional — quem bate na porta precisa "
        "de certificado de cliente valido.",
        "proxy reverso que TERMINA o mTLS: verifica o "
        "certificado da instituicao cliente e injeta "
        "X-Cliente-Orgao. Aplica rate limit e HSTS.",
        "identidade institucional por criptografia de "
        "certificado — substituiu JWT (reprovado: token em "
        "browser e vulneravel a XSS). mTLS identifica o ORGAO, "
        "nao um usuario.",
        "deploy/malha: nginx.conf + certs gerados por "
        "scripts/gerar_certs_mtls.py.",
        "e a portaria do predio: so entra quem apresenta "
        "credencial de instituicao reconhecida — e a borda ja "
        "carimba de que orgao e a requisicao.")

    r.tec(
        "Vault (os segredos)",
        "a custodia das chaves — a chave E2E mora la, nao no "
        "codigo nem em arquivo.",
        "servidor de segredos (KV v2): a API e o worker leem a "
        "chave E2E via AppRole — login com role_id + secret_id, "
        "token curto de 60s renovavel. Suporta rotacao "
        "(atual + anterior_N) e revogacao.",
        "separar a chave do codigo: da para girar a chave sem "
        "trocar deploy, revogar sem recompilar, e auditar quem "
        "leu o que. E2E_FONTE=env|vault — env so para dev.",
        "app/cofre.py; deploy/malha/vault-init.sh (policy "
        "e2e-leitura + role no-a).",
        "e o cofre de chaves do predio: a chave que decifra os "
        "envelopes nao fica escrita em lugar nenhum do codigo — "
        "cada servico pede emprestada ao Vault e ela tem prazo "
        "de validade.")

    r.tec(
        "Worker + porta MotorIA",
        "o anonimizador — roda DENTRO do no, a documento nunca "
        "sai para ser tratado.",
        "processo que consome a fila, baixa a copia cifrada, "
        "aplica o motor e publica no bucket anonimizados — "
        "depois do gate de PII residual (fail-closed: sobrou "
        "PII, nao grava).",
        "MotorIA e uma PORTA permutavel: anonimizar(bytes)->"
        "bytes. Trocar o motor (regex, modelo medido, NER "
        "discriminativo futuro) nao toca worker, fila ou "
        "buckets.",
        "app/worker.py; implementacoes: DemoMotorIA (demo), "
        "app/motor_ollama.py (POC medida).",
        "e o funcionario que trata o documento no arquivo do "
        "proprio orgao: o motor e peca trocavel — a esteira ao "
        "redor nao muda.")

    r.tec(
        "Relay (o outbox)",
        "a ponte transacional entre banco e fila.",
        "varre a tabela outbox e publica no RabbitMQ — o evento "
        "e gravado junto com a operacao na mesma transacao e o "
        "relay garante a entrega ao broker (com retry).",
        "resolve o problema classico: sem outbox, 'commitou no "
        "banco mas caiu antes de avisar a fila' perderia o "
        "evento. Com outbox, gravar e anunciar sao atomicos.",
        "app/relay.py; migracao 0005 (outbox retry).",
        "e o carteiro interno: o que o banco registra, o relay "
        "garante que chega a fila — nenhum evento se perde "
        "entre a gravacao e o processamento.")

    # ============ criptografia ============
    r.add_page()
    r.h1("3. As primitivas de seguranca")
    r.p(
        "Nao sao 'servicos' mas sao o que a plateia pergunta "
        "quando ve 'E2E', 'assinatura' e 'hash' na tela.")

    r.tec(
        "ChaCha20-Poly1305 (o E2E)",
        "a blindagem ponta a ponta — tudo que atravessa ou "
        "repousa vai dentro de quadros AEAD.",
        "cifra autenticada: cada quadro e "
        "0xE2|0x02|nonce|len|ts_ms|ct — o timestamp entra no "
        "AAD (adultera-lo quebra o selo). Cobre os 3 pontos de "
        "I/O: request/response HTTP, mensagens do broker e "
        "objetos no storage.",
        "AEAD = confidencialidade + integridade no mesmo selo; "
        "ChaCha20 e rapido em software puro (sem AES-NI). O "
        "formato versionado permite evoluir o quadro.",
        "app/crypto_e2e.py (selar/abrir), "
        "app/middleware_e2e.py (HTTP), PublicadorRabbitMQ "
        "(broker), ArmazenamentoCifrado (storage).",
        "e o envelope lacrado de ponta a ponta: mesmo que "
        "alguem capture o pacote no fio ou abra o MinIO, ve so "
        "ciphertext — e qualquer alteracao estoura o lacre.")

    r.tec(
        "Ed25519 (as assinaturas)",
        "a prova de autoria — envelopes e acks sao assinados "
        "pela chave da instituicao.",
        "assinatura digital de curva eliptica: A assina TODOS os "
        "campos do envelope; B verifica contra a chave publica "
        "de A antes de persistir. O ack e assinado por B e "
        "verificado por A.",
        "deterministica, rapida, chaves curtas — e fail-closed "
        "por construcao: uma virgula adulterada invalida tudo.",
        "app/assinatura.py; chaves ORG_SIGN_*/ORGAO_PUBKEYS_* "
        "no .env da malha (gitignored).",
        "e o selo de cera da instituicao: quem recebe sabe DE "
        "QUEM veio e que ninguem mexeu — por isso o envelope "
        "adulterado da demo e jogado fora.")

    r.tec(
        "SHA-256 (integridade + cadeia)",
        "a impressao digital do documento e o elo da corrente "
        "de auditoria.",
        "hash criptografico: declarado no criar, conferido no "
        "upload, revalidado no download e recomputado por B no "
        "proprio storage antes de assinar. Na trilha, cada elo "
        "e sha256(elo anterior | evento).",
        "deterministico e publico — qualquer ponta recomputa e "
        "confere sem confiar na outra. Encadear transforma "
        "uma lista de eventos em uma corrente: mexer num elo "
        "quebra todos os seguintes.",
        "app/repository.py (encadear_uma_vez); GET /verificar "
        "rejoga do GENESIS.",
        "e a impressao digital: nao prova que voce tem o "
        "documento certo porque alguem disse — prova porque os "
        "64 hexadecimais batem, e cada um pode conferir sozinho.")

    r.tec(
        "replay_nonces (anti-replay)",
        "o carimbo unico — um pacote cifrado so vale uma vez.",
        "tabela no Postgres onde cada nonce de quadro E2E e "
        "reivindicado atomicamente (PK) antes de processar; "
        "janela de frescura E2E_JANELA_MS = 300s.",
        "capturar e reentregar o MESMO pacote nao pode repetir "
        "a operacao — o claim atomico garante isso ate com "
        "replicas. AMQP so usa frescura (redelivery legitima "
        "repete o envelope).",
        "middleware_e2e (claim); migracao de replay_nonces; "
        "passo 'replay' da demo prova 200 -> 400.",
        "e o carimbo de correio: o pacote chega, recebe o "
        "carimbo unico — a fotocopia dele depois e rejeitada "
        "porque esse carimbo ja foi gasto.")

    # ============ plataforma ============
    r.add_page()
    r.h1("4. Plataforma e motor — o que sustenta")
    r.tec(
        "Docker Compose (a malha)",
        "a bancada que prova tudo: 2 nos reais, ~16 conteineres.",
        "cada no = api + postgres + rabbitmq + minio + worker + "
        "relay + nginx; mais vault e o conteiner peer que dirige "
        "a demo. Redes separadas: borda (mTLS) e interna.",
        "reproduzivel: docker compose up e a arquitetura inteira "
        "existe — com TLS real em todos os links internos "
        "(postgres ssl, rabbitmq 5671, minio https, vault https).",
        "deploy/malha/compose.malha.yaml (+ compose.demo.yaml "
        "para o motor da demo).",
        "e a maquete que funciona de verdade: nao e desenho da "
        "arquitetura, e a arquitetura executando — cada orgao "
        "real rodaria essa mesma composicao na sua infra.")
    r.tec(
        "Alembic (migracoes)",
        "a evolucao versionada do banco.",
        "migracoes incrementais: 0005 = outbox retry, 0007 = "
        "trigger append-only + replay_nonces.",
        "o schema nao e arte manual: sobe junto com a aplicacao "
        "(alembic upgrade head no boot da api).",
        "alembic/versions/.",
        "e o diario de obras do banco: cada mudanca de estrutura "
        "e uma migracao versionada e aplicada na subida.")
    r.tec(
        "Motor de anonimizacao — a ressalva honesta",
        "a peca que remove PII — trocavel por desenho.",
        "na DEMO roda DemoMotorIA (regex LGPD deterministica) — "
        "a anonimizacao fica VISIVEL e repetivel ao vivo. O "
        "candidato medido e a cascata regex+Ollama qwen2.5: NER "
        "exact F1 0,953, reidentificacao 0/360 — no corpus "
        "SINTETICO.",
        "separar 'provar a esteira' de 'medir o modelo': a demo "
        "precisa de determinismo; a qualidade e medida a parte "
        "em docs/metricas.md. A cascata e desvio documentado da "
        "ADR-0011 (zero IA generativa) — producao exige NER "
        "discriminativo treinado no mesmo gate.",
        "app/motor_ollama.py; docs/metricas.md; ADR-0011.",
        "na demonstracao o motor e o didatico — prova que a "
        "esteira inteira funciona. A nota do modelo real esta "
        "medida no relatorio de metricas e ainda nao esta "
        "plugada na porta.")

    # ============ faq ============
    r.add_page()
    r.h1("5. Cola de perguntas — 'o que o X faz?'")
    r.p("Uma linha por tecnologia, na ordem em que costumam "
        "perguntar:")
    r.ln(2)
    r.tab(
        ("Pergunta", "Resposta em uma frase"),
        [
            ("o que o Vault faz?",
             "guarda a chave E2E fora do codigo — os servicos "
             "pedem emprestada com token de 60s; da pra girar e "
             "revogar sem deploy"),
            ("o que o RabbitMQ faz?",
             "a fila interna do no — desacopla a API da "
             "anonimizacao pesada; quorum + DLQ"),
            ("o que o MinIO faz?",
             "o cofre de objetos da instituicao — guarda o "
             "documento e o anonimizado, sempre so ciphertext"),
            ("o que o nginx faz?",
             "a borda mTLS — exige certificado de instituicao e "
             "carimba de que orgao e a requisicao"),
            ("o que o Postgres faz?",
             "o livro-razao — metadados, trilha hash-chain e "
             "nonces; sem coluna para bytes de documento"),
            ("o que o FastAPI faz?",
             "a porta do no — recebe tudo e aplica as regras "
             "antes de tocar banco ou storage"),
            ("o que o worker faz?",
             "o anonimizador interno — consome a fila e publica "
             "o objeto tratado, com gate de PII residual"),
            ("o que o relay faz?",
             "o carteiro outbox — o que o banco grava, ele "
             "garante que chega a fila"),
            ("o que e o 'E2E'?",
             "quadros ChaCha20-Poly1305 em HTTP, fila e storage "
             "— lacrado + cifrado de ponta a ponta"),
            ("o que e o Ed25519?",
             "a assinatura da instituicao em envelopes e acks "
             "— uma virgula adulterada invalida tudo"),
            ("o que e a hash-chain?",
             "cada evento vira sha256(elo anterior | evento) — "
             "mexer num elo quebra todos os seguintes"),
            ("o que sao os nonces?",
             "o carimbo unico por pacote — a fotocopia reenviada "
             "e recusada porque o carimbo ja foi gasto"),
        ],
        (40, 150), fs=8)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    r.output(str(OUT))
    print(f"relatorio gerado: {OUT}")


if __name__ == "__main__":
    main()
