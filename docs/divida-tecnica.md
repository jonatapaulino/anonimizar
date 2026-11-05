# Dívida técnica — esteira de tramitação

Itens identificados na revisão de arquitetura e **não** entregues no
MVP. Categorias:

- **demo** — necessário para demonstração convincente
- **dados reais** — necessário antes de qualquer documento real
- **produção** — necessário para operação contínua em produção

## Segurança de acesso

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| ~~`receber` não autentica o `origem` declarado~~ **resolvido 05/11:** `receber` exige `org == env.origem` (o contrato do envelope, ADR-0007) — quem posta é o remetente com o cert dele; 409 uniforme antes do carregar, sem oráculo | dados reais | `app/service.py` `receber` | órgão forja envelope em nome de terceiro |
| RBAC/ABAC — identidade mTLS carrega só o CN do órgão, sem roles/escopos (JWT removido; OIDC segue opção para identidade humana — emenda ADR-0006) | produção | `app/deps.py` | privilégio excessivo dentro do órgão |
| Credencial única MinIO acessa todos os buckets — sem policy por órgão | dados reais | `app/storage.py` | nó comprometido lê bruto de todos |
| ~~Rotação de chave via JWKS e `kid`~~ **obsoleto 05/11:** JWT removido da borda (mTLS puro); rotação E2E é por `ChavesE2E{atual,anteriores}` no cofre | produção | `app/cofre.py` | — |
| ~~Revogação de token~~ **obsoleto 05/11:** sem token a revogar na borda; revogação de cert é problema de PKI (CRL/OCSP no nginx — dívida nova, não implementada) | produção | `deploy/nginx.conf` | cert comprometido aceito até expirar/revogar |
| ~~Ordem das checagens por convenção~~ **resolvido 05/11:** sequência participação→papel→nó centralizada em `NoTramitacao._autorizar` — call site que reordenar quebra num lugar só | dados reais | `app/service.py` `_autorizar` | terceiro descobre que o caso existe |
| `org` é confiado dentro do serviço (§4.8): `NoTramitacao` não autentica — a identidade vem do mTLS em `deps.orgao_atual` (JWT→cert); qualquer chamada interna futura com `org` forjado contorna a autorização. **Mitigado 05/11:** a confiança agora converge num método (`_autorizar`), mas `org` segue parâmetro confiável | dados reais | `app/service.py` `NoTramitacao`; `app/deps.py` | endpoint interno futuro vira bypass de soberania |
| ~~Envelope, ack e confirmação trafegam sem assinatura (§5.5)~~ **resolvido 05/11 (B):** Ed25519 em `app/assinatura.py` — `EnvelopeRecebimento.assinatura` cobre todos os demais campos (JSON canônico ordenado); `receber` verifica contra a pública de `env.origem`, `ConfirmacaoOut` sai assinado pelo destino e `aplicar_confirmacao` só aplica com a assinatura dele — fail-closed onde o par existe (`ORG_SIGN_SEED_B64`+`ORGAO_PUBKEYS_JSON`); ausente = dev sem verificação | dados reais | `app/assinatura.py`; `app/service.py` `receber`, `aplicar_confirmacao`, `confirmar` | par forja decisão/hash sem prova |
| ~~Envelope sem `destino`~~ **resolvido 05/11 (B):** campo `destino` no `EnvelopeRecebimento`; `receber` rejeita `env.destino != self.orgao` — envelope mal-endereçado não vira registro | dados reais | `app/schemas/tramitacao.py`; `app/service.py` `receber` | envelope re-direcionado registrava no nó errado |
| ~~Hash da confirmação é auto-declarado por B (§4.7)~~ **resolvido 05/11 (B):** `confirmar` exige os bytes no storage de B, relê e recomputa SHA-256 contra o registrado — tudo antes de `_transitar`; declarar sem bytes verificados é 409 | dados reais | `app/service.py` `confirmar`; `tests/smoke/test_seguranca_b.py` | confirmação afirma integridade sem prová-la |

