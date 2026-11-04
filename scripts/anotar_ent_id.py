"""Anota `ent_id` (cluster de correferência) nos gabaritos do
corpus gerado (corpus/ajuste, corpus/teste).

Regra derivada da estrutura do gerador (scripts/gerar_corpus.py):
cada bloco `_pessoa` planta os dados de UMA pessoa física —
NOME + RG/CPF/ENDERECO/EMAIL/TELEFONE subsequentes pertencem ao
mesmo referente. Portanto, em ordem de offset:

  - NOME privado  -> abre um novo cluster (nova pessoa)
  - CPF/RG/ENDERECO/EMAIL/TELEFONE privado -> entra no cluster
    aberto pelo NOME mais recente; sem NOME anterior, vira
    cluster unitário próprio
  - preservar=true (CNJ, VALOR, INSTITUICAO, ORGAO, CARGO, CIDADE)
    -> ent_id = None (não são referentes de pessoa física)

Consequência deliberada: duas pessoas plantadas com o MESMO texto
nominal ficam em clusters distintos (homônimo de template) — é o
comportamento correto para anti-merge.

O script é determinístico e idempotente. Regrava cada doc-NNNN.json
em linha (campo novo por entidade; texto/tipo/offsets/preservar
inalterados) e refaz o SHA256SUMS da partição acrescentando a
emenda ao manifesto — os hashes de .txt/.pdf não mudam.
"""
import hashlib
import json
from pathlib import Path

TIPOS_PESSOA = {"CPF", "RG", "TELEFONE", "EMAIL", "ENDERECO"}
BASE = Path(__file__).resolve().parents[1]


def anotar(ents, docid):
    """Atribui ent_id por ordem de offset; devolve n. de clusters."""
    k = 0
    aberto = None
    for e in sorted(ents, key=lambda x: (x["inicio"], x["fim"])):
        if e["preservar"]:
            e["ent_id"] = None
            continue
        if e["tipo"] == "NOME" or aberto is None or \
                e["tipo"] not in TIPOS_PESSOA:
            k += 1
            aberto = f"{docid}:p{k}"
        e["ent_id"] = aberto
    return k


def sha256_de(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main():
    hash_anot = sha256_de(Path(__file__).read_bytes())
    for particao in ("ajuste", "teste"):
        pasta = BASE / "corpus" / particao
        linhas, hashes = [], []
        nclu = nent = ndocs = 0
        for arq in sorted(pasta.glob("doc-*.*")):
            b = arq.read_bytes()
            if arq.suffix == ".json":
                gab = json.loads(b)
                nclu += anotar(gab["entidades"], arq.stem)
                nent += len(gab["entidades"])
                ndocs += 1
                b = (json.dumps(gab, ensure_ascii=False, indent=2)
                     + "\n").encode("utf-8")
                arq.write_bytes(b)
            h = sha256_de(b)
            linhas.append(f"{h}  {arq.name}")
            hashes.append(h)
        conjunto = sha256_de("".join(hashes).encode())
        antigo = (pasta / "SHA256SUMS").read_text(
            encoding="utf-8").splitlines()
        cabeca = [l for l in antigo
                  if (l.startswith("#") or l.startswith("GEN ")
                      or not l.strip())
                  and not l.startswith("# EMENDA")]
        cabeca.append(
            "# EMENDA 2026-11-04: campo `ent_id` anotado por "
            "scripts/anotar_ent_id.py (cluster de correferencia; "
            "regra de bloco _pessoa). texto/tipo/offsets/preservar "
            "inalterados — .txt/.pdf com mesmos hashes.")
        saida = cabeca + [
            f"ANOT {hash_anot}  ../../scripts/anotar_ent_id.py"
        ] + linhas + [f"SET  {conjunto}"]
        (pasta / "SHA256SUMS").write_text(
            "\n".join(saida) + "\n", encoding="utf-8")
        print(f"[{particao}] {ndocs} docs, {nent} entidades, "
              f"{nclu} clusters — SET {conjunto[:16]}…")


if __name__ == "__main__":
    main()
