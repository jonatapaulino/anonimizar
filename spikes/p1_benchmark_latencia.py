"""P1 — Benchmark de latência: encoder BERT jurídico em CPU.

Spike do docs/plano-de-validacao.md.
Pergunta que responde: a API síncrona é viável com janelas de 512 tokens
sobre documentos de 1k–50k tokens, em CPU, sem GPU?

Método: Legal-BERTimbau-base (fallback: BERTimbau base), AutoModel (encoder
puro — o head de NER é uma camada linear, custo desprezível). Latência por
janela medida com N amostras; latência por documento medida executando o
pipeline real de janelas deslizantes (batch=1, como na API síncrona).

Nota sobre o pipeline real: o módulo roda o encoder mais de uma vez por
janela (NER + perplexidade via MLM; classificador de papel é leve). O
número de passes multiplica o custo — reportado no resultado.
"""
import json
import os
import platform
import statistics
import sys
import time

import torch
from transformers import AutoModel, AutoTokenizer

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "cpu"

MODEL_CANDIDATES = [
    "rufimelo/Legal-BERTimbau-base",
    "neuralmind/bert-base-portuguese-cased",
]
WINDOW = 512
STRIDES = {256: "50% overlap", 384: "25% overlap"}
DOC_SIZES = [1_000, 5_000, 10_000, 25_000, 50_000]
WARMUP_WINDOWS = 3
WINDOW_SAMPLES = 25        # amostras para latência/janela
DOC_RUNS = {1_000: 5, 5_000: 3, 10_000: 3, 25_000: 2, 50_000: 2}

# Parágrafo modelo em legês — conteúdo irrelevante para latência,
# só importa o comprimento em tokens.
PARAGRAFO = (
    "O requerente João da Silva, brasileiro, maior, capaz, residente e "
    "domiciliado na Rua das Flores, número 123, bairro do Marco, Comarca de "
    "Belém, Estado do Pará, por seu advogado infra-assinado, com procuração "
    "anexa, vem, respeitosamente, à presença de Vossa Excelência, com fundamento "
    "nos artigos 189 e seguintes do Código de Processo Civil, requerer a "
    "concessão de medida liminar para suspensão dos efeitos do ato administrativo "
    "impugnado, ante a evidência de fumaça do bom direito e o periculum in mora "
    "configurado pela exigibilidade imediata do débito discutido nos autos, "
    "ressalvada a produção de prova documental e testemunhal em momento "
    "oportuno, nos termos do artigo 300 do referido diploma processual. "
)


def load_model():
    for name in MODEL_CANDIDATES:
        try:
            tok = AutoTokenizer.from_pretrained(name)
            model = AutoModel.from_pretrained(name).eval().to(DEVICE)
            return name, tok, model
        except Exception as e:
            print(f"[warn] falha ao carregar {name}: {e}", file=sys.stderr)
    raise SystemExit("nenhum modelo disponível")


def make_doc_ids(tok, n_tokens):
    """Gera input_ids de ~n_tokens repetindo o parágrafo modelo."""
    ids = tok(PARAGRAFO, add_special_tokens=False)["input_ids"]
    reps = (n_tokens // len(ids)) + 1
    return (ids * reps)[:n_tokens]


def windows_of(ids, window, stride):
    """Recorta ids em janelas de `window` tokens avançando `stride`."""
    out, start = [], 0
    while start < len(ids):
        chunk = ids[start:start + window]
        if len(chunk) < window:
            chunk = chunk + [0] * (window - len(chunk))  # pad última janela
        out.append(chunk)
        if start + window >= len(ids):
            break
        start += stride
    return out


def bench_window(model, sample, n=WINDOW_SAMPLES, warmup=WARMUP_WINDOWS):
    x = torch.tensor([sample]).to(DEVICE)
    with torch.no_grad():
        for _ in range(warmup):
            model(input_ids=x)
        ts = []
        for _ in range(n):
            t0 = time.perf_counter()
            model(input_ids=x)
            if DEVICE == "cuda":
                torch.cuda.synchronize()
            ts.append((time.perf_counter() - t0) * 1000)
    return ts


def bench_doc(model, wins):
    t0 = time.perf_counter()
    with torch.no_grad():
        for w in wins:
            model(input_ids=torch.tensor([w]).to(DEVICE))
        if DEVICE == "cuda":
            torch.cuda.synchronize()
    return (time.perf_counter() - t0) * 1000


def pct(v, p):
    v = sorted(v)
    k = max(0, min(len(v) - 1, round((p / 100) * (len(v) - 1))))
    return v[k]


def main():
    print(f"modelo: carregando...", file=sys.stderr)
    name, tok, model = load_model()
    threads = torch.get_num_threads()

    meta = {
        "modelo": name,
        "parametros": sum(p.numel() for p in model.parameters()),
        "cpus_logicos": os.cpu_count(),
        "torch_threads": threads,
        "cpu": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": DEVICE,
        "gpu": torch.cuda.get_device_name(0) if DEVICE == "cuda" else None,
        "janela": WINDOW,
    }
    print(json.dumps(meta, ensure_ascii=False))

    # latência por janela (amostra robusta)
    base_ids = make_doc_ids(tok, WINDOW)
    w_ts = bench_window(model, base_ids)
    window_stats = {
        "mediana_ms": round(statistics.median(w_ts), 1),
        "p95_ms": round(pct(w_ts, 95), 1),
        "min_ms": round(min(w_ts), 1),
        "n": len(w_ts),
    }
    print(json.dumps({"por_janela_512": window_stats}, ensure_ascii=False))

    # tokenização (overhead do pipeline)
    doc10k = make_doc_ids(tok, 10_000)
    texto10k = tok.decode(doc10k)
    t0 = time.perf_counter()
    tok(texto10k, add_special_tokens=False)
    tok_ms = (time.perf_counter() - t0) * 1000
    print(json.dumps({"tokenizacao_10k_tokens_ms": round(tok_ms, 1)},
                     ensure_ascii=False))

    # latência por documento — pipeline real de janelas
    for size in DOC_SIZES:
        ids = make_doc_ids(tok, size)
        for stride in STRIDES:
            wins = windows_of(ids, WINDOW, stride)
            runs = [bench_doc(model, wins) for _ in range(DOC_RUNS[size])]
            rec = {
                "doc_tokens": size,
                "stride": stride,
                "overlap": STRIDES[stride],
                "n_janelas": len(wins),
                "mediana_ms": round(statistics.median(runs), 0),
                "p95_ms": round(pct(runs, 95), 0),
                "runs_ms": [round(r, 0) for r in runs],
                "ms_por_janela": round(statistics.median(runs) / len(wins), 1),
            }
            print(json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main()
