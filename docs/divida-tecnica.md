# Dívida técnica — esteira de tramitação

Itens identificados na revisão de arquitetura e **não** entregues no
MVP. Categorias:

- **demo** — necessário para demonstração convincente
- **dados reais** — necessário antes de qualquer documento real
- **produção** — necessário para operação contínua em produção

## Segurança de acesso

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| `receber` não autentica o `origem` declarado no envelope — confia no canal. Depende de mTLS no túnel entre nós (ADR-0007), ainda não implementado | dados reais | `app/service.py` `receber`; `docs/adr/0007-rede-isolada-e-tuneis.md` | órgão forja envelope em nome de terceiro |
| RBAC/ABAC — JWT carrega só `orgao_id`, sem roles/escopos | produção | `app/deps.py` | privilégio excessivo dentro do órgão |
| Credencial única MinIO acessa todos os buckets — sem policy por órgão | dados reais | `app/storage.py` | nó comprometido lê bruto de todos |
| Rotação de chave via JWKS e `kid` — hoje `JWT_PUBLIC_KEY` única, rotacionar = redeploy | produção | `app/deps.py` | chave vazada exige janela de indisponibilidade |
| Revogação de token — validação offline não consulta denylist; mitigar com TTL curto | produção | `app/deps.py` | token furtado vale até o `exp` |
| Ordem das checagens é propriedade de segurança não codificada (análise §4.1): participação (404) → papel (404) → estado (409) só vale por convenção de escrita — reordenar `enviar`/`confirmar`/`aplicar_confirmacao` vaza existência/status a terceiros | dados reais | `app/service.py` `enviar`, `confirmar`, `aplicar_confirmacao` | terceiro descobre que o caso existe |
| `org` é confiado dentro do serviço (§4.8): `NoTramitacao` não autentica — a identidade só é vinculada ao JWT em `deps.orgao_atual`; qualquer chamada interna futura com `org` forjado contorna toda a autorização | dados reais | `app/service.py` `NoTramitacao`; `app/deps.py` | endpoint interno futuro vira bypass de soberania |
| Envelope, ack e confirmação trafegam sem assinatura (§5.5): `origem`, `status` e `hash_documento_recebido` são declarados e confiados — a cadeia de custódia repousa na honestidade dos pares até existir assinatura + mTLS (ADR-0007) | dados reais | `app/service.py` `receber`, `aplicar_confirmacao`, `confirmar` | par forja decisão/hash sem prova |
| Hash da confirmação é auto-declarado por B (§4.7): `confirmar` compara `hash_documento_recebido` com o valor registrado — declaração contra declaração, não recomputação sobre bytes; o teste do caminho feliz usa o `hash_doc` do próprio envelope como valor (eco). Um destino que não recomputa bytes passa igual | dados reais | `app/service.py` `confirmar`; `tests/smoke/test_fluxo_e2e.py` | confirmação afirma integridade sem prová-la |

## Integridade da trilha

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| Cadeia refutável por quem escreve no Postgres — sem assinatura por entrada nem âncora externa | dados reais | `app/repository.py` `encadear` | DBA reescreve e re-encadeia a trilha |
| Assinatura Ed25519 por linha + endpoint `GET /trilha/{id}/verificar` | dados reais | idem | sem prova a terceiros |
| Fork por corrida: `encadear` lê topo e insere filho na mesma tx — falta `UNIQUE(hash_anterior)` + serialização | dados reais | `app/repository.py` `encadear` | bifurcação silenciosa da cadeia |
| `tramitacoes.hash_cadeia` fica obsoleto após eventos fora do `_commit` (§4.13): `encadear` via `tx` no worker (`processar_evento`/`registrar_falha`) e no relay (`outbox_falhar` → `falha_outbox:`) não atualiza o campo — `consultar` devolve um topo anterior ao real | dados reais | `app/repository.py` `encadear`; `app/worker.py`; `app/repository.py` `outbox_falhar` | verificação do topo do caso usa elo antigo |

