# ADR-0009: Stack de testes e toolchain

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

O projeto adota desenvolvimento orientado a testes (TDD) e precisa
transformar suas próprias métricas de sucesso (F1, reidentificação,
utility, latência) em verificações automatizadas de CI. As dependências de
toolchain também passam pela régua.

## Opções consideradas

| Função | Escolhido | Release | Descartado | Motivo |
|--------|-----------|---------|------------|--------|
| Framework de teste | **pytest** | 2004+ | unittest | Ecossistema, fixtures, plugins |
| Property-based | **hypothesis** | ~2015 | — | Gera casos adversariais de PII |
| Teste de contrato | **schemathesis** | 2019 | dredd | Faz fuzzing da API contra o próprio OpenAPI — drift vira falha de CI |
| Teste de integração | **testcontainers** | 2015 | mocks | Postgres/Vault reais descartáveis |
| Lint/format | **ruff** | dez/2022 (~3,8a) | flake8+isort | Velocidade; passa na régua |
| Tipagem | **mypy** | 2015 | pyright | Padrão maduro |
| Security lint | **bandit** | 2015 | — | SAST Python |
| Deps Python | **poetry** | 2018 | **uv (fev/2024 ❌)** | uv falha a régua por ~1,5 ano — revisitar se flexibilizada |
| SBOM | **syft** | 2020 | — | Cadeia de custódia |
| Varredura de CVEs | **grype** | 2020 | — | SBOM sem gate não detecta nada — varre o SBOM no CI |
| Assinatura imagem | **cosign** | 2021 | — | Proveniência do artefato |
| Métricas | **Prometheus** | 2012 | statsd | `/metrics` alimenta as próprias métricas do projeto |
| CI | **GitHub Actions** ou **GitLab CI** | 2019/2015 | — | GitLab self-hosted se soberania total no CI for exigida |

## Decisão

1. **TDD com pytest** como ciclo base (red-green-refactor).
2. **Testes orientados às métricas do projeto**:
   - hypothesis: propriedade *"a saída nunca contém PII presente na
     entrada"* — a taxa de reidentificação vira teste automatizado;
   - schemathesis: contrato OpenAPI testado em CI — documentação nunca
     diverge do comportamento;
   - avaliação de NER/coreferência como job de CI no corpus da Etapa 3
     (gate: F1 ≥ 0,85, consistência ≥ 0,90).
3. **poetry** com lockfile pinado (determinismo de build); ruff+mypy+bandit
   como gates; syft+cosign nos artefatos de release; **grype** varre o
   SBOM como gate de CVEs no CI.
4. **Prometheus** expõe latência/throughput — as métricas de avaliação
   experimental (Etapa 10) usam a mesma instrumentação de produção.

## Consequências

- **Positivas**: as metas científicas do projeto viram código de CI, não
  relatório posterior; contrato e comportamento não divergem; toolchain
  inteira madura.
- **Custo**: hypothesis/schemathesis adicionam tempo de CI (mitigado com
  budgets); poetry é inferior a uv em velocidade — troca simples se a régua
  for flexibilizada.
