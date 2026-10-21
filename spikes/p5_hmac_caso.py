"""P5 — PoC: cofre de mapeamentos com HMAC derivado por caso.

Spike do docs/plano-de-validacao.md (emenda ADR-0004).
Esquema sob teste: chave = HMAC(K, entidade ∥ case_id)

Hipóteses:
  H1: mesma entidade em casos diferentes → HMACs distintos →
      ZERO correlação transversal no cofre (insider não enxerga
      "entidade X aparece nos casos A e B").
  H2: esquema ANTIGO (HMAC(K, entidade) sem case_id) correlacionaria
      — demonstra o que a emenda corrigiu.
  H3: destruição da chave K (ADR-0012) torna o lookup impossível —
      o oráculo de dicionário morre; irreversibilidade operacional.
  H4: lookup por HMAC funciona para quem tem K + entidade + case_id.
"""
import hashlib
import hmac as _hmac
import secrets


def key_old(K: bytes, entidade: str, case_id: str) -> str:
    # esquema anterior à emenda: sem case_id
    return _hmac.new(K, entidade.encode(), hashlib.sha256).hexdigest()


def key_new(K: bytes, entidade: str, case_id: str) -> str:
    # esquema emendado: entidade ∥ case_id
    return _hmac.new(K, f"{entidade}\x1f{case_id}".encode(),
                     hashlib.sha256).hexdigest()


class Cofre:
    """Mini cofre: mapa hmac -> pseudônimo cifrado (simplificado)."""
    def __init__(self, K: bytes, fn):
        self.K, self.fn, self.mapa = K, fn, {}

    def put(self, entidade, case_id, pseudo):
        self.mapa[self.fn(self.K, entidade, case_id)] = pseudo

    def get(self, entidade, case_id):
        return self.mapa.get(self.fn(self.K, entidade, case_id))

    def chaves(self):
        return set(self.mapa)


def main():
    K = secrets.token_bytes(32)
    entidade = "João da Silva|CPF:123.456.789-00"

    # --- H1: sem correlação no esquema novo ---
    c_new = Cofre(K, key_new)
    c_new.put(entidade, "case-A", "PARTE-1")
    c_new.put(entidade, "case-B", "ARG-7")
    c_new.put(entidade, "case-C", "PER-3")
    print("H1 esquema novo: 3 casos, chaves distintas:",
          len(c_new.chaves()) == 3, "| correlação possível:",
          len(c_new.chaves()) != 3)

    # --- H2: esquema antigo correlacionava (demonstração) ---
    c_old = Cofre(K, key_old)
    for c in ("case-A", "case-B", "case-C"):
        c_old.put(entidade, c, "PSEUDO")
    print("H2 esquema antigo: mesma entidade -> 1 chave só:",
          len(c_old.chaves()) == 1,
          "(insider veria entidade em 3 casos)")

    # --- H4: lookup funciona para quem tem K + entidade + case_id ---
    print("H4 lookup legítimo:", c_new.get(entidade, "case-B") == "ARG-7")

    # --- H3: destruição da chave -> oráculo morto ---
    K_morta = secrets.token_bytes(32)  # destruição = nova chave aleatória
    c_dead = Cofre(K_morta, key_new)
    oraculo_morto = all(c_dead.fn(K_morta, entidade, cid) not in c_new.chaves()
                        for cid in ("case-A", "case-B", "case-C"))
    # sem K, nem brute-force prático: espaço de nomes ~1e6 -> mas cada
    # tentativa é inútil porque a chave não reproduz o HMAC original
    print("H3 pós-destruição: nenhuma chave reproduzível:", oraculo_morto)
    print("   (mesmo adivinhando a entidade, sem K não há como gerar")
    print("    o HMAC que acharia a linha — o oráculo de dicionário morre)")

    ok = (len(c_new.chaves()) == 3 and len(c_old.chaves()) == 1
          and c_new.get(entidade, "case-B") == "ARG-7" and oraculo_morto)
    print("\nRESULTADO:", "H1..H4 provadas" if ok else "FALHOU")


if __name__ == "__main__":
    main()