## Anonimização (LGPD)

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| Rescan determinístico pós-NER (CPF/CNPJ/RG/e-mail/telefone residual na saída) | dados reais | `app/motor_langchain.py` `anonimizar` | `doc_anonimizado` gravado sobre saída defeituosa |
| Validação estrutural da saída LLM (diff/simetria — só a tag deve diferir) | dados reais | `app/motor_langchain.py` `_limpar` | modelo induzido devolve texto arbitrário |
| Gate de residual: `residuais > 0` em `app/metricas.py` deve bloquear a gravação no bucket anonimizado e registrar `falha_anonimizacao` — hoje a métrica só observa (item 3, sem gate por decisão de escopo) | dados reais | `app/metricas.py` `medir`; `app/worker.py` `processar_evento` | PII residual vaza para o bucket anonimizado sob `doc_anonimizado` na trilha |
| Rescan parcial: saída **ilegível** já vira `falha_anonimizacao` sem gravação — implementado | dados reais | `app/worker.py` | — |
| Persistência das métricas de anonimização — hoje ficam só em log + `_registro` em memória do worker; para avaliar o MVP é preciso gravá-las em arquivo/coletor consultável | demo (avaliação do MVP) | `app/metricas.py` `_registro` | sem histórico, não há como comparar execuções |
| `substituidas` por tipo é proxy (delta detectadas−residuais): a tag `[ANONIMIZADO_LGPD]` não carrega o tipo substituído, então um tipo pode "pagar" a conta de outro — atribuição real exige saída estruturada do NER | dados reais | `app/metricas.py` `medir` | métrica por tipo pode mascarar recall ruim de um tipo específico |
| Métricas de recall por tipo de entidade (N2) | dados reais | — | sem evidência quantitativa de qualidade |
| Magic bytes / validação de formato real do upload | dados reais | `app/service.py` `upload_documento` | executável nomeado `.pdf` entra na esteira |
| Sandbox do parser PDF + antivírus (ClamAV) | produção | `app/worker.py` | PDF hostil explora pypdf |
| Metadados de DOCX/imagem (hoje só PDF; reconstrução fpdf2 já descarta metadados por acidente) | dados reais | `app/motor_langchain.py` | autoria/data vazam no anonimizado |
| LLM local (vLLM/Ollama na rede interna) como default soberano — `openai`/`google` mandam o documento para egress externo | dados reais | `app/motor_de_env` `IA_LLM` | documento sai do perímetro soberano |
| Destruição cerimonial da chave no modo `anonimizacao` irreversível | dados reais | enum `ModoAnon` | pseudônimo permanece reversível indevidamente |
| Divergência spec × API (§5.2): a especificação descreve `/v1/anonymize\|pseudonymize\|reversal`, cofre, `risk_score` e guardrails — nada disso existe; o implementado é a API de tramitação com esteira de IA. Hoje não há produto de anonimização como especificado, só a infraestrutura que o hospedará | dados reais | `app/main.py` rotas; especificação técnica | promessa de produto sem implementação |
| Núcleo criptográfico ausente (§5.3): não há cofre de mapeamentos (ADR-0004), nem Vault/KEK/DEK (ADR-0005), nem distinção operacional entre `anonimizacao` e `pseudonimizacao` — `modo` é metadado inerte; a reversibilidade prometida não tem implementação que a sustente ou a impeça | dados reais | `app/schemas/`; `docs/adr/0004`, `0005` | pseudonimização declarada sem sustentação |

## Confiabilidade e operação

