"""Gerador de corpus sintético de anonimização (pt-BR).

Documentos jurídico-administrativos com entidades plantadas e
gabarito exato (texto, tipo, offsets de caractere, preservar) —
independente de qualquer motor ou do regex da métrica. A geração
é determinística (seed fixa): o mesmo código produz o mesmo
corpus byte a byte.

Uso:  python scripts/gerar_corpus.py [saida]     # default: corpus/

Saída por partição:
  <particao>/doc-NNNN.txt   — o documento (gabarito aponta aqui)
  <particao>/doc-NNNN.pdf   — renderização via pdf_de_texto (fpdf2)
  <particao>/doc-NNNN.json  — gabarito das entidades plantadas
  <particao>/SHA256SUMS     — manifesto + hash por arquivo +
                              hash do gerador + hash do conjunto

Partições: ajuste=30 docs (calibragem/tuning), teste=80 docs
(avaliação) — desvio do plano original (70 em teste) registrado
no manifesto de cada partição.

Preservados (preservar=true): número CNJ, valores monetários e
termos que PARECEM nomes mas não são PII de pessoa física —
INSTITUICAO, ORGAO, CARGO e CIDADE (contados à parte de NOME).
"""
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.motor_langchain import pdf_de_texto   # noqa: E402

SEMENTE = 20261020
PARTICOES = {"ajuste": 30, "teste": 80}

# ---------------- vocabulário ----------------
NOMES = [
    "MARIA JOSE FERREIRA", "JOAO CARLOS DE SOUZA", "ANA PAULA SANTOS",
    "JOSE RIBAMAR DA COSTA", "FRANCISCA DE OLIVEIRA LIMA",
    "ANTONIO MARCOS PINHEIRO", "LUCIA HELENA BARBOSA",
    "CARLOS EDUARDO NASCIMENTO", "MARIA DAS GRACAS SANTANA",
    "PEDRO HENRIQUE ALMEIDA", "ROSA MARIA CONCEICAO",
    "SEBASTIAO VITOR PEREIRA", "IVONETE CRISTINA ROCHA",
    "MARCOS AURELIO TAVARES", "DENISE APARECIDA MORAES",
]
SOBRENOMES = ["DA SILVA", "DE SOUZA", "FERREIRA", "OLIVEIRA",
              "SANTOS", "COSTA", "BARBOSA", "PINHEIRO"]
SIGLAS = ["TJPA", "MPPA", "SEFAZ-PA", "SEDUC-PA"]
ORGAOS = ["Tribunal de Justica do Estado do Para",
          "Ministerio Publico do Estado do Para",
          "Ministerio Publico Federal",
          "Defensoria Publica do Estado do Para",
          "Secretaria de Estado de Fazenda",
          "Camara Municipal de Belem",
          "Tribunal Regional Eleitoral do Para"]
CARGOS = ["Juiz de Direito", "Desembargador", "Promotor de Justica",
          "Procurador da Republica", "Defensor Publico",
          "Analista Judiciario", "Escrivao Judicial",
          "Perito Judicial"]
INSTITUICOES = ["Ordem dos Advogados do Brasil - Secao Para",
                "Banco do Brasil S.A.", "Caixa Economica Federal",
                "Universidade Federal do Para",
                "Tribunal de Contas dos Municipios",
                "Instituto Nacional do Seguro Social"]
LOGRADOUROS = ["Rua das Flores", "Av. Almirante Barroso",
               "Tv. Castelo Branco", "Rua dos Mundurucus",
               "Av. Conselheiro Furtado", "Travessa Dom Pedro I",
               "Rua Santo Antonio", "Av. Governador Jose Malcher"]
BAIRROS = ["Centro", "Nazare", "Umarizal", "Reduto", "Batista Campos",
           "Sao Bras", "Marco", "Cidade Velha"]
CIDADES = [("Belem", "PA"), ("Ananindeua", "PA"), ("Santarem", "PA"),
           ("Maraba", "PA"), ("Castanhal", "PA")]


# ---------------- geradores de entidade ----------------
def _dv(digs):
    """Dígito verificador CPF (módulo 11)."""
    for _ in range(2):
        peso = len(digs) + 1
        s = sum(d * (peso - i) for i, d in enumerate(digs))
        digs.append(0 if (r := s * 10 % 11) > 9 else r)
    return digs


