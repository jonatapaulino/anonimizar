"""Relatorio estruturado da avaliacao do motor de anonimizacao.

Gera docs/relatorio_avaliacao.pdf. Numeros do corpus sao
recontados dos gabaritos; resultados das configuracoes vem dos
artefatos de avaliacao (corpus/*/avaliacao_*.json e saidas).

Uso: python scripts/relatorio_pdf.py
"""
from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from fpdf import FPDF

BASE = Path(__file__).resolve().parent.parent
CORPUS = BASE / "corpus"
OUT = BASE / "docs" / "relatorio_avaliacao.pdf"

PRIV = {"NOME", "CPF", "EMAIL", "TELEFONE", "RG", "ENDERECO"}


def _lat(s: str) -> str:
    """Helvetica core = latin-1; normaliza o que nao cabe."""
    return s.encode("latin-1", "replace").decode("latin-1")


def corpus_stats(part: str) -> dict:
    docs = ent = priv = 0
    tipos: dict[str, int] = {}
    for g in sorted((CORPUS / part).glob("doc-*.json")):
        gab = json.loads(g.read_text("utf-8"))
        docs += 1
        for e in gab["entidades"]:
            ent += 1
            tipos[e["tipo"]] = tipos.get(e["tipo"], 0) + 1
            if not e["preservar"]:
                priv += 1
    return {"docs": docs, "ent": ent, "priv": priv,
            "pres": ent - priv, "tipos": tipos}


class Rel(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(110)
        self.cell(0, 5, _lat(
            "PIDE/FAPESPA - iSACI | Avaliacao do motor de "
            "anonimizacao (POC)"), align="R")
        self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(110)
        self.cell(0, 6, _lat(f"pagina {self.page_no()}"),
                  align="C")

    def h1(self, t):
        self.set_font("Helvetica", "B", 15)
        self.set_text_color(0)
        self.cell(0, 10, _lat(t))
        self.ln(12)

    def h2(self, t):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(30)
        self.cell(0, 8, _lat(t))
        self.ln(9)

    def p(self, t):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(0)
        self.multi_cell(0, 5, _lat(t))
        self.ln(2)

    def bullet(self, t):
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5, _lat("- " + t))
        self.ln(1)

    def tabela(self, cab, linhas, larguras=None):
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(230)
        n = len(cab)
        w = larguras or [190 / n] * n
        for i, c in enumerate(cab):
            self.cell(w[i], 6, _lat(str(c)), border=1,
                      fill=True, align="C")
        self.ln()
        self.set_font("Helvetica", "", 9)
        for ln in linhas:
            for i, c in enumerate(ln):
                self.cell(w[i], 5.6, _lat(str(c)), border=1,
                          align="C")
            self.ln()
        self.ln(3)


