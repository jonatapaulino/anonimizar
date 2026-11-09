"""Roteiro de fala da apresentacao — visualizador web + demo real.

Gera docs/roteiro_apresentacao_demo.pdf: um guia de palco para
apresentar a jornada do documento com a pagina
(http://localhost:8080) no projetor e demo_coordenador.py no
terminal do apresentador. Cada secao mapeia O QUE APARECE na
tela para O QUE DIZER — incluindo todos os cards, chips,
banner, painel de provas e o rodape honesto.

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
            "PIDE/FAPESPA | Roteiro de apresentacao - demo ao vivo"),
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

    def fala(self, t, indent=6):
        """Fala sugerida — em italico, como citacao de palco."""
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
        "Roteiro de Apresentacao\n"
        "FAPESPA / Anonimizar - Jornada do Documento"), align="C")
    r.ln(8)
    r.set_font("Helvetica", "", 11.5)
    r.set_text_color(74, 85, 104)
    r.multi_cell(0, 7, _lat(
        "Guia de palco para a demonstracao ao vivo:\n"
        "pagina no projetor + execucao real no terminal\n"
        "dois nos soberanos - nao e simulacao"), align="C")
    r.ln(20)
    r.set_font("Helvetica", "", 10)
    r.multi_cell(0, 6, _lat(
        "Cada secao diz: [TELA] o que aparece -> o que dizer.\n"
        "As falas sao sugestoes - ajuste ao seu jeito de falar."),
        align="C")

    # ============ 1. preparacao ============
    r.add_page()
    r.h1("1. Antes de comecar (5 min de preparo)")
    r.p("Tres comandos, nesta ordem:")
    r.bullet("docker compose -f deploy/malha/compose.malha.yaml up -d")
    r.p("     -> espera 30-60s (banco migra e os healthchecks "
        "sobem)", 6)
    r.bullet("python scripts/demo_web.py   (terminal 1 - deixa "
             "aberto; abre a pagina no browser)")
    r.bullet("python scripts/demo_coordenador.py --pausar   "
             "(terminal 2 - o seu, do apresentador)")
    r.ln(4)
    r.h2("Como funciona o palco")
    r.p(
        "O projetor mostra a PAGINA (localhost:8080): dois cards "
        "de no, a figura do documento viajando, chips de "
        "travessia, os dois textos do documento e o painel de "
        "provas. O seu terminal roda a execucao de verdade - "
        "cada Enter executa um ato; a pagina acompanha ao vivo "
        "(poll de ~1s).")
    r.p(
        "Com --pausar, o ritmo ja sai espacado (2.5s entre "
        "etapas dentro de cada ato). Se quiser mais lento: "
        "--pausar --ritmo 4.")
    r.p(
        "Frase de abertura sugerida, apontando para o subtitulo:")
    r.fala(
        "Isto nao e um video nem um desenho do que vai ser - "
        "esta rodando de verdade agora, em dois nos reais. Cada "
        "coisa que aparecer na tela e uma chamada real que "
        "aconteceu no sistema.")

    # ============ 2. mapa da tela ============
    r.add_page()
    r.h1("2. O mapa da tela (o que cada elemento e)")
    r.p(
        "Antes do primeiro Enter, passe 1-2 minutos apresentando "
        "os elementos fixos da pagina. Cada um tem uma frase "
        "pronta:")

    r.h2("Titulo e subtitulo")
    r.tela("'FAPESPA · Anonimizar - jornada real de um documento'"
           " + 'isto esta rodando de verdade agora, nao e "
           "simulacao'")
    r.fala(
        "Vamos acompanhar a vida de um documento judicial que "
        "sai de um orgao, chega a outro e e anonimizado no "
        "destino - tudo acontecendo agora, nao em slides.")

    r.h2("Card do No A - tjpa (esquerda)")
    r.tela("'instituicao de origem · storage proprio' | API + "
           "Postgres + RabbitMQ (TLS) | MinIO (HTTPS) + borda "
           "mTLS | linha de storage + trilha-mini")
    r.fala(
        "Este e o no do orgao de origem. Repare: cada instituicao "
        "roda a MESMA pilha soberana - API, banco, fila e storage "
        "proprios, dentro do proprio dominio. Nada e compartilhado "
        "de graca: cada um e dono dos seus dados e dos seus "
        "objetos.")

    r.h2("Corredor (centro) - o canal entre as instituicoes")
    r.tela("o fio horizontal, a figura do documento, os chips de "
           "travessia e a tag de canal")
    r.fala(
        "Aqui e a fronteira: a rede entre os dois orgaos. A "
        "figura so anda quando algo REALMENTE atravessa - e cada "
        "travessia vira um chip no historico ali embaixo. A "
        "etiqueta do canal (mTLS + criptografia ponta a ponta) so "
        "acende enquanto a travessia esta acontecendo.")

    r.h2("Card do No B - mpfpa (direita)")
    r.tela("'instituicao de destino · storage proprio' | mesma "
           "pilha + 'worker de anonimizacao'")
    r.fala(
        "O no de destino e identico em soberania - e tem uma "
        "peca a mais: o trabalhador de anonimizacao, que processa "
        "o documento DENTRO de B. O documento nunca precisa "
        "voltar para ser tratado.")

    r.h2("Banner do passo (faixa azul)")
    r.tela("titulo do passo + detalhe tecnico + frase em italico")
    r.fala(
        "Esta faixa conta o que esta acontecendo em tres "
        "camadas: o titulo, o detalhe tecnico para quem quer "
        "verificar, e a frase simples - o 'por que isso importa' "
        "para todo mundo.")

    r.h2("Os dois textos do documento")
    r.tela("esquerda: 'documento (com dados pessoais)' com PII "
           "em laranja | direita: 'documento anonimizado (bucket "
           "de B)' com tarjas verdes")
    r.fala(
        "O da esquerda e a peticao original com os dados "
        "pessoais destacados - nome, CPF, e-mail, telefone. O da "
        "direita so preenche no final: e o mesmo documento "
        "depois da anonimizacao em B.")

    r.h2("Painel de provas (8 itens)")
    r.tela("circulos que ACENDEM em verde conforme cada prova e "
           "executada")
    r.fala(
        "Cada promessa da arquitetura vira uma prova na tela - "
        "e elas so acendem quando a prova de fato aconteceu. Se "
        "algo falhar, o circulo nao acende: a tela nao mente.")

    r.h2("Rodape (a ressalva honesta)")
    r.tela("'motor de anonimizacao nesta demo: regex LGPD "
           "deterministica ... nao e o modelo medido'")
    r.fala(
        "E aqui o compromisso de honestidade: o motor de "
        "anonimizacao nesta demonstracao e didatico. A qualidade "
        "do modelo real esta medida no relatorio - a demo prova "
        "a ESTEIRA inteira funcionando, nao a nota do modelo.")

    # ============ 3. roteiro ato a ato ============
    r.add_page()
    r.h1("3. O roteiro - ato a ato")
    r.p(
        "Sao 6 atos. Cada bloco: o que acontece na tela e a "
        "fala sugerida. O Enter e seu - nao tenha pressa.")

    # ---- ATO 1 ----
    r.h2("ATO 1 - Registro e arquivo no no origem")
    r.tela("figura parada na porta de A; card A acende; storage "
           "de A vira 'tjpa-docs - objeto cifrado'; provas 1 e 2 "
           "acendem")
    r.fala(
        "O processo nasce registrando so a capa e a impressao "
        "digital do documento - o conteudo fica dentro da "
        "instituicao. E quando o arquivo sobe, ele e conferido "
        "byte a byte contra a impressao declarada e guardado "
        "trancado no cofre do proprio orgao.")
    r.fala(
        "Repare uma coisa forte: nem o banco de dados guarda o "
        "documento. No terminal esta o esquema da tabela - nao "
        "existe coluna para bytes. A regra nao e disciplina, e "
        "estrutura.")

    # ---- ATO 2 ----
    r.h2("ATO 2 - Transito com custodia (o ataque ao vivo)")
    r.tela("chip 'envelope A->B' pipoca; a figura envelope "
           "atravessa; AVISO para no meio e vira selo 'recusado'; "
           "o envelope verdadeiro atravessa; chip 'barrado' em "
           "vermelho")
    r.fala(
        "O que atravessa a fronteira nao e o papel - e so um "
        "aviso: 'existe este documento, com esta impressao "
        "digital', assinado pela origem. Zero bytes do documento "
        "viajam aqui.")
    r.fala(
        "Agora o teste de fogo: alguem mexeu no aviso no meio do "
        "caminho. Olha o que acontece - a assinatura nao confere "
        "mais e o destino JOGA A COPIA FORA. Ela nao vira "
        "registro em lugar nenhum. O selo 'recusado' fica parado "
        "na trilha enquanto o aviso verdadeiro atravessa e vira "
        "registro de verdade.")
    r.p(
        "Ponto de fala extra, se perguntarem: rejeitar so o "
        "falso (sem derrubar o fluxo) e de proposito - se a "
        "defesa parasse tudo, qualquer um travaria a integracao "
        "enviando lixo.")

    # ---- ATO 3 ----
    r.h2("ATO 3 - Arquivo soberano no no destino")
    r.tela("figura documento atravessa A->B; card B acende; "
           "storage de B vira 'mpfpa-docs - objeto cifrado'")
    r.fala(
        "Recebido o aviso, B vai buscar o documento direto na "
        "fonte - por um canal trancado de ponta a ponta - e "
        "confere a impressao digital de novo. Depois tranca a "
        "propria copia no proprio cofre.")
    r.fala(
        "E aqui a soberania em acao: a copia de B fica no storage "
        "DE B, cifrada. No terminal da para ver o objeto cru no "
        "MinIO: comeca com os bytes magicos do quadro cifrado - "
        "e2 02 - e nenhum texto do documento aparece em claro.")

    # ---- ATO 4 ----
    r.h2("ATO 4 - Fechamento de custodia B -> A")
    r.tela("figura de confirmacao volta B->A e pousa na porta "
           "de A; chip 'ack B->A' pipoca; prova 'custodia "
           "assinada' acende")
    r.fala(
        "B nao apenas diz 'recebi'. Antes de assinar, ele "
        "recalcula a impressao digital do que esta no proprio "
        "cofre - evidencia, nao declaracao. O recibo sai assinado "
        "com a chave de B, volta para A e fecha o ciclo.")
    r.fala(
        "Resultado: custodia de ponta a ponta - A entregou, B "
        "confirmou, e a prova existe nas duas pontas, assinada.")

    # ---- ATO 5 ----
    r.h2("ATO 5 - Anonimizacao soberana em B")
    r.tela("card B PULSA com 'esteira de B em processamento - "
           "Xs'; as trilhas-mini enchem; o painel da direita "
           "preenche com o texto anonimizado; prova 'PII "
           "removido' acende")
    r.fala(
        "Agora a parte assincrona: o upload em B disparou a "
        "esteira de anonimizacao - fila segura, trabalhador, "
        "portao de verificacao. O card de B pulsando e o "
        "processamento acontecendo de verdade; a contagem de "
        "segundos e real.")
    r.fala(
        "E o resultado, na direita: nome, CPF, e-mail e telefone "
        "viraram tarjas ANONIMIZADO_LGPD no objeto publicado. "
        "O portao de PII residual e fail-closed - se sobrar "
        "algum dado, o objeto nem grava.")
    r.p(
        "Aqui vale a ressalva em voz alta (credibilidade): 'o "
        "motor nesta demo e didatico - o resultado medido do "
        "modelo real esta no relatorio de metricas'.")

    # ---- ATO 6 ----
    r.h2("ATO 6 - Provas finais: auditoria e resistencia")
    r.tela("provas 'hash-chain' e 'replay barrado' acendem; o "
           "banner vira verde 'jornada concluida - execucao real "
           "verificada'")
    r.fala(
        "Por fim, a auditoria: a corrente de eventos e refeita "
        "do zero nos dois nos e confere elo a elo - mexer numa "
        "linha quebraria tudo depois dela. E no banco, um gatilho "
        "append-only barra qualquer UPDATE ou DELETE - a "
        "integridade nao depende de boa vontade.")
    r.fala(
        "E a ultima prova: copiar um pacote cifrado na rede e "
        "reenviar nao funciona - o carimbo unico ja foi gasto. "
        "A segunda entrega identica volta com recusa. Com isso "
        "a jornada fecha - e a tela mostra o encerramento.")

    # ============ 4. tela final ============
    r.add_page()
    r.h1("4. A tela final e as ressalvas")
    r.p(
        "Com a execucao concluida, a pagina mostra o estado "
        "completo: a figura na porta de A (depois do recibo de "
        "B), os 5 chips de travessia, os 8 circulos de prova "
        "acesos, o documento original ao lado do anonimizado e "
        "o banner verde de encerramento.")
    r.fala(
        "Tudo que voces viram aconteceu agora, nestes dois nos: "
        "o documento nunca saiu dos storages cifrados das "
        "instituicoes, so metadados e a impressao digital "
        "atravessaram a fronteira, a adulteracao foi jogada "
        "fora, a custodia fechou assinada nas duas pontas, e o "
        "PII virou tarja no objeto publicado de B.")
    r.ln(3)
    r.h2("As ressalvas que voce MESMO aponta (isso da "
         "credibilidade)")
    r.bullet(
        "O motor de anonimizacao da demo e uma regex "
        "deterministica - prova a ESTEIRA, nao a nota do modelo. "
        "O medido esta em docs/metricas.md: cascata v2, NER F1 "
        "0,953, reidentificacao 0/360 - no corpus SINTETICO.")
    r.bullet(
        "O mecanismo de re-entrega do ack (se a rede cair) e "
        "item do roadmap - a assinatura ja existe e foi "
        "exercida.")
    r.bullet(
        "Corpus real, gates de utilidade/latencia e decisoes "
        "juridicas (reidentificacao, caso_cnj em claro) "
        "permanecem abertos.")
    r.fala(
        "E por ultimo: se algo nao funcionasse, voces veriam na "
        "tela - as provas so acendem quando acontecem de "
        "verdade.")

    # ============ 5. cola rapida ============
    r.h1("5. Cola rapida - uma frase por prova")
    r.bullet("Envelope sem bytes: 'o papel nao viaja - viaja o "
             "aviso'")
    r.bullet("Ciphertext no MinIO: 'em repouso so existe texto "
             "cifrado - o claro so existe dentro do processo'")
    r.bullet("Adulteracao rejeitada: 'mexeu, quebrou o selo - "
             "e recusado antes de virar registro'")
    r.bullet("Custodia A->B->A: 'A entregou, B conferiu e "
             "assinou - prova nas duas pontas'")
    r.bullet("PII removido: 'o objeto publicado so sai se o "
             "portao residual aprovar'")
    r.bullet("Hash-chain: 'a corrente e refeita do zero - uma "
             "mexida quebra tudo depois'")
    r.bullet("Replay barrado: 'o carimbo do pacote so vale uma "
             "vez'")
    r.bullet("Trigger append-only: 'o proprio banco barra "
             "UPDATE e DELETE na trilha'")

    # ============ 6. perguntas esperadas ============
    r.add_page()
    r.h1("6. Perguntas esperadas (respostas curtas)")
    r.h2("'E se a rede cair no meio da tramitacao?'")
    r.p(
        "O evento sai da API junto com o registro, numa unica "
        "transacao (outbox transacional) - nao existe 'gravou "
        "mas nao avisou'. O relay republica ate a fila "
        "confirmar; fila tem DLQ para o que falhar de vez.")
    r.h2("'Quem guarda o documento?'")
    r.p(
        "Cada instituicao guarda a sua copia no proprio storage, "
        "cifrado. B nao acessa o storage de A - baixa uma copia "
        "pelo canal e arquiva localmente. Soberania e fisica, "
        "nao contratual.")
    r.h2("'Isso prova que a anonimizacao e boa?'")
    r.p(
        "Prova que a ESTEIRA funciona de ponta a ponta "
        "(transporte, custodia, processamento, auditoria, "
        "resistencia). A qualidade do modelo e outra medicao - "
        "esta no relatorio de metricas, com gate pre-registrado. "
        "Na demo, o motor e didatico por escolha.")
    r.h2("'Daria para apagar ou reescrever a trilha depois?'")
    r.p(
        "Duas barreiras: a corrente de hash (mexer num elo "
        "quebra os seguintes - detectavel no replay) e o "
        "gatilho append-only no Postgres, que recusa UPDATE e "
        "DELETE na trilha no nivel do banco.")
    r.h2("'E se quiserem reidentificar depois?'")
    r.p(
        "E uma decisao juridica, nao tecnica - esta em aberto "
        "nas atas do projeto. A arquitetura ja tem o cofre de "
        "pseudonimos preparado para quando a decisao sair.")
    r.ln(6)
    r.p(
        "Fechamento sugerido:")
    r.fala(
        "O que voces viram nao e a promessa - e o mecanismo. "
        "Cada prova acesa foi uma chamada real executada nesta "
        "sala. O que falta fazer esta escrito no relatorio - e "
        "e exatamente por isso que o que ja funciona merece "
        "confianca.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    r.output(str(OUT))
    print(f"roteiro gerado: {OUT}")


if __name__ == "__main__":
    main()