def cpf(rng):
    d = _dv([rng.randrange(10) for _ in range(9)])
    return (f"{''.join(map(str, d[:3]))}.{''.join(map(str, d[3:6]))}"
            f".{''.join(map(str, d[6:9]))}-{d[9]}{d[10]}"
            if rng.random() < 0.6 else "".join(map(str, d)))


def rg(rng):
    n = [rng.randrange(10) for _ in range(8)]
    base = f"{n[0]}{n[1]}.{n[2]}{n[3]}{n[4]}.{n[5]}{n[6]}{n[7]}"
    sufixo = rng.choice([f"-{rng.randrange(10)}", "-X", ""])
    uf = rng.choice(["", "PA ", "SSP-PA ", ""])
    return uf + base + sufixo


def email(rng):
    user = rng.choice(NOMES).split()[0].lower()
    dom = rng.choice(["TJPA.JUS.BR", "MPPA.MP.BR", "GMAIL.COM",
                      "SEFAZ.PA.GOV.BR", "HOTMAIL.COM"])
    sep = rng.choice([".", "_", ""])
    return (f"{user}{sep}{rng.choice(SOBRENOMES).split()[-1]}"
            f"@{dom}").upper()


def telefone(rng):
    ddd = rng.choice(["91", "93", "94"])
    cel = rng.random() < 0.6
    if cel:
        meio = f"9{rng.randrange(6, 9)}{rng.randrange(100, 999):03d}"
    else:
        meio = f"{rng.randrange(3, 5)}{rng.randrange(100, 999):03d}"
    fim = f"{rng.randrange(1000, 9999):04d}"
    forma = rng.randrange(4)
    return [f"({ddd}) {meio}-{fim}", f"{ddd} {meio}-{fim}",
            f"({ddd}){meio}{fim}", f"{ddd}{meio}{fim}"][forma]


def endereco(rng):
    cid, uf = rng.choice(CIDADES)
    cep = f"{rng.randrange(66000, 69999)}-{rng.randrange(100, 999):03d}"
    return (f"{rng.choice(LOGRADOUROS)}, {rng.randrange(1, 3000)}, "
            f"{rng.choice(BAIRROS)}, {cid}-{uf}, CEP {cep}")


def nome(rng):
    """Caixa alta ou mista; a cauda pode virar outro sobrenome."""
    n = rng.choice(NOMES)
    if rng.random() < 0.25:
        n = f"{n.split()[0]} {rng.choice(SOBRENOMES)}"
    if rng.random() < 0.5:
        n = n.title()           # caixa mista
    return n


def cnj(rng):
    return (f"{rng.randrange(1000000, 9999999)}-"
            f"{rng.randrange(10, 99)}.{rng.randrange(2019, 2027)}"
            f".8.{rng.randrange(10, 15)}."
            f"{rng.randrange(1000, 9999)}")


def valor(rng):
    v = rng.randrange(500, 250000) + rng.randrange(0, 99) / 100
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",") \
        .replace("X", ".")
    return rng.choice([f"R$ {s}", f"R${s}", f"de R$ {s}"])


def rot_nome(rng):
    return rng.choice(["Sr.", "Sra.", "Dra.", "Dr.", "Exmo. Sr.",
                       "Requerente:", "Autor:", "Reu:",
                       "Testemunha:", "Servidor:", "Impugnante:"])


def rot_endereco(rng):
    return rng.choice(["residente e domiciliado em",
                       "residente e domiciliado a",
                       "Endereco:", "com endereco em", "sito em",
                       "estabelecido em"])


# ---------------- montagem com offsets ----------------
class Montador:
    """Monta o documento segmento a segmento registrando, para
    cada entidade, texto/tipo/inicio/fim/preservar."""
    def __init__(self):
        self.buf, self.ents = [], []

    def txt(self, s):
        self.buf.append(s)
        return self

    def ent(self, s, tipo, preservar=False):
        ini = sum(map(len, self.buf))
        self.ents.append({"texto": s, "tipo": tipo,
                          "inicio": ini, "fim": ini + len(s),
                          "preservar": preservar})
        self.buf.append(s)
        return self

    def doc(self):
        return "".join(self.buf)