| Item | Categoria | Referência | Risco |
|---|---|---|---|
| Dedup do evento `doc_anonimizado:{id}` em redelivery (at-least-once grava duplicata na trilha) | dados reais | `app/worker.py` | trilha com evento duplicado |
| Versionamento no bucket anonimizado + evento `doc_reprocessado:vN` | produção | `app/storage.py` `garantir` | reprocessamento destrói anonimizado anterior |
| Worker/RabbitMQ/MinIO ausentes do `deploy/compose.yaml` soberano | demo | `deploy/compose.yaml` | topologia de produção não reflete o desenho |
| DLQ: dono, runbook de triagem, retenção e alerta de profundidade | produção | `app/worker.py` drain DLQ | falha fica invisível por tempo indeterminado |
| Criptografia em repouso (volume Postgres/MinIO, DEK por caso, serviço `cofre` declarado não implementado) | dados reais | `deploy/compose.yaml` | disco roubado expõe documentos |
| TLS/mTLS serviço-a-serviço na rede interna | produção | `deploy/compose.yaml` | lateral movement dentro da `interna` |
| Rate limiting (nginx/API) | produção | `deploy/compose.yaml` | abuso da API pública |
| Backup Postgres/MinIO + RPO/RTO documentado | produção | — | perda de caso sem recuperação |
| Retenção/eliminação: TTL do bruto pós-anonimização, purge de outbox, fluxo de exclusão LGPD (direito do titular) — **decisão do encarregado/DPO** | dados reais | — | retenção além do necessário viola LGPD |
| `caso_cnj` em claro em eventos/outbox/consulta — número de processo é metadado sob sigilo; pseudonimizar ou não é **pendência do encarregado/DPO**, não decisão de engenharia (a métrica deliberadamente não conta CNJ como PII, sem afirmar que é inofensivo) | dados reais | `app/schemas/tramitacao.py` | metadado sensível vaza entre nós |
| Ack B→A perdido: B confirmou mas `POST /v1/tramitacoes/{id}/acks` nunca chega a A — a projeção em A fica EM_TRANSITO sem fechamento local. Mitigação parcial: o eco idempotente de `receber` informa `status` atual de B **ao cliente que chamou** — não atualiza a tramitação de A (que só transita via `aplicar_confirmacao`, invocada por B). Re-entrega do ack exige prova de autoria — implementar quando houver assinatura sobre `ConfirmacaoOut` + mTLS entre nós (ADR-0007) | dados reais | `app/service.py` `aplicar_confirmacao`; `tests/smoke/test_reconciliacao.py` | origem nunca encerra o caso |
| `RecebimentoOut` tem dois formatos: primeiro ingresso traz `hash_cadeia` preenchido e `status="recebida"`; o eco de duplicata traz `status` atual e `hash_cadeia` **ausente** (prova interna da trilha, omitida por decisão). O cliente distingue eco por `hash_cadeia is None` | produção | `app/schemas/tramitacao.py` `RecebimentoOut`; `app/service.py` `_eco_recebimento` | cliente que não distingue eco trata reentrega como ingresso novo |
| `enviar` transita o registro antes de conferir o storage (§4.2): `_transitar(EM_TRANSITO)` precede `storage.existe` — hoje inofensivo (o dict mutado é descartado no erro), mas o padrão "muta depois valida" depende do descarte do `rec` não persistido | produção | `app/service.py` `enviar` | refactor futuro persiste estado mutado |
| `upload_documento` não consulta status (§4.4): bytes sobem com a tramitação em qualquer estado — inclusive após `CONFIRMADA`; a regra "upload só entre CRIADA e EM_TRANSITO" não existe | dados reais | `app/service.py` `upload_documento` | documento trocado após decisão do destino |
| `confirmar` tem dupla fonte da mesma regra (§4.6): checa `status is RECEBIDA` e depois `_transitar` repete via `TRANSICOES` — podem divergir se o mapa mudar | produção | `app/service.py` `confirmar` | guarda e mapa dizem coisas diferentes |
| Nomes de bucket duplicados como literais (§4.9): `"docs"`/`"docs-anonimizados"` inline em `_storage_de_env` vs. `NOME_BRUTOS`/`NOME_ANONIMIZADOS` no worker — divergência quebra a esteira silenciosamente | produção | `app/main.py` `_storage_de_env`; `app/worker.py` | esteira lê/grava no bucket errado sem erro |
| Chave de objeto = `str(tramitacao_id)` em serviço e worker (§4.10) — convenção partilhada sem constante única | produção | `app/service.py`; `app/worker.py` | divergência de formato perde objetos |
| Flags da esteira por prefixo lexical (§4.11): `doc_anonimizado:`/`falha_anonimizacao:`/`falha_outbox:` escritos por worker/relay e lidos por `consultar` via `startswith` — acoplamento por convenção de string, sem registro único dos prefixos | produção | `app/service.py` `consultar`; `app/worker.py`; `app/repository.py` `outbox_falhar` | prefixo divergente apaga falha da consulta |
| Residual do relay (§4.14): publish pode duplicar se o relay cair entre o ACK do broker e `outbox_marcar` — tolerado (at-least-once, consumidor idempotente) | produção | `app/relay.py` `relay_pass` | evento entregue duas vezes ao consumidor |
| Migração `0005_outbox_retry` **não verificada em Postgres real** (`TEST_DB_URL` ausente na sessão): coluna + índice revisados por leitura e DDL compilada; executar `alembic upgrade head` num Postgres de verdade antes de dados reais | dados reais | `alembic/versions/0005_outbox_retry.py` | migração pode falhar no deploy soberano |
| Bifurcação da hash-chain por concorrência (item 1B da revisão): `encadear` lê o topo e insere sem `UNIQUE(hash_anterior)` — duas tx paralelas derivam do mesmo elo e a cadeia bifurca sem alarme. Escritores hoje: serviço (`_commit`), worker (`processar_evento`/`registrar_falha`) **e relay** (`outbox_falhar` → `falha_outbox:`). Correção: `UNIQUE(hash_anterior)` em `trilha_auditoria` + retry da tx perdedora; eficaz só em Postgres (isolamento real — sqlite serializa writes por arquivo) | dados reais | `app/repository.py` `encadear`; `app/models.py` `Trilha` | duas linhas afirmam o mesmo elo — a cadeia deixa de ser linear sem ninguém notar |
| Eventos `ESGOTADO` na outbox: terminais e registrados na hash-chain (`falha_outbox:{tid}`, visível via `consultar`), mas sem alerta ativo, sem endpoint de re-drain e **sem runbook de triagem** — a operação depende de alguém consultar o caso. Implementar alarme quando houver observabilidade consolidada | dados reais | `app/relay.py`; `app/repository.py` `outbox_falhar` | despacho morto só é notado por consulta individual |
| ESGOTADO sem trilha (falha do `encadear` isolada pelo savepoint): o estado terminal comita, mas sem o evento `falha_outbox:{tid}` — `consultar` não reflete o esgotamento e o caso aparece como em processamento. Mitigação atual: warning no log (`outbox_falhar`). Ação necessária: estado de inconsistência consultável ou reprocessamento da trilha | dados reais | `app/repository.py` `outbox_falhar`; `app/service.py` `consultar` | caso esgotado parece vivo na consulta |
