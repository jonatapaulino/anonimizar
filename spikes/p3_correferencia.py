"""P3 — Spike: motor simbólico de correferência (Linked Entities, ADR-0002).

Pergunta: regras determinísticas conseguem consistência ≥0,90 em
correferência de documentos jurídicos pt-BR? Este spike constrói as
primeiras regras e mede sobre casos artesanais com gabarito.

Fenômenos cobertos:
  - repetição de nome completo / parcial (João, Sr. Silva)
  - papel processual ("o autor", "a ré", "a requerente")
  - discurso anaforico ("o referido autor", "o mesmo", "a mencionada")
  - pronomes com restrição de gênero ("ele", "ela")
  - possessivo conservador ("seu/sua" só quando inequívoco)
  - parentesco ("seu filho Pedro", "esposa do autor") -> REL
  - apositivos ("o médico André Reis", "João Silva, comerciante")
  - anti-merge: sobrenome compartilhado NÃO funde entidades
  - anti-link: primeiro nome ambíguo NÃO vincula (conservador)
"""
import re
import unicodedata

def fold(s):
    return unicodedata.normalize("NFC", s).lower().strip()

# ---------- léxico ----------
# papel -> (canonico, genero inerente: M/F/N)
ROLES = {
    "autor": ("autor", "M"), "autora": ("autor", "F"),
    "réu": ("reu", "M"), "ré": ("reu", "F"),
    "requerente": ("requerente", "N"),
    "requerido": ("requerido", "M"), "requerida": ("requerido", "F"),
    "reclamante": ("reclamante", "N"),
    "reclamado": ("reclamado", "M"), "reclamada": ("reclamado", "F"),
    "exequente": ("exequente", "N"),
    "executado": ("executado", "M"), "executada": ("executado", "F"),
    "impetrante": ("impetrante", "N"),
    "advogado": ("advogado", "M"), "advogada": ("advogado", "F"),
    "testemunha": ("testemunha", "F"),
    "perito": ("perito", "M"), "perita": ("perito", "F"),
    "médico": ("medico", "M"), "médica": ("medico", "F"),
    "juiz": ("juiz", "M"), "juíza": ("juiz", "F"),
    "empresário": ("empresario", "M"), "empresária": ("empresario", "F"),
    "credor": ("credor", "M"), "credora": ("credor", "F"),
    "devedor": ("devedor", "M"), "devedora": ("devedor", "F"),
    "menor": ("menor", "N"), "vítima": ("vitima", "F"),
    "servidor": ("servidor", "M"), "servidora": ("servidor", "F"),
    "funcionário": ("funcionario", "M"), "funcionária": ("funcionario", "F"),
    "sócio": ("socio", "M"), "sócia": ("socio", "F"),
    "motorista": ("motorista", "M"), "policial": ("policial", "N"),
    "delegado": ("delegado", "M"), "delegada": ("delegado", "F"),
    "magistrado": ("magistrado", "M"), "magistrada": ("magistrado", "F"),
    "embargante": ("embargante", "N"),
    "apelante": ("apelante", "N"), "apelado": ("apelado", "M"),
    "bancário": ("bancario", "M"), "bancária": ("bancario", "F"),
    "comerciante": ("comerciante", "N"), "empregador": ("empregador", "M"),
    "segurado": ("segurado", "M"), "segurada": ("segurado", "F"),
    "paciente": ("paciente", "N"),
}
KIN = {"filho": ("filho", "M"), "filha": ("filho", "F"),
       "esposo": ("esposo", "M"), "esposa": ("esposa", "F"),
       "pai": ("pai", "M"), "mãe": ("mae", "F"),
       "irmão": ("irmao", "M"), "irmã": ("irmao", "F")}
DISC = {"referido", "referida", "mencionado", "mencionada",
        "supracitado", "supracitada", "suprarreferido", "suprarreferida",
        "dito", "dita", "mesmo", "mesma", "citado", "citada"}

