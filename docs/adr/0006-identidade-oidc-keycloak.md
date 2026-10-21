# ADR-0006: OIDC com validação JWT offline; Keycloak como IdP de referência

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

Proposta exige "autenticação OAuth2/OIDC" e "autenticação institucional".
Consumidores são sistemas de órgãos do sistema jurídico (TJPA, DPE, MPPA,
PGE). Restrição de soberania (ADR-0007): **não pode haver dependência de
IdP SaaS externo em runtime** — a rede é isolada.

Insight estruturante: a API não deve acoplar-se a um IdP específico; deve
validar tokens de **qualquer issuer OIDC-compliant** via discovery
(`/.well-known/openid-configuration`) + JWKS.

## Opções consideradas

| Opção | Régua | Avaliação |
|-------|-------|-----------|
| **Keycloak** | ✅ 2014 | Padrão self-hosted; Login Único gov.br é Keycloak — pedigree institucional BR |
| authentik | ✅ ~5 anos | Válido; ecossistema e histórico menores |
| Dex | ✅ | Apenas federação — requer IdP upstream |
| Ory Hydra | ✅ | Só token service; exige peças companheiras |
| Auth0/Okta/Entra (SaaS) | — | Viola isolamento de rede |

## Decisão

1. **API agnóstica de issuer**: valida JWT offline com JWKS em cache
   (biblioteca **PyJWT** ou **Authlib** — 2014/2018 ✅; evitar python-jose,
   manutenção fraca). Emissão de token exige IdP; **validação não** —
   essencial para operação isolada.
2. **Keycloak como IdP de referência** no compose de implantação: garante
   "funciona isolado out-of-the-box". Órgão com IdP próprio (AD/Entra
   interno) apenas reconfigura a URL do issuer.
3. **Dois grants**:
   - `client_credentials` — sistemas consumidores (máquina→máquina);
   - `authorization_code` — operadores/auditores humanos via IdP.
4. **`client_id` como principal** de autorização (scopes por endpoint),
   cotas/rate limit e identidade do ator na trilha de auditoria — três
   requisitos da proposta resolvidos por uma decisão.
5. **mTLS + OAuth2 como camadas ortogonais** (ADR-0007): mTLS prova a
   máquina/rede no ingress; JWT prova o cliente e os escopos na aplicação.
   **RFC 8705 certificate-bound tokens obrigatório** (2020 ✅, suportado
   pelo Keycloak) — token vinculado ao certificado não é rejogável de
   outra máquina; com validação offline, é o único controle real de replay.
6. **TTL curto obrigatório**: validação offline via JWKS em cache não
   permite revogação — token vazado vale até expirar. Mitigação por
   desenho: expiração em minutos para `client_credentials`, sessão curta
   para humanos. Renovar é barato; revogar, impossível.

## Consequências

- **Positivas**: zero acoplamento a fornecedor; funciona 100% offline após
  emissão; identidade de auditoria nativa; alinhado a CNJ 615/2025.
- **Custo**: Keycloak é serviço a mais (JVM/RAM/ops) — justificado como IdP
  de referência; trocável por configuração.
- **Proibido**: implementar IdP próprio ou validar token por introspecção
  online como caminho único (quebraria isolamento).

## Emenda 2026-10-16

- RFC 8705 promovido de recomendado a obrigatório: com validação offline,
  o vínculo token↔certificado é o único controle efetivo de replay.
- Incluído TTL curto obrigatório para tokens: a ausência de introspecção
  elimina revogação, e expiração curta é a mitigação por desenho.