def _pessoa(m, rng):
    """Bloco de identificação completo de uma pessoa física."""
    if rng.random() < 0.5:
        m.txt(rot_nome(rng) + " ")
    m.ent(nome(rng), "NOME")
    m.txt(", ")
    if rng.random() < 0.7:
        m.txt(rng.choice(["portador(a) do RG ", "RG n. ",
                          "inscrito no RG sob o n. "]))
        m.ent(rg(rng), "RG")
        m.txt(", ")
    m.txt(rng.choice(["inscrito(a) no CPF sob o n. ", "CPF ",
                      "CPF n. ", ""]))
    m.ent(cpf(rng), "CPF")
    if rng.random() < 0.7:
        m.txt(", ")
        if rng.random() < 0.7:
            m.txt(rot_endereco(rng) + " ")
        m.ent(endereco(rng), "ENDERECO")
    if rng.random() < 0.6:
        m.txt(", e-mail ")
        m.ent(email(rng), "EMAIL")
    if rng.random() < 0.6:
        m.txt(", telefone ")
        m.ent(telefone(rng), "TELEFONE")
    m.txt(". ")


def peticao(m, rng):
    m.txt("EXCELENTISSIMO SENHOR ")
    m.ent(rng.choice(CARGOS), "CARGO", True)
    m.txt(" DA VARA CIVEL DA COMARCA DE ")
    m.ent(rng.choice([c for c, _ in CIDADES]).upper(),
          "CIDADE", True)
    m.txt("\n\nProcesso n. ")
    m.ent(cnj(rng), "CNJ", True)
    m.txt("\n\n")
    _pessoa(m, rng)
    m.txt("vem, por seu advogado, propor a presente ACAO DE "
          "INDENIZACAO em face de ")
    if rng.random() < 0.4:
        m.ent(rng.choice(INSTITUICOES), "INSTITUICAO", True)
    else:
        m.ent(nome(rng), "NOME")
    m.txt(", requerendo a condenacao ao pagamento de ")
    m.ent(valor(rng), "VALOR", True)
    m.txt(" a titulo de danos morais, acrescidos de ")
    m.ent(valor(rng), "VALOR", True)
    m.txt(" de danos materiais.\n\nTermos em que pede "
          "deferimento.\nBelem, PA.")


def despacho(m, rng):
    m.ent(rng.choice(ORGAOS), "ORGAO", True)
    m.txt(" — PODER JUDICIARIO\n\nDESPACHO\n\nProcesso n. ")
    m.ent(cnj(rng), "CNJ", True)
    m.txt(".\n\nIntime-se ")
    m.ent(nome(rng), "NOME")
    m.txt(", via e-mail ")
    m.ent(email(rng), "EMAIL")
    m.txt(" ou telefone ")
    m.ent(telefone(rng), "TELEFONE")
    m.txt(", para manifestacao em 15 dias. Custas de ")
    m.ent(valor(rng), "VALOR", True)
    m.txt(".\n\n")
    m.ent(rng.choice([c for c, _ in CIDADES]), "CIDADE", True)
    m.txt(", PA — Gabinete do ")
    m.ent(rng.choice(CARGOS), "CARGO", True)
    m.txt(".")


def intimacao(m, rng):
    m.txt("INTIMACAO — ")
    m.ent(rng.choice(ORGAOS), "ORGAO", True)
    m.txt("\n\nFica intimado(a) ")
    m.ent(nome(rng), "NOME")
    m.txt(", CPF ")
    m.ent(cpf(rng), "CPF")
    m.txt(", endereco ")
    m.ent(endereco(rng), "ENDERECO")
    m.txt(", do teor da decisao proferida no processo n. ")
    m.ent(cnj(rng), "CNJ", True)
    m.txt(". Contato oficial: ")
    m.ent(email(rng), "EMAIL")
    m.txt(" / ")
    m.ent(telefone(rng), "TELEFONE")
    m.txt(".")


