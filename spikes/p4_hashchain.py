"""P4 — PoC: trilha hash-chained com âncora externa.

Spike do docs/plano-de-validacao.md (emenda ADR-0004).
Duas hipóteses sob teste:
  H1: adulteração de UMA linha da trilha é detectada pela verificação
      da cadeia (recomputar e comparar hashes).
  H2: REWRITE TOTAL da trilha (atacante reescreve tudo e recalcula
      todos os hashes) é INDETECTÁVEL pela verificação sozinha —
      e DETECTÁVEL comparando o hash de topo com a âncora externa.

Modelo da linha de auditoria (conforme ADR-0004/emenda):
  hash_linha = SHA256(seq | payload_hash | prev_hash)
  payload_hash = SHA256(evento)   — nunca conteúdo em claro
"""
import hashlib
import json


def h(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def nova_linha(seq: int, evento: str, prev_hash: str) -> dict:
    payload_hash = h(evento)
    hash_linha = h(f"{seq}|{payload_hash}|{prev_hash}")
    return {"seq": seq, "payload_hash": payload_hash,
            "prev_hash": prev_hash, "hash_linha": hash_linha}


def verifica_cadeia(trilha: list) -> bool:
    """Recomputa a cadeia inteira e compara com o que está gravado."""
    prev = "GENESIS"
    for linha in trilha:
        esperado = h(f"{linha['seq']}|{linha['payload_hash']}|{prev}")
        if esperado != linha["hash_linha"] or linha["prev_hash"] != prev:
            return False
        prev = linha["hash_linha"]
    return True


def topo(trilha: list) -> str:
    return trilha[-1]["hash_linha"] if trilha else "GENESIS"


def main():
    # trilha original: 5 eventos
    trilha = []
    prev = "GENESIS"
    for i, ev in enumerate(["anonymize job-1", "review flag-2",
                            "reversal req-3", "map insert-4", "export-5"]):
        linha = nova_linha(i, ev, prev)
        trilha.append(linha)
        prev = linha["hash_linha"]

    # âncora externa: hash de topo exportado/assinado fora do host
    ancora = topo(trilha)

    print("cadeia original íntegra:", verifica_cadeia(trilha))

    # ATAQUE 1 — adulterar a linha 2 (mudar payload_hash)
    t1 = [dict(l) for l in trilha]
    t1[2]["payload_hash"] = h("reversal req-3 ADULTERADO")
    print("ataque-1 adultera linha -> detectado:", not verifica_cadeia(t1))

    # ATAQUE 2 — rewrite total: reescreve evento E recalcula a cadeia
    t2 = []
    prev = "GENESIS"
    for i, ev in enumerate(["anonymize job-1", "review flag-2",
                            "evento-inocuo-3",  # história reescrita
                            "map insert-4", "export-5"]):
        linha = nova_linha(i, ev, prev)
        t2.append(linha)
        prev = linha["hash_linha"]

    verifica_ok = verifica_cadeia(t2)
    ancora_confere = (topo(t2) == ancora)
    print("ataque-2 rewrite total:")
    print("  verificacao da cadeia (sem ancora): passa =",
          verifica_ok, "<- indistinguivel do original" if verifica_ok
          else "falhou")
    print("  comparacao com ancora externa: detectado =",
          not ancora_confere)

    # resultado
    ok = (verifica_cadeia(trilha) and not verifica_cadeia(t1)
          and verifica_ok and not ancora_confere)
    print("\nRESULTADO:", "H1+H2 provadas" if ok else "FALHOU")


if __name__ == "__main__":
    main()
