# Perguntas e respostas — gates, métricas e avaliação

Perguntas feitas durante a revisão da POC, com as explicações
correspondentes. Complementa `docs/relatorio_avaliacao.pdf`.

## O gate NER exact 0,85 não pode ser maior? Ou é isso mesmo?

O 0,85 é uma **decisão do projeto**, não uma propriedade do número —
foi o limiar pré-registrado em `docs/metricas.md` *antes* da
avaliação rodar. Três pontos:

1. **Aumentar não faz sentido prático**: com F1 exact 0,755, qualquer
   gate ≥0,755 falha — 0,85, 0,90, tanto faz;
2. **Baixar pra passar é trapaça metodológica**: mover o alvo depois
   de ver o resultado invalida o pré-registro inteiro;
3. **0,85 é exigente**: exact exige fronteira idêntica ao gabarito —
   cortar ou arrastar uma palavra já reprova o span. É por isso que
   o relatório também mostra overlap (0,938): o motor *encontra*
   quase tudo, só *delimita* mal.

Caminho honesto: **renegociar o gate para a próxima rodada**, com
justificativa documentada (ex.: overlap parcial aceitável para spans
longos de endereço; exact obrigatório para CPF/RG — gates por tipo).
Legítimo porque vale para medição futura, não para salvar o atual.

## Como funcionam as métricas? Maior é melhor?

Sim — P, R e F1 vão de 0 a 1 e **quanto maior, melhor**:

- **Precisão (P)**: do que o motor marcou como PII, quanto era PII de
  verdade. P baixo = mancha texto bom (falso positivo). Ours exact:
  0,780 — 22% do marcado estava errado;
- **Recall (R)**: do PII existente, quanto foi achado. R baixo =
  vazamento. Exact 0,731 — mas na prática o motor achou 98,9% das
  entidades; delimitou mal as bordas;
- **F1**: média harmônica de P e R — pune o pior dos dois lados.

| métrica | P | R | F1 | leitura |
|---|---|---|---|---|
| exact | 0,780 | 0,731 | 0,755 | bordas precisas? reprova |
| overlap | 0,970 | 0,908 | 0,938 | achou a região? quase perfeito |

## O que é um span?

Trecho contíguo de texto que o detector marca como entidade — um par
`[início, fim]` sobre os caracteres do documento.

```
o servidor JOÃO PEREIRA, inscrito no CPF 123.456.789-00
```

Gabarito: `JOÃO PEREIRA` = NOME, span `[12,24]`. Se o motor marca
`servidor JOÃO PEREIRA,` → achou a região mas arrastou palavras —
exact reprova (FP + FN), overlap aceita. O LLM da cascata tende a
spans "generosos": ex. do relatório, declarou ENDERECO o trecho
inteiro `'IVONETE CRISTINA ROCHA, inscrito no RG sob o n. 58.320.829,
inscrito(a)...'` (203c) — o PII estava dentro, mas ele apagaria
contexto junto.

## Então 0,85 seria o ideal?

Não — é o **mínimo aceitável**. O ideal seria 1,0 (inexistente na
prática). E para privacidade o número que mais pesa é o **recall**:
R=1,0 com P=0,7 é "seguro porém destrutivo"; P=1,0 com R=0,6 é
perigoso (vaza dado). Por isso existe o gate residual: mesmo que o
NER erre, nada com PII restante sai para o bucket.

## O 0,85 foi validado pela arquitetura para produção?

Não — é um **critério de aceitação definido antes de medir** (em
`docs/metricas.md`). Diz: "um motor só é *candidato* a produção se
atingir 0,85". E mesmo atingindo, ainda precisaria passar nos outros
gates: F1 por tipo ≥0,70, correferência pairwise ≥0,90, anti-merge
≤5%, consistência ≥0,85, reidentificação ≤0,05, utility TAB ≥0,85,
latência. 0,85 é necessário, não suficiente.

## Com um "cérebro mais inteligente" ele passa de 0,85?

Pode — dois caminhos:

1. **Refino barato**: o déficit é fronteira frouxa, não falta de
   inteligência. **Poda determinística pós-extração** (cortar
   rótulos/conectivos das bordas antes do merge) pode subir o F1 sem
   trocar modelo;
2. **Cérebro melhor**: NER discriminativo treinado (fine-tune
   legal-BERT / LeNER-Br / UlyssesNER-Br) delimita melhor que LLM
   generativo com prompt — e devolve conformidade com a ADR-0011.

Ressalva: não é garantido — só medindo na teste com o mesmo gate. E
o corpus sintético tem viés de geração; o número precisa segurar em
documento real.

## Com documento real, precisa revalidar a arquitetura?

**Arquitetura não, avaliação sim.** O desenho é agnóstico ao
conteúdo (outbox, hash-chain, idempotência, gate residual funcionam
igual). Mas os números **não se transferem**: documento real traz
OCR imperfeito, formatos variados, PII "no selvagem", documentos
longos. Caminho: Etapa 3 (corpus real, após exclusões jurídicas) →
nova partição teste → mesmo protocolo, mesmos gates.

## O que é o "motor"?

O componente que faz a anonimização — a caixa `MotorIA` do diagrama,
atrás da porta `anonimizar(bytes) → bytes`. Tudo ao redor (worker,
fila, trilha, buckets, gates) ignora o que tem dentro. Por isso é
permutável: stub → demo-regex → **cascata POC (atual)** → futuro
NER discriminativo. A arquitetura é o carro; o motor é a peça
trocável — e o gate residual é o freio que segura independente dele.
