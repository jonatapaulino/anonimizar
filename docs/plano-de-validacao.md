# Plano de Validação — Módulo de Anonimização Jurídica

> O que separa a arquitetura de "validada no papel" para "validada em
> princípio" e, depois, para "sistema validado". Cada prova lista
> objetivo, método, critério de sucesso e a decisão que destrava.
> Ordenado por risco × esforço — as provas mais baratas e mais
> incertas vêm primeiro.
>
> Estado: 2026-10-16 · **N1 completo (P1–P7) + P8 métricas-proxy
> executadas**. Última linha do documento tem o consolidado.

## Níveis de validação

| Nível | O que prova | Custo | Quando |
|-------|-------------|-------|--------|
| **N1 — Arquitetural** | o desenho funciona (spikes/PoCs) | dias cada | agora, sem corpus |
| **N2 — Experimental** | as metas científicas são atingidas | semanas | após corpus (E3+) |
| **N3 — Institucional** | órgão opera e aceita o módulo | semanas | Etapa 11 |

## N1 — Provas arquiteturais (sem corpus)

| # | Prova | O que valida | Método | Critério de sucesso | Destrava |
|---|-------|--------------|--------|---------------------|----------|
| P1 | **Benchmark latência BERT/CPU** | viabilidade da API síncrona | stock legal-BERT sobre docs de tamanho variado (1k–50k tokens), medir mediana/p95 por doc e por janela | latência/doc dentro de budget que viabilize UX síncrona; caso contrário, batch vira obrigatório | decisão DEFINIDO/ELIMINADO do "Batch assíncrono" |
| P2 | **Smoke test de isolamento** | soberania verificável (ADR-0007) | compose mínimo api+nginx+pg com `internal: true`; probe de egress (HTTP, DNS, IPv6) de dentro dos containers | zero conectividade externa medida — soberania é prova, não declaração | implantação de referência; hardening do compose |
| P3 | **Spike correferência simbólica** | plausibilidade da meta ≥0,90 (ADR-0002) | 20–30 casos artesanais com correferência anotada à mão (nomes, papéis, pronomes, parentesco); primeiras regras do motor | ≥ ~0,80 no conjunto artesanal indica que ≥0,90 é alcançável com regras adicionais | ADR-0002 segue ou reabre — **maior risco científico** |
| P4 | **PoC hash-chain + âncora** | mecanismo da emenda ADR-0004 | script: insere N linhas, adultera uma, detecta; exporta hash de topo, simula rewrite total, verifica | adulteração parcial detectada 100%; rewrite total detectado só com âncora | desenho da trilha definitivo |
| P5 | **PoC cofre HMAC por caso** | correção da emenda ADR-0004 | `HMAC(e∥c1) ≠ HMAC(e∥c2)` para mesma entidade em dois casos; teste de correlação; destruição de chave → lookup impossível | zero correlação transversal; destruição = irreversibilidade operacional | schema do cofre |
| P6 | **Pipeline de normalização** | estágio 0 anti-evasão | NFKC + strip zero-width + fold homoglifos sobre bateria adversarial ("Jοão", "J o ã o", "Ｊｏａｏ") | todas as variantes convergem para forma canônica antes de regex/NER | ordem do pipeline; corpus adversarial |
| P7 | **PoC auth offline** | fluxo ADR-0006 completo | Keycloak local emite JWT cert-bound; API valida offline com JWKS cache; token expira em minutos | validação sem chamada ao IdP; RFC 8705 rejeita token sem cert | integração auth no compose |

## Decisões pendentes — trabalho de papel, não provas

| Item | Dono | Bloqueia |
|------|------|----------|
| Tagset definitivo + esquema de anotação | Etapa 3 | fine-tune + todas as métricas |
| Regra de merge de spans do janelamento | especificar **antes** do corpus | corpus de avaliação (senão retrabalho) |
| Fórmula `residual_score` + pesos | pré-registro (Etapa 1) | contrato de risco |
| Métrica recall de correferência | pré-registro (Etapa 1) | medição do maior risco |
| Política de pseudônimos (`placeholder_tipado` × `nome_ficticio`) | **decisão com jurídico** | utility score, legibilidade |
| Break-glass da reversão | **desenho com jurídico** | `/v1/reversal` |
| Redis × rate limit em memória | fechar agora (emenda ADR-0003 ou nota) | compose de referência |
| Amostras reais | **pedir autorização já** — lead time burocrático | validade externa (N2/N3) |

