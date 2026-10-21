# P6 — Resultado: normalização Unicode (estágio 0)

> Spike do `docs/plano-de-validacao.md`. Executado em 2026-10-16.
> Hipótese: NFKC + remoção de zero-width/formatos + dobra de
> homoglifos e traços faz variantes adversariais convergirem para a
> forma canônica **antes** de regex/NER.

## Implementação

`spikes/p6_normalizacao.py` — três passes, só stdlib (`unicodedata`):

1. **NFKC** — resolve fullwidth, ligaduras, compatibilidade
2. **Remoção de invisíveis** — zero-width (U+200B–D, U+2060, U+FEFF,
   soft hyphen) e categoria Cf genérica
3. **Dobras explícitas** — homoglifos cirílico/grego/itálico,
   dígitos árabe-indicos, e a família de traços tipográficos

## Resultado: 19/19 baterias convergem

Cobertura provada: homoglifos cirílicos (`Jоão`) e gregos (`Jοão`),
fullwidth (`Ｊｏãｏ`, `１２３`), ZWSP/ZWNJ/ZWJ/word-joiner/BOM
embutidos, soft hyphen, dígitos árabe-indicos, non-breaking hyphen,
en-dash.

## Achado relevante (não óbvio)

**NFKC sozinho não basta para traços**: U+2011 (hífen não-quebrável)
normaliza para U+2010 (hífen tipográfico), **não** para ASCII `-`.
Um regex de CPF `\d{3}\.\d{3}\.\d{3}-\d{2}` falharia no documento
adulterado mesmo após NFKC. Corrigido com tabela `TRACOS` explícita
— todo dash-like → `-`. Foi o único caso que falhou na primeira
execução (18/19) e motivou a dobra adicional.

## O que a PoC deliberadamente NÃO resolve

- **Espaços inseridos** (`J o ã o`): colapsar quebraria texto
  legítimo; fica para os detectores tolerarem espaçamento ou para
  regra específica no corpus adversarial.
- **Diacríticos trocados** (`Jõão`): normalização compõe, não
  "corrige" — caso para fuzzy matching no detector, não no estágio 0.
- Homoglifos fora da tabela (a tabela deve crescer com o corpus
  adversarial, Etapa 9 — já previsto).

**Status P6: ✅ provado — mecanismo funciona, ordem correta
(normalizar antes de detectar) confirmada, e uma classe real de
bypass (traços tipográficos) foi encontrada e fechada no spike.**
