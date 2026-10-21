# ADR-0011: Zero IA generativa — somente modelos discriminativos locais

**Status**: Aceito · **Data**: 2026-10-15 · **Régua**: ADR-0000

## Contexto

Restrição arquitetural fixada pelo projeto: o módulo não pode depender de
IA generativa em nenhum ponto do pipeline. Os motivos convergem com decisões
já tomadas — soberania (ADR-0007), régua de maturidade (ADR-0000, que já
cortava LLMs), auditabilidade determinística (ADR-0002) e o posicionamento de
camada de pré-processamento da proposta. Há ainda um argumento estrutural:
os modos de falha que o módulo foi desenhado para conter (alucinação,
memorização explorável, prompt injection executável) são propriedades de
modelos generativos — adotá-los internamente criaria no módulo a
vulnerabilidade que ele protege nos consumidores.

Distinção que a decisão precisa fixar: "zero IA" não significa "zero modelo
estatístico". Modelos **discriminativos/encoder** (BERT de marcação de
spans, embeddings de similaridade, spaCy NER) recebem texto e produzem
rótulos/vetores — não geram conteúdo, não executam instruções embutidas,
não memorizam para regurgitar. São o núcleo científico do módulo (ADR-0001)
e a única forma de atingir as metas (F1 ≥ 0,85; reidentificação ≤ 5%).

## Opções consideradas

| Opção | Avaliação |
|-------|-----------|
| LLM no pipeline (geração, verificação, correferência) | Descartado: régua + soberania + importa os riscos que o módulo existe para conter |
| Zero literal — só regex + gazetteers + simbólico | Determinístico total, mas não detecta nomes/identificadores indiretos fora de lista; metas da proposta inalcançáveis; elimina o núcleo científico |
| **Zero generativo + encoders discriminativos locais** | Escolhido: mantém a detecção contextual; nenhuma superfície generativa |
| RAG dentro do módulo | Não se aplica: RAG pressupõe geração e o módulo não tem tarefa generativa. Retrieval sobre docs anonimizados é serviço adjacente futuro, fora deste escopo |

## Decisão

1. **Proibido**: qualquer componente que gere texto — LLMs (locais ou via
   API), decodificação autoregressiva, sumarizadores, reescritores.
2. **Permitido**: modelos discriminativos locais e determinísticos — NER
   encoder (ADR-0001), embeddings de similaridade (guardrails),
   classificadores, spaCy do re-scan (ADR-0010).
3. **Caso-borda resolvido — filtro de perplexidade**: implementado como
   *pseudo-perplexidade* via masked-LM (BERTimbau, mesmo backbone do
   guardrail semântico) — o modelo pontua tokens mascarados, não gera.
   Nenhum LM autoregressivo entra só para scoring.
4. **Reenquadramento honesto do guardrail**: sem LLM interno, injeção
   embutida no documento é inerte *para o módulo* — a camada de
   higienização protege o consumidor que alimentará o texto anonimizado a
   sistemas com LLM (ex.: arquitetura tipo JUDICATA) e sinaliza documentos
   envenenados. Mantida conforme Etapa 6 da proposta.
5. Consistência com a régua: ADR-0000 já cortava LLMs por data; este ADR
   transforma o corte em propriedade arquitetural permanente, não apenas
   critério de maturidade.

## Consequências

- **Positivas**: inferência é função pura e determinística → auditável por
  construção; não existe superfície de ataque de LLM; nenhuma dependência
  generativa para manter sob a régua; discurso institucional simplificado —
  "o módulo não contém IA generativa" é verificável no código.
- **Custos aceitos**: perdem-se capacidades que só generativos oferecem
  (correferência via LLM, detecção zero-shot por descrição) — compensadas
  pelo motor simbólico (ADR-0002) e pelo tagset supervisionado (ADR-0001).
- **Fronteira registrada**: se um componente generativo for proposto no
  futuro (ex.: LLM local para correferências difíceis), exige ADR que
  supersedá este + revisão do threat model — não entra por dependência
  silenciosa.