def main():
    aj = corpus_stats("ajuste")
    te = corpus_stats("teste")

    pdf = Rel()
    pdf.set_auto_page_break(True, 18)
    pdf.add_page()

    pdf.h1("Relatorio de avaliacao - motor de anonimizacao")
    pdf.p("Projeto iSACI (PIDE/FAPESPA) - avaliacao de "
          "configuracoes para a porta MotorIA da esteira de "
          "anonimizacao soberana. Corpus sintetico pt-BR "
          "juridico-administrativo; execucao local via Ollama, "
          "GPU dedicada, temperatura 0.")
    pdf.p("ESTE DOCUMENTO REPORTA UMA POC. Os resultados sao "
          "proxies de engenharia sobre corpus sintetico e NAO "
          "estabelecem validade externa nem aptidao de "
          "producao.")
    pdf.p("DESVIO DA ADR-0011: a ADR-0011 define processamento "
          "deterministico/discriminativo local; a cascata "
          "avaliada usa LLM GENERATIVO local (qwen2.5) para "
          "extracao de spans e de nomes. Justificativa do "
          "experimento: medir se um LLM local disponivel "
          "fechava o recall residual onde a camada "
          "deterministica falhava, antes de investir em "
          "treino. Condicao de retorno a ADR: substituir o "
          "componente generativo por discriminativo treinado "
          "(ex.: NER LeNER-Br/UlyssesNER-Br), medido contra o "
          "mesmo gate na particao teste. A decisao de aceitar "
          "o desvio e do requisitante, nao desta POC.")
    pdf.p("Distancia da especificacao: a especificacao preve "
          "NER legal-BERT com cofre criptografico e guardrails; "
          "a cascata e um proxy de engenharia que nao "
          "implementa esses componentes.")

    pdf.h2("1. Corpus de avaliacao")
    pdf.tabela(
        ["particao", "documentos", "entidades", "alvos (priv)",
         "preservadas"],
        [["ajuste (tuning)", aj["docs"], aj["ent"], aj["priv"],
          aj["pres"]],
         ["teste (held-out)", te["docs"], te["ent"], te["priv"],
          te["pres"]]],
        larguras=[48, 34, 34, 40, 34])
    pdf.p("Tipos anonimizaveis: NOME, CPF, EMAIL, TELEFONE, RG, "
          "ENDERECO. Preservados: ORGAO, CARGO, CIDADE, "
          "INSTITUICAO, CNJ, VALOR. INSTITUICAO tem amostra "
          "pequena (4 ajuste / 10 teste) - conclusoes por tipo "
          "nao sao suportadas.")
    pdf.p("Declaracao: corpus integralmente sintetico/"
          "fabricado; gabaritos JSON com offsets sobre o TXT; "
          "PDFs regenerados com wrap seguro (sobrevivencia de "
          "extracao 241/241 e 665/665).")

    pdf.h2("2. Ambiente e versoes")
    pdf.bullet("Ollama 0.40.5 em localhost:11434; GPU NVIDIA "
               "RTX 5090 Laptop (~24 GB); temperature=0; "
               "num_ctx=1024.")
    pdf.bullet("Modelos: qwen2.5:7b (digest 845dbda0ea48ed74...)"
               ", qwen2.5:14b "
               "(7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8"
               "a9489440385b22f6).")
    pdf.bullet("Prompts: v0 sha256 644cac43... (1100c, congelada"
               "); v1 cf92a61d... REJEITADA; contrato-spans-v0 "
               "7d7ac2b2...; contrato-cascata-nome-v0.")

    pdf.h2("3. Configuracoes avaliadas na ajuste")
    pdf.tabela(
        ["#", "configuracao", "recall agregado", "status"],
        [["0", "DemoMotorIA (regex)", "baseline", "referencia"],
         ["1", "qwen2.5:7b + v0 (texto->texto)", "98/123 (79.7%)",
          "baseline LLM"],
         ["2", "qwen2.5:7b + v1 (endereco/fone)",
          "113/123 (91,9%)", "REJEITADA"],
         ["3", "qwen2.5:14b + v0", "106/123 (86.2%)",
          "regressao parcial"],
         ["4", "qwen2.5:7b + spans-v0 (JSON)", "105/123 (85.4%)",
          "gate falhou"],
         ["5", "cascata (det + 2x LLM + guarda)",
          "ajuste: 123/123 (tuning); "
          "teste: 356/360 (98,9%)", "candidata"]],
        larguras=[8, 72, 74, 36])
    pdf.p("v1 rejeitada: regressao NOME/CPF/RG, mutacao de texto"
          " preservado (Santarem->Santarem com acento) e tag "
          "fora do padrao em 2 documentos - a rejeicao deve-se "
          "a regressao e a mutacao, NAO ao agregado (que "
          "subiu). 14B melhorou ENDERECO/TELEFONE mas regrediu "
          "NOME/CPF/RG - evidencia de que escala de modelo nao "
          "e monotonica.")

    pdf.add_page()
    pdf.h2("4. Gate na particao teste (cascata)")
    pdf.p("80 documentos cegos; desenho congelado apos a ajuste."
          " Camadas: detectores deterministicos (CPF, RG, "
          "email, telefone, endereco) -> spans LLM -> segunda "
          "passada LLM so nomes -> guarda de zona protegida "
          "(CNJ/VALOR) -> substituicao por codigo.")
    pdf.tabela(
        ["tipo", "recall", "excesso preservados"],
        [["NOME", "97/101 (96.0%)", "-"],
         ["CPF", "65/65 (100%)", "-"],
         ["EMAIL", "57/57 (100%)", "-"],
         ["ENDERECO", "44/44 (100%)", "-"],
         ["RG", "32/32 (100%)", "-"],
         ["TELEFONE", "61/61 (100%)", "-"],
         ["AGREGADO", "356/360 (98.9%)", "0/305"]],
        larguras=[60, 60, 60])
    pdf.p("Excesso em preservados: denominador = 305 entidades "
          "preservadas do gabarito (ORGAO 73, CARGO 40, CIDADE "
          "41, CNJ 70, VALOR 71, INSTITUICAO 10). O '278' da "
          "versao anterior era erro de denominador - o excesso "
          "medido e 0 sobre as 305.")
    pdf.tabela(
        ["nivel NER", "P", "R", "F1", "gate", "veredicto"],
        [["exact (ini,fim,tipo)=gold", "0.780", "0.731", "0.755",
          ">= 0.85", "FAIL"],
         ["overlap (>=1 char,tipo)", "0.970", "0.908", "0.938",
          "-", "referencia"]],
        larguras=[56, 22, 22, 22, 30, 38])
    pdf.tabela(
        ["NER exact por fonte", "TP", "FP", "FN", "P", "R", "F1"],
        [["so det (deterministico)", "180", "22", "180", "0.891",
          "0.500", "0.641"],
         ["so llm (spans+so-nomes)", "83", "52", "277", "0.615",
          "0.231", "0.335"],
         ["uniao (cascata)", "263", "74", "97", "0.780", "0.731",
          "0.755"]],
        larguras=[52, 18, 18, 18, 24, 24, 24])
    pdf.tabela(
        ["tipo", "det: candidato pre-merge",
         "det: aceito pela cascata", "llm: aceito"],
        [["CPF", "65/65 (100%)", "36/65 (55%)", "-"],
         ["EMAIL", "57/57 (100%)", "56/57 (98%)", "-"],
         ["ENDERECO", "38/44 (86%)", "35/44 (80%)", "-"],
         ["RG", "32/32 (100%)", "16/32 (50%)", "-"],
         ["TELEFONE", "61/61 (100%)", "59/61 (97%)", "-"],
         ["TOTAL det (5 tipos)", "253/259 (97,7%)",
          "202/259 (78,0%)", "-"],
         ["PESSOA", "-", "-", "97/101 (96%)"]],
        larguras=[52, 50, 48, 30])
    pdf.p("97,7% e o recall POTENCIAL do deterministico sobre "
          "candidatos pre-merge (recomputado sem motor); o "
          "recall entregue pela cascata via spans dessa fonte e "
          "a coluna 'aceito pela cascata' (202/259 = 78,0%) - a "
          "diferenca sao spans det descartados no merge em "
          "favor de spans llm sobre-estendidos (mesclar() "
          "guarda UMA fonte por span). Cobertos por ambos: CPF "
          "29, RG 16, ENDERECO 3, TELEFONE 2, EMAIL 1. O llm "
          "sobre PESSOA e limite inferior - seus candidatos "
          "que perderam o merge nao sao registrados. O recall "
          "ENTREGUE por tipo (uniao das fontes) permanece o da "
          "tabela principal acima.")
    pdf.tabela(
        ["FP por tipo declarado", "det:", "llm:"],
        [["CPF", "8", "25"], ["RG", "14", "15"],
         ["ENDERECO", "0", "5"], ["PESSOA", "0", "3"],
         ["TELEFONE", "0", "2"], ["CEP (inventado)", "0", "2"],
         ["TOTAL", "22", "52"]],
        larguras=[90, 45, 45])
    pdf.p("Top-10 FP do llm: por tamanho de span, com o padrao:")
    for f, t, d in (
        ("IVONETE CRISTINA ROCHA, inscrito no RG sob o n. "
         "58.320.829, inscrito(a", "ENDERECO",
         "prosa+rotulo+nome (203c)"),
        ("Francisca Ferreira, RG n. 18.338.687-7, CPF "
         "73358622991, Endereco: Rua", "RG",
         "prosa+nome+2 entidades (169c)"),
        ("DENISE PINHEIRO, inscrito(a) no CPF sob o n. "
         "448.502.234-00", "CPF", "rotulo+nome (59c)"),
        ("Rua dos Mundurucus, 2580, Centro, Maraba-PA, CEP "
         "68482-331.", "ENDERECO", "fronteira+CEP (59c)"),
        ("Francisca De Oliveira Lima, portador(a) do RG "
         "59.798.381-2", "RG", "rotulo+nome (58c)"),
        ("Pedro De Souza, inscrito no RG sob o n. "
         "30.677.315-X", "RG", "rotulo+nome (52c)"),
        ("Tv. Castelo Branco, 1674, Nazare, Castanhal-PA",
         "ENDERECO", "fronteira+cidade-UF (46c)"),
        ("Tv. Castelo Branco, 690, Reduto, Santarem-PA",
         "ENDERECO", "fronteira+cidade-UF (44c)"),
        ("Tv. Castelo Branco, 1491, Sao Bras, Belem-PA",
         "ENDERECO", "fronteira+cidade-UF (44c)"),
        ("IVONETE CRISTINA ROCHA, CPF 204.306.939-07.", "CPF",
         "rotulo+nome (43c)"),
    ):
        pdf.set_font("Courier", "", 6.5)
        pdf.multi_cell(0, 3.6, _lat(f"  {t:<9} [{d}] {f}"),
                       new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.ln(1)
    pdf.p("Leitura corrigida da atribuicao por camada: nos "
          "tipos sob sua responsabilidade o det: cobre "
          "253/259 (97,7%) - unica lacuna real: ENDERECO sem "
          "CEP (6). Dos 74 FP exact, 52 sao do llm: "
          "(sobre-extensao: rotulo + prosa + fronteira) e 22 "
          "do det: (rotulo 'RG ' dentro do span; regex de CPF "
          "casando telefone de 11 digitos). A atribuicao do "
          "exact F1 por camada: a fronteira frouxa do llm: e "
          "o maior contribuinte de FP, mas a afirmacao 'o llm "
          "derruba o F1' e simplista - isolado, det F1=0,641 "
          "e llm F1=0,335, ambos abaixo de 0,85; os FP do det "
          "(rotulo no span, confusao CPF/telefone) tambem "
          "precisam de correcao.")
    pdf.tabela(
        ["metrica pre-registrada", "resultado", "gate", "veredicto"],
        [["reidentificacao (mencao)",
          "4/360=0,0111 IC95%[0,4-2,8%]", "<= 0.05",
          "PASS robusto"],
         ["reidentificacao (documento)",
          "4/80=0,050 IC95%[2,0-12,2%]", "<= 0.05",
          "limite dentro do IC"],
         ["coreferencia pairwise F1", "-", ">= 0.90",
          "nao avaliado*"],
         ["coreferencia anti-merge", "-", "<= 5% pares",
          "nao avaliado*"],
         ["consistencia por documento", "-", ">= 0.85",
          "nao avaliado*"],
         ["utility (TAB adaptado)", "-", ">= 0.85",
          "nao avaliado**"],
         ["latencia (contrato API)", "-", "a fixar",
          "nao avaliado"]],
        larguras=[52, 62, 26, 50])
    pdf.p("* corpus v0 nao anota ent_id (cluster de "
          "correferencia) - pairwise, anti-merge e consistencia "
          "nao sao computaveis. ** utility TAB exige checklist "
          "humano e decisao juridica de pesos (metricas.md "
          "sec.5); latencia tem barra a fixar no hardware-alvo.")
    pdf.p("Reidentificacao em duas unidades: por mencao 4/360 = "
          "1,1% (Wilson 95%: 0,4%-2,8%); por documento 4/80 = "
          "5,0% (Wilson 95%: 2,0%-12,2%). O PASS do gate "
          "<=0,05 e robusto na unidade de mencao (limite fora "
          "do intervalo) e NAO e robusto na unidade de "
          "documento - 5,0% esta dentro do intervalo. Unidade "
          "de risco para LGPD: o DOCUMENTO - um documento com "
          "qualquer nome residual sai com dado pessoal "
          "identificavel; a unidade por mencao dilui o risco "
          "em documentos com muitas entidades.")
    pdf.p("NER exact reprova por precisao de fronteira: spans "
          "LLM sobre-estendidos comem rotulos ('RG ', 'CPF n. ', "
          "prosa conectiva) - e o mesmo comportamento medido "
          "pela divergencia de fidelidade (44/80 docs), sem "
          "vazamento adicional. Excesso sobre nao-entidade: "
          "419c de rotulo + 59c de prosa conectiva em 43/80 "
          "docs; zero conteudo substantivo perdido (inspecao "
          "manual de 6 documentos; nao e metrica automatica).")
    pdf.tabela(
        ["excesso por gravidade", "spans", "chars fora de gold"],
        [["a) rotulo curto (span <=20c)", "38", "142"],
         ["b) prosa conectiva (span 21-100c)", "21", "216"],
         ["c) span >100c (dano alto)", "2", "120"],
         ["TOTAL", "61", "478"]],
        larguras=[90, 30, 50])
    pdf.p("Faixa (c) - duas leituras lado a lado: (i) spans "
          "com excesso fora de gold acima de 100 caracteres: "
          "0; (ii) spans com tamanho total acima de 100 "
          "caracteres: 2. A faixa (c) usa a leitura de "
          "tamanho total, por medir contexto removido do "
          "documento; na leitura de excesso fora de gold "
          "nenhum span entra nessa faixa.")
    pdf.p("Faixa (c), inspecionada:")
    for f, t, d in (
        ("doc-0057 llm1:ENDERECO 203c: 'IVONETE CRISTINA "
         "ROCHA, inscrito no RG sob o n. 58.320.829, inscrito(a)"
         " no CPF sob o n. 732.590.332-46, reside...'", "",
         "clausula de atribuicao inteira: nome + rotulos + RG +"
         " CPF + 'reside'"),
        ("doc-0102 llm1:RG 169c: 'Francisca Ferreira, RG n. "
         "18.338.687-7, CPF 73358622991, Endereco: Rua dos "
         "Mundurucus, 440, ...'", "",
         "nome + RG + CPF + endereco num unico span"),
    ):
        pdf.set_font("Courier", "", 6.5)
        pdf.multi_cell(0, 3.6, _lat(f"  {f}\n    motivo: {d}"),
                       new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.ln(1)
    pdf.p("Atencao de utilidade: substituir os spans da faixa "
          "(c) remove CONTEXTO do documento (clausula de "
          "atribuicao, sequencia nome+documento+endereco), "
          "nao apenas o dado pessoal - e o erro que a metrica "
          "utility TAB (nao avaliada) mediria.")
    pdf.p("Vazamentos (reident): 4 nomes - doc-0051, doc-0066, "
          "doc-0078 ('Pedro Henrique Almeida') e doc-0080 "
          "('MARCOS AURELIO TAVARES'). Modo de falha unico: a "
          "passada so-nomes omite uma pessoa quando o documento "
          "tem varias. Falhas de JSON: 2/160 chamadas (sem "
          "impacto - camada deterministica cobriu).")

    pdf.h2("5. Metodo e interpretacoes declaradas")
    for d in (
        "gold = entidades com preservar=false (PRIV); "
        "preservadas = preservar=true.",
        "Mapa de tipos para o tagset de metricas.md: "
        "NOME->PESSOA, CNJ->PROCESSO_CNJ; demais nomes "
        "identicos. Tipos inventados pelo modelo (CEP, "
        "PROCESSO) mantidos como estao - contam FP.",
        "Entidade = cada ocorrencia plantada; o corpus nao "
        "anota ent_id, logo reident conta por mencao (a "
        "unidade por documento e reportada em separado como "
        "unidade de risco).",
        "Preditos = spans aceitos e mesclados do eval_cascata, "
        "com fonte det:/llm: convertida em tipo.",
        "O NER span-level agrega as duas camadas (det: e llm:) "
        "na tabela principal; a separacao validador-"
        "deterministico x NER exigida por metricas.md sec.2 "
        "esta na tabela 'NER exact por fonte' (secao 4).",
        "Excesso sobre nao-entidade: caracteres de spans "
        "preditos fora de qualquer span gold; 'rotulo' vs "
        "'conteudo' por classificacao de fragmento - conteudo "
        "inspecionado manualmente (6 docs), nao e metrica "
        "automatica."):
        pdf.bullet(d)

    pdf.h2("6. Gate de residual PII (salvaguarda POC)")
    pdf.p("app/pii_residual.py - padroes deterministicos sobre "
          "a saida do motor (CPF, RG, email, telefone, nome em "
          "contexto: intimad[oa]/em face de/servidor(a)). Em "
          "processar_evento: residual > 0 -> "
          "falha_anonimizacao:{id}:residual_pii na trilha, "
          "nada vai ao bucket anonimizado, nenhum "
          "doc_anonimizado; log com contagens, nunca valores.")
    pdf.p("Testes: 27 unitarios (positivos por tipo, negativos "
          "de CNJ/valor/cargo/orgao/cidade, e2e com bucket "
          "vazio e trilha de falha). Suite completa verde. Na "
          "ajuste: 0 disparos em 30 saidas (1 FP corrigido - "
          "'Caixa Economica Federal' entrou na lista de "
          "nao-pessoa).")
    pdf.p("Nota sobre xfails: os 4 xfails da suite (CPF sem "
          "pontuacao, nome livre sem rotulo, endereco livre, "
          "telefone sem hifen) referem-se ao regex ISOLADO do "
          "DemoMotorIA, nao a cascata - na cascata esses casos "
          "passaram.")
    pdf.p("Avaliacao na teste: o gate NAO foi avaliado na "
          "particao teste como salvaguarda. Aplicacao pos-hoc "
          "sobre as 4 saidas com vazamento: dispararia em 3 "
          "dos 4 documentos (contextos 'em face de' e "
          "'servidor') - nao e avaliacao da salvaguarda; o 4o "
          "('intimado(a)') esta fora do formato coberto - o "
          "padrao aceita '(s)', nao '(a)'.")

    pdf.h2("7. Declaracoes")
    for d in (
        "O desenho da cascata foi definido APOS observar "
        "falhas da particao ajuste; a teste e held-out, mas o "
        "desenho carrega conhecimento da ajuste.",
        "Os padroes de contexto do gate foram definidos apos "
        "observar falhas da ajuste e NAO sao validados como "
        "cobertura de nomes; o gate NAO garante ausencia de "
        "PII.",
        "Corpus sintetico/template: resultados sao proxies de "
        "engenharia; documentos reais (OCR, digitalizados, "
        "novos formatos) podem degradar as metricas.",
        "INSTITUICAO: amostra insuficiente (4+10) para "
        "conclusao por tipo."):
        pdf.bullet(d)

    pdf.add_page()
    pdf.h2("8. Trabalho futuro")
    pdf.p("Curto prazo (motor):")
    for d in (
        "Aparar rotulos/fronteiras dos spans por codigo antes "
        "de substituir - recupera NER exact F1 sem tocar no "
        "recall e melhora a fidelidade de contexto.",
        "Retry da passada so-nomes em JSON invalido (2/160) e "
        "segunda passada de verificacao sobre a saida - "
        "ataca o modo de falha observado (omissao de 1 pessoa "
        "em documento com varias).",
        "Gate congelado: qualquer mudanca futura de modelo, "
        "prompt ou regex mede-se contra a particao teste, "
        "nunca contra a ajuste."):
        pdf.bullet(d)
    pdf.p("Medio prazo (cobertura e qualidade):")
    for d in (
        "NER discriminativo treinado (LeNER-Br / UlyssesNER-Br "
        "+ encoder tipo BERT) como detector de nomes - a "
        "resposta arquitetural correta para extrator "
        "deterministico-auditavel, alinhado a ADR-0011.",
        "Avaliar qwen2.5:32b apenas na passada so-nomes "
        "(cabe nos 24 GB) para isolar capacidade vs contrato.",
        "Corpus real autorizado e anotado - os gates "
        "(F1>=0.85, reident<=0.05) so sao declarados cumpridos "
        "sobre corpora reais.",
        "Documentos digitalizados/OCR na avaliacao - modo de "
        "falha nao coberto pelo corpus textual."):
        pdf.bullet(d)
    pdf.p("Plataforma (independente do motor):")
    for d in (
        "mTLS inter-nos (planejado), assinatura de envelope e "
        "verificacao de integridade fim a fim.",
        "RBAC por caso_cnj, cofre de chaves e rotacao.",
        "Runbook de falha_anonimizacao: triagem residual_pii x "
        "saida_ilegivel, reprocessamento manual supervisionado.",
        "Dashboard de metricas (detectadas/residuais/"
        "substituidas) com alerta de drift em producao.",
        "Custo/latencia: 2 chamadas LLM por documento "
        "(~1.6s/doc em 7B) - orcar fila e throughput antes de "
        "piloto."):
        pdf.bullet(d)
    pdf.p("Dependencias de decisao (ata de alinhamento da "
          "arquitetura - nao medidas nesta POC):")
    for d in (
        "Cofre de chaves nasce na Etapa 4/5, nao na 7 - o "
        "mapeamento pseudonimo->nome real comeca no primeiro "
        "documento de cada caso; e dependencia da "
        "correferencia (Etapa 5) e da pseudonimizacao, "
        "upstream do motor, nao item generico de plataforma.",
        "Reidentificacao (decisao juridica aberta): quem pode "
        "pedir, quem autoriza e se o cofre e obrigatorio - "
        "define se o modo e anonimizacao irreversivel ou "
        "pseudonimizacao reversivel, e afeta a leitura do "
        "reident <=0,05 (reidentificavel por quem?).",
        "Exclusoes de processo (aberta): segredo de justica, "
        "ECA, violencia domestica - categorias que definem o "
        "escopo do corpus real da Etapa 3.",
        "Irreversibilidade do HMAC (aberta): com a chave no "
        "servidor, um atacante com acesso ao banco pode testar "
        "candidatos e reverter pseudonimos; o modo so e "
        "irreversivel com a chave destruida?",
        "Registros de supressao (aberta): review_flags e spans "
        "suprimidos podem guardar trechos? O gate de residual "
        "desta POC ja loga so contagens - alinhado, mas a "
        "decisao de conteudo dos registros esta pendente.",
        "Etapa 6 (higienizacao/guardrails): o texto diz que "
        "precede a anonimizacao, o cronograma a agenda depois "
        "da Etapa 5 - conflito registrado na ata, sem decisao.",
        "Mapa POC->cronograma: esta avaliacao cobre Etapa 3 "
        "(corpus) e parte da 4 (NER); correferencia (Etapa "
        "5), higienizacao (6), auditoria/cofre (7) e utility "
        "TAB (10-11) seguem pendentes; Etapa 11 depende de "
        "CEP/TCLE, ausentes do cronograma."):
        pdf.bullet(d)
    pdf.p("Recomendacao: manter a cascata como candidata de "
          "POC, nao aprovada para producao, dado que o gate "
          "NER exact (0,85) falhou; manter o gate de residual "
          "ativo. Reavaliar apos correcao de fronteira, "
          "corpus real e piloto supervisionado.")

    pdf.add_page()
    pdf.h2("9. Reprodutibilidade")
    pdf.p("Seed do gerador de corpus: 20261020. Todas as "
          "medicoes em 2026-10-20 (timestamps dos artefatos): "
          "v0 ajuste 15:23; v1 15:43; 14B 15:56; spans-v0 "
          "16:01; cascata ajuste ~16:28; cascata teste ~16:49; "
          "metricas pre-registradas e gate de residual na "
          "mesma sessao.")
    pdf.p("sha256sum dos artefatos de codigo (saida literal):")
    SHA = (
        "3cd8dc1ce6d2142fdbda192ea4e75a22e81e1fdf771c67cc4316200"
        "c674f4656 *scripts/gerar_corpus.py\n"
        "085609ac0ff8d9ad14e26f624385deb33d1a31ffeaa24fcff83291b4"
        "da05e870 *scripts/eval_ollama_ajuste.py\n"
        "507a2d2a315f0bd5eb8a3f1002bc5756eb29920d22e3327aabb8e538"
        "565b65db *scripts/eval_ollama_prompt.py\n"
        "0082c7404bcd0a2b1b9d18d94de6826e4d470305c202340856a26994"
        "fec0c097 *scripts/eval_spans.py\n"
        "84cea94c28c290424372869c2a4a11e65452c6005561a8faab0811c1"
        "39aa93c4 *scripts/eval_cascata.py\n"
        "92394e90518062b67dbe2cdab8fe6e882a418c877b787a2c873ebef6"
        "daad2506 *scripts/metricas_prereg.py\n"
        "be38a6de5ff90f6a6e16d6b1bd24edcf409bea577a93493f41dbfff9"
        "5f8ea202 *scripts/painel.py\n"
        "d30fa82aa34787263b2c566d1995fdddb63528a0f79b76505c15c475"
        "bfbaeb22 *scripts/fidelidade.py\n"
        "76f1d90369fd2d0e5770729ad4176c080a62a84f1b4286b610638432"
        "9821de0d *scripts/analisar_extracao.py\n"
        "9046bdddcdae60ad2bd6dd89daa27a9df0a3075f18f564b25d2797b0"
        "b2af8dfe *app/pii_residual.py\n"
        "955d472f24f2467349285b1bc8d7e746b21f724bf1981f55eadf1a02"
        "06b4275c *app/worker.py\n")
    pdf.set_font("Courier", "", 6)
    pdf.multi_cell(0, 3.4, _lat(SHA),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.p("Comandos de execucao (reconstruidos do historico; "
          "marcados quando nao verificados):")
    for c in (
        "python scripts/gerar_corpus.py  "
        "(reconstruido, nao verificado)",
        "python scripts/eval_ollama_ajuste.py  # v0+7B ajuste "
        "(reconstruido, nao verificado)",
        "python scripts/eval_ollama_prompt.py  # v1+7B ajuste "
        "(reconstruido, nao verificado)",
        "IA_MODEL=qwen2.5:14b python scripts/eval_ollama_prompt."
        "py  # 14B (reconstruido, nao verificado)",
        "python scripts/eval_spans.py  # spans-v0 "
        "(reconstruido, nao verificado)",
        "IA_MODEL=qwen2.5:7b python -X utf8 scripts/eval_cascata."
        "py corpus ajuste  (reexecutado nesta sessao: "
        "reproduziu 123/123 e 0 excesso)",
        "IA_MODEL=qwen2.5:7b python -X utf8 scripts/eval_cascata."
        "py corpus teste  (executado nesta sessao; NAO "
        "reexecutado de forma independente)",
        "python -X utf8 scripts/metricas_prereg.py corpus teste "
        "saidas_ollama_cascata_teste  (verificado)",
        "python -X utf8 -m pytest tests/ -q  (verificado)"):
        pdf.set_font("Courier", "", 7)
        pdf.multi_cell(0, 3.8, _lat(c),
                     new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.ln(2)
    pdf.p("Reexecucao: a particao ajuste foi reexecutada no "
          "mesmo ambiente e modelo e reproduziu 123/123 alvos "
          "e 0 excesso em preservados; a particao teste nao "
          "foi reexecutada de forma independente. Isso "
          "demonstra determinismo local, nao reprodutibilidade "
          "em outro ambiente.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"gerado: {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
