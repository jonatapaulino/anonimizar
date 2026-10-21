"""P6 — PoC do estágio 0: normalização Unicode anti-evasão.

Spike do docs/plano-de-validacao.md (emenda à especificação técnica).
Hipótese: NFKC + remoção de zero-width + dobra de homoglifos comuns faz
variantes adversariais de nomes convergirem para a forma canônica que
regex/NER esperam — antes da detecção, não depois.

Bateria: variantes reais de evasão tipográfica sobre nomes e CPF.
Critério: 100% das variantes convergem para a forma canônica.
"""
import unicodedata

# zero-width / formatos invisíveis que devem sumir
ZERO_WIDTH = {
    "​", "‌", "‍", "⁠",
    "﻿",  # BOM/ZWNBSP
    "­",       # soft hyphen
    "᠎",          # mongolian vowel separator
}

# homoglifos frequentes: visualmente idênticos ou quase, codepoints distintos.
# cobre cirílico (а е о р с х), grego (ο) e letras fullwidth — NFKC já
# resolve fullwidth; os demais precisam de tabela explícita.
HOMOGLIFOS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C", "Х": "X",
    "ο": "o", "Ο": "O",
    "і": "i", "І": "I",
    "ɑ": "a", "ρ": "p",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})

# traços tipográficos — o teste revelou que NFKC para U+2011 gera
# U+2010, não ASCII. Dobra explícita: qualquer dash-like vira "-".
# Sem isso, CPF/placa com en-dash ou hífen-typográfico evade o regex.
TRACOS = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-",
    "–": "-", "—": "-", "―": "-",
    "−": "-", "－": "-", "﹘": "-", "﹣": "-",
})


def normaliza(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = "".join(c for c in s if c not in ZERO_WIDTH
                and unicodedata.category(c) != "Cf")
    return s.translate(HOMOGLIFOS).translate(TRACOS)


CANON_NOME = "João Silva"
CANON_CPF = "123.456.789-00"

CASOS = [
    # (variante adversarial, esperado)
    ("João Silva", CANON_NOME),
    ("Jοão Silva", CANON_NOME),          # omicron grego no o
    ("Jоão Silva", CANON_NOME),          # o cirílico
    ("João Silvа", CANON_NOME),          # a cirílico no fim
    ("J o ã o   S i l v a", "J o ã o   S i l v a"),  # espaços: NÃO dobra (nota 1)
    ("João​Silva", "JoãoSilva"),   # ZWSP some
    ("João‌Silva", "JoãoSilva"),
    ("João‍Silva", "JoãoSilva"),
    ("Ｊｏãｏ Ｓｉｌｖａ", CANON_NOME),     # fullwidth
    ("João⁠Silva", "JoãoSilva"),   # word joiner
    ("Jo﻿ão Silva", CANON_NOME),          # BOM dentro da palavra
    ("João Si­lva", CANON_NOME),    # soft hyphen some
    ("Jõão Silva", "Jõão Silva"),        # til no lugar errado: fica (nota 2)
    ("123.456.789-00", CANON_CPF),
    ("123​.456​.789​-00", CANON_CPF),  # ZWSP entre dígitos
    ("１２３.４５６.７８９-００", CANON_CPF),     # dígitos fullwidth
    ("١٢٣.٤٥٦.٧٨٩-٠٠", CANON_CPF),       # dígitos árabe-indicos
    ("123.456.789‑00", CANON_CPF),       # hífen não-quebrável U+2011
    ("123.456.789–00", CANON_CPF),       # en-dash agora dobra p/ "-"
]


def main():
    ok = falhas = 0
    for entrada, esperado in CASOS:
        got = normaliza(entrada)
        mark = "OK " if got == esperado else "FALHOU"
        if got == esperado:
            ok += 1
        else:
            falhas += 1
        print(f"{mark} in={entrada!r:40} -> {got!r}")
    print(f"\n{ok}/{len(CASOS)} convergem como esperado "
          f"({'TODOS' if falhas == 0 else f'{falhas} falhas'})")


if __name__ == "__main__":
    main()
