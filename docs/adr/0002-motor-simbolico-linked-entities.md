# ADR-0002: Correferência por motor simbólico (Linked Entities)

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

A substituição deve ser **consistente**: o mesmo ator recebe o mesmo
pseudônimo ao longo do documento e entre documentos do mesmo caso, com
preservação de relações de parentesco, hierarquia e linha temporal (meta:
consistência de correferência ≥ 0,90). Isso exige resolver menções —
"João", "o réu", "ele", "seu pai" — para a mesma entidade.

## Opções consideradas

| Opção | Régua | Avaliação |
|-------|-------|-----------|
| Coreferência neural PT-BR | — | **Não existe ferramenta madura** — só pesquisa acadêmica (corpora literários, teses) |
| fastcoref / LingMess | ❌/⚠️ | fastcoref: out/2023, no fio da régua e focado em inglês; LingMess: pesquisa |
| neuralcoref (spaCy) | ❌ | Abandonado — falha "em uso" mesmo sendo antigo |
| AllenNLP coref | ⚠️ | Inglês; projeto descontinuado |
| LLM para resolver menções | ❌ | Régua + soberania |
| **Motor simbólico determinístico** | ✅ | Regras próprias: registro de entidades + matching determinístico |

## Decisão

Implementar **motor simbólico Linked Entities** (código próprio), conforme
Etapa 5 da proposta:

- Registro de entidades por caso (`entity registry`); cada entidade real tem
  um pseudônimo canônico.
- Detecção de menções por regras: nomes próprios (NER), designações
  processuais ("o autor", "a testemunha"), pronomes e possessivos (regras
  morfossintáticas), títulos e parentesco ("seu pai", "a esposa do réu").
- Resolução intra-documento por ordenação de evidências (match exato >
  match parcial de nome > papel processual > regra pronominal com janela).
- Resolução inter-documento via cofre de mapeamentos por `case_id`
  (ver ADR-0004).
- Toda decisão de vínculo registra a **regra que disparou** — trilha
  auditável por menção.

## Consequências

- **Positivas**: determinístico → 100% auditável (exigência da Resolução CNJ
  615/2025); explicável para revisão humana; único caminho maduro em PT-BR;
  cobre a distinção anonimização/pseudonimização (reversão = consulta ao
  registro autorizado).
- **Custo**: é código próprio — o trabalho científico do projeto está aqui;
  cobertura de regras cresce com o corpus; casos ambíguos exigem política de
  fallback conservadora (não vincular > vincular errado).
- **Risco controlado**: meta de consistência ≥ 0,90 é mensurável por
  avaliação no corpus anotado com correferência (Etapa 3).
