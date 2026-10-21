# ADR-0010: Verificação residual de saída e controle por confiança

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

Reidentificação residual, vinculação errada e cobertura de tagset são riscos
**inerentes** a sistemas probabilísticos — não elimináveis por escolha de
tecnologia. O padrão jurídico aplicável (LGPD/ANPD) é "meios razoavelmente
disponíveis", não impossibilidade absoluta; a própria proposta fixa meta de
reidentificação ≤ 5%. O objetivo correto da arquitetura é tornar o risco
residual **limitado, medido e auditado**, sem degradar a utilidade nem
complicar o contrato da API.

Restrição de desenho assumida: nenhum mecanismo pode criar estados novos que
o consumidor precise tratar (a API segue síncrona e de resposta única) nem
duplicar o custo computacional do pipeline.

## Opções consideradas

| Opção | Avaliação |
|-------|-----------|
| Nada — aceitar residual silencioso | Irresponsável: falhas passam sem rastro nem revisão |
| Bloquear docs incertos (202/fila) | Quebra o contrato síncrono; cria fila de revisão acoplada à API e atrasa o pipeline |
| **Re-scan + supressão conservadora + flags** | Segurança aumentada, contrato intacto, custo limitado |

## Decisão

Três mecanismos aditivos na Camada de Anonimização/Saída:

1. **Re-scan de saída (verification pass)**: após a substituição, uma
   segunda passagem *orientada a recall* sobre o texto já anonimizado —
   regex/validadores + NER em limiar baixo + gazetteers + **detector
   independente** (spaCy `pt_core_news_lg`) — procura PII residual. A independência do
   detector é proposital: modelo diferente do backbone principal reduz
   falhas correlacionadas. É deliberadamente a passagem **barata** (não
   o pipeline completo): custo de latência limitado a uma fração da
   detecção principal. Span suspeito residual → suprimido + registrado.
2. **Supressão conservadora por confiança**: entidade detectada abaixo do
   limiar de confiança é **mascarada mesmo assim** (over-suppression:
   perde-se um pouco de utilidade, nunca proteção) e sinalizada em
   `review_flags[]` — sem bloquear a resposta.
3. **`risk` no contrato de resposta**: `residual_score`,
   `low_confidence_spans`, `needs_review` — o consumidor e a trilha de
   auditoria passam a *conhecer* a confiança de cada saída.

Complemento operacional (não-código): documentos de alto risco (infância,
violência doméstica, sigilo reforçado) devem ter **gate humano por política
de uso** do órgão — coerente com o posicionamento do módulo como camada de
apoio, não substituto de profissional.

## Consequências

- **Positivas**: falha da detecção principal deixa de ser silenciosa —
  vira flag auditável; o pior caso deixa de ser "vazou PII" e vira
  "mascaramos demais um trecho" (erro no lado seguro do trade-off
  privacidade×utilidade); `risk_score` torna o residual *mensurável por
  documento*, alimentando a métrica de reidentificação do experimento.
- **Custos aceitos (registrados)**: latência aumenta por uma passagem
  barata (estimada em fração da detecção — a medir no benchmark);
  `needs_review=true` pressupõe que exista processo institucional de
  revisão no consumidor — documentado como pré-requisito operacional;
  over-suppression pode reduzir marginalmente o utility score — a
  calibragem do limiar é feita sobre o corpus da Etapa 3.
- **Não resolve**: risco zero segue inatingível — estes mecanismos contêm
  e medem, não eliminam. Isso é intencional e defensável perante LGPD,
  CNJ 615/2025 e banca.