def oficio(m, rng):
    m.txt(f"OFICIO N. {rng.randrange(100, 9999)}/2026-")
    m.ent(rng.choice(SIGLAS), "ORGAO", True)
    m.txt("\n\nAo ")
    m.ent(rng.choice(ORGAOS), "ORGAO", True)
    m.txt(":\n\nEncaminho os dados funcionais do servidor ")
    m.ent(nome(rng), "NOME")
    m.txt(", RG ")
    m.ent(rg(rng), "RG")
    m.txt(", CPF ")
    m.ent(cpf(rng), "CPF")
    m.txt(", e-mail institucional ")
    m.ent(email(rng), "EMAIL")
    m.txt(", telefone ")
    m.ent(telefone(rng), "TELEFONE")
    m.txt(", remuneracao bruta de ")
    m.ent(valor(rng), "VALOR", True)
    m.txt(". Solicito ciencia.\n\n")
    m.ent(rng.choice(CARGOS), "CARGO", True)
    m.txt(" responsavel.")


def contrato(m, rng):
    m.txt("CONTRATO DE PRESTACAO DE SERVICOS\n\nContratante: ")
    if rng.random() < 0.5:
        m.ent(rng.choice(INSTITUICOES), "INSTITUICAO", True)
    else:
        m.ent(nome(rng), "NOME")
        m.txt(", CPF ")
        m.ent(cpf(rng), "CPF")
    m.txt(".\nContratada: ")
    m.ent(nome(rng), "NOME")
    m.txt(", CPF ")
    m.ent(cpf(rng), "CPF")
    m.txt(", endereco ")
    m.ent(endereco(rng), "ENDERECO")
    m.txt(".\nObjeto: servicos no valor global de ")
    m.ent(valor(rng), "VALOR", True)
    m.txt(", conforme processo administrativo n. ")
    m.ent(cnj(rng), "CNJ", True)
    m.txt(" perante o ")
    m.ent(rng.choice(ORGAOS), "ORGAO", True)
    m.txt(".\n\nAssinado digitalmente.")


def certidao(m, rng):
    m.txt("CERTIDAO — ")
    m.ent(rng.choice(ORGAOS), "ORGAO", True)
    m.txt("\n\nCertifico que ")
    m.ent(nome(rng), "NOME")
    m.txt(", RG ")
    m.ent(rg(rng), "RG")
    m.txt(", compareceu a audiencia do processo n. ")
    m.ent(cnj(rng), "CNJ", True)
    m.txt(" realizada nesta data na comarca de ")
    m.ent(rng.choice([c for c, _ in CIDADES]), "CIDADE", True)
    m.txt(", podendo ser contatado(a) pelo telefone ")
    m.ent(telefone(rng), "TELEFONE")
    m.txt(" ou e-mail ")
    m.ent(email(rng), "EMAIL")
    m.txt(".\n\nO presente documento tem plena validade.")


TEMPLATES = [peticao, despacho, intimacao, oficio, contrato,
             certidao]

# ---------------- geração ----------------
def gerar(n_docs, rng, rotulo, ini_idx):
    docs = []
    for i in range(n_docs):
        m = Montador()
        rng.choice(TEMPLATES)(m, rng)
        texto = m.doc()
        # coerência do gabarito: offsets apontam o texto exato
        for e in m.ents:
            assert texto[e["inicio"]:e["fim"]] == e["texto"]
        nome_doc = f"doc-{ini_idx + i:04d}"
        docs.append({
            "nome": nome_doc, "texto": texto,
            "gabarito": {"documento": f"{nome_doc}.txt",
                         "pdf": f"{nome_doc}.pdf",
                         "particao": rotulo,
                         "entidades": m.ents}})
    return docs


