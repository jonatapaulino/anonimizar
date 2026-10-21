# P8 — Métricas v0 sobre corpus sintético (proxy N2)

**Data:** 16/10/2026 · **Corpus:** `spikes/corpus_v0.jsonl` —
36 docs gerados por template (petição, decisão, depoimento,
sentença, execução, parentesco), 252 entidades gold, 186 PESSOA
· **Harness:** `spikes/p8_metricas.py` · **Espec:** `docs/metricas.md`

> **Escopo**: proxy de engenharia sobre texto limpo. Mede o gap dos
> componentes, não validade externa. Gates só se declaram sobre
> corpus anotado com amostras reais.

## A) Validadores regex — F1 micro = **1,00**

| Tipo | P | R | F1 |
|---|---|---|---|
| CPF, OAB, PROCESSO_CNJ, CEP, TELEFONE, EMAIL, DATA_NASC, VALOR | 1,00 | 1,00 | 1,00 |

Em formato limpo, identificadores estruturados são problema
resolvido — confirma que a detecção híbrida pode tratar esses tipos
como camada determinística. A lacuna real é em texto com ruído de
OCR (hífens/quebras dentro do número) — já previsto no estágio-0 de
normalização; medir com corpus degradado é trabalho E9.

## B) NER stock LeNER-Br — `ner-bert-base-cased-pt-lenerbr`

| Subconjunto | P | R | F1 |
|---|---|---|---|
| todas as menções PESSOA | 0,85 | 0,52 | 0,64 |
| **só nomes próprios** | **0,85** | **1,00** | **0,92** |

O NER stock cobre **todos** os nomes próprios do corpus (fn=0 no
subconjunto justo). Os fp=17 são fragmentos/splits de fronteira —
higiene de span, não problema conceitual. As menções que ele "perde"
no conjunto total são papéis, pronomes, discurso — **domínio do
motor simbólico, não do NER**: a divisão de trabalho do ADR-0001
apareceu na medida. O gap que o fine-tune precisa fechar não é
"achar nomes" — é o tagset completo (ORG/END/DATA etc.) + robustez
a ruído.

## C) Correferência (motor simbólico) — pairwise F1 = **0,88**

| Métrica | Valor | Gate N2 |
|---|---|---|
| Pairwise P / R / F1 | 0,86 / 0,90 / **0,88** | F1 ≥ 0,90 |
| Consistência por entidade | 78/90 = **0,87** | ≥ 0,85 ✓ |
| Menções alinhadas | 186 | — |

**Abaixo do gate de pares por 2 pontos** — e o corpus v0 já fez o
serviço dele: expôs uma classe de falha real (apositivo após
parentesco, "a esposa do autor, Maria,") que a bateria artesanal do
P3 não cobria. Regra adicionada (motor agora nomeia o parente pelo
apositivo) → F1 subiu de 0,80 para 0,88, bateria P3 segue 40/40.

Falhas restantes (18 pares FP, 12 FN): principalmente co-resolução
de parentesco genitivo composto e pronomes em contexto de duas
entidades do mesmo gênero — exatamente as classes do "long tail"
previsto no ADR-0002. Trabalho normal de motor, não bloqueio
arquitetural.

## Decisões destravadas

- **Harness de métricas existe** — quando o corpus real chegar, é
  `p8_metricas.py` + caminho do arquivo; as fórmulas já são as
  pré-registradas.
- **Baseline stock NER**: recall de nomes já é 1,00 → o fine-tune
  pode focar em tagset próprio e ruído, não em coverage básica.
- **Correferência**: distância ao gate quantificada (0,88 vs 0,90)
  em corpus de template — a meta segue plausível; o gap é de
  cobertura de regras, mensurável e iterável.

## Limitações honestas

- Corpus sintético de 6 templates — não representa variação real;
  resultados são piso de dificuldade, não teto.
- Overlap matching favorece NER; exact matching é a barra do gate.
- Sem medida de reidentificação/utility — exigem pipeline de saída
  e decisão jurídica de pseudônimos.
