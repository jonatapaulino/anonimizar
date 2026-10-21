# Especificação Técnica — Módulo de Anonimização Jurídica

> Projeto PIDE/FAPESPA — iSACI · "Anonimização Jurídica com Preservação de
> Coerência Processual: módulo API para governança e proteção de documentos
> no sistema jurídico estadual do Pará"
>
> Formato inspirado no documento de fluxo de desenvolvimento (referência:
> spec de integração Stripe). Decisões detalhadas em `docs/adr/`.

---

## Contexto

Órgãos do sistema jurídico estadual do Pará (TJPA, DPE, MPPA, PGE,
secretarias) precisam usar documentos jurídicos em pesquisa, gestão e
sistemas de IA **sem expor dados pessoais e sensíveis**. Anonimização
ingênua (apagar nomes) falha: deixa identificadores indiretos ou destrói a
compreensão do caso.

O módulo é uma **camada de pré-processamento e governança documental**,
consumível por API REST, que anonimiza preservando papéis processuais,
correferência, relações entre sujeitos e linha temporal.

Restrições arquiteturais fixas: **zero IA generativa** — somente modelos
discriminativos/encoders locais (ADR-0011); implantação de referência como
**nó edge soberano autocontido por órgão** (ADR-0007, ADR-0008).

## Motivo do Projeto

- Não existe solução madura de anonimização jurídica em PT-BR que concilie
  proteção de dados + utilidade semântica + auditabilidade + API.
- LGPD exige distinção real entre anonimização irreversível e
  pseudonimização reversível controlada.
- Resolução CNJ 615/2025 exige governança, auditoria e uso responsável de IA.
- Um serviço padronizado evita soluções fragmentadas por órgão.

## Glossário

| Termo | Descrição |
|-------|-----------|
| **Anonimização** | Substituição **irreversível** de identificadores; sem meios razoáveis de reidentificação (LGPD) |
| **Pseudonimização** | Substituição **reversível** mediante chave protegida e acesso restrito — continua sendo dado pessoal |
| **NER** | Named Entity Recognition — detecção de entidades (PESSOA, ORG, IDs) no texto |
| **Papel processual** | Função do sujeito na demanda: autor, réu, vítima, testemunha, procurador, autoridade, terceiro |
| **Correferência** | Menções distintas à mesma entidade ("João", "o réu", "ele") |
| **Linked Entities** | Motor simbólico que vincula menções à entidade canônica (ADR-0002) |
| **Cofre de mapeamentos** | Tabela cifrada entidade→pseudônimo, escopo por `case_id` (ADR-0004) |
| **KEK/DEK** | Chave-mestra (no Vault) que embrulha chaves de dados por caso (ADR-0005) |
| **Hash-chain** | Encadeamento de hashes na trilha de auditoria → tamper-evidence |
| **Prompt injection** | Instruções maliciosas embutidas no documento (guardrail de entrada) |
| **Filtro de perplexidade** | Detecta passagens estatisticamente anômalas (possível envenenamento) |
| **Proveniência** | Metadados de origem, assinatura e cadeia de custódia do documento |
| **mTLS** | TLS mútuo — cliente apresenta certificado; prova identidade da máquina |
| **OIDC / JWKS** | OpenID Connect; conjunto de chaves públicas para validar JWT **offline** |
| **Egress deny-all** | Contêineres sem rota de saída — soberania por configuração (ADR-0007) |
| **TAB** | Text Anonymization Benchmark — framework de avaliação (utilidade × proteção) |
| **Régua de 3 anos** | Toda tecnologia deve estar em uso ≥ 3 anos (ADR-0000) |
| **Re-scan de saída** | Segunda passagem recall-oriented sobre o texto anonimizado, caçando PII residual (ADR-0010) |
| **risk_score / review_flags** | Metadados da resposta que tornam a confiança de cada saída mensurável e auditável |
| **Zero IA generativa** | Nenhum componente gera texto — só encoders discriminativos (ADR-0011) |
| **Pseudo-perplexidade** | Score de anomalia via masked-LM (BERT pontua tokens mascarados, sem gerar) |
| **Nó edge** | Instância autocontida no órgão — processa onde o documento nasce, sem saída à nuvem |
| **Normalização Unicode** | Estágio 0 do pipeline: NFKC + remoção de zero-width/homoglifos (anti-evasão) |
| **Âncora externa** | Hash de topo da trilha exportado e assinado fora do host — impede recompute da cadeia |

