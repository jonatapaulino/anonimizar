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

---

## Emenda 2026-11-04 — cascata v2 (poda + validador + residual)

Medição `saidas_ollama_cascata_v2` (mesmo modelo/digest). Mudanças
de **pipeline** (não de definição de métrica), registradas por
transparência conforme a regra de emenda:

1. **Poda de fronteira** (`scripts/poda_fronteira.py`): candidatos
   `llm*` encolhem ao núcleo por tipo antes do merge. ENDERECO
   admite completar a borda direita até `CEP` próximo (o ouro
   inclui CEP dentro de ENDERECO).
2. **Validador determinístico de CPF (mod-11)**: instância da
   classe "validadores" já prevista na sec. 2 — elimina celulares
   de 11 dígitos soltos que o regex confundia com CPF.
3. **Tipos declarados fora do tagset ouro v0** (`CEP`, `PROCESSO`,
   `OAB`…) são descartados na cascata: o ouro v0 não anota esses
   tipos como entidade própria (CEP existe só dentro de ENDERECO),
   logo preditos desses tipos seriam FP estruturais.
4. **Camada residual `res:NOME`**: nome próprio (≥2 tokens
   capitalizados) após papel jurídico (`intimado(a)`, `em face de`,
   `servidor`, `réu`…), com truncamento em léxico de órgão/cargo.
   Cobre a omissão de enumeração observada da passada só-NOME.

Gate por tipo: com o item 3, `CEP` deixa de aparecer como tipo
predito; o gate ≥0,70 segue aplicado a tipos com suporte no ouro.

---

## Emenda 2026-11-04b — `ent_id` no corpus + motor simbólico revisto

1. **`ent_id` anotado** nos gabaritos de `corpus/ajuste` e
   `corpus/teste` por `scripts/anotar_ent_id.py` (regra de bloco
   `_pessoa`: NOME privado abre cluster; CPF/RG/ENDERECO/EMAIL/
   TELEFONE subsequentes herdam; preservados recebem `None`).
   906 entidades → 137 clusters; homônimos de template ficam em
   clusters distintos (caso anti-merge). Manifestos SHA256SUMS
   emendados; texto/tipo/offsets/preservar inalterados.
2. **Medição nos 110 docs** (motor simbólico P3 como predito,
   menções tipo NOME): pairwise é **degenerado** — TP+FN=0 porque
   o gerador planta cada pessoa uma só vez (não existem pares de
   mesmo cluster); consistência 137/137 (vacuosa: um nome por
   cluster); **anti-merge 1/27 = 3,7% ≤5% PASS** — o único par
   fundido é o homônimo de template doc-0067 (autor e réu com o
   mesmo nome sorteado; ambiguidade genuína do corpus).
   Conclusão: `ent_id` tornou os gates mensuráveis, mas o corpus
   v0 só exerce anti-merge — pairwise/consistência continuam
   sendo medidos no `corpus_v0` (item 4) até existir partição
   com menções repetidas.
3. **Motor P3 revisto** (`spikes/p3_correferencia.py`):
   (a) âncora de parentesco aceita papel com artigo contraído
   ("esposa do autor") e roda antes do passo ART+PAPEL, que antes
   comia "do autor"; (b) KIN nu ("seu filho presenciou") vincula
   ao titular único do papel de parentesco; (c) anti-merge por
   papel adversarial — mesmo nome com papéis opostos (exequente
   ≠ executado) não funde; (d) nome introduzido por menção de
   parentesco não recebe papel de parte (pai/filho homônimos);
   (e) desempate por entidade nomeada em `_link_role`. Bateria
   artesanal segue 40/40.
4. **`corpus_v0` reavaliado** (mesmo harness p8): pairwise
   0,88 → **F1 1,000** (tp126 fp0 fn0), consistência
   0,87 → **1,000** (90/90), **anti-merge 0/270 = 0,000%**
   (primeira vez reportado). Os 3 gates de correferência passam
   no proxy — segue corpus de template: piso de plausibilidade,
   não validade externa.
