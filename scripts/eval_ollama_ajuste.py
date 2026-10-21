"""Avalia o MotorOllama na particao AJUSTE apenas (30 docs).

Entrada do LLM: o texto do .txt (metrica principal — gabarito
aponta para o .txt). Nunca bytes crus. NAO executa sobre PDF e
NAO roda a particao teste.

Metricas por tipo:
  recall   = entidades a anonimizar (preservar=false) cujo texto
             exato sumiu da saida / total
  excesso  = entidades preservadas (preservar=true) cujo texto
             exato sumiu da saida / total (foi anonimizado o que
             nao devia)

Grava corpus/ajuste/saidas_ollama/doc-NNNN.txt (resposta crua)
e corpus/ajuste/avaliacao_ollama.json (resumo por tipo/doc).

Uso:  python scripts/eval_ollama_ajuste.py [base_corpus]
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.motor_ollama import MotorOllama, TAG   # noqa: E402


async def avaliar(base: Path):
    pasta = base / "ajuste"
    goldens = sorted(pasta.glob("doc-*.json"))
    docs = []
    for g in goldens:
        gab = json.loads(g.read_text(encoding="utf-8"))
        txt = (pasta / gab["documento"]).read_text(encoding="utf-8")
        docs.append((g.stem, gab, txt))

    max_chars = max(len(t) for _, _, t in docs)
    # tokens ~ chars/3 (conservador) + saida de tamanho similar
    num_ctx = 1024
    while num_ctx < (max_chars // 3) * 2 + 512:
        num_ctx *= 2
    motor = MotorOllama.de_env(num_ctx=num_ctx)
    print(f"modelo={motor.modelo} digest={motor.digest}")
    print(f"num_ctx={num_ctx} (maior doc: {max_chars} chars)")

    saidas = pasta / "saidas_ollama"
    saidas.mkdir(exist_ok=True)

    por_tipo = {}
    erros_doc = []
    t0 = time.time()
    for nome, gab, txt in docs:
        resp = await motor.anonimizar_texto(txt)
        (saidas / f"{nome}.txt").write_text(resp, encoding="utf-8")
        miss, exc = [], []
        for e in gab["entidades"]:
            t, sumiu = e["tipo"], e["texto"] not in resp
            st = por_tipo.setdefault(
                t, {"alvo": 0, "rem": 0, "pres": 0, "pres_perd": 0})
            if e["preservar"]:
                st["pres"] += 1
                st["pres_perd"] += sumiu
                if sumiu:
                    exc.append(e["texto"])
            else:
                st["alvo"] += 1
                st["rem"] += sumiu
                if not sumiu:
                    miss.append(e["texto"])
        if miss or exc or resp.count(TAG) == 0:
            erros_doc.append({
                "doc": nome,
                "nao_anonimizados": miss,
                "preservados_removidos": exc,
                "tags_emitidas": resp.count(TAG)})
        print(f"  {nome}: {len(txt)}c -> {len(resp)}c "
              f"miss={len(miss)} exc={len(exc)} "
              f"tags={resp.count(TAG)}")

    dt = time.time() - t0
    print(f"\n== recall / excesso por tipo (ajuste, {dt:.0f}s) ==")
    resumo = {}
    for t in sorted(por_tipo):
        st = por_tipo[t]
        rec = st["rem"] / st["alvo"] if st["alvo"] else None
        ov = (st["pres_perd"] / st["pres"]) if st["pres"] else None
        resumo[t] = {"recall": rec, "excesso": ov, **st}
        recs = f"{st['rem']}/{st['alvo']}={rec:.1%}" \
            if rec is not None else "-"
        ovs = f"{st['pres_perd']}/{st['pres']}={ov:.1%}" \
            if ov is not None else "-"
        print(f"  {t:<12} recall {recs:<18} excesso {ovs}")

    out = {"modelo": motor.modelo, "digest": motor.digest,
           "num_ctx": num_ctx, "segundos": round(dt, 1),
           "por_tipo": resumo, "erros": erros_doc}
    (pasta / "avaliacao_ollama.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), "utf-8")

    print("\n== erros por documento ==")
    if not erros_doc:
        print("  nenhum")
    for e in erros_doc:
        print(f"  {e['doc']}: miss={len(e['nao_anonimizados'])} "
              f"exc={len(e['preservados_removidos'])} "
              f"tags={e['tags_emitidas']}")
        for m in e["nao_anonimizados"]:
            print(f"      permaneceu: {m!r}")
        for x in e["preservados_removidos"]:
            print(f"      removeu indevido: {x!r}")


if __name__ == "__main__":
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    asyncio.run(avaliar(base))
