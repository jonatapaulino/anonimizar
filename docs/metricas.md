# Métricas — pré-registro de avaliação

> Status: **v1.0 — pré-registradas em 16/10/2026, antes de qualquer
> medição em corpus**. Mudanças posteriores exigem nota de emenda
> datada (mesma disciplina dos ADRs).

Este documento fixa **o que conta como acerto** em cada métrica do
projeto, para que os números futuros não possam ser ajustados ao
resultado. Os gates abaixo são os critérios de aprovação do pipeline;
as fórmulas são as que o harness (`spikes/p8_metricas.py`) calcula.

---

## 1. Convenções

- **Span**: `(start, end)` em caracteres sobre o texto original,
  `end` exclusivo.
- **Entidade gold**: span anotado com `type` e `ent_id` (cluster de
  correferência). Menções à mesma pessoa compartilham `ent_id`.
- **Tipos** (tagset provisório v0 — o definitivo é decisão da
  Etapa 3): `PESSOA`, `CPF`, `RG`, `OAB`, `PROCESSO_CNJ`, `CEP`,
  `TELEFONE`, `EMAIL`, `ENDERECO`, `DATA_NASC`, `ORGAO`, `LOCAL`.
- Dois níveis de concordância de fronteira:
  - **exact**: predito `(start,end,type)` == gold.
  - **overlap**: predito ∩ gold ≥ 1 caractere, tipos iguais.
    Reporta-se ambos; o gate usa **exact** (mais duro).

## 2. Detecção de entidades (NER + validadores)

Para cada tipo `t` e para o micro-global:

```
P = TP / (TP + FP)      R = TP / (TP + FN)      F1 = 2PR / (P+R)
```

| Gate | Barra | Medição |
|---|---|---|
| **F1 micro global (exact) ≥ 0,85** | corpus anotado held-out | CI job |
| F1 por tipo ≥ 0,70 | nenhum tipo pode ser carregado pelos outros | relatório |

Validadores determinísticos (CPF, OAB, CNJ…) reportam-se em separado
do modelo NER: são componentes distintos, com expectativas distintas
(regex deve beirar 1,0 em formato limpo; NER é probabilístico).

## 3. Correferência (motor simbólico)

Sobre menções `PESSOA` alinhadas gold↔predito (alinhamento por
overlap: toma-se a entidade predita do span predito que mais
intersecta o gold; gold sem predito conta FN de menção):

- **Pairwise**: todo par de menções. TP = mesmo `ent_id` gold ∧
  mesmo predito; FP = mesmo predito ∧ gold diferente; FN = mesmo
  gold ∧ predito diferente. P/R/F1 sobre pares.
- **Consistência de documento**: fração de `ent_id` gold cujas
  menções caem **todas** numa única entidade predita.

| Gate | Barra |
|---|---|
| **Pairwise F1 ≥ 0,90** | corpus |
| Consistência por documento ≥ 0,85 | corpus |
| **Anti-merge**: pares gold-distintos fundidos pelo predito ≤ 5%
  dos pares (over-link é o erro fatal) | corpus |

## 4. Reidentificação

Taxa de vazamento: fração de entidades `PRIV` (tipos exceto
`ORGAO`/`LOCAL` públicos) cujo texto em claro ainda aparece na saída
anonimizada — busca literal + busca normalizada (estágio-0).

```
reident = |entidades com ≥1 menção em claro na saída| / |entidades PRIV|
```

| Gate | Barra |
|---|---|
| **reident ≤ 0,05** | sobre a saída real do pipeline |

## 5. Utilidade (TAB adaptado)

Pré-registro da forma, pesos sujeitos à decisão jurídica de
pseudônimos:

```
utility = w1·legibilidade + w2·papéis_preservados
        + w3·relações_preservadas + w4·cronologia_preservada
```

cada componente ∈ [0,1] medido por checklist humano em amostra
estratificada (n ≥ 30 docs). **Meta ≥ 0,85.** Pesos default
`w=(0,3; 0,3; 0,2; 0,2)` até decisão com jurídico.

## 6. Escore residual do contrato (ADR-0010)

```
residual_score = 1 − (a·F1_ner + b·F1_corref + c·(1−reident))
```

com `a+b+c=1`, default `a=b=c=⅓` até calibração em corpus.
`needs_review` quando `residual_score > τ`; `τ` a fixar no piloto
(Etapa 8) — pré-registrado como pendente deliberada, não omissão.

## 7. Resumo dos gates

| Métrica | Gate | Nível | Status |
|---|---|---|---|
| NER F1 micro (exact) | ≥ 0,85 | N2 | medida-proxy em corpus v0 abaixo |
| Correferência pairwise F1 | ≥ 0,90 | N2 | idem |
| Correferência anti-merge | ≤ 5% pares errados | N2 | idem |
| Reidentificação | ≤ 0,05 | N2 | exige pipeline de saída |
| Utility (TAB) | ≥ 0,85 | N2 | exige decisão jurídica |
| Latência (contrato API) | a fixar no hardware-alvo | N2/N3 | P1 mediu insumos |
| Operabilidade pelo órgão | binário | N3 | Etapa 11 |

**Declaração de escopo**: números sobre `corpus_v0.jsonl` (sintético,
gerado por template) são *proxies de engenharia* — medem o gap dos
componentes, não validade externa. Gates só se declaram atingidos
sobre corpus anotado com amostras reais autorizadas.
