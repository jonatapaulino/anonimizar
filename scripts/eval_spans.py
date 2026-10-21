"""Avalia contrato-spans-v0: o modelo devolve JSON {spans:
[{trecho,tipo}]} e o CODIGO faz a substituicao.

- JSON invalido => falha, listada; saida = texto intacto.
- span['trecho'] que nao e substring exata => invalido, contado.
- substituicao: todas as ocorrencias do trecho -> TAG.
- precisao de spans: exato (=entidade alvo), parcial_alvo
  (recorta parte de uma entidade alvo), preservado (atinge
  entidade preservada), fora (nao toca entidade alguma).

Uso: python scripts/eval_spans.py [base] [prompt_file] [rotulo]
"""
from __future__ import annotations

import asyncio
import difflib
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.motor_ollama as mo                        # noqa: E402
from app.motor_ollama import MotorOllama, TAG        # noqa: E402


def sobrepoe(a_ini, a_fim, b_ini, b_fim):
    return a_ini < b_fim and b_ini < a_fim


async def main(base: Path, pf: Path, rotulo: str):
    mo.SYSTEM_PROMPT = pf.read_text(encoding="utf-8")
    pasta = base / "ajuste"
    docs = []
    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text(encoding="utf-8"))
        txt = (pasta / gab["documento"]).read_text("utf-8")
        docs.append((g.stem, gab, txt))

    motor = MotorOllama.de_env(num_ctx=1024)
    print(f"modelo={motor.modelo} digest={motor.digest[:16]}… "
          f"num_ctx={motor.num_ctx} prompt={rotulo}")

    out_dir = pasta / f"saidas_ollama_{rotulo}"
    out_dir.mkdir(exist_ok=True)
    raws = out_dir / "raw"
    raws.mkdir(exist_ok=True)

    falhas_json, spans_stats = [], []
    t0 = time.time()
    for nome, gab, txt in docs:
        resp = await motor.anonimizar_texto(txt)
        (raws / f"{nome}.json").write_text(resp, encoding="utf-8")
        alvo = [e for e in gab["entidades"] if not e["preservar"]]
        pres = [e for e in gab["entidades"] if e["preservar"]]
        try:
            data = json.loads(mo._limpar(resp))
            spans = data.get("spans", [])
            if not isinstance(spans, list):
                raise ValueError("spans nao-lista")
        except Exception as ex:
            falhas_json.append((nome, str(ex)[:80],
                                resp[:120].replace("\n", " ")))
            (out_dir / f"{nome}.txt").write_text(txt, "utf-8")
            continue
        saida, ok, inv = txt, 0, 0
        for s in spans:
            tr, tp = s.get("trecho", ""), s.get("tipo", "?")
            if not tr or tr not in txt:
                inv += 1
                spans_stats.append((nome, tp, tr[:40], "invalido"))
                continue
            kind = "fora"
            for e in alvo:
                if e["texto"] == tr:
                    kind = "exato"
                    break
            else:
                i = txt.find(tr)
                for e in alvo:
                    if sobrepoe(i, i + len(tr),
                                e["inicio"], e["fim"]):
                        kind = "parcial_alvo"
                        break
                if kind == "fora":
                    for e in pres:
                        if sobrepoe(i, i + len(tr),
                                    e["inicio"], e["fim"]):
                            kind = "preservado"
                            break
            spans_stats.append((nome, tp, tr[:40], kind))
            ok += 1
            saida = saida.replace(tr, TAG)
        (out_dir / f"{nome}.txt").write_text(saida, "utf-8")
        print(f"  {nome}: spans={len(spans)} validos={ok} "
              f"invalidos={inv}")
    dt = time.time() - t0

    print(f"\n== spans por tipo declarado ({dt:.0f}s) ==")
    por_decl = {}
    for n, tp, tr, kind in spans_stats:
        d = por_decl.setdefault(tp, {})
        d[kind] = d.get(kind, 0) + 1
    for tp in sorted(por_decl):
        d = por_decl[tp]
        tot = sum(d.values())
        prec = d.get("exato", 0) / tot if tot else 0
        print(f"  {tp:<10} n={tot:<3} exato={d.get('exato',0):<3}"
              f" parcial={d.get('parcial_alvo',0):<3}"
              f" preservado={d.get('preservado',0):<3}"
              f" fora={d.get('fora',0):<3}"
              f" invalido={d.get('invalido',0):<3}"
              f" prec_exata={prec:.0%}")

    print(f"\nfalhas de JSON: {len(falhas_json)}")
    for n, err, trecho in falhas_json:
        print(f"  {n}: {err} | resp={trecho!r}")
    det = [x for x in spans_stats if x[3] != "exato"]
    print(f"spans nao-exatos ({len(det)}):")
    for n, tp, tr, k in det:
        print(f"  {n} {tp:<10} {k:<12} {tr!r}")

    resumo = {"contrato": rotulo, "modelo": motor.modelo,
              "digest": motor.digest, "num_ctx": motor.num_ctx,
              "segundos": round(dt, 1),
              "falhas_json": [f[0] for f in falhas_json],
              "spans_por_tipo_declarado": por_decl,
              "spans_detalhe": [
                  {"doc": n, "tipo": tp, "trecho": tr,
                   "classe": k} for n, tp, tr, k in spans_stats]}
    (pasta / f"avaliacao_{rotulo}.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    b = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    pf = Path(sys.argv[2] if len(sys.argv) > 2
              else "corpus/prompt_contrato_spans_v0.txt")
    rot = sys.argv[3] if len(sys.argv) > 3 else "spans-v0"
    asyncio.run(main(b, pf, rot))