NAME = r"[A-ZÀ-ÖØ-Þ][a-záéíóúâêôãõçü]+(?:(?:\s(?:da|de|do|das|dos))?\s+[A-ZÀ-ÖØ-Þ][a-záéíóúâêôãõçü]+)*"
# palavras que parecem nome mas não são (pronomes, honoríficos, início
# de frase genérico) — excluídas da passada de NAME solto
STOPNAME = {"ele", "ela", "este", "esta", "esse", "essa", "isso",
            "aquele", "aquela", "sr", "sra", "dr", "dra", "exmo",
            "exma", "o", "a", "os", "as"}
ROLE_RE = "|".join(sorted(ROLES, key=len, reverse=True))
KIN_RE = "|".join(KIN)
ART = r"(?:o|a|os|as|do|da|pelo|pela|ao|à)"
CI = lambda p: f"(?i:{p})"   # case-insensitive scopado — NAME fica sensível


def canon_role(rsurf):
    r = fold(rsurf)
    if r in ROLES: return ROLES[r][0]
    if r.endswith("s") and r[:-1] in ROLES: return ROLES[r[:-1]][0]   # pl -s
    if r.endswith("es") and r[:-2] in ROLES: return ROLES[r[:-2]][0]  # pl -es
    return None

class Ent:
    def __init__(self, eid):
        self.id, self.name, self.roles = eid, None, set()
        self.gender, self.kin = None, []

class Mention:
    def __init__(self, text, start, kind, ent):
        self.text, self.start, self.kind, self.ent = text, start, kind, ent