## Integridade da trilha

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| Cadeia refutável por quem escreve no Postgres — sem assinatura por entrada nem âncora externa | dados reais | `app/repository.py` `encadear` | DBA reescreve e re-encadeia a trilha |
| ~~Endpoint de verificação~~ **parcial 05/11 (B):** `GET /v1/tramitacoes/{id}/verificar` rejoga a cadeia elo a elo (`repo.verificar`) e aponta a 1ª divergência — auditoria autônoma sem confiar no topo. Assinatura Ed25519 **por linha** da trilha segue aberta (prova a terceiros exigiria a assinatura persistida por evento) | dados reais | `app/repository.py` `verificar`; `app/service.py` `verificar_trilha`; `app/main.py` | sem prova a terceiros |
| ~~Fork por corrida~~ **resolvido 05/11:** `pg_advisory_xact_lock` no `encadear` serializa a extensão (Postgres; sqlite serializa por arquivo) + `UNIQUE(hash_anterior)` migração 0006 como backstop — quem burlar a trava vira `ErroConflitoTrilha` 409 | dados reais | `app/repository.py` `encadear` | bifurcação silenciosa da cadeia |
| ~~`tramitacoes.hash_cadeia` obsoleto~~ **resolvido 05/11:** `encadear` agora atualiza `tramitacoes.hash_cadeia` em todo caminho — worker/relay fora do `_commit` não deixam o topo denormalizado para trás | dados reais | `app/repository.py` `encadear` | verificação do topo do caso usa elo antigo |

## Anonimização (LGPD)

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| Rescan determinístico pós-NER (CPF/CNPJ/RG/e-mail/telefone residual na saída) | dados reais | `app/motor_langchain.py` `anonimizar` | `doc_anonimizado` gravado sobre saída defeituosa |
| Validação estrutural da saída LLM (diff/simetria — só a tag deve diferir) | dados reais | `app/motor_langchain.py` `_limpar` | modelo induzido devolve texto arbitrário |
| ~~Gate de residual~~ **resolvido (estava implementado):** `app/pii_residual.py` faz o re-scan da saída e o worker bloqueia a gravação com `falha_anonimizacao:{id}:residual_pii` — `metricas.medir` continua só observando (nunca levanta, por desenho). Limite declarado: cobre só os formatos/contextos codificados, não é prova de ausência de PII | dados reais | `app/pii_residual.py`; `app/worker.py` `processar_evento` | formatos não cobertos ainda podem passar |
| Rescan parcial: saída **ilegível** já vira `falha_anonimizacao` sem gravação — implementado | dados reais | `app/worker.py` | — |
| Persistência das métricas de anonimização — hoje ficam só em log + `_registro` em memória do worker; para avaliar o MVP é preciso gravá-las em arquivo/coletor consultável | demo (avaliação do MVP) | `app/metricas.py` `_registro` | sem histórico, não há como comparar execuções |
| `substituidas` por tipo é proxy (delta detectadas−residuais): a tag `[ANONIMIZADO_LGPD]` não carrega o tipo substituído, então um tipo pode "pagar" a conta de outro — atribuição real exige saída estruturada do NER | dados reais | `app/metricas.py` `medir` | métrica por tipo pode mascarar recall ruim de um tipo específico |
| Métricas de recall por tipo de entidade (N2) | dados reais | — | sem evidência quantitativa de qualidade |
| ~~Magic bytes / validação de formato real do upload~~ **resolvido 05/11 (B):** `_formato_documento_ok` confere o cabeçalho (512B) — PDF/office(zip)/PNG/JPEG/texto UTF-8 entram; MZ/ELF/shebang e binários não-decodificáveis não | dados reais | `app/service.py` `upload_documento` | executável nomeado `.pdf` entra na esteira |
| Sandbox do parser PDF + antivírus (ClamAV) | produção | `app/worker.py` | PDF hostil explora pypdf |
| Metadados de DOCX/imagem (hoje só PDF; reconstrução fpdf2 já descarta metadados por acidente) | dados reais | `app/motor_langchain.py` | autoria/data vazam no anonimizado |
| LLM local (vLLM/Ollama na rede interna) como default soberano — `openai`/`google` mandam o documento para egress externo | dados reais | `app/motor_de_env` `IA_LLM` | documento sai do perímetro soberano |
| Destruição cerimonial da chave no modo `anonimizacao` irreversível | dados reais | enum `ModoAnon` | pseudônimo permanece reversível indevidamente |
| Divergência spec × API (§5.2): a especificação descreve `/v1/anonymize\|pseudonymize\|reversal`, cofre, `risk_score` e guardrails — nada disso existe; o implementado é a API de tramitação com esteira de IA. Hoje não há produto de anonimização como especificado, só a infraestrutura que o hospedará | dados reais | `app/main.py` rotas; especificação técnica | promessa de produto sem implementação |
| Núcleo criptográfico ausente (§5.3): não há cofre de mapeamentos (ADR-0004), nem Vault/KEK/DEK (ADR-0005), nem distinção operacional entre `anonimizacao` e `pseudonimizacao` — `modo` é metadado inerte; a reversibilidade prometida não tem implementação que a sustente ou a impeça | dados reais | `app/schemas/`; `docs/adr/0004`, `0005` | pseudonimização declarada sem sustentação |