def sha256_de(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _wrap_seguro(texto, ents, largura_mm=180.0):
    """Requebra o texto em linhas <= largura_mm sem nunca partir
    uma entidade: espacos dentro de um span de entidade nao sao
    ponto de quebra (a entidade inteira vira um atomo). '\n'
    originais permanecem quebras duras. A largura e medida com a
    mesma fonte que pdf_de_texto usa (helvetica 11) — assim o
    multi_cell nao precisa adicionar nenhuma quebra propria."""
    from fpdf import FPDF
    med = FPDF()
    med.add_page()
    med.set_font("helvetica", size=11)
    # mesma conversao latin-1 que pdf_de_texto aplica, para que a
    # largura medida seja exatamente a do texto renderizado
    texto = texto.encode("latin-1", "replace").decode("latin-1")
    prot = set()
    for e in ents:
        prot.update(range(e["inicio"], e["fim"]))
    atomos, seg = [], ""
    for i, c in enumerate(texto):
        if c == "\n" or (c == " " and i not in prot):
            atomos.append(seg)
            seg = ""
            if c == "\n":
                atomos.append("\n")
        else:
            seg += c
    atomos.append(seg)
    linhas, linha = [], ""
    for a in atomos:
        if a == "\n":
            linhas.append(linha)
            linha = ""
            continue
        cand = a if not linha else linha + " " + a
        if not linha or med.get_string_width(cand) <= largura_mm:
            linha = cand
        else:
            linhas.append(linha)
            linha = a
    linhas.append(linha)
    for l in linhas:
        assert med.get_string_width(l) <= 185, \
            f"linha excede a pagina: {l[:70]!r}"
    return "\n".join(linhas)


_MANIFESTO = """\
# CORPUS SINTETICO/FABRICADO — nenhum dado real de pessoa
# fisica ou de processo. Entidades geradas por
# scripts/gerar_corpus.py (seed 20261020), deterministico.
# Gabaritos (*.json) apontam para o .txt original; o .pdf e
# apenas renderizacao via pdf_de_texto (fpdf2).
# Desvio do plano: particao teste = 80 docs (plano previa 70;
# total = 110 vs. 100 previstos) — quantidade mantida por
# aprovacao expressa do requisitante apos a geracao.
# Metrica principal do motor: medida sobre o .txt (gabarito).
# Metrica de extracao: medida sobre o .pdf (extrair_texto) —
# sao avaliacoes separadas e reportadas separadamente.
# REGENERADO: PDFs re-renderizados com quebra segura por
# entidade (_wrap_seguro); .txt e .json byte-identicos.
"""


def gravar(particao, docs, base: Path, hash_gerador: str):
    pasta = base / particao
    pasta.mkdir(parents=True, exist_ok=True)
    linhas, hashes = [f"GEN  {hash_gerador}  "
                      "../../scripts/gerar_corpus.py"], []
    for d in docs:
        tb = d["texto"].encode("utf-8")
        pb = pdf_de_texto(_wrap_seguro(
            d["texto"], d["gabarito"]["entidades"]))  # renderiza
        jb = (json.dumps(d["gabarito"], ensure_ascii=False,
                         indent=2) + "\n").encode("utf-8")
        (pasta / f"{d['nome']}.txt").write_bytes(tb)
        (pasta / f"{d['nome']}.pdf").write_bytes(pb)
        (pasta / f"{d['nome']}.json").write_bytes(jb)
        for arq, b in ((f"{d['nome']}.txt", tb),
                       (f"{d['nome']}.pdf", pb),
                       (f"{d['nome']}.json", jb)):
            h = sha256_de(b)
            linhas.append(f"{h}  {arq}")
            hashes.append(h)
    conjunto = sha256_de("".join(hashes).encode())
    (pasta / "SHA256SUMS").write_text(
        _MANIFESTO + "\n".join(linhas) + f"\nSET  {conjunto}\n",
        encoding="utf-8")
    return conjunto


def distribuicao(docs):
    dist = {}
    for d in docs:
        for e in d["gabarito"]["entidades"]:
            k = e["tipo"] + ("(preservar)" if e["preservar"] else "")
            dist[k] = dist.get(k, 0) + 1
    return dist


def main():
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    rng = random.Random(SEMENTE)
    hash_gerador = sha256_de(
        Path(__file__).read_bytes())
    idx = 0
    resumo = {}
    for particao, n in PARTICOES.items():
        docs = gerar(n, rng, particao, idx)
        idx += n
        resumo[particao] = (gravar(particao, docs, base,
                                   hash_gerador),
                            distribuicao(docs), len(docs))
    for p, (h, dist, n) in resumo.items():
        print(f"[{p}] {n} docs — SET {h[:16]}…")
        for tipo, qtd in sorted(dist.items()):
            print(f"    {tipo:<22} {qtd}")
    print(f"GEN  {hash_gerador}")
    print(f"corpus em {base}/")


if __name__ == "__main__":
    main()