class Engine:
    def __init__(self):
        self.ents, self.mentions, self.last = [], [], []

    def _new(self, name=None, role=None, gender=None):
        e = Ent(len(self.ents))
        e.name, e.gender = name, gender
        if role: e.roles.add(role)
        self.ents.append(e)
        return e

    def _by_name(self, name):
        n = fold(name)
        return [e for e in self.ents if e.name and fold(e.name) == n]

    def _by_first(self, first):
        f = fold(first)
        return [e for e in self.ents
                if e.name and fold(e.name.split()[0]) == f]

    def _by_surname(self, surname):
        s = fold(surname)
        return [e for e in self.ents
                if e.name and s in fold(e.name).split()[1:]]

    def _by_role(self, rcanon):
        return [e for e in self.ents if rcanon in e.roles]

    def _gender(self, art, rsurf, name=None):
        art = fold(art) if art else None
        if art:
            if art in ("a", "as", "da", "pela", "à"): return "F"
            if art in ("o", "os", "do", "pelo", "ao"): return "M"
        g = ROLES.get(fold(rsurf), (None, None))[1]
        if g and g != "N": return g
        if name:
            first = fold(name).split()[0]   # primeiro nome, não sobrenome
            if first.endswith("a"): return "F"
            if first.endswith(("o", "r", "l")): return "M"
        return None

    def _link_role(self, rcanon, gender=None):
        """Vincula menção de papel à entidade titular (única) ou cria."""
        cand = [e for e in self._by_role(rcanon)]
        if len(cand) == 1:
            return cand[0]
        e = self._new(role=rcanon, gender=gender)
        return e

    def _link_name(self, name, role=None, gender=None):
        full = self._by_name(name)
        if full:
            e = full[0]
            if role: e.roles.add(role)
            if gender and not e.gender: e.gender = gender
            return e
        # entidade de papel sem nome que "casa" com esta menção?
        if role:
            cand = [e for e in self._by_role(role) if e.name is None]
            if len(cand) == 1:
                cand[0].name = name
                if gender: cand[0].gender = gender
                return cand[0]
        return self._new(name=name, role=role, gender=gender)

    def _link_pronoun(self, surf):
        g = "M" if fold(surf) in ("ele", "este", "esse") else "F"
        for e in self.last:
            if e.gender == g or e.gender is None:
                if g == "F" and e.gender == "M": continue
                if g == "M" and e.gender == "F": continue
                return e
        return None

    def _link_possessive(self):
        """seu/sua: só vincula se últimas ≤2 menções têm 1 só entidade."""
        recent = []
        for e in self.last:
            if e not in recent:
                recent.append(e)
            if len(recent) >= 2:
                break
        return recent[0] if len(recent) == 1 else None

    def _mention(self, text, start, kind, ent):
        m = Mention(text, start, kind, ent)
        self.mentions.append(m)
        if ent and kind != "poss":
            self.last.insert(0, ent)
        elif ent:
            self.last.insert(0, ent)
        return m

    def analyze(self, text):
        marks = []  # (start,end) já consumidos por padrões específicos
        def busy(s, e):
            return any(s < me and e > ms for ms, me in marks)
        def take(s, e):
            marks.append((s, e))

        # 0) copular de parentesco: "NAME é/era KIN de|do|da X"
        for m in re.finditer(
            rf"\b({NAME})\s+(?:é|era|seria)\s+{CI(ART)}?\s*({KIN_RE})\s+"
            rf"(?:d[oe]|d')\s+({CI(ART)}\s+{CI(ROLE_RE)}|{NAME})", text):
            name, ksurf, anch = m.group(1), fold(m.group(2)), m.group(3)
            kcanon, kg = KIN[ksurf]
            anchor = None
            rm = re.match(rf"{CI(ART)}\s+({CI(ROLE_RE)})", anch)
            rbare = canon_role(anch)
            if rm:
                rcanon = canon_role(re.search(ROLE_RE, rm.group(2), re.I).group(0))
                anchor = self._link_role(rcanon)
            elif rbare:
                anchor = self._link_role(rbare)
            else:
                hits = self._by_name(anch) or self._by_first(anch.split()[0])
                anchor = hits[0] if len(hits) == 1 else None
            e = self._link_name(name)
            e.roles.add(kcanon)
            if kg and not e.gender: e.gender = kg
            if anchor: e.kin.append((anchor, kcanon))
            self._mention(name, m.start(1), "name", e)
            take(m.end(1), m.end())   # NAME fica livre p/ "a ré Maria é..."

        # 1) "ART ROLE NAME?"  — "o autor João da Silva" / "a ré"
        for m in re.finditer(
            rf"\b({CI(ART)})\s+({CI(ROLE_RE)})\b(?:\s+({NAME}))?", text):
            art, rsurf, name = m.group(1), m.group(2), m.group(3)
            rcanon = canon_role(rsurf)
            g = self._gender(art, rsurf, name)
            if name:
                e = self._link_name(name, role=rcanon, gender=g)
                # submenções: "o autor" e "João da Silva" avaliáveis a parte
                am = re.match(rf"({CI(ART)})\s+({CI(ROLE_RE)})",
                              m.group(0))
                role_txt = am.group(0)
                self._mention(role_txt, m.start(), "role", e)
                nstart = m.start(3)
                self._mention(name, nstart, "name", e)
            else:
                e = self._link_role(rcanon, gender=g)
                self._mention(m.group(0), m.start(), "role", e)
            take(m.start(), m.end())

        # 1b) apositivos com vírgula:
        #     "o autor, João da Silva,"  e  "Maria Souza, requerente,"
        for m in re.finditer(
            rf"\b({CI(ART)}\s+{CI(ROLE_RE)})\s*,\s*({NAME})", text):
            role_txt, name = m.group(1), m.group(2)
            rcanon = canon_role(re.search(ROLE_RE, role_txt, re.I).group(0))
            e = self._link_name(name, role=rcanon)
            self._mention(role_txt, m.start(1), "role", e)
            self._mention(name, m.start(2), "name", e)
            take(m.start(), m.end())
        for m in re.finditer(
            rf"\b({NAME})\s*,\s*(?:{CI(ART)}\s+)?({CI(ROLE_RE)})\s*,", text):
            if busy(m.start(), m.end()): continue
            name, rsurf = m.group(1), m.group(2)
            e = self._link_name(name, role=canon_role(rsurf))
            self._mention(name, m.start(1), "name", e)
            rstart = m.start(2)
            self._mention(rsurf, rstart, "role", e)
            take(m.start(), m.end())

        # 2) parentesco: "KIND (de|do|da|d') ANCHOR?" onde ANCHOR é
        #    "ART ROLE" (filho do autor) ou NAME (filho de Maria —
        #    a não ser precedido de possessivo, aí NAME é o parente).
        for m in re.finditer(
            rf"\b({CI(KIN_RE)})\s+((?i:d[oe]|d')\s+"
            rf"({CI(ART)}\s+{CI(ROLE_RE)}|{NAME})|({NAME}))?", text):
            if busy(m.start(), m.end()): continue
            ksurf = fold(m.group(1))
            kcanon, kg = KIN[ksurf]
            anchor_txt = m.group(3)    # com preposição
            child_name = m.group(4)    # NAME direto (possessivo implícito)
            anchor = None
            if anchor_txt:
                rm = re.match(rf"{CI(ART)}\s+({CI(ROLE_RE)})", anchor_txt)
                rbare = canon_role(anchor_txt)  # "do autor"→"autor"
                if rm:
                    rsurf = re.search(ROLE_RE, rm.group(2), re.I).group(0)
                    anchor = self._link_role(canon_role(rsurf))
                    am = re.search(re.escape(anchor_txt),
                                   text[m.start():m.end()])
                    astart = m.start() + (am.start() if am else 0)
                    self._mention(anchor_txt, astart, "role", anchor)
                elif rbare:
                    anchor = self._link_role(rbare)
                    am = re.search(re.escape(anchor_txt),
                                   text[m.start():m.end()])
                    astart = m.start() + (am.start() if am else 0)
                    self._mention(anchor_txt, astart, "role", anchor)
                else:
                    hits = self._by_name(anchor_txt) or \
                           self._by_first(anchor_txt.split()[0])
                    anchor = hits[0] if len(hits) == 1 else None
            e = self._new(role=kcanon, gender=kg)
            if child_name:
                e.name = child_name
            if anchor:
                e.kin.append((anchor, kcanon))
            self._mention(m.group(0), m.start(), "kin", e)
            # apositivo pós-parentesco: "esposa do autor, Maria,"
            am = re.match(rf"\s*,\s*({NAME})\s*,", text[m.end():])
            if am:
                e.name = am.group(1)
                g = self._gender(None, "", am.group(1))
                if g and not e.gender: e.gender = g
                self._mention(am.group(1),
                              m.end() + am.start(1), "name", e)
                take(m.start(), m.end() + am.end())
            else:
                take(m.start(), m.end())

        # 3) discurso: "o referido ROLE" / "o mesmo" / "a mencionada"
        for m in re.finditer(
            rf"\b{CI('o|a')}\s+({CI('|'.join(sorted(DISC)))})"
            rf"(?:\s+({CI(ROLE_RE)}))?", text):
            if busy(m.start(), m.end()): continue
            if m.group(2):   # grupo 1 = palavra de discurso; 2 = papel
                e = self._link_role(canon_role(m.group(2)))
            else:
                prior = [(m2.start, m2.ent) for m2 in self.mentions
                         if m2.ent and m2.start < m.start()]
                e = prior[-1][1] if prior else None
            self._mention(m.group(0), m.start(), "disc", e)
            take(m.start(), m.end())

        # 3b) honoríficos — detecta span aqui (antes do NAME solto),
        #     mas RESOLVE na 2ª passada: "Sr. Silva" depende de
        #     "João da Silva" já existir como entidade
        hon_pendentes = []
        for m in re.finditer(
            rf"\b({CI('o|a')}\s+)?{CI('(Sr|Sra)')}\.\s+({NAME})", text):
            if busy(m.start(), m.end()): continue
            hon_pendentes.append(
                (m.group(0).strip(), m.start(), fold(m.group(2) or ""),
                 m.group(3)))
            take(m.start(), m.end())

        # 4) NAME solto (>=2 palavras capitalizadas)
        for m in re.finditer(rf"\b{NAME}\b(?!\w)", text):
            if busy(m.start(), m.end()): continue
            name = m.group(0)
            w0 = fold(name).split()[0]
            # não é nome: pronome/honorífico/discurso; abreviatura é
            # palavra ÚNICA seguida de ponto ("Sr.") — nome multi-palavra
            # antes de ponto final de frase deve continuar valendo
            if w0 in STOPNAME or (len(name.split()) == 1 and
                                  text[m.end():m.end()+1] == "."):
                continue
            if len(name.split()) >= 2:
                e = self._link_name(name)
            else:
                cand = self._by_first(name)
                e = cand[0] if len(cand) == 1 else None  # ambíguo -> None
            self._mention(name, m.start(), "name", e)
            take(m.start(), m.end())

        # 5) pronomes / possessivo / honorífico — RESOLVE EM 2ª PASSADA
        #    (recência só existe na ordem real do texto)
        pendentes = []
        for m in re.finditer(
            rf"\b{CI('ele|ela|este|esta|esse|essa|seu|sua|seus|suas')}\b",
            text):
            if busy(m.start(), m.end()): continue
            p = fold(m.group(0))
            kind = "poss" if p in ("seu", "sua", "seus", "suas") \
                   else "pron"
            pendentes.append((m.group(0), m.start(), kind, p))
            take(m.start(), m.end())

        # segunda passada: resolve pron/poss pela história ordenada —
        # para cada pendente, candidatos = menções anteriores no texto
        for text_m, start, hon, nm in hon_pendentes:
            cand = self._by_name(nm)
            if not cand and len(nm.split()) == 1:
                cand = self._by_surname(nm)
            if hon == "sra":
                cand = [c for c in cand if c.gender != "M"]
            elif hon == "sr":
                cand = [c for c in cand if c.gender != "F"]
            e = cand[0] if len(cand) == 1 else None
            # honorífico+nome é âncora identitária: cria entidade mesmo
            # sem antecedente ("o Sr. Meira" introduz a pessoa)
            if e is None:
                e = self._new(name=nm,
                              gender="F" if hon == "sra" else "M")
            self._mention(text_m, start, "honor", e)

        hist = [(m.start, m.ent) for m in self.mentions if m.ent]
        for text_m, start, kind, p in pendentes:
            prior = [e for s, e in hist if s < start]
            dedup = []
            for e in reversed(prior):
                if e not in dedup:
                    dedup.append(e)
            self.last = dedup
            e = self._link_possessive() if kind == "poss" \
                else self._link_pronoun(p)
            self._mention(text_m, start, kind, e)
            if e:
                hist.append((start, e))

        # pós-passada: nome solto sem papel X papel-parte sem nome —
        # se existir EXATAMENTE um de cada, é o mesmo sujeito
        # ("O autor compareceu. João da Silva assinou."). Regra
        # estreita de propósito: over-link é o pior erro, então só
        # funde no caso 1×1 inequívoco.
        PARTE = {"autor", "reu", "requerente", "requerido",
                 "reclamante", "reclamado", "exequente", "executado",
                 "impetrante", "impetrado", "embargante", "embargado",
                 "apelante", "apelado"}
        sem_nome = [e for e in self.ents
                    if e.name is None and e.roles & PARTE]
        sem_papel = [e for e in self.ents
                     if e.name and not e.roles and not e.kin]
        if len(sem_nome) == 1 and len(sem_papel) == 1:
            a, b = sem_nome[0], sem_papel[0]
            a.name, a.gender = b.name, b.gender
            for m in self.mentions:
                if m.ent is b:
                    m.ent = a
            self.ents.remove(b)

        self.mentions.sort(key=lambda m: m.start)
        return self.mentions