## Confiabilidade e operação

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| ~~Dedup do evento `doc_anonimizado:{id}` em redelivery~~ **resolvido 05/11 (B):** `Tx.encadear_uma_vez` deduplica dentro da tx (mesma trava consultiva) — worker (anonimizado + falhas + DLQ) e `outbox_falhar` gravam efeito uma única vez sob at-least-once | dados reais | `app/repository.py` `encadear_uma_vez`; `app/worker.py` | trilha com evento duplicado |
| Versionamento no bucket anonimizado + evento `doc_reprocessado:vN` | produção | `app/storage.py` `garantir` | reprocessamento destrói anonimizado anterior |
| Worker/RabbitMQ/MinIO ausentes do `deploy/compose.yaml` soberano | demo | `deploy/compose.yaml` | topologia de produção não reflete o desenho |
| DLQ: dono, runbook de triagem, retenção e alerta de profundidade | produção | `app/worker.py` drain DLQ | falha fica invisível por tempo indeterminado |
| Criptografia em repouso (volume Postgres/MinIO, DEK por caso, serviço `cofre` declarado não implementado) | dados reais | `deploy/compose.yaml` | disco roubado expõe documentos |
| ~~TLS/mTLS serviço-a-serviço na rede interna~~ **resolvido 05/11 (malha):** TLS real em todos os links da `interna` provado em `deploy/malha/` com pcap — rabbitmq 5671 amqps, postgres ssl=on, minio https, vault https, CA privada (`TLS_CA_BUNDLE`) | produção | `deploy/malha/`; `app/tls_interno.py` | lateral movement dentro da `interna` |
| ~~Rate limiting (nginx/API)~~ **resolvido 05/11 (B):** `limit_req_zone` por IP a 50 r/s com `burst=100 nodelay` no `deploy/nginx.conf` — varredura/reenvio em massa enfileirado na borda | produção | `deploy/nginx.conf` | abuso da API pública |
| Backup Postgres/MinIO + RPO/RTO documentado | produção | — | perda de caso sem recuperação |
| Retenção/eliminação: TTL do bruto pós-anonimização, purge de outbox, fluxo de exclusão LGPD (direito do titular) — **decisão do encarregado/DPO** | dados reais | — | retenção além do necessário viola LGPD |
| `caso_cnj` em claro em eventos/outbox/consulta — número de processo é metadado sob sigilo; pseudonimizar ou não é **pendência do encarregado/DPO**, não decisão de engenharia (a métrica deliberadamente não conta CNJ como PII, sem afirmar que é inofensivo) | dados reais | `app/schemas/tramitacao.py` | metadado sensível vaza entre nós |
| Ack B→A perdido: B confirmou mas `POST /v1/tramitacoes/{id}/acks` nunca chega a A — a projeção em A fica EM_TRANSITO sem fechamento local. Mitigação parcial: o eco idempotente de `receber` informa `status` atual de B **ao cliente que chamou**. **Desbloqueado 05/11 (B):** o ack já sai assinado Ed25519 pelo destino (`ConfirmacaoOut.assinatura`) — a prova de autoria para re-entrega existe; falta o mecanismo de re-entrega em si (retry/pull do ack pendente) | dados reais | `app/service.py` `aplicar_confirmacao`; `tests/smoke/test_reconciliacao.py` | origem nunca encerra o caso |
| `RecebimentoOut` tem dois formatos: primeiro ingresso traz `hash_cadeia` preenchido e `status="recebida"`; o eco de duplicata traz `status` atual e `hash_cadeia` **ausente** (prova interna da trilha, omitida por decisão). O cliente distingue eco por `hash_cadeia is None` | produção | `app/schemas/tramitacao.py` `RecebimentoOut`; `app/service.py` `_eco_recebimento` | cliente que não distingue eco trata reentrega como ingresso novo |
| ~~`enviar` transita antes de conferir o storage~~ **resolvido 05/11:** reordenado — `storage.existe` valida antes de `_transitar`; mutação sempre por último | produção | `app/service.py` `enviar` | — |
| ~~`upload_documento` não consulta status (§4.4)~~ **resolvido 05/11 (B):** gate explícito — bytes só sobem em `CRIADA` (origem) e `RECEBIDA` (destino arquivando); EM_TRANSITO (já tem objeto como pré-condição) e terminais recusam | dados reais | `app/service.py` `upload_documento`; `tests/smoke/test_seguranca_b.py` | documento trocado após decisão do destino |
| ~~`confirmar` com dupla guarda~~ **resolvido 05/11:** fonte única `TRANSICOES` via `_transitar` (a checagem explícita de RECEBIDA saiu; `motivo` na recusa já é do schema) | produção | `app/service.py` `confirmar` | — |
| ~~Nomes de bucket como literais~~ **resolvido 05/11:** `app/constantes.py` — `BUCKET_BRUTOS`/`BUCKET_ANONIMIZADOS` únicos para `_storage_de_env` e worker | produção | `app/constantes.py` | — |
| ~~Chave de objeto sem constante~~ **resolvido 05/11:** `chave_objeto(tid)` em `app/constantes.py` — serviço e worker compartilham o formato | produção | `app/constantes.py` | — |
| ~~Flags da esteira por prefixo lexical~~ **resolvido 05/11:** prefixos e geradores `ev_*` centralizados em `app/constantes.py` — quem grava e quem lê (`startswith` em `consultar`) usam a mesma fonte | produção | `app/constantes.py` | — |
| Residual do relay (§4.14): publish pode duplicar se o relay cair entre o ACK do broker e `outbox_marcar` — tolerado (at-least-once, consumidor idempotente) | produção | `app/relay.py` `relay_pass` | evento entregue duas vezes ao consumidor |
| Migração `0005_outbox_retry` **não verificada em Postgres real** (`TEST_DB_URL` ausente na sessão): coluna + índice revisados por leitura e DDL compilada; executar `alembic upgrade head` num Postgres de verdade antes de dados reais | dados reais | `alembic/versions/0005_outbox_retry.py` | migração pode falhar no deploy soberano |
| ~~Bifurcação da hash-chain por concorrência~~ **resolvido 05/11:** `pg_advisory_xact_lock` serializa a leitura-do-topo+insert na mesma tx (Postgres) + `UNIQUE(hash_anterior)` migração 0006 como backstop — a tx perdedora vira `ErroConflitoTrilha` (409), nunca bifurca em silêncio. sqlite segue protegida por serialização de arquivo | dados reais | `app/repository.py` `encadear`; `app/models.py` `Trilha` | — |
| Eventos `ESGOTADO` na outbox: terminais e registrados na hash-chain (`falha_outbox:{tid}`, visível via `consultar`), mas sem alerta ativo, sem endpoint de re-drain e **sem runbook de triagem** — a operação depende de alguém consultar o caso. Implementar alarme quando houver observabilidade consolidada | dados reais | `app/relay.py`; `app/repository.py` `outbox_falhar` | despacho morto só é notado por consulta individual |
| ESGOTADO sem trilha (falha do `encadear` isolada pelo savepoint): o estado terminal comita, mas sem o evento `falha_outbox:{tid}` — `consultar` não reflete o esgotamento e o caso aparece como em processamento. Mitigação atual: warning no log (`outbox_falhar`). Ação necessária: estado de inconsistência consultável ou reprocessamento da trilha | dados reais | `app/repository.py` `outbox_falhar`; `app/service.py` `consultar` | caso esgotado parece vivo na consulta |

