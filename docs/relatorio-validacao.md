# Relatório de Validação — Módulo de Anonimização Jurídica

> Data: 2026-10-16 · Base: `docs/plano-de-validacao.md`, ADRs
> 0000–0012 (com emendas de 16/out), `especificacao-tecnica.md`,
> `arquitetura-interativav1.3.html`.
> Artefatos: `spikes/` (scripts, dados brutos, resultados por prova).

## Status geral

**Arquitetura validada no papel e em princípio para os mecanismos
determinísticos e de infraestrutura. Pendente: validação científica
(N2, depende de corpus) e institucional (N3, depende do órgão).**

Das 7 provas arquiteturais N1, **7 executadas, 7 com sinal positivo**:

| Prova | Mecanismo | Resultado |
|---|---|---|
| P1 | Latência encoder em CPU | ✅ ~110–180ms/janela 512; síncrono viável ≤~10k tokens; **batch assíncrono sai de INDEFINIDO → DEFINIDO acima** |
| P1b | Mesmo benchmark em GPU | ✅ ~9ms/janela (12–20×); 50k tokens = 1,75s → síncrono universal; vira decisão de hardware do edge |
| P2 | `internal: true` no Compose | ✅ zero egress (HTTP/DNS/ICMP/IPv6) medido; intra-rede preservada; DNS embutido sem upstream |
| P3 | Motor simbólico de correferência | ✅ 40/40 asserções em 30 casos artesanais — ≥0,90 plausível (não provado; corpus decide) |
| P4 | Hash-chain + âncora externa | ✅ adulteração parcial detectada; rewrite total detectado **só** pela âncora — emenda justificada |
| P5 | `HMAC(entidade∥case_id)` | ✅ zero correlação transversal; destruição de K = oráculo morto (efeito demonstrável) |
| P6 | Normalização Unicode (estágio 0) | ✅ 19/19 convergem; achado real: NFKC não dobra U+2011→`-`, tabela de traços fechou |
| P7 | JWT offline via JWKS cacheado | ✅ Keycloak real: validação sem IdP, TTL 120s, adulterado/issuer-falso rejeitados |

## Decisões destravadas por evidência

- **Batch assíncrono**: antes INDEFINIDO → agora DEFINIDO para docs
  >~10k tokens em CPU-only; dispensável com GPU no edge. Requer
  registro na especificação/ADR de empacotamento.
- **Stride**: 384 (25% overlap) economiza ~30% — dado para a regra
  de merge de spans pendente.
- **Normalização**: precisa de tabela de traços além do NFKC —
  bug de evasão real encontrado no spike, já documentado no código.
- **Amadurecimento do motor**: regra 1×1 (nome solto × papel
  anônimo) + resolução em 2ª passada — candidatas ao design oficial.

## O que ainda falta

### A. Decisões de papel (trabalho de especificação, sem código)

| Item | Dono | Desbloqueia |
|---|---|---|
| Tagset + esquema de anotação | Etapa 3 | todo o N2 |
| Regra de merge de spans | especificar antes do corpus | corpus avaliável |
| Fórmula `residual_score` + recall de correferência | pré-registro E1 | métricas oficiais |
| Política de pseudônimos + break-glass | **jurídico** | utility + `/v1/reversal` |
| Modelo de relações sujeito↔sujeito | spec (spike P3 validou o formato REL) | coerência processual |
| Redis × in-memory rate limit | decisão técnica trivial | compose de referência |
| Registrar decisões de P1 (batch, limiar, GPU?) | emenda ADR-0003/0008 | contrato |

### B. Validação científica N2 (trilha longa — E3–E10)

Corpus sintético → fine-tune → gates de CI: F1 NER ≥0,85 ·
correferência ≥0,90 + recall · reidentificação ≤5% · utility ≥0,85.
Depende de A.1–A.3 fechados + amostras reais autorizadas
(pedir já — dependência externa lenta).

### C. Validação institucional N3 (E11)

TI do órgão opera o compose; cerimônia de unseal; usuários jurídicos
avaliam utilidade; amostras reais medem validade externa.

### D. Hardening operacional restante (menor)

Binding de portas host-only, CRL/vida-curta de cert mTLS em campo,
métricas Prometheus, rotação real de JWKS, teste de nonce-único nas
DEKs — todos têm mecanismo provado ou são exercício de implantação.

## Leitura honesta

A arquitetura está **validada até onde a validação sem corpus e sem
órgão alcança**. As peças de risco estrutural (isolamento, cripto,
auth, auditabilidade) têm prova; as peças de risco estatístico
(NER, correferência em escala, reidentificação) têm sinal forte mas
resposta pendente — e o próprio desenho (`risk_score`,
`review_flags`, trilha auditável) assume isso.

O elo mais fraco segue sendo **correferência em documentos reais**
— mas o spike reduziu a incerteza de "será que funciona?" para
"quanto do fenômeno long-tail falta cobrir?", que é uma pergunta
menor e mensurável.
