# P1 — Resultado: latência de encoder jurídico em CPU

> Spike do `docs/plano-de-validacao.md`. Executado em 2026-10-16.
> Pergunta: a API síncrona é viável sobre janelas de 512 tokens?

## Setup

- Modelo: `rufimelo/Legal-BERTimbau-base` (108,9M parâmetros, stock — sem fine-tune)
- Hardware: Intel 24 CPUs lógicas · torch 2.14.1+cpu · Python 3.14.7
- Medição: `spikes/p1_benchmark_latencia.py` · dados brutos em `p1_raw.jsonl`
- Encoder puro (AutoModel) — head de NER é linear, custo desprezível
- Batch=1 por janela, como seria na API síncrona

## Números

| Métrica | Valor |
|---|---|
| Latência por janela 512 (isolada) | mediana **181ms** · p95 208ms |
| Latência por janela dentro de doc | ~**110ms** |
| Tokenização | ~16ms / 10k tokens (desprezível) |

| Tokens no doc | Janelas stride 256 (50%) | Mediana | Janelas stride 384 (25%) | Mediana |
|---|---|---|---|---|
| 1k | 3 | **0,6s** | 3 | **0,6s** |
| 5k | 19 | 2,4s | 13 | **1,4s** |
| 10k | 39 | 4,2s | 26 | **2,8s** |
| 25k | 97 | 10,9s | 65 | **7,2s** |
| 50k | 195 | **21,3s** | 130 | **15,0s** |

## Interpretação arquitetural

O pipeline real roda o encoder **mais de uma vez por janela**
(NER + pseudo-perplexidade via MLM; o classificador de papel é mais
leve). Multiplicador realista: **×2–3** sobre os números acima.

| Doc | ×1 passe | ×3 passes (estimativa) | Veredito síncrono |
|---|---|---|---|
| ≤5k tokens (≈2–3 págs) | ≤2,4s | ≤7s | ✅ viável |
| ~10k (≈5–10 págs) | ~3–4s | ~9–12s | ⚠️ fronteira — timeout alto, UX ruim |
| ≥25k | ≥7s | ≥21–32s | ❌ síncrono inviável |

## Decisão que destrava

- **"Batch assíncrono" sai de INDEFINIDO → DEFINIDO** para documentos
  grandes: acima de um limiar (~10k tokens), a API precisa devolver 202 +
  job_id e processar assíncrono (ou rejeitar com o budget já previsto).
- Para docs pequenos/médios, síncrono segura — o contrato pode oferecer
  os dois modos com limiar explícito.
- Stride 384 (25% overlap) economiza ~30% de latência — dado para a
  decisão pendente de merge de spans.

## Addendum — mesmo benchmark em GPU (RTX 5090 Laptop, 24GB)

Re-executado com torch 2.11.0+cu128 (`device=cuda`), mesmos parâmetros:

| Tokens no doc | stride 256 | stride 384 | vs CPU (mediana) |
|---|---|---|---|
| 1k | 27ms | 27ms | ~22× |
| 10k | 351ms | 234ms | ~12× |
| 50k | **1.750ms** | **1.171ms** | ~12× |

Latência por janela: **~9ms** (CPU: ~110–180ms).

**Leitura arquitetural**: com GPU, ×3 passes de encoder sobre 50k
tokens ≈ **5,3s** — API síncrona viável até para documentos grandes;
batch vira conforto, não necessidade. Isso alimenta a decisão de
hardware do edge node: (a) CPU-only + batch obrigatório para docs
grandes, ou (b) GPU no edge + síncrono universal — trade-off de
custo/supply-chain do setor público, não de software.

## Ressalvas

1. **Hardware-dependente**: 24 cores aqui; o edge node do órgão terá
   menos. Latência escala ~inversamente aos núcleos — re-rodar no
   hardware alvo antes de fixar o limiar no contrato.
2. Modelo stock; fine-tune não altera arquitetura → latência ≈ estável.
3. Não mediu memória nem o classificador de papel (leve, por entidade,
   não por janela).
4. Tokens gerados de parágrafo-modelo — latência depende de contagem,
   não de conteúdo; válido para a métrica.

**Status P1: ✅ provado — CPU: síncrono viável até ~10k tokens, batch
obrigatório acima. GPU: síncrono viável em todo o range testado.
Decisão de hardware do edge é input institucional (custo × UX).**
