# P5 — Resultado: cofre HMAC derivado por caso

> Spike do `docs/plano-de-validacao.md` (emenda ADR-0004). 2026-10-16.
> `spikes/p5_hmac_caso.py` — stdlib apenas.

## Hipóteses e veredito

| H | Hipótese | Resultado |
|---|---|---|
| H1 | `HMAC(K, e∥case)` → chaves distintas por caso | ✅ mesma entidade, 3 casos → 3 HMACs, **zero correlação** |
| H2 | esquema antigo `HMAC(K,e)` correlacionava | ✅ confirmado — 1 chave só: insider veria "entidade X nos casos A,B,C" |
| H3 | destruição de K (ADR-0012) mata o oráculo | ✅ sem K nenhum HMAC é reproduzível — nem adivinhando a entidade |
| H4 | lookup legítimo funciona | ✅ `get(entidade, "case-B")` retorna o pseudônimo |

## O que isso prova na prática

- A correção do esquema era **necessária e suficiente**: o mesmo
  registro de entidade agora é três linhas criptograficamente
  independentes no cofre — a propriedade "pseudônimo por caso"
  passou a valer também **no nível do storage**, não só no output.
- H3 é a peça que fecha o ADR-0012: a irreversibilidade do modo
  anonimização não é uma promessa de papel — é o evento de
  destruição da chave. A PoC demonstra que pós-destruição nem o
  operador do cofre consegue o lookup.

Detalhe de implementação registrado: separador `\x1f` (unit
separator) entre entidade e case_id — evita concatenação ambígua
(`"AB"+"C"` vs `"A"+"BC"`).

**Status P5: ✅ provado — esquema emendado elimina correlação
transversal; cerimônia de destruição tem efeito demonstrável.**