## Arquitetura — visão

```
                        rede interna ──┐
                                        │
   outro órgão ── WireGuard/IPsec ──────┤
                                        ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  VLAN ISOLADA · egress deny-all · NTP interno                │
   │                                                              │
   │   nginx (mTLS, TLS 1.3)                                      │
   │      │                                                       │
   │      ▼                                                       │
   │   FastAPI ── JWT OIDC offline · rate limit · idempotência    │
   │      │                                                       │
   │      ├──► GUARDRAILS ── norm Unicode · inj. dual-pass        │
   │      │              └── perplexidade · proveniência          │
   │      ├──► ANONIMIZAÇÃO ─ NER legal-BERT + regex/validadores  │
   │      │              └── gazetteers → papéis → Linked Entities│
   │      │              → substituição consistente               │
   │      └──► SAÍDA/AUDITORIA ─ audit hash-chain+âncora · OTLP   │
   │                                                              │
   │   Postgres (cofre + trilha) · Vault (KEK) · Keycloak (IdP)   │
   └──────────────────────────────────────────────────────────────┘
                         ▲ SSH bastion (admin)
```

## APIs expostas

| Endpoint | Descrição | Auth/Escopo | Status |
|----------|-----------|-------------|--------|
| `POST /v1/anonymize` | Anonimiza documento (modo irreversível; cofre guarda só HMAC) | `anonymize:write` | DEFINIDO |
| `POST /v1/pseudonymize` | Pseudonimiza (mapeamento reversível cifrado no cofre) | `pseudonymize:write` | DEFINIDO |
| `POST /v1/reversal` | Reverte pseudonimização — **break-glass**, auditoria reforçada | `reversal:execute` + justificativa | INDEFINIDO |
| `GET /v1/documents/{id}/audit` | Consulta trilha de um documento | `audit:read` | DEFINIDO |
| `GET /health` · `GET /ready` | Liveness/readiness | público (rede interna) | DEFINIDO |
| `GET /metrics` | Métricas Prometheus (latência, throughput) | rede interna | DEFINIDO |

### Contrato `POST /v1/anonymize` (rascunho)

```jsonc
// Request
{
  "case_id": "0001234-56.2026.8.14.0000",     // escopo de consistência
  "document": { "format": "text/plain", "content": "..." },
  "options": { "preserve_roles": true, "consistency_scope": "case" }
}
// Headers: Authorization: Bearer <jwt> · Idempotency-Key: <uuid>

// Response 200
{
  "request_id": "req_01J...",
  "document_id": "doc_01J...",
  "result": { "format": "text/plain", "content": "...anonimizado..." },
  "stats": { "entities": 42, "by_type": { "PESSOA": 12, "ENDERECO": 3 } },
  "risk": { "residual_score": 0.02, "low_confidence_spans": 1, "needs_review": false },
  "review_flags": [ { "span_ref": "w1042-w1051", "reason": "low_confidence" } ],
  "model_version": "api@1.0.0+ner@legal-bert-sha256:abcd",
  "mode": "anonymization",
  "audit_id": "aud_01J..."
}
```

Erros: `400` schema inválido · `401/403` auth/escopo · `413` documento acima
do limite (bytes **ou** budget de tokens) · `422` formato não suportado ·
`429` cota excedida. Erros de validação são sanitizados: parsers ecoam a
entrada por default, e payload jamais aparece em resposta ou log.

### Formatos de documento

| Fase | Formatos |
|------|----------|
| MVP | `text/plain` |
| Extensão | `application/pdf` (extração + layout-aware), `docx` |

## Fluxo técnico — ciclo de vida de uma requisição

1. **Borda**: nginx valida cert mTLS → TLS 1.3 → repassa fingerprint.
2. **AuthN/Z**: FastAPI valida JWT offline (JWKS) → verifica escopo →
   registra `client_id` (identidade da auditoria).
3. **Idempotência/cota**: `Idempotency-Key` evita reprocessamento; rate
   limit por `client_id`.
4. **Normalização (estágio 0)**: Unicode NFKC + remoção de zero-width e
   homoglifos — fecha evasão por variantes tipográficas antes de qualquer
   regex ou NER.