## N2 — Provas experimentais (trilha científica, E3+)

| Meta | Como se prova | Gate | Baseline v0 (corpus sintético) |
|------|---------------|------|--------------------------------|
| F1 NER ≥ 0,85 | job de CI sobre corpus anotado | schemathesis+pytest | NER stock LeNER-Br: F1=0,92 só-nomes / 0,64 total (overlap) |
| Correferência ≥ 0,90 + recall | avaliação no corpus com correferência | CI | motor simbólico: pairwise F1=0,88, consistência=0,87 |
| Validadores ≥ ~1,00 | CI | CI | F1=1,00 em texto limpo — falta corpus degradado (OCR) |
| Reidentificação ≤ 5% | avaliação adversarial + hypothesis | CI contínuo | exige pipeline de saída |
| Utility ≥ 0,85 (TAB) | medidor + revisão amostral | CI | exige decisão jurídica de pseudônimos |
| Latência mediana | `/metrics` Prometheus | alvo do pré-registro | P1: ~110–180ms/janela CPU, ~9ms GPU |

**P8 — harness de métricas executado** (`spikes/p8_metricas.py` +
`corpus_sintetico.py` → `corpus_v0.jsonl`; resultado em
`spikes/P8_resultado.md`). As fórmulas de `docs/metricas.md` estão
implementadas — o corpus real entra como entrada, sem mudar código.

## N3 — Validação institucional (Etapa 11)

- TI do órgão sobe o compose sozinho, a partir da documentação — prova de operabilidade.
- Cerimônia de unseal do Vault executada por papéis distintos do órgão (ADR-0012).
- Usuários jurídicos avaliam utilidade do texto anonimizado em trabalho real.
- Amostras reais autorizadas — primeira medição de validade externa.

## Sequência sugerida

| Período | Ação |
|---------|------|
| Semana 1–2 | P1 (latência) · P2 (isolamento) · P6 (normalização) |
| Semana 2–4 | P3 (spike correferência — prioridade máxima) · P4 · P5 · P7 |
| Paralelo | fechar specs abertas (merge de spans, fórmulas, tagset) · pedir autorização de amostras reais · decisões com jurídico |
| Depois | corpus (E3) → trilha N2 → validação N3 |

## Planos B — se a prova falhar

| Se falhar | Custo arquitetural | Caminho |
|-----------|--------------------|---------|
| P1 latência | Baixo | batch assíncrono (já INDEFINIDO — vira DEFINIDO) |
| P2 isolamento | Baixo | ajuste de redes/firewall — configuração, não desenho |
| **P3 correferência** | **Alto** | reabrir ADR-0002: revisar motor, ensemble simbólico+heurísticas, ou rebaixar meta com justificativa |
| P4/P5 cripto | Baixo | mecanismo é padrão conhecido — falha indica bug, não desenho errado |
| F1 < 0,85 no tagset | Médio | ciclo normal: mais dados, mais fine-tune, ou revisar tagset |
| Amostras reais negadas | Médio | métricas declaradas com escopo do corpus (já mitigado no risco) |

## Critério de "arquitetura validada em princípio"

- [x] P1 mostra viabilidade síncrona (batch DEFINIDO >~10k tokens CPU;
      GPU torna síncrono universal — spikes/P1_resultado.md)
- [x] P2 prova isolamento por smoke test (spikes/P2_resultado.md)
- [x] P3 indica plausibilidade de ≥0,90 (40/40 artesanal;
      spikes/P3_resultado.md — corpus decide)
- [x] P4–P7 confirmam os mecanismos emendados (spikes/P4–P7_resultado.md)
- [ ] Specs abertas fechadas (merge de spans, fórmulas, tagset)
- [ ] Decisões com jurídico agendadas (pseudônimos, break-glass)

**Estado 2026-10-16: 4/6 fechados — falta trabalho de papel, não
de prova. Ver docs/relatorio-validacao.md.**
