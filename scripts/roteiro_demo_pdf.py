"""Roteiro de fala da apresentação — visualizador web + demo real.

Gera docs/roteiro_apresentacao_demo.pdf: um guia de palco para
apresentar a jornada do documento com a página
(http://localhost:8080) no projetor e demo_coordenador.py no
terminal do apresentador. Cada seção mapeia O QUE APARECE na
tela para O QUE DIZER — incluindo todos os cards, chips,
banner, painel de provas e o rodapé honesto.

Uso: python scripts/roteiro_demo_pdf.py
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "docs" / "roteiro_apresentacao_demo.pdf"


def _lat(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


class Rel(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110)
        self.cell(0, 5, _lat(
            "PIDE/FAPESPA | Roteiro de apresentação - demo ao vivo"),
            align="R")
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

    def fala(self, t, indent=6):
        """Fala sugerida — em itálico, como citação de palco."""
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(60, 60, 90)
        self.set_x(10 + indent)
        self.multi_cell(0, 5, _lat('" ' + t + '"'))
        self.ln(1)

    def bullet(self, t, indent=6):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(30)
        self.set_x(10 + indent)
        self.multi_cell(0, 5, _lat("- " + t))

    def tela(self, t, indent=6):
        """O que aparece na tela — texto em cor de destaque."""
        self.set_font("Helvetica", "B", 9.5)
        self.set_text_color(0, 100, 60)
        self.set_x(10 + indent)
        self.multi_cell(0, 5, _lat("[TELA] " + t))
        self.ln(1)


def main():
    r = Rel()
    r.set_auto_page_break(True, margin=18)
    r.add_page()

    # ============ capa ============
    r.ln(45)
    r.set_font("Helvetica", "B", 21)
    r.set_text_color(22, 48, 94)
    r.multi_cell(0, 11, _lat(
        "Roteiro de Apresentação\n"
        "FAPESPA / Anonimizar - Jornada do Documento"), align="C")
    r.ln(8)
    r.set_font("Helvetica", "", 11.5)
    r.set_text_color(74, 85, 104)
    r.multi_cell(0, 7, _lat(
        "Guia de palco para a demonstração ao vivo:\n"
        "página no projetor + execução real no terminal\n"
        "dois nós soberanos - não é simulação"), align="C")
    r.ln(20)
    r.set_font("Helvetica", "", 10)
    r.multi_cell(0, 6, _lat(
        "Cada seção diz: [TELA] o que aparece -> o que dizer.\n"
        "As falas são sugestões - ajuste ao seu jeito de falar."),
        align="C")

    # ============ 1. preparação ============
    r.add_page()
    r.h1("1. Antes de começar (5 min de preparo)")
    r.p("Três comandos, nesta ordem:")
    r.bullet("docker compose -f deploy/malha/compose.malha.yaml up -d")
    r.p("     -> espera 30-60s (banco migra e os healthchecks "
        "sobem)", 6)
    r.bullet("python scripts/demo_web.py --limpar   (terminal 1 "
             "- deixa aberto; abre a página com a tela zerada)")
    r.bullet("python scripts/demo_coordenador.py --pausar   "
             "(terminal 2 - o seu, do apresentador)")
    r.ln(4)
    r.h2("Tela limpa antes de apresentar")
    r.p(
        "O estado da execução sobrevive no /run do peer entre "
        "runs - por isso a página abre mostrando o resultado "
        "anterior. O flag --limpar do demo_web.py já zera ao "
        "subir (equivale a 'docker exec isaci-malha-peer-1 rm -f "
        "/run/demo_state.json'). Entre execuções na MESMA sessão "
        "não precisa fazer nada: a página se reseta sozinha "
        "quando um novo caso começa, e as trilhas dos cards "
        "sempre mostram só os eventos do caso atual.")
    r.ln(4)
    r.h2("Como funciona o palco")
    r.p(
        "O projetor mostra a PÁGINA (localhost:8080): dois cards "
        "de nó, a figura do documento viajando, chips de "
        "travessia, os dois textos do documento e o painel de "
        "provas. O seu terminal roda a execução de verdade - "
        "cada Enter executa um ato; a página acompanha ao vivo "
        "(poll de ~1s).")
    r.p(
        "Com --pausar, o ritmo já sai espaçado (2.5s entre "
        "etapas dentro de cada ato). Se quiser mais lento: "
        "--pausar --ritmo 4.")
    r.p(
        "Frase de abertura sugerida, apontando para o subtítulo:")
    r.fala(
        "Isto não é um vídeo nem um desenho do que vai ser - "
        "está rodando de verdade agora, em dois nós reais. Cada "
        "coisa que aparecer na tela é uma chamada real que "
        "aconteceu no sistema.")

    # ============ 2. mapa da tela ============
    r.add_page()
    r.h1("2. O mapa da tela (o que cada elemento é)")
    r.p(
        "Antes do primeiro Enter, passe 1-2 minutos apresentando "
        "os elementos fixos da página. Cada um tem uma frase "
        "pronta:")

    r.h2("Título e subtítulo")
    r.tela("'FAPESPA · Anonimizar - jornada real de um documento'"
           " + 'isto está rodando de verdade agora, não é "
           "simulação'")
    r.fala(
        "Vamos acompanhar a vida de um documento judicial que "
        "sai de um órgão, chega a outro e é anonimizado no "
        "destino - tudo acontecendo agora, não em slides.")

    r.h2("Card do Nó A - tjpa (esquerda)")
    r.tela("'instituição de origem · storage próprio' | API + "
           "Postgres + RabbitMQ (TLS) | MinIO (HTTPS) + borda "
           "mTLS | linha de storage + trilha-mini (cresce ao "
           "vivo: cada evento aparece quando é gravado)")
    r.fala(
        "Este é o nó do órgão de origem. Repare: cada instituição "
        "roda a MESMA pilha soberana - API, banco, fila e storage "
        "próprios, dentro do próprio domínio. Nada é compartilhado "
        "de graça: cada um é dono dos seus dados e dos seus "
        "objetos.")

    r.h2("Corredor (centro) - o canal entre as instituições")
    r.tela("o fio horizontal, a figura do documento, os chips de "
           "travessia e a tag de canal")
    r.fala(
        "Aqui é a fronteira: a rede entre os dois órgãos. A "
        "figura só anda quando algo REALMENTE atravessa - e cada "
        "travessia vira um chip no histórico ali embaixo. A "
        "etiqueta do canal (mTLS + criptografia ponta a ponta) só "
        "acende enquanto a travessia está acontecendo.")

    r.h2("Card do Nó B - mpfpa (direita)")
    r.tela("'instituição de destino · storage próprio' | mesma "
           "pilha + 'worker de anonimização'")
    r.fala(
        "O nó de destino é idêntico em soberania - e tem uma "
        "peça a mais: o trabalhador de anonimização, que processa "
        "o documento DENTRO de B. O documento nunca precisa "
        "voltar para ser tratado.")

    r.h2("Banner do passo (faixa azul)")
    r.tela("título do passo + detalhe técnico + frase em itálico")
    r.fala(
        "Esta faixa conta o que está acontecendo em três "
        "camadas: o título, o detalhe técnico para quem quer "
        "verificar, e a frase simples - o 'por que isso importa' "
        "para todo mundo.")

    r.h2("Os dois textos do documento")
    r.tela("esquerda: 'documento (com dados pessoais)' com PII "
           "em laranja | direita: 'documento anonimizado (bucket "
           "de B)' com tarjas verdes")
    r.fala(
        "O da esquerda é a petição original com os dados "
        "pessoais destacados - nome, CPF, e-mail, telefone. O da "
        "direita só preenche no final: é o mesmo documento "
        "depois da anonimização em B.")

    r.h2("Painel de provas (8 itens)")
    r.tela("círculos que ACENDEM em verde conforme cada prova é "
           "executada")
    r.fala(
        "Cada promessa da arquitetura vira uma prova na tela - "
        "e elas só acendem quando a prova de fato aconteceu. Se "
        "algo falhar, o círculo não acende: a tela não mente.")

    r.h2("Rodapé (a ressalva honesta)")
    r.tela("'motor de anonimização nesta demo: regex LGPD "
           "determinística ... não é o modelo medido'")
    r.fala(
        "E aqui o compromisso de honestidade: o motor de "
        "anonimização nesta demonstração é didático. A qualidade "
        "do modelo real está medida no relatório - a demo prova "
        "a ESTEIRA inteira funcionando, não a nota do modelo.")

    # ============ 3. roteiro ato a ato ============
    r.add_page()
    r.h1("3. O roteiro - ato a ato")
    r.p(
        "São 6 atos. Cada bloco: o que acontece na tela e a "
        "fala sugerida. O Enter é seu - não tenha pressa.")

    # ---- ATO 1 ----
    r.h2("ATO 1 - Registro e arquivo no nó origem")
    r.tela("figura parada na porta de A; card A acende; storage "
           "de A vira 'tjpa-docs - objeto cifrado'; provas 1 e 2 "
           "acendem; a trilha-mini de A já mostra 'criada:' e "
           "'doc_arquivado:'")
    r.fala(
        "O processo nasce registrando só a capa e a impressão "
        "digital do documento - o conteúdo fica dentro da "
        "instituição. E quando o arquivo sobe, ele é conferido "
        "byte a byte contra a impressão declarada e guardado "
        "trancado no cofre do próprio órgão.")
    r.fala(
        "Repare uma coisa forte: nem o banco de dados guarda o "
        "documento. No terminal está o esquema da tabela - não "
        "existe coluna para bytes. A regra não é disciplina, é "
        "estrutura.")

    # ---- ATO 2 ----
    r.h2("ATO 2 - Trânsito com custódia (o ataque ao vivo)")
    r.tela("chip 'envelope A->B' pipoca; a figura envelope "
           "atravessa; AVISO para no meio e vira selo 'recusado'; "
           "o envelope verdadeiro atravessa; chip 'barrado' em "
           "vermelho")
    r.fala(
        "O que atravessa a fronteira não é o papel - é só um "
        "aviso: 'existe este documento, com esta impressão "
        "digital', assinado pela origem. Zero bytes do documento "
        "viajam aqui.")
    r.fala(
        "Agora o teste de fogo: alguém mexeu no aviso no meio do "
        "caminho. Olha o que acontece - a assinatura não confere "
        "mais e o destino JOGA A CÓPIA FORA. Ela não vira "
        "registro em lugar nenhum - repare que a trilha de B "
        "continua vazia. O selo 'recusado' fica parado "
        "na trilha enquanto o aviso verdadeiro atravessa e vira "
        "registro de verdade.")
    r.p(
        "Ponto de fala extra, se perguntarem: rejeitar só o "
        "falso (sem derrubar o fluxo) é de propósito - se a "
        "defesa parasse tudo, qualquer um travaria a integração "
        "enviando lixo.")

    # ---- ATO 3 ----
    r.h2("ATO 3 - Arquivo soberano no nó destino")
    r.tela("figura documento atravessa A->B; card B acende; "
           "storage de B vira 'mpfpa-docs - objeto cifrado'; a "
           "trilha-mini de B passa a existir ('recebida:', "
           "'doc_arquivado:')")
    r.fala(
        "Recebido o aviso, B vai buscar o documento direto na "
        "fonte - por um canal trancado de ponta a ponta - e "
        "confere a impressão digital de novo. Depois tranca a "
        "própria cópia no próprio cofre.")
    r.fala(
        "E aqui a soberania em ação: a cópia de B fica no storage "
        "DE B, cifrada. No terminal dá para ver o objeto cru no "
        "MinIO: começa com os bytes mágicos do quadro cifrado - "
        "e2 02 - e nenhum texto do documento aparece em claro.")

    # ---- ATO 4 ----
    r.h2("ATO 4 - Fechamento de custódia B -> A")
    r.tela("figura de confirmação volta B->A e pousa na porta "
           "de A; chip 'ack B->A' pipoca; prova 'custódia "
           "assinada' acende")
    r.fala(
        "B não apenas diz 'recebi'. Antes de assinar, ele "
        "recalcula a impressão digital do que está no próprio "
        "cofre - evidência, não declaração. O recibo sai assinado "
        "com a chave de B, volta para A e fecha o ciclo.")
    r.fala(
        "Resultado: custódia de ponta a ponta - A entregou, B "
        "confirmou, e a prova existe nas duas pontas, assinada.")

    # ---- ATO 5 ----
    r.h2("ATO 5 - Anonimização soberana em B")
    r.tela("card B PULSA com 'esteira de B em processamento - "
           "Xs'; a trilha-mini de B cresce ao vivo; o painel da "
           "direita preenche com o texto anonimizado; prova 'PII "
           "removido' acende")
    r.fala(
        "Agora a parte assíncrona: o upload em B disparou a "
        "esteira de anonimização - fila segura, trabalhador, "
        "portão de verificação. O card de B pulsando é o "
        "processamento acontecendo de verdade; a contagem de "
        "segundos é real. E olha a trilha de B: 'doc_anonimizado' "
        "aparece no exato momento em que o trabalhador grava.")
    r.fala(
        "E o resultado, na direita: nome, CPF, e-mail e telefone "
        "viraram tarjas ANONIMIZADO_LGPD no objeto publicado. "
        "O portão de PII residual é fail-closed - se sobrar "
        "algum dado, o objeto nem grava.")
    r.p(
        "Aqui vale a ressalva em voz alta (credibilidade): 'o "
        "motor nesta demo é didático - o resultado medido do "
        "modelo real está no relatório de métricas'.")

    # ---- ATO 6 ----
    r.h2("ATO 6 - Provas finais: auditoria e resistência")
    r.tela("provas 'hash-chain' e 'replay barrado' acendem; o "
           "banner vira verde 'jornada concluída - execução real "
           "verificada'")
    r.fala(
        "Por fim, a auditoria: a corrente de eventos é refeita "
        "do zero nos dois nós e confere elo a elo - mexer numa "
        "linha quebraria tudo depois dela. E no banco, um gatilho "
        "append-only barra qualquer UPDATE ou DELETE - a "
        "integridade não depende de boa vontade.")
    r.fala(
        "E a última prova: copiar um pacote cifrado na rede e "
        "reenviar não funciona - o carimbo único já foi gasto. "
        "A segunda entrega idêntica volta com recusa. Com isso "
        "a jornada fecha - e a tela mostra o encerramento.")

    # ============ 4. tela final ============
    r.add_page()
    r.h1("4. A tela final e as ressalvas")
    r.p(
        "Com a execução concluída, a página mostra o estado "
        "completo: a figura na porta de A (depois do recibo de "
        "B), os 5 chips de travessia, os 8 círculos de prova "
        "acesos, o documento original ao lado do anonimizado e "
        "o banner verde de encerramento.")
    r.fala(
        "Tudo que vocês viram aconteceu agora, nestes dois nós: "
        "o documento nunca saiu dos storages cifrados das "
        "instituições, só metadados e a impressão digital "
        "atravessaram a fronteira, a adulteração foi jogada "
        "fora, a custódia fechou assinada nas duas pontas, e o "
        "PII virou tarja no objeto publicado de B.")
    r.ln(3)
    r.h2("As ressalvas que você MESMO aponta (isso dá "
         "credibilidade)")
    r.bullet(
        "O motor de anonimização da demo é uma regex "
        "determinística - prova a ESTEIRA, não a nota do modelo. "
        "O medido está em docs/metricas.md: cascata v2, NER F1 "
        "0,953, reidentificação 0/360 - no corpus SINTÉTICO.")
    r.bullet(
        "O mecanismo de re-entrega do ack (se a rede cair) é "
        "item do roadmap - a assinatura já existe e foi "
        "exercida.")
    r.bullet(
        "Corpus real, gates de utilidade/latência e decisões "
        "jurídicas (reidentificação, caso_cnj em claro) "
        "permanecem abertos.")
    r.fala(
        "E por último: se algo não funcionasse, vocês veriam na "
        "tela - as provas só acendem quando acontecem de "
        "verdade.")

    # ============ 5. cola rápida ============
    r.h1("5. Cola rápida - uma frase por prova")
    r.bullet("Envelope sem bytes: 'o papel não viaja - viaja o "
             "aviso'")
    r.bullet("Ciphertext no MinIO: 'em repouso só existe texto "
             "cifrado - o claro só existe dentro do processo'")
    r.bullet("Adulteração rejeitada: 'mexeu, quebrou o selo - "
             "é recusado antes de virar registro'")
    r.bullet("Custódia A->B->A: 'A entregou, B conferiu e "
             "assinou - prova nas duas pontas'")
    r.bullet("PII removido: 'o objeto publicado só sai se o "
             "portão residual aprovar'")
    r.bullet("Hash-chain: 'a corrente é refeita do zero - uma "
             "mexida quebra tudo depois'")
    r.bullet("Replay barrado: 'o carimbo do pacote só vale uma "
             "vez'")
    r.bullet("Trigger append-only: 'o próprio banco barra "
             "UPDATE e DELETE na trilha'")

    # ============ 6. perguntas esperadas ============
    r.add_page()
    r.h1("6. Perguntas esperadas (respostas curtas)")
    r.h2("'E se a rede cair no meio da tramitação?'")
    r.p(
        "O evento sai da API junto com o registro, numa única "
        "transação (outbox transacional) - não existe 'gravou "
        "mas não avisou'. O relay republica até a fila "
        "confirmar; fila tem DLQ para o que falhar de vez.")
    r.h2("'Quem guarda o documento?'")
    r.p(
        "Cada instituição guarda a sua cópia no próprio storage, "
        "cifrado. B não acessa o storage de A - baixa uma cópia "
        "pelo canal e arquiva localmente. Soberania é física, "
        "não contratual.")
    r.h2("'Isso prova que a anonimização é boa?'")
    r.p(
        "Prova que a ESTEIRA funciona de ponta a ponta "
        "(transporte, custódia, processamento, auditoria, "
        "resistência). A qualidade do modelo é outra medição - "
        "está no relatório de métricas, com gate pré-registrado. "
        "Na demo, o motor é didático por escolha.")
    r.h2("'Daria para apagar ou reescrever a trilha depois?'")
    r.p(
        "Duas barreiras: a corrente de hash (mexer num elo "
        "quebra os seguintes - detectável no replay) e o "
        "gatilho append-only no Postgres, que recusa UPDATE e "
        "DELETE na trilha no nível do banco.")
    r.h2("'E se quiserem reidentificar depois?'")
    r.p(
        "É uma decisão jurídica, não técnica - está em aberto "
        "nas atas do projeto. A arquitetura já tem o cofre de "
        "pseudônimos preparado para quando a decisão sair.")
    r.ln(6)
    r.p(
        "Fechamento sugerido:")
    r.fala(
        "O que vocês viram não é a promessa - é o mecanismo. "
        "Cada prova acesa foi uma chamada real executada nesta "
        "sala. O que falta fazer está escrito no relatório - e "
        "é exatamente por isso que o que já funciona merece "
        "confiança.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    r.output(str(OUT))
    print(f"roteiro gerado: {OUT}")


if __name__ == "__main__":
    main()