5. **Guardrails**: prompt injection em dual-pass — regex + similaridade
   semântica BERTimbau contra ataques canônicos (limiar calibrado),
   perplexidade,
   validação de proveniência → rejeita ou sinaliza (`warnings[]`).
6. **Janelamento**: 512 tokens c/ overlap → reconciliação de spans.
7. **Detecção**: ensemble NER + regras + gazetteers → papéis processuais.
8. **Linked Entities**: resolve menções → entidade canônica → consulta
   cofre por `case_id` → pseudônimo estável (existente) ou novo.
9. **Substituição**: aplica pseudônimos preservando estrutura; grava
   mapeamento conforme modo (HMAC-only ou cifrado). Entidades abaixo do
   limiar de confiança são **mascaradas mesmo assim** e marcadas em
   `review_flags[]` (supressão conservadora — ADR-0010).
10. **Verificação residual**: re-scan recall-oriented sobre o texto
    anonimizado (regex + NER em limiar baixo + gazetteers); span suspeito
    residual → suprimido + registrado (ADR-0010).
11. **Auditoria**: audit row hash-chained (request_id, client_id, hashes,
    contagens, model_version, risk_score) — **nunca o conteúdo**.
12. **Resposta**: texto tratado + stats + `risk` + `audit_id`.

## Requisitos não funcionais

| RNF | Alvo |
|-----|------|
| Soberania | 100% offline após build; egress deny-all verificável |
| Latência | mediana por requisição medida via /metrics (alvo a definir no pré-registro) |
| Qualidade | F1 NER ≥ 0,85 · correferência ≥ 0,90 · reidentificação ≤ 5% · utility ≥ 0,85 (TAB adaptado) |
| Auditabilidade | trilha hash-chained; toda vinculação registra regra disparada |
| Disponibilidade | stateless API; escala horizontal trivial se necessário |
| Não-persistência | payload nunca toca disco nem log — inclui temporários, core dumps e erros de validação sanitizados |
| Budget de CPU | teto de tokens/janelas por requisição, além do limite de bytes — documento acima do budget é rejeitado, não enfileirado |
| Retenção | política TTL por caso + purge documentado (LGPD) |
| Maturidade | toda dependência ≥ 3 anos em uso (ADR-0000) |
| Classe de IA | zero modelos generativos; só encoders discriminativos, locais e determinísticos (ADR-0011) |

## Solução — tarefas

| Tarefa | Descrição | Status |
|--------|-----------|--------|
| Contrato OpenAPI | Gerar spec a partir dos modelos Pydantic; versionar `/v1` | DEFINIDO |
| Normalização de entrada | Estágio 0: Unicode NFKC + strip de zero-width/homoglifos antes de regex/NER — anti-evasão | DEFINIDO |
| Guardrails de entrada | Prompt injection dual-pass (regex + semântica BERTimbau contra ataques canônicos) + perplexidade + proveniência | DEFINIDO |
| NER jurídico | Fine-tune sobre backbone legal-BERT (STF) com tagset do projeto, no corpus sintético; Albertina-PT-BR como comparador | DEFINIDO |
| Classificador de papéis | Regras + features sobre pessoas detectadas | DEFINIDO |
| Linked Entities | Motor simbólico determinístico + registro por caso | DEFINIDO |
| Verificação residual | Re-scan com detector independente (spaCy) + supressão conservadora + `risk`/`review_flags` na resposta (ADR-0010) | DEFINIDO |
| Cofre de mapeamentos | Postgres; HMAC derivado por caso (irreversível) e cifrado (reversível) — ADR-0004/0012 | DEFINIDO |
| Trilha de auditoria | Tabela hash-chained + âncora externa + pgaudit + logs OTLP | DEFINIDO |
| Auth institucional | JWT offline (TTL curto) + RFC 8705 + Keycloak referência + mTLS no ingress | DEFINIDO |
| Empacotamento | OCI com modelo pinado por SHA (safetensors-only) + hardening baseline; compose de referência | DEFINIDO |
| Ciclo de vida de chaves | Destruição cerimonial HMAC por caso, unseal Shamir distribuído, bootstrap secret-zero (ADR-0012) | DEFINIDO |
| Cliente Python | Gerado do OpenAPI + wrapper `httpx` | DEFINIDO |
| Extração PDF/docx | Layout-aware, OCR quando necessário | INDEFINIDO — pós-MVP |
| API de reversão | Política break-glass, workflow de aprovação | INDEFINIDO — requer desenho com jurídico |
| Batch assíncrono | Fila p/ documentos grandes + webhooks de retorno | INDEFINIDO — se latência exigir |

