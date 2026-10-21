"""Avalia um prompt arbitrario (arquivo) na particao AJUSTE.

Uso: python scripts/eval_ollama_prompt.py corpus/prompt_v1.txt v1

- Injeta o prompt do arquivo no MotorOllama sem tocar app/
  (patch do global SYSTEM_PROMPT do modulo motor_ollama).
- Saidas cruas -> corpus/ajuste/saidas_ollama_<rotulo>/.
- Compara lado a lado com v0 (saidas_ollama/ gravadas).
- Metrica de fracao: intacta/parcial(>=50% sobrevive)/total.
- Excesso sobe vs v0 => linha marcada com '!!!'.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.motor_ollama as mo                        # noqa: E402
from app.motor_ollama import MotorOllama, TAG        # noqa: E402


def frac_removida(ent, saida):
    if ent in saida:
        return 0.0
    m = difflib.SequenceMatcher(None, ent, saida).find_longest_match()
    return 1.0 - m.size / max(len(ent), 1)


def faixa(f):
    return "intacta" if f <= 0.0 else \
           "parcial" if f <= 0.5 else "total"


def medir(docs, saidas):
    por_tipo, erros = {}, []
    for nome, gab in docs:
        resp = saidas[nome]
        miss, exc = [], []
        for e in gab["entidades"]:
            f = frac_removida(e["texto"], resp)
            st = por_tipo.setdefault(e["tipo"], {
                "alvo": dict.fromkeys(("intacta", "parcial",
                                       "total"), 0),
                "pres": dict.fromkeys(("intacta", "parcial",
                                       "total"), 0)})
            b = "pres" if e["preservar"] else "alvo"
            st[b][faixa(f)] += 1
            if e["preservar"]:
                if f > 0:
                    exc.append((e["texto"], f))
            elif f < 1.0:
                miss.append((e["texto"], f))
        if miss or exc:
            erros.append({"doc": nome, "miss": miss, "exc": exc,
                          "tags": resp.count(TAG)})
    return por_tipo, erros


def num(d, k):
    return d["total"] + d["parcial"] + d["intacta"], d[k]


async def main(base: Path, prompt_file: Path, rotulo: str):
    prompt = prompt_file.read_text(encoding="utf-8")
    mo.SYSTEM_PROMPT = prompt          # injeta sem tocar app/

    pasta = base / "ajuste"
    docs = []
    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text(encoding="utf-8"))
        docs.append((g.stem, gab))
    textos = {n: (pasta / gab["documento"]).read_text("utf-8")
              for n, gab in docs}

    motor = MotorOllama.de_env(num_ctx=1024)   # mesmo ctx do v0
    print(f"modelo={motor.modelo} digest={motor.digest[:16]}… "
          f"num_ctx={motor.num_ctx} prompt={rotulo}")

    out_dir = pasta / f"saidas_ollama_{rotulo}"
    out_dir.mkdir(exist_ok=True)
    saidas, t0 = {}, time.time()
    for n, _ in docs:
        resp = await motor.anonimizar_texto(textos[n])
        (out_dir / f"{n}.txt").write_text(resp, encoding="utf-8")
        saidas[n] = resp
        print(f"  {n}: {len(resp)}c tags={resp.count(TAG)}")
    dt = time.time() - t0

    t1, e1 = medir(docs, saidas)
    v0_dir = pasta / "saidas_ollama"
    if v0_dir.exists():
        t0d, _ = medir(docs, {n: (v0_dir / f"{n}.txt")
                              .read_text("utf-8") for n, _ in docs})
    else:
        t0d = {}

    print(f"\n== {rotulo} vs v0 — ajuste ({dt:.0f}s) ==")
    print(f"  {'tipo':<12} {'recall_v0':>10} {'recall_' + rotulo:>10}"
          f" {'exc_v0':>8} {'exc_' + rotulo:>8}  "
          f"parcial_{rotulo}(alvo/pres)")
    for t in sorted(set(t0d) | set(t1)):
        r0 = r1 = x0 = x1 = "-"
        if t in t0d:
            a = t0d[t]["alvo"]; n, k = num(a, "total")
            p = t0d[t]["pres"]; np_, kp = num(p, "total")
            _, kp2 = num(p, "parcial")
            if n:
                r0 = f"{k}/{n} {k / n:.0%}"
            if np_:
                x0 = f"{kp + kp2}/{np_}"
        if t in t1:
            a = t1[t]["alvo"]; n, k = num(a, "total")
            p = t1[t]["pres"]; np_, kp = num(p, "total")
            _, kp2 = num(p, "parcial")
            par_alvo = a["parcial"]
            if n:
                r1 = f"{k}/{n} {k / n:.0%}"
            if np_:
                x1 = f"{kp + kp2}/{np_}"
                if t in t0d:
                    p0 = t0d[t]["pres"]
                    e0 = p0["total"] + p0["parcial"]
                    if kp + kp2 > e0:
                        x1 += " !!!"   # excesso subiu vs v0
            else:
                par_alvo = a["parcial"]
        print(f"  {t:<12} {r0:>10} {r1:>10} {x0:>8} {x1:>8}  "
              f"parcial={par_alvo}/{t1.get(t, {}).get('pres', {}).get('parcial', 0)}")

    print("\n== erros por documento ({}) ==".format(rotulo))
    if not e1:
        print("  nenhum")
    for e in e1:
        print(f"  {e['doc']}: miss={len(e['miss'])} "
              f"exc={len(e['exc'])} tags={e['tags']}")
        for m, f in e["miss"]:
            print(f"      permaneceu({f:.0%}): {m!r}")
        for x, f in e["exc"]:
            print(f"      removeu({f:.0%}): {x!r}")

    resumo = {"prompt": rotulo, "sha256_prompt_file":
              str(prompt_file), "modelo": motor.modelo,
              "digest": motor.digest, "num_ctx": motor.num_ctx,
              "segundos": round(dt, 1), "por_tipo": t1,
              "erros": e1,
              "ordem": "2a config avaliada em ajuste "
                       "(1a=v0 7B; baseline=DemoMotorIA regex)"}
    (pasta / f"avaliacao_ollama_{rotulo}.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2,
                   default=str), "utf-8")


if __name__ == "__main__":
    b = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    pf = Path(sys.argv[2] if len(sys.argv) > 2
              else "corpus/prompt_v1.txt")
    rot = sys.argv[3] if len(sys.argv) > 3 else pf.stem
    asyncio.run(main(b, pf, rot))
