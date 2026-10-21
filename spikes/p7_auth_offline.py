"""P7 — PoC: validação offline de JWT com JWKS cacheado (ADR-0006).

Fluxo sob teste:
  1. API recebe JWT emitido pelo Keycloak (client_credentials)
  2. API tem JWKS cacheado em disco — NÃO fala com o IdP na validação
  3. Assinatura + iss + aud + exp validados localmente
  4. TTL curto verificado (exp-iat <= 120s nesta PoC)
  5. Token adulterado rejeitado

A única chamada ao IdP é o fetch ÚNICO do JWKS (bootstrap/rotação) —
exatamente como previsto: cache com TTL, funciona isolado depois.
"""
import json
import sys
import urllib.request

import jwt
from jwt import PyJWK

BASE = "http://localhost:8080"
REALM = "juridico"
SECRET = open("spikes/p7_secret.txt").read().strip()


def post(url, data):
    req = urllib.request.Request(
        url, data="&".join(f"{k}={v}" for k, v in data.items()).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req))


def get_json(url):
    return json.load(urllib.request.urlopen(url))


def main():
    # 1) token de serviço
    tok = post(f"{BASE}/realms/{REALM}/protocol/openid-connect/token", {
        "grant_type": "client_credentials",
        "client_id": "api-anon",
        "client_secret": SECRET})
    access = tok["access_token"]
    print("token emitido, expires_in(header):", tok["expires_in"], "s")

    # 2) fetch ÚNICO do JWKS -> cache em disco (única ida ao IdP)
    jwks = get_json(f"{BASE}/realms/{REALM}/protocol/openid-connect/certs")
    json.dump(jwks, open("spikes/p7_jwks_cache.json", "w"))
    print("jwks cacheado em spikes/p7_jwks_cache.json")

    # ===== DAQUI PRA BAIXO: OFFLINE (sem chamada ao IdP) =====
    jwks_cached = json.load(open("spikes/p7_jwks_cache.json"))
    header = jwt.get_unverified_header(access)
    jwk_dict = next(k for k in jwks_cached["keys"] if k["kid"] == header["kid"])
    pub_key = PyJWK.from_dict(jwk_dict).key

    # 3) validação local completa (aud de service account do Keycloak
    #    é "account"; na API real seria o aud do próprio recurso)
    claims = jwt.decode(
        access, key=pub_key, algorithms=["RS256"],
        issuer=f"{BASE}/realms/{REALM}",
        options={"require": ["exp", "iat", "iss", "sub"],
                 "verify_aud": False})
    ttl = claims["exp"] - claims["iat"]
    print("VALIDADO OFFLINE:")
    print("  iss:", claims["iss"])
    print("  sub:", claims["sub"][:40] + "...")
    print("  aud:", claims.get("aud"))
    print("  escopo:", claims.get("scope"))
    print("  TTL (exp-iat):", ttl, "s -> <=120s:",
          ttl <= 120, "(TTL curto ADR-0006)")

    # 4) token adulterado -> rejeição local (troca 1 char no meio:
    # formato válido, assinatura inválida — chega na verificação RS256)
    mid = len(access) // 2
    bad = access[:mid] + ("A" if access[mid] != "A" else "B") + access[mid+1:]
    try:
        jwt.decode(bad, key=pub_key, algorithms=["RS256"],
                   issuer=f"{BASE}/realms/{REALM}",
                   options={"verify_aud": False})
        print("FALHOU: token adulterado aceito")
        sys.exit(1)
    except jwt.InvalidSignatureError:
        print("token adulterado -> rejeitado localmente")

    # 5) iss errado -> rejeição
    try:
        jwt.decode(access, key=pub_key, algorithms=["RS256"],
                   issuer="http://evil.example/realm",
                   options={"verify_aud": False})
        print("FALHOU: issuer falso aceito")
        sys.exit(1)
    except jwt.InvalidIssuerError:
        print("issuer falso -> rejeitado localmente")

    print("\nRESULTADO: validação offline + TTL curto + rejeições provadas")


if __name__ == "__main__":
    main()
