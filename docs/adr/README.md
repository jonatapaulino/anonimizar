# Architecture Decision Records — Módulo de Anonimização Jurídica

Decisões de arquitetura do módulo de **Anonimização Jurídica com Preservação de
Coerência Processual** (projeto PIDE/FAPESPA — iSACI), consumível como API
REST/HTTP documentada em OpenAPI.

Cada ADR segue o formato: Contexto → Opções → Decisão → Consequências.
A data de referência da régua de maturidade (ADR-0000) é **outubro/2026**.

## Índice

| ADR | Decisão | Status |
|-----|---------|--------|
| [0000](0000-regra-de-maturidade.md) | Régua de maturidade ≥ 3 anos como critério de corte | Aceito |
| [0001](0001-deteccao-hibrida-de-entidades.md) | Detecção híbrida de entidades (BERT jurídico + regex/validadores + gazetteers) | Aceito |
| [0002](0002-motor-simbolico-linked-entities.md) | Correferência por motor simbólico determinístico | Aceito |
| [0003](0003-framework-web-fastapi.md) | FastAPI como framework da API REST | Aceito |
| [0004](0004-postgres-cofre-e-auditoria.md) | PostgreSQL para cofre de mapeamentos e trilha de auditoria | Aceito |
| [0005](0005-vault-cofre-de-chaves.md) | HashiCorp Vault como cofre de chaves (KEK/DEK) | Aceito |
| [0006](0006-identidade-oidc-keycloak.md) | OIDC com validação JWT offline; Keycloak como IdP de referência | Aceito |
| [0007](0007-rede-isolada-e-tuneis.md) | Topologia de rede isolada, mTLS no ingress, túneis site-to-site | Aceito |
| [0008](0008-empacotamento-oci-compose.md) | Imagem OCI com modelo embutido; deploy via docker compose | Aceito |
| [0009](0009-stack-de-testes-e-toolchain.md) | Stack de testes (pytest/hypothesis/schemathesis) e toolchain | Aceito |
| [0010](0010-verificacao-residual-e-confianca.md) | Re-scan de saída, supressão conservadora e risk_score | Aceito |
| [0011](0011-zero-ia-generativa.md) | Zero IA generativa — somente modelos discriminativos locais | Aceito |
| [0012](0012-ciclo-de-vida-de-chaves.md) | Ciclo de vida de chaves: destruição cerimonial, unseal distribuído, bootstrap | Aceito |
| [0013](0013-mensageria-barramento-ia.md) | RabbitMQ + outbox transacional obrigatória para o handoff assíncrono de IA | Aceito |

## Convenção

- **Aceito**: decisão validada e incorporada à arquitetura.
- **Superseded**: substituído por ADR posterior (manter histórico).
- Candidatos cortados pela régua ficam registrados na seção "Opções consideradas"
  de cada ADR, com a data de referência do corte.
