# P4 — Resultado: hash-chain + âncora externa

> Spike do `docs/plano-de-validacao.md` (emenda ADR-0004). 2026-10-16.
> `spikes/p4_hashchain.py` — stdlib apenas.

## Hipóteses e veredito

| H | Hipótese | Resultado |
|---|---|---|
| H1 | adulteração de 1 linha é detectada | ✅ recomputar cadeia → mismatch |
| H2a | rewrite total passa na verificação isolada | ✅ **confirmado** — cadeia recalculada é indistinguível do original |
| H2b | rewrite total é detectado pela âncora externa | ✅ hash de topo diverge da âncora exportada |

## O que isso prova na prática

A emenda era necessária — e está correta:

- **Sem âncora**: atacante com write total no Postgres reescreve a
  história E recalcula os hashes. `verifica_cadeia` retorna `True`.
  A trilha é tamper-evident contra edição parcial, não contra
  reescrita completa.
- **Com âncora**: o hash de topo exportado para fora do host é o
  ponto fixo. Qualquer reescrita diverge dele — detectado.

Implicação operacional registrada: a âncora precisa ser **periódica**
(exportação/assinatura do topo) — quanto menor o intervalo, menor a
janela em que um rewrite pode fingir honestidade.

**Status P4: ✅ provado — mecanismo correto, emenda justificada por
demonstração, não só argumento.**