# ---------- bateria de casos ----------
CASOS = [
  dict(id=1, texto="O autor João da Silva propôs a ação. João da Silva alega dano moral.",
       corref=[["o autor", "João da Silva", "João da Silva"]]),
  dict(id=2, texto="Maria Souza, requerente, narra que o réu Pedro Alves a agrediu. Pedro Alves nega. A requerente pede indenização.",
       corref=[["Maria Souza", "requerente", "a requerente"],
               ["o réu", "Pedro Alves", "Pedro Alves"]]),
  dict(id=3, texto="Os sócios Carlos Lima e Roberto Lima divergem. Carlos Lima vendeu sua parte.",
       corref=[["Carlos Lima", "Carlos Lima"]],
       separados=[("Carlos Lima", "Roberto Lima")]),
  dict(id=4, texto="João da Silva depôs em audiência. João afirmou que estava presente.",
       corref=[["João da Silva", "João"]]),
  dict(id=5, texto="O réu Pedro Alves compareceu. Ele negou os fatos.",
       corref=[["o réu", "Pedro Alves", "ele"]]),
  dict(id=6, texto="O autor João e a testemunha Ana estavam presentes. Ela confirmou os fatos.",
       corref=[["a testemunha", "Ana", "ela"]],
       separados=[("João", "ela")]),
  dict(id=7, texto="O autor Carlos Mota pediu indenização. O referido autor anexou documentos.",
       corref=[["o autor", "Carlos Mota", "o referido autor"]]),
  dict(id=8, texto="O autor João da Silva compareceu com seu filho Pedro da Silva.",
       corref=[["o autor", "João da Silva", "seu"]],
       entidade_nova=["Pedro da Silva"]),
  dict(id=9, texto="O autor recorreu. A ré Maria Costa é esposa do autor.",
       corref=[["a ré", "Maria Costa"]],
       entidade_nova=["Maria Costa"]),
  dict(id=10, texto="O empresário Roberto Farias foi ouvido. O mesmo relatou os fatos.",
       corref=[["o empresário", "Roberto Farias", "o mesmo"]]),
  dict(id=11, texto="O médico André Reis atendeu a vítima no hospital.",
       corref=[["o médico", "André Reis"]]),
  dict(id=12, texto="A reclamada, Empresa X Ltda., foi citada para contestar.",
       corref=[["a reclamada"]]),
  dict(id=13, texto="O credor Jorge Pires cobrou o débito. O dito credor persistiu na cobrança.",
       corref=[["o credor", "Jorge Pires", "o dito credor"]]),
  dict(id=14, texto="O autor relatou que seu advogado protocolou a petição.",
       corref=[["o autor", "seu"]]),
  dict(id=15, texto="O autor encontrou o réu na saída. Seu carro estava estacionado.",
       nao_resolver=["seu"]),
  dict(id=16, texto="Compareceu o Sr. João Meira à delegacia.",
       corref=[["o Sr. João Meira"]]),
  dict(id=17, texto="João da Silva depôs pela manhã. O Sr. Silva retornou à tarde.",
       corref=[["João da Silva", "o Sr. Silva"]]),
  dict(id=18, texto="A autora pede guarda. O menor M. P. S. é filho da autora.",
       corref=[["a autora", "da autora"]]),
  dict(id=19, texto="A ré compareceu à audiência. A mesma juntou procuração.",
       corref=[["a ré", "a mesma"]]),
  dict(id=20, texto="Os autores João Silva e Pedro Reis alegam concorrência desleal.",
       corref=[["João Silva"], ["Pedro Reis"]],
       separados=[("João Silva", "Pedro Reis")]),
  dict(id=21, texto="Houve dano causado pelo réu ao patrimônio do autor.",
       corref=[["pelo réu"], ["do autor"]]),
  dict(id=22, texto="A empresa empregadora não pagou o salário. A reclamada foi citada.",
       corref=[["a reclamada"]]),
  dict(id=23, texto="O autor requereu a citação. O autor, João da Silva, alega fato novo.",
       corref=[["o autor", "o autor", "João da Silva"]]),
  dict(id=24, texto="João Silva e João Pereira foram ouvidos. João afirmou a versão.",
       nao_resolver=["João"]),
  # ---- casos duros: honestidade do sinal ----
  dict(id=25, texto="O autor compareceu. João da Silva assinou o termo. "
                    "Em audiência posterior, o autor reiterou.",
       corref=[["o autor", "João da Silva", "o autor"]]),
  dict(id=26, texto="João Silva e sua esposa foram ouvidos.",
       corref=[["João Silva", "sua"]]),
  dict(id=27, texto="A penhora foi requerida pelo autor e recusada pela ré.",
       corref=[["pelo autor"], ["pela ré"]]),
  dict(id=28, texto="Antes de depor, ela foi orientada pelo advogado. "
                    "Maria Costa, a autora, então depôs.",
       nao_resolver=["ela"]),     # catáfora: conservador não vincula
  dict(id=29, texto="Compareceram o autor e o réu. Ambos assinaram.",
       corref=[["o autor"], ["o réu"]]),
  dict(id=30, texto="O Sr. Meira apresentou documentos. Mais tarde, "
                    "o referido senhor confirmou.",
       corref=[["o Sr. Meira"]]),  # "o referido senhor" — não vincula (limitação aceita)
]


