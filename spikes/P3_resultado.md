# P3 — Resultado: spike do motor simbólico de correferência

> Spike do `docs/plano-de-validacao.md` (ADR-0002 — o maior risco
> científico do projeto). Executado em 2026-10-16.
> `spikes/p3_correferencia.py` — stdlib apenas, ~300 linhas.

## Resultado

**40/40 asserções = 100% de consistência** sobre 30 casos
artesanais cobrindo os fenômenos de correferência do legês pt-BR.

| Fenômeno | Caso | Resultado |
|---|---|---|
| Repetição de nome completo/parcial | 1, 4, 25 | ✅ |
| Papel processual (autor/réu/requerente…) | 2, 21, 27, 29 | ✅ |
| Appositivos ("o autor João", "Maria, requerente,") | 2, 11, 23 | ✅ |
| Anáfora de discurso ("o referido autor", "o mesmo") | 7, 10, 13, 19 | ✅ |
| Pronome com restrição de gênero | 5, 6 | ✅ |
| Possessivo "seu/sua" | 8, 14 | ✅ |
| Possessivo ambíguo → **não vincula** (conservador) | 15 | ✅ |
| Catáfora (pronome antes do antecedente) → não vincula | 28 | ✅ |
| Parentesco ("filho da autora", "esposa do autor") | 8, 9, 18, 26 | ✅ |
| Honorífico+sobrenome ("o Sr. Silva") | 16, 17 | ✅ |
| Anti-merge: sobrenome compartilhado ≠ mesma pessoa | 3, 20 | ✅ |
| Anti-link: primeiro nome ambíguo → não vincula | 24 | ✅ |
| Fusão nome-solto × papel-anônimo (regra 1×1) | 25 | ✅ |
| Papéis anônimos distintos ficam separados | 29 | ✅ |

## Arquitetura do spike (lições para o motor real)

- **Ordem importa**: copulativos → papel+nome → apositivos →
  parentesco → discurso → honoríficos → nomes soltos; pronomes e
  possessivos resolvem numa **2ª passada** sobre a história real do
  texto (recência + gênero + cardinalidade).
- **Dois erros assimétricos confirmam o desenho conservador**:
  under-link divide identidade (degrada coerência, seguro);
  over-link funde pessoas (fatal). O spike mantém `não_resolver`
  explícito e o relatório de falhas separa os dois tipos.
- **Achados de engenharia que o documento de texto não pegaria**:
  `re.I` global corrompe NAME; plural de papel precisa de stripping
  ("autores"→autor); honorífico precisa resolver depois dos nomes;
  abreviatura ("Sr.") vs nome-em-fim-de-frase distingue-se por
  contagem de palavras.
- **Parentesco gera entidade nova com aresta REL** — valida o
  modelo de relações entre sujeitos pendente na spec.

## Ressalvas honestas — o que isto NÃO prova

1. **Casos artesanais do próprio autor do motor** — risco de
   ensinar para o teste. Mitigação: bateria inclui casos que
   falharam durante desenvolvimento (25 era falha real antes da
   regra 1×1); o conjunto adversarial do corpus (E9) precisa de
   casos escritos por quem não escreveu o motor.
2. **Textos de 1–3 frases**: dependências de longo alcance, orações
   intercaladas e ruído de OCR não estão cobertos.
3. **Cobertura do léxico**: ~40 papéis mapeados; vocabulário real é
   maior. Cada papel novo = entrada no léxico — trabalho linear,
   risco baixo.
4. Plural de papel ("os autores") resolve parcialmente (vincula o
   grupo ao primeiro titular); refinamento pendente.

## Veredito para o ADR-0002

O mecanismo é **expressivo o suficiente**: ~300 linhas de regras já
cobrem o repertório principal. A meta ≥0,90 permanece
**plausível — não provada**; a prova definitiva vem da avaliação no
corpus (E10). Não há sinal para reabrir o ADR — seguir o motor
simbólico, com `review_flags` absorvendo o residual conservador.

**Status P3: ✅ sinal positivo forte — consistência artesanal 100%;
gap para corpus real identificado e delimitado.**
