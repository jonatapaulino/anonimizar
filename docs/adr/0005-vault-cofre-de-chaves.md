# ADR-0005: HashiCorp Vault como cofre de chaves (KEK/DEK)

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

A proposta (Etapa 7) exige "cofre cifrado de chaves (HSM/Vault)" para a
pseudonimização reversível controlada. O desenho de ADR-0004 usa cifragem
envelope: DEKs por caso cifram mapeamentos; a KEK que embrulha as DEKs
precisa de um lar que não seja o próprio banco nem variável de ambiente em
texto claro.

## Opções consideradas

| Opção | Régua | Avaliação |
|-------|-------|-----------|
| **HashiCorp Vault** | ✅ 2016 | Transit engine = criptografia como serviço; KEK nunca sai; audit devices nativos; citado na proposta |
| OpenBao (fork do Vault) | ❌ nov/2023 | Cortado pela régua (~23 meses) |
| HSM físico | ✅ | Padrão-ouro, mas custo/ops desproporcionais a um módulo de pesquisa; SoftHSM cobre testes de PKCS#11 |
| KMS de nuvem | — | Viola soberania — dependência externa em runtime |
| KEK em arquivo/secret montado | ✅ | Fallback válido para implantação mínima, com criptografia de disco — documentado, não preferido |
| Infisical e similares | ❌ | Novos demais / modelo SaaS |

## Decisão

**HashiCorp Vault (self-hosted, na mesma VLAN isolada) com Transit secrets
engine**:

- KEK reside no Vault e **nunca é exportada**; a aplicação envia DEKs para
  embrulhar/desembrulhar via API do Transit.
- Licença BSL: proíbe oferecer Vault como serviço concorrente; **uso interno
  governamental é permitido** — aderente ao cenário.
- Audit devices do Vault registram cada operação de chave → trilha
  independente da trilha da aplicação.
- Autenticação da aplicação ao Vault via AppRole (máquina) ou JWT/OIDC.
- **Fallback documentado** para implantação mínima: KEK como secret montado
  + disco cifrado + acesso restrito — aceitável quando Vault for
  inviável operacionalmente, com a degradação registrada no plano de auditoria.

## Consequências

- **Positivas**: separação real entre dados cifrados (Postgres) e chaves
  (Vault) — comprometer um não expõe o outro; rotação de KEK sem
  recifrar banco; conformidade com "cofre cifrado de chaves" literal da
  proposta.
- **Custo**: Vault é um serviço a mais (unseal, HA/raft, backup próprio) —
  incluído no compose de referência (ADR-0008); documentado como requisito
  de operação no estudo de implantação.
- **Soberania mantida**: Vault roda on-prem na VLAN isolada; zero
  dependência externa.
