# ADR-0003: FastAPI como framework da API REST

**Status**: Aceito · **Data**: 2026-10-07

## Contexto

A proposta exige: REST/HTTP + JSON, OpenAPI/Swagger como contrato
**derivado do código** (deliverable do projeto), OAuth2/OIDC, rate
limit/cotas, biblioteca cliente em Python, latência e throughput
medidos — sobre pipeline NLP em Python com inferência CPU-bound.

## Opções avaliadas

| Framework | Release | Régua | OpenAPI derivado do código? | Concorrência | Veredito |
|---|---|---|---|---|---|
| **FastAPI** | dez/2018 | ✅ ~7 anos | **Sim — core do framework** | ASGI nativo | **Escolhido** |
| Django + DRF + drf-spectacular | 2005/2011/2020 | ✅ | Sim — addon (introspecção) | workers síncronos | Peso morto p/ API stateless |
| Flask + apispec | 2010/2017 | ✅ | Sim — addon | workers síncronos | Contrato vira plugin |
| Litestar | 2021–22 | ❌ | Sim | ASGI | Cortado pela régua |

## Decisão

**FastAPI** (sobre Starlette/ASGI, servido por uvicorn):

1. **OpenAPI é gerado do código, não configurado à parte** — o contrato
   nasce dos modelos Pydantic: fonte única de verdade, zero drift. É o
   requisito mais rígido da proposta satisfeito por construção, e o
   cliente Python sai por `openapi-generator`/`httpx` por consequência.
2. **ASGI nativo**: uma anonimização pode levar segundos (encoder em
   janelas de 512 tokens). Async não acelera inferência CPU-bound (isso é
   trabalho de process pool), mas sustenta muitas conexões concorrentes
   enquanto a inferência roda fora do loop — conta para throughput.
3. **Ecossistema NLP**: padrão de facto para servir modelos HF
   Transformers — mesma stack do restante do pipeline.

## Consequências

- Rate limit não é embutido → `slowapi` (2019 ✅) por `client_id` com
  **Redis como backend de storage** (fallback em memória por worker é
  aceitável no scale inicial).
- Histórico de breaking changes no versionamento 0.x → pin de versão no
  lockfile (poetry).
- Pydantic v2 (jul/2023) passa na régua com margem justa — registrado.
- FastAPI organiza auth/auditoria como dependências — JWT offline e
  `client_id` injetados de forma uniforme em todos os endpoints.
