# iSACI — contexto para agentes

PIDE/FAPESPA: nó de borda **soberano por instituição** para
anonimização e tramitação de documentos jurídicos. Repo privado:
`github.com/jonatapaulino/anonimizar`.

## Invariantes (não quebrar)

- Binário **nunca** entra em PostgreSQL, envelopes, broker ou
  resposta de API — só metadados + SHA-256 circulam entre nós.
- Upload: metadados + hash → multipart → verificação SHA-256 →
  MinIO `<org>-docs` → trilha + outbox numa **única transação**.
- Trilha append-only encadeada por hash (`hash_cadeia`).
- Idempotência por `(orgao, chave)` — reenvio é eco.
- `pii_residual`: residual>0 → `falha_anonimizacao:{id}:residual_pii`
  na trilha, **sem gravação** no bucket anonimizado. Logs só
  **contam** por tipo — nunca logar valores de PII.
- `MotorIA.anonimizar(bytes)->bytes` é porta permutável: trocar o
  motor não toca worker/trilha/buckets.

## Estrutura

- `app/` — API FastAPI, worker, relay, repository, `pii_residual.py`
- `app/motor_ollama.py` — implementação POC da porta MotorIA
- `corpus/ajuste` (30 docs, tuning) e `corpus/teste` (80, held-out)
  + gabaritos JSON + saídas da cascata
- `scripts/` — `gerar_corpus.py`, `eval_cascata.py`,
  `metricas_prereg.py`, `relatorio_pdf.py`, `apresentacao_pdf.py`
- `docs/metricas.md` — gates pré-registrados;
  `docs/relatorio_avaliacao.pdf` — relatório (GERADO);
  `docs/apresentacao_arquitetura.*` — apresentação (GERADA);
  `docs/atas/` — especificação e decisões de arquitetura
- `tests/smoke/` — suíte e2e
- `alembic/versions/` — migrações (0005 = outbox retry)

## Comandos

- Testes: `pytest -q` (suíte smoke/e2e)
- Ambiente local: `docker-compose.yml` (api+pg+rabbitmq+minio+worker
  +relay); credenciais dev vêm de env (`edvar_dev`, `edvar_dev_minio`)
- Relatório: `python scripts/relatorio_pdf.py`
  → `docs/relatorio_avaliacao.pdf` (edite a FONTE, não o PDF)
- Apresentação: `python scripts/apresentacao_pdf.py`
  → `docs/apresentacao_arquitetura.pdf` (idem; HTML é a fonte manual)

## Regras

- **Nunca alterar números medidos.** Não rodar motor nem reavaliar
  partições sem autorização explícita do usuário.
- Distinguir: medido × pós-hoc × cobertura potencial × não avaliado.
- ADR-0011: zero IA generativa. A cascata regex+Ollama qwen2.5 é
  **desvio documentado de POC**, não aprovada para produção; retorno
  à ADR exige NER discriminativo treinado medido no mesmo gate.
- Git: autor único `jonatapaulino <jonatapaulino@gmail.com>`;
  **sem co-autor nem trailer de bot**. Sem `git config` global.

## Estado medido (teste, 80 docs)

- Recall alvo 356/360 (98,9%); excesso preservado 0/305
- Reident: menção 4/360 (1,1%); documento 4/80 (5,0%)
- NER exact F1 **0,755 < gate 0,85 (FAIL)**; overlap F1 0,938
- Det pré-merge 253/259 (97,7%) dos seus tipos; aceito 202/259
- Ajuste reexecutado reproduziu 123/123 + 0 excesso (determinismo
  local, não reprodutibilidade cruzada)

## Próximos passos (ordem de dependência)

1. Fechar NER exact ≥0,85: podar FP de fronteira dos spans LLM
   (rótulos/prosa; 52/74 FP); caminho longo = NER discriminativo
   (LeNER-Br/UlyssesNER-Br) na porta MotorIA.
2. `ent_id` no corpus → destrava gates de correferência (pairwise
   ≥0,90, anti-merge ≤5%, consistência ≥0,85).
3. Cofre de chaves (Etapa 4/5) — decisão jurídica de reidentificação
   pendente (ver ata em `docs/atas/`).
4. mTLS na fronteira A↔B (JWT offline já existe).
5. Corpus real (Etapa 3) — depende das exclusões jurídicas.
6. Gates não avaliados: utility TAB ≥0,85, latência.