## Resolvido — rodada B/C (05/11): endurecimento de segurança

Camada de custódia criptográfica + gates físicos + fail-closed de
operação. Cada item provado em `tests/smoke/test_seguranca_b.py` no
ponto onde a brecha morria.

- **Assinatura Ed25519 de envelope e ack** (`app/assinatura.py`):
  JSON canônico sobre todos os campos exceto `assinatura`.
  `receber` verifica contra a pública de `env.origem`;
  `aplicar_confirmacao` contra a do destino do caso. Fail-closed
  onde `ORG_SIGN_SEED_B64`+`ORGAO_PUBKEYS_JSON` existem; sem par
  configurado = dev sem verificação (mesma política do cofre E2E).
  Novas envs: `ORG_SIGN_SEED_B64`, `ORG_SIGN_SEED_FILE`,
  `ORGAO_PUBKEYS_JSON`, `ORGAO_PUBKEYS_FILE`.
- **Envelope endereçado**: `destino` obrigatório;
  `env.destino != self.orgao` → 409 antes de gravar.
- **Confirmação verificável**: B só confirma após storage +
  releitura + recomputação de SHA-256 — "dizer que recebeu" não
  prova; os bytes provam.
- **Upload com gate**: somente `CRIADA`/`RECEBIDA`; magic bytes
  (PDF/office/PNG/JPEG/texto) — executável/script não entra.
