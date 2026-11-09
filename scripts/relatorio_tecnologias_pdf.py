"""Relatorio de tecnologias — o papel de cada uma na arquitetura.

Gera docs/relatorio_tecnologias.pdf: para cada tecnologia da
stack, o que é, o papel que exerce na arquitetura do nó soberano,
por que foi escolhida, onde encontrar no código — e uma RESPOSTA
EM UMA FRASE para quando perguntarem na apresentação.

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
            "PIDE/FAPESPA | Relatório de Tecnologias da "
            "Arquitetura"), align="R")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(110)
        self.cell(0, 6, _lat(f"página {self.page_no()}"), align="C")

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
        self.p(f"O que é: {oq}")
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
    r.set_text_color(22, 48, 94)
    r.multi_cell(0, 11, _lat(
        "Relatório de Tecnologias\n"
        "Nó Soberano - PIDE / FAPESPA"), align="C")
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
        "Stack real da malha de dois nós (deploy/malha/) —\n"
        "a mesma imagem em cada instituição; muda o papel,\n"
        "não a stack."), align="C")

    # ============ visão geral ============
    r.add_page()
    r.h1("1. Visão geral da stack")
    r.p(
        "Cada nó soberano é a MESMA composição de serviços. O que "
        "muda entre instituições é o papel na tramitação (origem "
        "ou destino), nunca a stack. Esta é a arquitetura-alvo: "
        "cada órgão opera esta composição na própria "
        "infraestrutura.")
    r.ln(3)
    r.tab(
        ("Camada", "Tecnologia", "Função no nó"),
        [
            ("API", "FastAPI (Python)", "tramitações, upload, "
             "recebimentos, acks, verificação"),
            ("Banco", "PostgreSQL", "metadados, trilha "
             "hash-chain, outbox, replay_nonces — SEM bytes"),
            ("Fila", "RabbitMQ (TLS)", "esteira assíncrona de "
             "anonimização — quorum + DLQ"),
            ("Storage", "MinIO (HTTPS)", "objetos — sempre "
             "ciphertext E2E em repouso"),
            ("Borda", "nginx + mTLS", "identidade institucional "
             "por certificado de cliente"),
            ("Segredos", "Vault", "custódia da chave E2E — "
             "AppRole, rotação, revogação"),
            ("Worker", "Python + MotorIA", "anonimização via "
             "porta permutável"),
            ("Relay", "Python", "outbox -> broker"),
            ("Cripto", "ChaCha20-Poly1305, Ed25519, SHA-256",
             "E2E nos 3 pontos de I/O; assinaturas; integridade"),
            ("Plataforma", "Docker Compose, Alembic, pytest",
             "malha de 2 nós; migrações; suíte smoke/e2e"),
        ],
        (26, 62, 102), fs=8)
    r.p(
        "Regra que atravessa tudo: o binário do documento NUNCA "
        "entra em banco, envelope, broker ou resposta de API — "
        "só metadados + SHA-256 circulam entre os nós.")

    # ============ serviços do nó ============
    r.add_page()
    r.h1("2. Os serviços do nó — um a um")

    r.tec(
        "FastAPI (a API)",
        "a superfície pública do nó — todas as operações de "
        "tramitação passam por ela.",
        "framework web Python assíncrono. Recebe criação de "
        "tramitação, upload multipart, recebimento de envelope, "
        "acks e o endpoint de verificação da cadeia.",
        "mesma linguagem do worker e do motor — uma base só de "
        "código; async aguenta I/O concorrente sem complexidade.",
        "app/main.py, app/service.py, app/deps.py.",
        "é a porta do nó: tudo que a instituição ou outra "
        "instituição pede ao sistema entra pela API — e ela "
        "aplica as regras antes de tocar storage ou banco.")

    r.tec(
        "PostgreSQL (o banco)",
        "guarda só metadados e evidências — nunca o documento.",
        "registros de tramitação, trilha de auditoria (hash-"
        "chain), outbox de eventos, replay_nonces e o cofre de "
        "pseudônimos.",
        "transações: o upload grava objeto + trilha + outbox numa "
        "ÚNICA transação — não existe 'arquivou mas não "
        "registrou'. E o gatilho append-only barra UPDATE/DELETE "
        "na trilha no nível do banco.",
        "alembic/versions/ (migrações — 0007 = append-only); "
        "app/repository.py.",
        "o banco é o livro-razão: metadados, hashes e a corrente "
        "de auditoria — e por desenho não existe sequer coluna "
        "para guardar bytes de documento.")

    r.tec(
        "RabbitMQ (a fila)",
        "a esteira assíncrona — desacopla a API do processamento "
        "pesado de anonimização.",
        "broker de mensagens só em TLS (porta 5671). Fila quorum "
        "com DLQ: evento de 'documento arquivado' dispara o "
        "worker sem a chamada de upload ficar esperando.",
        "anonimização pode demorar — a API responde na hora e o "
        "processamento continua em segundo plano. Fila quorum "
        "sobrevive a restart; DLQ guarda o que falhar de vez.",
        "deploy/malha/rabbitmq.conf (TLS-only); app/worker.py "
        "(consumidor); app/relay.py (produtor via outbox).",
        "é a correia interna do nó: o evento sai da API, viaja "
        "cifrado pela fila e acorda o worker — tudo dentro do "
        "domínio da instituição.")

    r.tec(
        "MinIO (o storage)",
        "o cofre de objetos da instituição — guarda o documento "
        "e depois o anonimizado.",
        "object storage compatível com S3, servido em HTTPS. "
        "Dois buckets por nó: <org>-docs e <org>-docs-"
        "anonimizados.",
        "soberania física: cada instituição é dona do próprio "
        "storage. E em repouso só existe ciphertext — o objeto "
        "cru começa com a magia E2 (0xE2 0x02), legível só "
        "dentro do processo.",
        "app/storage.py (ArmazenamentoCifrado); prova no "
        "terminal: 'objeto cru no MinIO' na demo.",
        "é o cofre da instituição: quem olha o MinIO por dentro "
        "vê só ciphertext — o documento em claro nunca repousa "
        "em lugar nenhum.")

    r.tec(
        "nginx + mTLS (a borda)",
        "a fronteira institucional — quem bate na porta precisa "
        "de certificado de cliente válido.",
        "proxy reverso que TERMINA o mTLS: verifica o "
        "certificado da instituição cliente e injeta "
        "X-Cliente-Orgao. Aplica rate limit e HSTS.",
        "identidade institucional por criptografia de "
        "certificado — substituiu JWT (reprovado: token em "
        "browser é vulnerável a XSS). mTLS identifica o ÓRGÃO, "
        "não um usuário.",
        "deploy/malha: nginx.conf + certs gerados por "
        "scripts/gerar_certs_mtls.py.",
        "é a portaria do prédio: só entra quem apresenta "
        "credencial de instituição reconhecida — e a borda já "
        "carimba de que órgão é a requisição.")

    r.tec(
        "Vault (os segredos)",
        "a custódia das chaves — a chave E2E mora lá, não no "
        "código nem em arquivo.",
        "servidor de segredos (KV v2): a API e o worker leem a "
        "chave E2E via AppRole — login com role_id + secret_id, "
        "token curto de 60s renovável. Suporta rotação "
        "(atual + anterior_N) e revogação.",
        "separar a chave do código: dá para girar a chave sem "
        "trocar deploy, revogar sem recompilar, e auditar quem "
        "leu o que. E2E_FONTE=env|vault — env só para dev.",
        "app/cofre.py; deploy/malha/vault-init.sh (policy "
        "e2e-leitura + role no-a).",
        "é o cofre de chaves do prédio: a chave que decifra os "
        "envelopes não fica escrita em lugar nenhum do código — "
        "cada serviço pede emprestada ao Vault e ela tem prazo "
        "de validade.")

    r.tec(
        "Worker + porta MotorIA",
        "o anonimizador — roda DENTRO do nó, o documento nunca "
        "sai para ser tratado.",
        "processo que consome a fila, baixa a cópia cifrada, "
        "aplica o motor e publica no bucket anonimizados — "
        "depois do gate de PII residual (fail-closed: sobrou "
        "PII, não grava).",
        "MotorIA é uma PORTA permutável: anonimizar(bytes)->"
        "bytes. Trocar o motor (regex, modelo medido, NER "
        "discriminativo futuro) não toca worker, fila ou "
        "buckets.",
        "app/worker.py; implementações: DemoMotorIA (demo), "
        "app/motor_ollama.py (POC medida).",
        "é o funcionário que trata o documento no arquivo do "
        "próprio órgão: o motor é peça trocável — a esteira ao "
        "redor não muda.")

    r.tec(
        "Relay (o outbox)",
        "a ponte transacional entre banco e fila.",
        "varre a tabela outbox e publica no RabbitMQ — o evento "
        "é gravado junto com a operação na mesma transação e o "
        "relay garante a entrega ao broker (com retry).",
        "resolve o problema clássico: sem outbox, 'commitou no "
        "banco mas caiu antes de avisar a fila' perderia o "
        "evento. Com outbox, gravar e anunciar são atômicos.",
        "app/relay.py; migração 0005 (outbox retry).",
        "é o carteiro interno: o que o banco registra, o relay "
        "garante que chega à fila — nenhum evento se perde "
        "entre a gravação e o processamento.")

    # ============ criptografia ============
    r.add_page()
    r.h1("3. As primitivas de segurança")
    r.p(
        "Não são 'serviços' mas são o que a plateia pergunta "
        "quando vê 'E2E', 'assinatura' e 'hash' na tela.")

    r.tec(
        "ChaCha20-Poly1305 (o E2E)",
        "a blindagem ponta a ponta — tudo que atravessa ou "
        "repousa vai dentro de quadros AEAD.",
        "cifra autenticada: cada quadro é "
        "0xE2|0x02|nonce|len|ts_ms|ct — o timestamp entra no "
        "AAD (adulterá-lo quebra o selo). Cobre os 3 pontos de "
        "I/O: request/response HTTP, mensagens do broker e "
        "objetos no storage.",
        "AEAD = confidencialidade + integridade no mesmo selo; "
        "ChaCha20 é rápido em software puro (sem AES-NI). O "
        "formato versionado permite evoluir o quadro.",
        "app/crypto_e2e.py (selar/abrir), "
        "app/middleware_e2e.py (HTTP), PublicadorRabbitMQ "
        "(broker), ArmazenamentoCifrado (storage).",
        "é o envelope lacrado de ponta a ponta: mesmo que "
        "alguém capture o pacote no fio ou abra o MinIO, vê só "
        "ciphertext — e qualquer alteração estoura o lacre.")

    r.tec(
        "Ed25519 (as assinaturas)",
        "a prova de autoria — envelopes e acks são assinados "
        "pela chave da instituição.",
        "assinatura digital de curva elíptica: A assina TODOS os "
        "campos do envelope; B verifica contra a chave pública "
        "de A antes de persistir. O ack é assinado por B e "
        "verificado por A.",
        "determinística, rápida, chaves curtas — e fail-closed "
        "por construção: uma vírgula adulterada invalida tudo.",
        "app/assinatura.py; chaves ORG_SIGN_*/ORGAO_PUBKEYS_* "
        "no .env da malha (gitignored).",
        "é o selo de cera da instituição: quem recebe sabe DE "
        "QUEM veio e que ninguém mexeu — por isso o envelope "
        "adulterado da demo é jogado fora.")

    r.tec(
        "SHA-256 (integridade + cadeia)",
        "a impressão digital do documento e o elo da corrente "
        "de auditoria.",
        "hash criptográfico: declarado no criar, conferido no "
        "upload, revalidado no download e recomputado por B no "
        "próprio storage antes de assinar. Na trilha, cada elo "
        "é sha256(elo anterior | evento).",
        "determinístico e público — qualquer ponta recomputa e "
        "confere sem confiar na outra. Encadear transforma "
        "uma lista de eventos em uma corrente: mexer num elo "
        "quebra todos os seguintes.",
        "app/repository.py (encadear_uma_vez); GET /verificar "
        "rejoga do GENESIS.",
        "é a impressão digital: não prova que você tem o "
        "documento certo porque alguém disse — prova porque os "
        "64 hexadecimais batem, e cada um pode conferir sozinho.")

    r.tec(
        "replay_nonces (anti-replay)",
        "o carimbo único — um pacote cifrado só vale uma vez.",
        "tabela no Postgres onde cada nonce de quadro E2E é "
        "reivindicado atomicamente (PK) antes de processar; "
        "janela de frescura E2E_JANELA_MS = 300s.",
        "capturar e reentregar o MESMO pacote não pode repetir "
        "a operação — o claim atômico garante isso até com "
        "réplicas. AMQP só usa frescura (redelivery legítima "
        "repete o envelope).",
        "middleware_e2e (claim); migração de replay_nonces; "
        "passo 'replay' da demo prova 200 -> 400.",
        "é o carimbo de correio: o pacote chega, recebe o "
        "carimbo único — a fotocópia dele depois é rejeitada "
        "porque esse carimbo já foi gasto.")

    # ============ plataforma ============
    r.add_page()
    r.h1("4. Plataforma e motor — o que sustenta")
    r.tec(
        "Docker Compose (a malha)",
        "a bancada que prova tudo: 2 nós reais, ~16 contêineres.",
        "cada nó = api + postgres + rabbitmq + minio + worker + "
        "relay + nginx; mais vault e o contêiner peer que dirige "
        "a demo. Redes separadas: borda (mTLS) e interna.",
        "reproduzível: docker compose up e a arquitetura inteira "
        "existe — com TLS real em todos os links internos "
        "(postgres ssl, rabbitmq 5671, minio https, vault https).",
        "deploy/malha/compose.malha.yaml (+ compose.demo.yaml "
        "para o motor da demo).",
        "é a maquete que funciona de verdade: não é desenho da "
        "arquitetura, é a arquitetura executando — cada órgão "
        "real rodaria essa mesma composição na sua infra.")
    r.tec(
        "Alembic (migrações)",
        "a evolução versionada do banco.",
        "migrações incrementais: 0005 = outbox retry, 0007 = "
        "gatilho append-only + replay_nonces.",
        "o schema não é arte manual: sobe junto com a aplicação "
        "(alembic upgrade head no boot da api).",
        "alembic/versions/.",
        "é o diário de obras do banco: cada mudança de estrutura "
        "é uma migração versionada e aplicada na subida.")
    r.tec(
        "Motor de anonimização — a ressalva honesta",
        "a peça que remove PII — trocável por desenho.",
        "na DEMO roda DemoMotorIA (regex LGPD determinística) — "
        "a anonimização fica VISÍVEL e repetível ao vivo. O "
        "candidato medido é a cascata regex+Ollama qwen2.5: NER "
        "exact F1 0,953, reidentificação 0/360 — no corpus "
        "SINTÉTICO.",
        "separar 'provar a esteira' de 'medir o modelo': a demo "
        "precisa de determinismo; a qualidade é medida à parte "
        "em docs/metricas.md. A cascata é desvio documentado da "
        "ADR-0011 (zero IA generativa) — produção exige NER "
        "discriminativo treinado no mesmo gate.",
        "app/motor_ollama.py; docs/metricas.md; ADR-0011.",
        "na demonstração o motor é o didático — prova que a "
        "esteira inteira funciona. A nota do modelo real está "
        "medida no relatório de métricas e ainda não está "
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
             "guarda a chave E2E fora do código — os serviços "
             "pedem emprestada com token de 60s; dá pra girar e "
             "revogar sem deploy"),
            ("o que o RabbitMQ faz?",
             "a fila interna do nó — desacopla a API da "
             "anonimização pesada; quorum + DLQ"),
            ("o que o MinIO faz?",
             "o cofre de objetos da instituição — guarda o "
             "documento e o anonimizado, sempre só ciphertext"),
            ("o que o nginx faz?",
             "a borda mTLS — exige certificado de instituição e "
             "carimba de que órgão é a requisição"),
            ("o que o Postgres faz?",
             "o livro-razão — metadados, trilha hash-chain e "
             "nonces; sem coluna para bytes de documento"),
            ("o que o FastAPI faz?",
             "a porta do nó — recebe tudo e aplica as regras "
             "antes de tocar banco ou storage"),
            ("o que o worker faz?",
             "o anonimizador interno — consome a fila e publica "
             "o objeto tratado, com gate de PII residual"),
            ("o que o relay faz?",
             "o carteiro outbox — o que o banco grava, ele "
             "garante que chega à fila"),
            ("o que é o 'E2E'?",
             "quadros ChaCha20-Poly1305 em HTTP, fila e storage "
             "— lacrado + cifrado de ponta a ponta"),
            ("o que é o Ed25519?",
             "a assinatura da instituição em envelopes e acks "
             "— uma vírgula adulterada invalida tudo"),
            ("o que é a hash-chain?",
             "cada evento vira sha256(elo anterior | evento) — "
             "mexer num elo quebra todos os seguintes"),
            ("o que são os nonces?",
             "o carimbo único por pacote — a fotocópia reenviada "
             "é recusada porque o carimbo já foi gasto"),
        ],
        (40, 150), fs=8)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    r.output(str(OUT))
    print(f"relatório gerado: {OUT}")


if __name__ == "__main__":
    main()