def avalia():
    tot_grupos = ok_grupos = tot_sep = ok_sep = tot_nr = ok_nr = 0
    tot_ent = ok_ent = 0
    falhas = []
    for c in CASOS:
        eng = Engine()
        ms = eng.analyze(c["texto"])
        by_text = {}
        for m in ms:
            by_text.setdefault(fold(m.text), m.ent)  # text -> Ent|None
        # grupos corref
        for g in c.get("corref", []):
            tot_grupos += 1
            ids = []
            missing = False
            for t in g:
                e = by_text.get(fold(t), "MISSING")
                if e == "MISSING" or e is None:
                    missing = True
                else:
                    ids.append(e.id)
            if not missing and len(set(ids)) == 1 and ids:
                ok_grupos += 1
            else:
                falhas.append((c["id"], "corref", g, ids, missing))
        # separação
        for a, b in c.get("separados", []):
            tot_sep += 1
            ea = by_text.get(fold(a), "MISSING")
            eb = by_text.get(fold(b), "MISSING")
            ea = ea.id if isinstance(ea, Ent) else None
            eb = eb.id if isinstance(eb, Ent) else None
            if ea is not None and eb is not None and ea != eb:
                ok_sep += 1
            else:
                falhas.append((c["id"], "sep", (a, b), (ea, eb), False))
        # nao_resolver
        for t in c.get("nao_resolver", []):
            tot_nr += 1
            e = by_text.get(fold(t), "MISSING")
            ok = (e == "MISSING") or (e is None)
            if ok: ok_nr += 1
            else: falhas.append((c["id"], "nao_resolver", t, e.id, False))
        # entidade_nova esperada
        for t in c.get("entidade_nova", []):
            tot_ent += 1
            e = [x for x in eng.ents if x.name and fold(x.name) == fold(t)]
            if e: ok_ent += 1
            else: falhas.append((c["id"], "entidade_nova", t, None, True))

    total = tot_grupos + tot_sep + tot_nr + tot_ent
    ok = ok_grupos + ok_sep + ok_nr + ok_ent
    print(f"corref:   {ok_grupos}/{tot_grupos}")
    print(f"separados:{ok_sep}/{tot_sep}")
    print(f"nao_resolv:{ok_nr}/{tot_nr} (conservador correto)")
    print(f"ent_nova: {ok_ent}/{tot_ent}")
    print(f"\nCONSISTÊNCIA TOTAL: {ok}/{total} = {ok/total:.0%}")
    print("\n--- falhas ---")
    for f in falhas:
        print(" ", f)


if __name__ == "__main__":
    avalia()