- **Replay compartilhado multi-réplica**: `ReplayCache` em
  processo substituído por `replay_nonces` no Postgres
  (claim atômico por PK + varredura oportunista de expirados —
  sem sweeper). O bug de claim por tentativa-de-chave no
  `abrir_todas` corrigido de brinde.
- **Ingresso E2E streaming**: `abrir_stream_todas` — corpo
  decifrado quadro a quadro, rejeição precoce no frame 0,
  requests não-E2E passam direto; `x-e2e-ct` em allowlist
  (json + multipart) → 415 para o resto. Corpos grandes não
  materializam mais o ciphertext inteiro.
- **Resposta 100% selada**: cobertura E2E no egresso já provada
  por `test_e2e_cobertura.py` (todas as rotas `/v1/`).
- **Verificação autônoma da trilha**: `repo.verificar` rejoga
  elo a elo; `GET /v1/tramitacoes/{id}/verificar` expõe
  (participante-only, mesma autorização da consulta). Trigger
  append-only no Postgres (migração 0007) barra UPDATE/DELETE
  na trilha por mecanismo, não convenção.
- **Dedup de efeito**: `Tx.encadear_uma_vez` — worker,
  `outbox_falhar` e DLQ gravam `doc_anonimizado:`/`falha_*:`
  uma única vez sob at-least-once.
- **Borda**: `BORDA_SEGREDO` (opcional) — quando definido exige
  `X-Borda-Segredo` conferido em `hmac.compare_digest`;
  `X-Cliente-Orgao` validado no formato `OrgaoID` (401 opaco
  para malformado). nginx: `limit_req` 50 r/s + HSTS.
- **Fail-closed de operação**: worker exige `DATABASE_URL` +
  `IA_ENGINE` válidos (SystemExit — sem stub silencioso);
  `E2E_FONTE=vault` sem credencial utilizável = boot falha.
  AppRole preferido (`VAULT_ROLE_ID[_FILE]`/`VAULT_SECRET_ID[_FILE]`)
  com token curto (TTL 60s) para a leitura do KV; `VAULT_TOKEN[_FILE]`
  segue como fallback dev. Malha provisiona policy `e2e-leitura` +
  role `no-a` e monta os segredos em `/segredos` ro.

### Pendente da rodada B/C

- Assinatura Ed25519 **por linha** da trilha (prova a terceiros
  fora do nó) — a verificação elo a elo existe; a assinatura
  persistida por evento não.
- CRL/OCSP no nginx (cert comprometido aceito até expirar).
- Mecanismo de re-entrega do ack pendente (a prova de autoria
  já existe; falta o retry/pull).
- Decisões jurídicas (DPO): pseudonimização/reidentificação,
  `caso_cnj` em claro, retenção. Não implementadas — aguardam
  decisão fora do código.
