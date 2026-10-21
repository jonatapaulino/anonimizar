# P7 — Resultado: validação offline de JWT (JWKS cacheado)

> Spike do `docs/plano-de-validacao.md` (ADR-0006). 2026-10-16.
> Keycloak 26.4 (dev-mode) no Docker + `spikes/p7_auth_offline.py`.

## Fluxo executado

1. Realm `juridico` criado com `accessTokenLifespan=120s`
   (TTL curto — ADR-0006 emendado)
2. Client `api-anon` confidencial com service account
   (client_credentials — o grant M2M da arquitetura)
3. Token emitido → JWKS fetched **uma vez** → cache em disco
4. **Daí em diante: zero chamada ao IdP**

## Veredito

| Teste | Resultado |
|---|---|
| Assinatura RS256 validada só com JWKS cacheado | ✅ |
| `iss` verificado offline | ✅ `http://localhost:8080/realms/juridico` |
| TTL curto | ✅ `exp-iat = 120s` (realm configurado) |
| Token adulterado (1 char trocado) | ✅ `InvalidSignatureError` |
| Issuer falso | ✅ `InvalidIssuerError` |

## O que isso prova

A premissa central do ADR-0006 funciona: **a API consegue validar
tokens sem falar com o IdP** — JWKS cacheado é suficiente para
assinatura + iss + exp. O isolamento do edge (P2) não quebra auth:
o IdP só precisa ser alcançável no bootstrap/rotação do JWKS, ou o
JWKS pode ser distribuído como artefato.

## Fora do escopo deste spike (documentado)

- **RFC 8705 (`cnf.x5t#S256`)**: cert-bound exige mTLS até o token
  endpoint + CA interna — depende da infra de certificados
  (ADR-0007), não do fluxo JWT. Spike próprio quando a CA existir.
- `aud`: token de service account vem com `aud=account`; na API real
  o resource server valida seu próprio aud — configuração de client,
  não limitação.
- Rotação de JWKS: cache com TTL + fallback documentado; testar
  quando houver key rotation real.

**Status P7: ✅ provado — validação offline funciona como desenhado.**