## Decisões pendentes de refinamento (rascunhos a validar)

| Item | Rascunho de proposta | Pendência |
|------|----------------------|-----------|
| Geração de pseudônimos | Estratégia configurável por política: `placeholder_tipado` (`[AUTOR_1]`, `[TESTEMUNHA_2]` — default: máxima proteção e auditabilidade) ou `nome_ficticio` (nome plausível PT-BR consistente — máxima legibilidade narrativa). Escopo sempre `case_id` | Validar com jurídico; medir impacto no utility score (TAB adaptado) |
| `risk.residual_score` | `min(1, (w1·low_confidence_spans + w2·rescan_suppressed + w3·menções_sem_vínculo) / n_tokens)` — densidade ponderada de sinais de risco | Fixar fórmula e pesos no pré-registro (Etapa 1); calibrar no corpus da Etapa 3 |
| Recall de correferência | Métrica separada: % de menções que ficaram sem vínculo — o fallback "não vincular" (ADR-0002) degrada utilidade silenciosamente | Incluir no plano analítico pré-registrado (Etapa 10) |

## Riscos

| Risco | Descrição | Mitigação |
|-------|-----------|-----------|
| Reidentificação residual | Identificadores indiretos escapam ao detector | Ensemble + gazetteers + **re-scan de saída** (ADR-0010) + avaliação adversarial + hypothesis em CI; métrica ≤ 5% |
| Tagset divergente | Modelos prontos usam esquema LeNER-Br ≠ tagset do projeto | Fine-tune no corpus próprio (Etapa 3) — já previsto |
| Vinculação errada | Motor liga menção à entidade errada → quebra coerência | Fallback conservador (não vincular); supressão conservadora em baixa confiança (ADR-0010); regras auditáveis; meta ≥ 0,90 |
| Prompt injection evasivo | Ataque contorna regex+classificador | Dataset adversarial sintético; filtro de perplexidade; quarentena de docs suspeitos |
| Evasão tipográfica | Homoglifos/zero-width/acentos forjados contornam regex e degradam NER | Normalização Unicode (estágio 0) + re-scan de saída (ADR-0010) |
| Comprometimento de chaves | KEK/DEK vazam → pseudonimização vira exposição | Vault transit (KEK não exporta); unseal distribuído e destruição cerimonial (ADR-0012); rotação; hash-chain ancorada detecta acesso anômalo |
| Abuso da reversão | Endpoint de reversão mal utilizado | Escopo separado, break-glass, justificativa obrigatória, auditoria reforçada, rate limit agressivo |
| Dependência de órgão | Infra do órgão (CA, NTP, IdP) indisponível | CA step-ca e IdP Keycloak de referência no compose — funciona autônomo |
| Modelo desatualizado | Novos tipos de peça degradam NER | `model_version` auditado; ciclo de fine-tune documentado; release = nova imagem |
| Validade externa do corpus | Métricas medidas só sobre dados sintéticos podem superestimar desempenho em peças reais | Templates adversariais (ruído de OCR, variação de formato); amostras reais quando autorizadas (Etapa 3); validação institucional (Etapa 11); escopo do corpus declarado no pré-registro |

## Roadmap (alinhado às 12 etapas da proposta)

| Período | Entrega arquitetural |
|---------|----------------------|
| M1–M2 | Corpus sintético + tagset definitivo + requisitos (base do fine-tune) |
| M3–M5 | NER + papéis processuais (Etapa 4) |
| M4–M6 | Motor simbólico (Etapa 5) |
| M5–M7 | Guardrails (Etapa 6) |
| M6–M8 | Cofre + auditoria + Vault (Etapa 7) |
| M7–M9 | Integração API: OpenAPI, OIDC, cotas, container, cliente Py (Etapa 9) |
| M8–M10 | Avaliação experimental nas métricas (Etapa 10) |
| M9–M11 | Validação institucional no órgão parceiro (Etapa 11) |
| M12 | Documentação OpenAPI pública + código aberto + white paper (Etapa 12) |

## Referências de decisão

Cada bloco arquitetural tem ADR correspondente em `docs/adr/` — ver
[índice](adr/README.md). Régua de maturidade: ADR-0000.
