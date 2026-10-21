"""Corpus sintético v0 — gerador de documentos processuais com
gabarito automático (gold spans + clusters de correferência).

NÃO é validade externa: mede o gap dos componentes (validadores,
NER stock, motor de correferência) sob texto limpo de template.
Saída: spikes/corpus_v0.jsonl — {id, text, gold:[{text,start,end,type,ent}]}
"""
import json, random

random.seed(42)

NOMES_M = ["João da Silva", "Pedro Alves Rocha", "Carlos Mota Lima",
           "Roberto Farias", "André Reis Monteiro", "Marcos Paulo Sá",
           "Felipe Duarte", "Ricardo Nunes Prado", "Tiago Ferreira",
           "Luís Otávio Ramos"]
NOMES_F = ["Maria Costa Souza", "Ana Beatriz Melo", "Cláudia Regina Paz",
           "Fernanda Oliveira", "Patrícia Almeida", "Juliana Castro Reis",
           "Renata Duarte Lima", "Sônia Maria Freitas", "Carla Nogueira",
           "Beatriz Santos Reis"]
SOBR = ["Silva", "Costa", "Alves", "Farias", "Reis", "Mota", "Duarte",
        "Nunes", "Prado", "Ramos", "Melo", "Paz", "Lima", "Castro"]

def cpf():
    d = [random.randint(0, 9) for _ in range(9)]
    d += [sum(d[i] * (10 - i) for i in range(9)) * 10 % 11 % 10]
    d += [sum(d[i] * (11 - i) for i in range(10)) * 10 % 11 % 10]
    return f"{''.join(map(str, d[:3]))}.{''.join(map(str, d[3:6]))}.{''.join(map(str, d[6:9]))}-{d[9]}{d[10]}"

def cnj():
    return f"{random.randint(1000000,9999999)}-{random.randint(10,99)}." \
           f"{random.randint(2020,2026)}.8.{random.randint(10,26)}." \
           f"{random.randint(1000,9999)}"

class Doc:
    def __init__(self, did):
        self.id, self.parts, self.gold, self.pos = did, [], [], 0
    def t(self, s):
        self.parts.append(s); self.pos += len(s); return self
    def e(self, s, typ, ent=None):
        self.gold.append(dict(text=s, start=self.pos,
                              end=self.pos + len(s), type=typ, ent=ent))
        return self.t(s)
    def out(self):
        return dict(id=self.id, text="".join(self.parts), gold=self.gold)

def peticao(i, nm, nf):
    """Autor × réu, com identificadores e correferência básica."""
    d = Doc(f"pet{i:02d}")
    a, r = f"E{len(nm)+i}a", f"E{len(nf)+i}r"
    d.t(f"Processo nº ").e(cnj(), "PROCESSO_CNJ") \
     .t(". PETIÇÃO INICIAL. O autor ")
    d.e(nm, "PESSOA", a).t(", brasileiro, inscrito no CPF sob o nº ")
    d.e(cpf(), "CPF", a).t(", residente no CEP ")
    d.e(f"66{random.randint(100,999)}-{random.randint(100,999)}", "CEP") \
     .t(", propõe a presente ação contra a ré ")
    d.e(nf, "PESSOA", r).t(", portadora da OAB/PA nº ")
    d.e(f"{random.randint(10000,99999)}", "OAB", r).t(". ")
    d.t("O autor ").t("alega que ").e("a ré", "PESSOA", r) \
     .t(" deixou de cumprir obrigação contratual. ").e("Ele", "PESSOA", a) \
     .t(" requer indenização por danos morais. A testemunha ")
    d.e(random.choice(NOMES_M), "PESSOA", f"T{i}") \
     .t(" confirmará os fatos em audiência.")
    return d

def decisao(i, nm, nf):
    """Decisão judicial com discurso anaforico."""
    d = Doc(f"dec{i:02d}")
    a, r, j = f"A{i}", f"R{i}", f"J{i}"
    d.t(f"DECISÃO. Processo ").e(cnj(), "PROCESSO_CNJ").t(". ")
    d.t("Vistos. O autor ").e(nm, "PESSOA", a)
    d.t(" requereu tutela de urgência contra a ré ")
    d.e(nf, "PESSOA", r).t(". ")
    d.e("O referido autor", "PESSOA", a).t(" comprovou o fumus boni iuris. ")
    d.t("Defiro o pedido. Intime-se ").e("a ré", "PESSOA", r)
    d.t(". O juiz ").e(random.choice(NOMES_M), "PESSOA", j)
    d.t(", em ").e(f"{random.randint(1,28)} de março de 2026", "DATA_NASC")
    d.t(", assim decidiu.")
    return d

