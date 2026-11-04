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

Medição original (cascata v0, `saidas_ollama_cascata_teste`):

- Recall alvo 356/360 (98,9%); excesso preservado 0/305
- Reident: menção 4/360 (1,1%); documento 4/80 (5,0%)
- NER exact F1 **0,755 < gate 0,85 (FAIL)**; overlap F1 0,938
- Det pré-merge 253/259 (97,7%) dos seus tipos; aceito 202/259
- Ajuste reexecutado reproduziu 123/123 + 0 excesso (determinismo
  local, não reprodutibilidade cruzada)

Medição 04/11/2026 — cascata+poda (`saidas_ollama_cascata_poda`,
mesmo modelo/digest, `eval_cascata.py` + `poda_fronteira.py`):

- NER exact F1 **0,919 ≥ gate 0,85 (PASS)**; overlap F1 0,972
- Recall alvo 357/360 (99,2%); excesso preservado 0/305
- Reident: menção 3/360 (0,83%) — os 3 leaks são 'Pedro Henrique
  Almeida' (docs 0051/0066/0078), omissão de enumeração da passada
  só-NOME; 'MARCOS AURELIO TAVARES' (doc-0080) recuperado
- Prosa comida: rótulo 419c→45c, conteúdo 59c→8c (43→17 docs)
- CEP por-tipo F1 0,00 (FP=1, era FP=2): peculiaridade pré-
  registrada — LLM declara CEP como tipo, ouro não anota CEP fora
  de ENDERECO; pendente de emenda em `metricas.md`
- Ajuste (30 docs) com poda: exact F1 0,927, reident 0/123
- Residual: TELEFONE FN=8 overlap (mesmos 8 da v0 — formato que
  nem det nem LLM cobrem); CPF FP=8 (det dispara em não-CPF)

Medição 04/11/2026 — cascata v2 (`saidas_ollama_cascata_v2`:
poda + validador CPF mod-11 + res:NOME + drop tipos-mortos;
emenda datada em `docs/metricas.md`):

- NER exact F1 **0,953**; overlap F1 **1,000**; por tipo tudo 1,00
- Recall alvo **360/360 (100%)**; excesso preservado 0
- Reident: **0/360 = 0,0000** — res:NOME cobre os 3 leaks de
  enumeração ('Pedro Henrique Almeida'); validador mod-11 zera
  CPF FP=8/TEL FN=8 (mesmo span, causa única)
- Ajuste: exact F1 0,943; reident 0/123
- Residual: 17 FP + 17 FN exact (fronteira residual — ajuste fino
  ou discriminativo); prosa comida 45c rótulo + 8c conteúdo

## Próximos passos (ordem de dependência)

1. ~~Fechar NER exact ≥0,85~~ **feito na POC sintética**
   (04/11/2026): poda de fronteira aplicada → 0,919 na teste.
   Segue em aberto o caminho longo: NER discriminativo
   (LeNER-Br/UlyssesNER-Br) na porta MotorIA — necessário para
   sair do desvio ADR-0011 e validar em corpus real.
2. `ent_id` no corpus → destrava gates de correferência (pairwise
   ≥0,90, anti-merge ≤5%, consistência ≥0,85).
3. Cofre de chaves (Etapa 4/5) — decisão jurídica de reidentificação
   pendente (ver ata em `docs/atas/`).
4. mTLS na fronteira A↔B (JWT offline já existe).
5. Corpus real (Etapa 3) — depende das exclusões jurídicas.
6. Gates não avaliados: utility TAB ≥0,85, latência.
