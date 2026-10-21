# ADR-0000: Régua de maturidade — mínimo de 3 anos de uso

**Status**: Aceito · **Data**: 2026-10-07

## Contexto

O projeto exige que toda tecnologia adotada esteja aprovada e em uso há no
mínimo três anos. Trata-se de requisito de governança: o módulo manipulará
documentos sob segredo de justiça (art. 189 CPC) em ambiente soberano, e a
conservadorismo na seleção de dependências reduz risco de componentes
imaturas, abandonadas ou com superfície de segurança instável.

## Decisão

**Critério de corte**: uma tecnologia é elegível somente se lançada (ou em
versão estável com adoção comprovada) **antes de ~outubro/2023** — três anos
antes da data de referência desta arquitetura. Além da idade, exige-se sinal
de uso ativo: projeto abandonado falha o critério mesmo sendo antigo.

A régua aplica-se a: frameworks, bibliotecas, modelos de PLN, serviços de
infraestrutura e ferramentas de toolchain. Modelos e bibliotecas limítrofes
(lançados entre jul/2023 e out/2023) são registrados como "no fio" e exigem
justificativa adicional.

## Consequências

### Cortados explicitamente pela régua

| Candidato | Release | Idade em out/2026 | Motivo do corte |
|-----------|---------|-------------------|-----------------|
| GLiNER (NER zero-shot) | nov/2023 | ~23 meses | < 3 anos |
| Sabiá-2 / Sabiá-3 (LLM) | 2024–2025 | < 2 anos | < 3 anos (+ soberania) |
| OpenBao (fork do Vault) | nov/2023 | ~23 meses | < 3 anos |
| Litestar (framework web) | 2021–22 | ~2 anos | < 3 anos |
| uv (gerenciador de deps) | fev/2024 | ~20 meses | < 3 anos |
| fastcoref (correferência) | out/2023 | ~3 anos no fio | limítrofe + foco em inglês |
| neuralcoref | 2018 | antigo | **abandonado** — falha "em uso" |
| LLMs externos (APIs) | — | — | soberania + régua |

### Limítrofes registrados

| Tecnologia | Release | Situação |
|-----------|---------|----------|
| Pydantic v2 | jul/2023 | ~3,2 anos — passa no fio; versão pinada |
| fastcoref | out/2023 | no fio; descartado por escopo (inglês) |

### Efeito geral

A régua elimina alternativas "hype" (LLMs, NER zero-shot recente, forks
novos) e força o caminho comprovado — que coincide com o desenho da proposta
(NER supervisionado + motor simbólico + REST). Decisões individuais citam
este ADR ao registrar datas de release.