def parentesco(i, nm, nf):
    """Parentesco: filho/esposa geram entidades novas com REL."""
    d = Doc(f"kin{i:02d}")
    a, f = f"A{i}", f"K{i}"
    filho = random.choice(NOMES_M)
    d.t("O autor ").e(nm, "PESSOA", a) \
     .t(" compareceu em audiência acompanhado de seu filho ")
    d.e(filho, "PESSOA", f).t(". ")
    d.e("A esposa do autor", "PESSOA", f"K{i}b") \
     .t(", ").e(nf, "PESSOA", f"K{i}b") \
     .t(", também esteve presente. ")
    d.e("O autor", "PESSOA", a).t(" declarou que ")
    d.e("seu filho", "PESSOA", f).t(" presenciou o ocorrido.")
    return d

def depoimento(i, nm):
    """Depoimento com pronomes e honoríficos."""
    d = Doc(f"dep{i:02d}")
    w = f"W{i}"
    d.t("DEPOIMENTO. A testemunha ").e(nm, "PESSOA", w)
    d.t(", inscrita no CPF nº ").e(cpf(), "CPF", w)
    d.t(", telefone ").e(f"(91) 9{random.randint(8000,9999)}-{random.randint(1000,9999)}", "TELEFONE", w)
    d.t(", afirmou que estava presente. ").e("Ela", "PESSOA", w)
    d.t(" declarou conhecer o réu. Perguntada, ")
    d.e("a testemunha", "PESSOA", w).t(" manteve a versão. ")
    d.t("A Sra. ").e(nm.split()[-1], "PESSOA", w) \
     .t(" ratificou o depoimento.")
    return d

def sentenca(i, nm, nf):
    """Sentença com papéis múltiplos e e-mail."""
    d = Doc(f"sen{i:02d}")
    a, r, adv = f"A{i}", f"R{i}", f"V{i}"
    d.t(f"SENTENÇA — Processo ").e(cnj(), "PROCESSO_CNJ").t(". ")
    d.e(nm, "PESSOA", a).t(", autor,") \
     .t(" moveu ação contra ").e(nf, "PESSOA", r)
    d.t(", ré, representada pelo advogado ")
    d.e(random.choice(NOMES_M), "PESSOA", adv)
    d.t(", e-mail ").e(f"adv{i}@escritorio.adv.br", "EMAIL", adv)
    d.t(". JULGO PROCEDENTE o pedido d").e("o autor", "PESSOA", a)
    d.t(". ").e("A ré", "PESSOA", r) \
     .t(" pagará indenização de R$ ")
    d.e(f"{random.randint(5,50)}.000,00", "VALOR")
    d.t(". Custas por ").e("ela", "PESSOA", r).t(".")
    return d

def execut(i, nm):
    """Execução: exequente × executado, catáfora conservadora."""
    d = Doc(f"exe{i:02d}")
    a, r = f"X{i}", f"Y{i}"
    d.t("EXECUÇÃO. O exequente ").e(nm, "PESSOA", a) \
     .t(" requereu penhora de bens do executado ")
    d.e(random.choice(NOMES_M), "PESSOA", r).t(". ")
    d.e("O executado", "PESSOA", r).t(" foi citado. ")
    d.e("Ele", "PESSOA", r).t(" não apresentou embargos. ")
    d.e("O exequente", "PESSOA", a).t(" requereu prosseguimento.")
    return d

# ---- geração ----
docs, i = [], 0
for k in range(6):
    nm = random.choice(NOMES_M); nf = random.choice(NOMES_F)
    docs += [peticao(k, nm, nf), decisao(k, nm, nf),
             parentesco(k, nm, nf), depoimento(k, random.choice(NOMES_F)),
             sentenca(k, nm, nf), execut(k, nm)]

with open("spikes/corpus_v0.jsonl", "w", encoding="utf-8") as f:
    for d in docs:
        f.write(json.dumps(d.out(), ensure_ascii=False) + "\n")

n_ent = sum(len(d.gold) for d in docs)
n_pe  = sum(1 for d in docs for g in d.gold if g["type"] == "PESSOA")
print(f"{len(docs)} documentos | {n_ent} entidades gold | {n_pe} PESSOA")
