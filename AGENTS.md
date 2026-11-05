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

Medição 04/11/2026 — correferência (`spikes/p3_correferencia.py`
revisto, harness `p8_metricas.py`, emenda 04/11-04b em
`docs/metricas.md`):

- `corpus_v0` (36 docs): pairwise **F1 1,000** (0,88→1,00),
  consistência **90/90 = 1,000**, anti-merge **0/270 = 0%** —
  os 3 gates PASS no proxy de template
- `ent_id` anotado nos 110 gabaritos (`scripts/anotar_ent_id.py`,
  regra de bloco `_pessoa`): 906 ents → 137 clusters, manifestos
  emendados; offsets/tipos inalterados
- Corpus gerado: pairwise/consistência degenerados por
  construção (cada pessoa plantada 1×); anti-merge 1/27 = 3,7%
  PASS (homônimo de template doc-0067)
- Aberto: partição com menções repetidas (multi-menção real)
  para exercer pairwise/consistência fora do corpus_v0; e o
  link de correferência ainda não está na saída do pipeline —
  TAG uniforme não carrega identidade (pseudonimização é modo
  separado da arquitetura)

## Próximos passos (ordem de dependência)

1. ~~Fechar NER exact ≥0,85~~ **feito na POC sintética**
   (04/11/2026): poda de fronteira aplicada → 0,919 na teste.
   Segue em aberto o caminho longo: NER discriminativo
   (LeNER-Br/UlyssesNER-Br) na porta MotorIA — necessário para
   sair do desvio ADR-0011 e validar em corpus real.
2. ~~`ent_id` no corpus~~ **feito** (04/11/2026): 137 clusters;
   gates de correferência mensuráveis; motor simbólico passa
   1,000/1,000/0% no proxy corpus_v0. Aberto: exercício real de
   pairwise/consistência exige docs com menções repetidas.
3. Cofre de chaves (Etapa 4/5) — decisão jurídica de reidentificação
   pendente (ver ata em `docs/atas/`).
4. ~~mTLS na fronteira A↔B~~ **feito** (04/11/2026): JWT removido
   (reprovado — XSS); identidade = certificado de cliente verificado
   no nginx (`deploy/nginx.conf`, `scripts/gerar_certs_mtls.py`) →
   `X-Cliente-Orgao`. Blindagem E2E (AEAD ChaCha20-Poly1305) nos 3
   pontos de I/O: `app/middleware_e2e.py` (request/response),
   broker (`PublicadorRabbitMQ`/`payload_de_mensagem`) e storage
   (`ArmazenamentoCifrado`). Chave via `E2E_CHAVE` (Vault); API sobe
   com `E2E_OBRIGATORIO=1` no compose. Provas: sniffer de socket
   real + cobertura de todas as rotas + handshake mTLS real
   (`docs/relatorio_seguranca_e2e.md`). Aberto:
   (a) ~~emissor E2E~~ **feito** (04/11/2026): `app/cliente_e2e.py`
       — selar+`x-e2e-ct`, GET selado canônico, multipart sob
       envelope, cert/verify p/ mTLS real; round-trip A↔B provado
       (tjpa→mpf.pa, dois uvicorns, `test_cliente_e2e.py`);
   (b) ~~replay~~ **feito** (04/11/2026): quadro v2 = `0xE2|0x02|
       nonce|len|ts_ms|ct` — ts no AAD (adulterá-lo quebra o selo);
       frescura `E2E_JANELA_MS` (300 s) + `ReplayCache` de nonces
       no ingresso HTTP; AMQP só frescura (redelivery legítima
       repete o envelope); S3/DLQ sem janela (repouso/forense não
       expira). Dívida: cache é processo-local — multi-réplica
       exige store compartilhado;
   (c) **ingress stream** — `abrir` materializa o corpo: upload
       multipart grande atravessa num quadro só;
   (d) TLS interno nos clientes (amqps/pg/ssl/s3) é contrato de
       URL — falta prova dinâmica + tcpdump na `interna`.
5. Corpus real (Etapa 3) — depende das exclusões jurídicas.
6. Gates não avaliados: utility TAB ≥0,85, latência.
