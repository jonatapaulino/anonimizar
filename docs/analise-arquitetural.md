# Análise Arquitetural — projeto_edvar

> Análise estrutural do código e da documentação em 2026-10-20.
> Método: leitura estática — nenhum código executado, nenhum
> arquivo alterado. Foco: estrutura de módulos, regras de negócio,
> pontos de decisão e riscos estruturais.

---

## 1. Identidade do sistema: o que existe vs. o que está especificado

Há uma distinção fundamental que estrutura toda a análise:

- **A especificação** (`docs/especificacao-tecnica.md`) descreve um
  *módulo de anonimização jurídica* consumível via `/v1/anonymize`,
  `/v1/pseudonymize`, `/v1/reversal` — com NER legal-BERT,
  guardrails, cofre de mapeamentos HMAC/DEK e Linked Entities.
- **O código implementado** é outra coisa: uma **API de tramitação
  inter-órgãos** — o tecido de transporte e governança sobre o qual
  a anonimização vai operar. As rotas reais são `/v1/tramitacoes`,
  `/v1/recebimentos`, `/v1/tramitacoes/{id}/confirmacao`,
  `/v1/tramitacoes/{id}/acks`, `/v1/documentos/{id}/upload`,
  `/download`, `/download-anonimizado` (`app/main.py`).

O MVP construído é o **substrato soberano de trânsito documental**
(criar → enviar → receber → confirmar → ack) com uma esteira de
anonimização assíncrona acoplada. O núcleo científico da
especificação — NER, correferência simbólica, cofre criptográfico,
guardrails — **não existe em `app/`**; vive apenas como prova de
conceito em `spikes/` (P1–P8). O "motor de IA" atual é um stub
parametrizável. A separação é legítima de roadmap, mas deve ser
lida conscientemente: a arquitetura implementada é a *malha*, não
o *cérebro*.

## 2. Estrutura dos módulos

### 2.1 Mapa de responsabilidades e dependências

```
                        ┌─────────────┐
   HTTP cliente  ──────►│  main.py    │  FastAPI: rotas, handlers de erro,
                        │  (borda)    │  lifespan, fábrica create_app
                        └──────┬──────┘
              usa identidade   │        injeta NoTramitacao via app.state
              ┌──────────┐     │
              │ deps.py  │◄────┤  orgao_atual: JWT RS256 offline,
              │ (authN)  │     │  fail-closed, erro opaco
              └──────────┘     ▼
                        ┌─────────────┐
                        │ service.py  │  NÚCLEO: NoTramitacao — máquina de
                        │ NoTramitacao│  estados, autorização, upload/download
                        └──┬───┬───┬──┘
             Protocols     │   │   │      erros de domínio
        ┌──────────────────┘   │   └────────────► errors.py (base neutra)
        ▼                      ▼
 ┌──────────────┐      ┌──────────────┐      ┌────────────────┐
 │ repository.py│      │ storage.py   │      │ schemas/       │
 │ Repositorio  │      │ Armazenamen- │      │ comum.py +     │
 │ (Protocol) + │      │ toPort       │      │ tramitacao.py  │
 │ Repositorio- │      │ (Protocol) + │      │ contratos +    │
 │ SQL (UoW)    │      │ MinIO/Memória│      │ TRANSICOES     │
 └──────┬───────┘      └──────────────┘      └────────────────┘
        │ persiste             ┌──────────────────────────┐
        ▼                      │ events.py                │
 ┌──────────────┐              │ PublicadorEventos +      │
 │ models.py    │              │ PublicadorRabbitMQ +     │
 │ ORM (4       │              │ topologia quorum+DLX     │
 │ tabelas)     │              └───────────┬──────────────┘
 └──────────────┘                          │ publica
        ▲                                  ▼
        │ lê outbox          ┌──────────────────────────┐
        └────────────────────│ relay.py                 │ task in-process
        PENDENTE→PROCESSADO  │ (outbox→broker, só marca │ no lifespan da API
                             │  após ACK do broker)     │
                             └───────────┬──────────────┘
                                         │ AMQP
                             ┌───────────▼──────────────┐
                             │ worker.py                │ processo separado
                             │ consome ia.anonimizacao, │ (python -m app.worker)
                             │ download→motor→upload,   │
                             │ feedback na trilha, DLQ  │
                             └──┬──────────┬─────────┬──┘
              motor.anonimizar  │          │ repo     │ medir()
              (bytes→bytes)     ▼          ▼          ▼
                        ┌────────────┐ ┌─────────┐ ┌───────────┐
                        │motores:    │ │Reposito-│ │metricas.py│
                        │Stub/Demo/  │ │rioSQL   │ │observa,   │
                        │LangChain   │ │(opcional│ │nunca      │
                        │(IA_ENGINE) │ │ por env)│ │bloqueia   │
                        └────────────┘ └─────────┘ └───────────┘
```

### 2.2 Módulos, um a um

| Módulo | Papel | Natureza |
|---|---|---|
| `app/main.py` | Borda HTTP: rotas, handlers de erro sanitizados, lifespan, `create_app` com DI | Adaptador de entrada |
| `app/deps.py` | Autenticação: JWT RS256 validado **offline** via `JWT_PUBLIC_KEY`, fail-closed, resposta opaca | Adaptador de entrada |
| `app/schemas/comum.py` | Tipos canônicos (CasoCNJ, OrgaoID, HashSHA256), enums, máquina de estados `TRANSICOES`, detector de PII estruturada | Contrato de domínio |
| `app/schemas/tramitacao.py` | DTOs de entrada/saída com validadores (metadados ≤8KiB e sem PII, recusa exige motivo) | Contrato de domínio |
| `app/errors.py` | Hierarquia de erros de domínio → mapeados a 404/409/413 | Núcleo neutro |
| `app/service.py` | `NoTramitacao` — todo o domínio: criação, envio, recebimento, confirmação, consulta, upload/download | Núcleo (regras de negócio) |
| `app/repository.py` | `Repositorio`/`Tx` como Protocols + `RepositorioSQL`; UoW `transacao()`; hash-chain; outbox | Porta + adaptador de persistência |
| `app/models.py` | ORM: `tramitacoes`, `trilha_auditoria`, `idempotencia`, `outbox_eventos` | Esquema de persistência |
| `app/storage.py` | `ArmazenamentoPort` Protocol + MinIO (aioboto3, streaming) + memória; bucket por órgão | Porta + adaptadores |
| `app/events.py` | `PublicadorEventos` Protocol + RabbitMQ (aio-pika, confirms, topologia quorum+DLX) | Porta + adaptador |
| `app/relay.py` | Drenagem outbox→broker; marca `PROCESSADO` só após ACK do broker | Processo de infraestrutura |
| `app/worker.py` | Consumidor da fila `ia.anonimizacao`: download → motor → upload → feedback na trilha; drenador de DLQ | Processo independente |
| `app/motor_langchain.py` | Motor "real" via LangChain + LLM externo (ver §5 — contradição) | Adaptador de IA |
| `app/metricas.py` | Instrumentação: conta PII por tipo no bruto e na saída; só observa, nunca bloqueia | Observabilidade |

### 2.3 Fronteiras efetivas

| Fronteira | Onde está | Forma |
|---|---|---|
| HTTP → domínio | `main.py` rotas + `orgao_atual` (deps.py) | DTOs Pydantic entram, DTOs saem; identidade JWT vira string `org` |
| Domínio → persistência | `Repositorio`/`Tx` Protocols em `repository.py` | O serviço manipula **dicts** `rec`, nunca ORM — conversão em `_para_orm`/`_para_dict` |
| Domínio → storage | `ArmazenamentoPort` em `storage.py` | `guardar(fileobj)`, `abrir()→AsyncIterator`, `existe`, `garantir`, `fechar` |
| Domínio → barramento | `PublicadorEventos` em `events.py` + tabela `outbox_eventos` | Publicação indireta: serviço só escreve linha na outbox dentro da tx |
| Worker → IA | `motor.anonimizar(bytes) -> bytes` em `worker.py` | A porta mais estreita do sistema — motor permutável sem tocar o worker (`motor_de_env`) |
| Worker → trilha | `Repositorio.transacao()` reutilizado | O worker escreve na mesma hash-chain do nó |

### 2.4 Convenções estruturais notáveis

- **Domínio como dado, não como classe**: o "agregado" tramitação é
  um `dict` de chaves fixas (`id`, `caso_cnj`, `origem`, `destino`,
  `modo`, `status`, `hash_doc`, `hash_cadeia`, `metadados`,
  `requer_anonimizacao_lgpd`, `criado_em`, `atualizado_em`). Não
  existe classe de entidade de domínio — as invariantes vivem nos
  métodos de `NoTramitacao`.
- **Imports preguiçosos deliberados**: `aio_pika`, `aioboto3`,
  `pypdf`, `fpdf`, `langchain`, `app.repository` (no worker),
  `app.metricas` são importados *dentro* das funções — mantém o
  grafo de import do núcleo enxuto.
- **Injeção por fábrica**: `create_app(orgao, repo|repo_factory,
  publicador, storage, storage_anon)` — `repo_factory` existe
  porque o engine asyncpg precisa nascer no event loop que o usa
  (lifespan), não no loop do chamador.
- **Configuração por env vars**: `JWT_PUBLIC_KEY`, `DATABASE_URL`,
  `MINIO_URL/USER/PASS`, `RABBITMQ_URL`, `IA_ENGINE`, `IA_LLM`,
  `IA_MODEL`.

## 3. Regras de negócio

### 3.1 Máquina de estados

Declarada como mapa em `TRANSICOES` (`app/schemas/comum.py`) e
executada por `NoTramitacao._transitar` (`app/service.py`), que
rejeita qualquer aresta fora do mapa com `ErroFluxo`→409.

| Estado | Significado | Pode ir para |
|---|---|---|
| `CRIADA` | aceita pelo nó de origem | `EM_TRANSITO`, `CANCELADA` |
| `EM_TRANSITO` | envelope emitido | `RECEBIDA`, `CRIADA` ("reenvio"), `CONFIRMADA`, `RECUSADA` |
| `RECEBIDA` | destino ingressou o envelope | `CONFIRMADA`, `RECUSADA` |
| `CONFIRMADA` / `RECUSADA` / `CANCELADA` | terminais | — |

**Observação estrutural importante**: cada tramitação tem **duas
projeções locais** — uma no banco do nó A (origem), outra no do nó
B (destino) — ambas sob o mesmo `tid` (UUID criado por A). As
projeções não são iguais: A percorre
`CRIADA→EM_TRANSITO→CONFIRMADA/RECUSADA` (nunca passa por
`RECEBIDA`); B nasce direto em `RECEBIDA` via `receber` e vai a
`CONFIRMADA/RECUSADA`. É uma máquina de estados **distribuída e
reconciliada por handshake** (envelope + ack), não uma entidade
única replicada.

**Transições declaradas sem caminho de código**: `EM_TRANSITO→CRIADA`
("reenvio") e `→CANCELADA` existem no mapa, mas **nenhum método as
executa** — não há endpoint de cancelamento nem de reenvio. Não está
claro se é lacuna do MVP ou transição planejada; o código não
documenta.

### 3.2 Quem pode fazer o quê

A autorização é **por participação + papel**, aplicada em camadas
dentro de cada método de `NoTramitacao`:

| Ação | Regra | Implementação |
|---|---|---|
| `criar` | identidade autenticada = este nó | `criar`: `origem != self.orgao` → 409 |
| `enviar` | participante + papel `origem` + é este nó + estado `CRIADA` + arquivo presente | `_checar_participacao`→404, `_checar_papel`→404, `org!=self.orgao`→409, `_transitar`→409, `storage.existe`→409 |
| `receber` | qualquer autenticado; envelope `frozen` com metadados | **sem checagem de origem declarada** (confia no canal — dívida registrada) |
| `confirmar` | participante + papel `destino` + estado `RECEBIDA` + hash recomputado confere + recusa exige `motivo` | checagens + `model_validator` no DTO |
| `aplicar_confirmacao` (acks) | participante + papel `destino` (o destino entrega o ack ao nó da origem) + `conf.tramitacao_id==tid` | `_checar_papel(rec, org, "destino")` |
| `consultar` | participante (origem **ou** destino); aceita UUID ou CNJ | `por_caso` filtra órgão no WHERE + re-verificação em memória |
| `upload`/`download`/`download-anonimizado` | participante | `_checar_participacao` antes de qualquer I/O |

A propriedade central: **papel não vira oráculo** — terceiro e
participante-no-papel-errado recebem o *mesmo* 404
(`ErroNaoEncontrado`). Confirmado em `tests/smoke/test_autorizacao.py`.

### 3.3 Fluxo do documento, ponta a ponta

Caminho feliz (verificado em `tests/smoke/test_fluxo_e2e.py` e
`scripts/demo_e2e.py`):

1. **A: `POST /v1/tramitacoes`** — metadados +
   `hash_documento_sha256` *declarado* + `idempotency_key`. Tx
   única: `salvar` + `encadear("criada:{tid}")` + `idem`.
   Status `CRIADA`.
2. **A: `POST /v1/documentos/{tid}/upload`** — stream de 64KiB →
   hasher + spool de disco (rollover em 8MiB); corte de stream em
   20MiB→413; digest medido deve igualar o declarado→409 se
   divergir; dedup por `existe(tid)`; então tx:
   `encadear("doc_arquivado:{tid}")` + **outbox se
   `requer_anonimizacao_lgpd`**.
3. **A: `POST /v1/tramitacoes/{tid}/envio`** — gate físico:
   `storage.existe(tid)` obrigatório; transita `EM_TRANSITO`;
   **retorna o `EnvelopeRecebimento` (só metadados) como
   resposta** — *o transporte A→B é responsabilidade do cliente do
   órgão A*, não da plataforma. Não há dispatcher interno.
4. **B: `POST /v1/recebimentos`** — cria a projeção local em
   `RECEBIDA` com trilha própria (`recebida:{tid}`).
5. **B obtém os bytes** — *não implementado no código*: o caminho
   plausível é `GET /v1/documentos/{tid}/download` no nó A
   autenticado como B (a checagem de participação permite), mas o
   repo não contém cliente/orquestração que faça isso. B sobe o
   arquivo no seu próprio storage via upload (mesma chave `tid` no
   bucket `b-docs`), cujo hash é conferido contra o envelope.
6. **B: `POST /v1/tramitacoes/{tid}/confirmacao`** — exige
   `RECEBIDA`; `hash_documento_recebido` declarado deve igualar o
   gravado → `CONFIRMADA`/`RECUSADA` + trilha.
7. **B→A: `POST /v1/tramitacoes/{tid}/acks`** — B entrega o
   `ConfirmacaoOut` ao nó A; A aplica
   `EM_TRANSITO→CONFIRMADA/RECUSADA` + trilha. O conteúdo do ack é
   **confiado** (não assinado — cobre-se pelo canal mTLS planejado).

### 3.4 Ramo de anonimização (assíncrono)

`upload` com flag LGPD → linha `DocumentoProntoParaAnonimizacao`
(só IDs) na `outbox_eventos` **na mesma tx** → `relay_loop` (task
do lifespan, poll 1s) lê `PENDENTE`, publica com publisher-confirm,
marca `PROCESSADO` só após ACK → worker consome `ia.anonimizacao`
(quorum, `delivery-limit:3`, DLX) → download de `<org>-docs` →
`motor.anonimizar` → `metricas.medir` → **gate de legibilidade**
(saída ilegível = falha determinística:
`falha_anonimizacao:{id}:saida_ilegivel` na trilha, sem retry) →
upload em `<org>-docs-anonimizados` → `doc_anonimizado:{id}` na
trilha → ACK. Falhas transitórias → NACK+requeue → após 3 entregas
→ DLQ → `falha_anonimizacao:{id}` na trilha.

`consultar` deriva `anonimizacao_concluida`/`anonimizacao_falhou`
varrendo os prefixos de evento na trilha — o progresso da esteira
é lido *da própria hash-chain*, sem tabela de estado paralela.

### 3.5 Trilha (hash-chain)

`encadear` (`app/repository.py`): `topo_n = sha256(topo_{n-1} ∥
evento)`, `topo_0 = GENESIS`. O encadeamento é **global ao nó**
(último `seq` da tabela inteira, não por tramitação) — adulterar a
trilha de um caso exige reescrever a cadeia de todos os casos
posteriores. `tramitacoes.hash_cadeia` guarda o topo no momento do
último `_commit` do registro.

### 3.6 Integridade e higiene de PII como invariantes

- Payload nunca entra em resposta, log, trilha ou banco — só
  metadados + hashes.
- `contem_pii_estruturada` (`schemas/comum.py`) recusa metadados
  com CPF/RG (422) — PII só pode viver *dentro* do documento.
- Handler de `RequestValidationError` extrai só `loc+msg` — o
  handler padrão do FastAPI ecoaria `ctx.input` (o documento
  inteiro).
- `ErroAuth` carrega `motivo` interno (log) mas responde mensagem
  opaca fixa; fail-closed sem `JWT_PUBLIC_KEY`.
- Eventos no barramento carregam **só IDs** — a esteira busca o
  documento no nó soberano.
- Idempotência em três camadas: `Idempotencia(orgao, chave)` na
  criação (PK composta + `ErroConflitoIdempotencia` em corrida);
  dedup por `existe` no upload; chave = `id_documento` no worker.

## 4. Pontos de decisão: regra em código vs. convenção/ordem

**Garantidos por construção (a estrutura força a regra):**

- Transições só via `TRANSICOES` + `_transitar` — não há escrita de
  status fora dela.
- status+trilha+outbox atômicos: a interface `Tx` só existe dentro
  de `transacao()` — commit único, rollback total.
- Erro de validação sanitizado: o handler customizado de
  `RequestValidationError` é o único caminho — Pydantic nunca
  serializa `ctx.input`.
- Limite de documento corta o stream em `upload_documento` — o
  excesso nunca chega ao spool.
- `delivery-limit` + DLQ são argumentos de declaração de fila —
  impostos pelo broker, não pelo código.
- Autorização por participação acontece **antes** de qualquer I/O
  de storage (`_checar_participacao` antes de `existe`/`abrir`/
  `guardar`).

**Dependem de convenção ou ordem de chamada (nada estrutural
impede a violação):**

1. **Ordem das checagens é propriedade de segurança.** Em
   `enviar`/`confirmar`/`aplicar_confirmacao`, participação (404)
   precede papel (404) precede regras de estado (409). Se alguém
   reordenar — ex.: checar `_transitar` antes de `_checar_papel` —
   um terceiro passaria a receber 409 em vez de 404, vazando a
   existência da tramitação. A ordem correta é só convenção de
   escrita.
2. **`enviar` transita antes de verificar o storage.**
   `_transitar(rec, EM_TRANSITO)` precede `storage.existe` — hoje
   inofensivo (o dict mutado é descartado no erro), mas o padrão
   "muta depois valida" depende do descarte do `rec` não
   persistido.
3. **`receber` não verifica estado existente.** `merge`
   sobrescreve: um envelope re-enviado reverte
   `CONFIRMADA→RECEBIDA` no nó destino e duplica a linha
   `recebida:` na trilha. Não há checagem de "já recebido" nem de
   frescor (`enviado_em` é ignorado).
4. **`upload_documento` não consulta status.** Bytes podem subir
   com a tramitação em qualquer estado — inclusive após
   `CONFIRMADA`. A regra "upload só faz sentido entre CRIADA e
   EM_TRANSITO" não existe no código.
5. ~~**Dedup de upload confunde "arquivo existe" com "evento
   commitado".**~~ **RESOLVIDO 2026-10-20** (item 2): duplicata
   exige arquivo + `doc_arquivado:{tid}` commitado; órfão é
   reparado pelo re-upload (trilha + outbox, sem regravar bytes)
   após re-hash do objeto em storage — divergência → 409.
   Residual: sob corrida dois uploads podem ver `arquivado=False`
   e gravar dois eventos (at-least-once aceito pela esteira).
6. **`confirmar` tem dupla fonte da mesma regra.** Checa
   explicitamente `status is RECEBIDA` *e* depois `_transitar`
   repete a validação via `TRANSICOES`. Duas implementações
   independentes de "só se confirma o recebido" — podem divergir
   se o mapa mudar.
7. **O hash da confirmação é auto-declarado.** B afirma
   `hash_documento_recebido`; o teste de caminho feliz usa
   `obter(tid).hash_documento_sha256` como valor — ou seja, eco.
   Um destino que não recomputa bytes passa igual. A verificação
   de integridade é um compromisso declarado, não provado pelo
   protocolo.
8. **`org` no serviço é confiado.** `NoTramitacao` não autentica —
   quem chama `upload_documento(tid, arq, "qualquer-orgao")` no
   nível serviço contorna tudo. A identidade só é vinculada ao JWT
   em `deps.orgao_atual`. Válido como desenho (fronteira na
   borda), mas é convenção: nada impede um futuro endpoint interno
   de chamar o serviço com `org` forjado.
9. **Nomes de bucket duplicados como literais.** `_storage_de_env`
   usa `"docs"`/`"docs-anonimizados"` inline; `worker.py` usa
   `NOME_BRUTOS`/`NOME_ANONIMIZADOS`. Duas fontes para a mesma
   convenção — divergência quebra a esteira silenciosamente.
10. **Chave de objeto = `str(tramitacao_id)`** em serviço e worker
    — convenção partilhada sem constante única.
11. **Flags da esteira = prefixo de string de evento.**
    `doc_anonimizado:`/`falha_anonimizacao:` são escritos pelo
    worker e lidos por `consultar` via `startswith` — acoplamento
    por convenção lexical.
12. ~~**Eventos em `ERRO` na outbox não têm retry automático.**~~
    **RESOLVIDO 2026-10-20** (item 3): `outbox_elegiveis` torna
    ERRO elegível após `proximo_retry_em` (backoff exponencial
    com teto); esgotadas `OUTBOX_MAX_TENTATIVAS` tentativas, o
    relay grava `ESGOTADO` + `falha_outbox:{tid}` na hash-chain na
    mesma tx — `consultar` reporta `anonimizacao_falhou`. Claim
    por UPDATE condicional + lease `PUBLICANDO` cobre N réplicas:
    relay caído não trava a linha (lease expira → re-claim).
13. **`tramitacoes.hash_cadeia` fica obsoleto após eventos do
    worker.** `encadear` chamado via `tx` em `processar_evento`/
    `registrar_falha` não atualiza o campo no registro — a
    consulta devolve um topo anterior ao real (a trilha completa,
    essa sim correta, vem junto).
14. **Relay in-process por réplica.** `relay_loop` é task do
    lifespan — N réplicas da API = N relays concorrentes. Após o
    item 3 (2026-10-20), o claim `outbox_reservar` é UPDATE
    condicional por linha: duas réplicas não publicam a mesma
    linha ao mesmo tempo; crash ⇒ lease vence ⇒ re-claim.
    Residual: publish pode duplicar se o relay cair entre ACK e
    `outbox_marcar` — tolerado (at-least-once, consumidor
    idempotente).

## 5. Riscos estruturais (por leitura, não bugs pontuais)

1. **Contradição fundacional no motor de IA.** `LangChainMotorIA`
   envia o documento integral a OpenAI/Google — viola ADR-0011
   (zero generativo), ADR-0007 (egress deny-all) e ADR-0000
   (régua) simultaneamente. O projeto permite por
   `IA_ENGINE=langchain` o que a arquitetura declara proibido; a
   dívida técnica registra "LLM local como default soberano", mas
   o código presente oferece o caminho vedado, não o permitido.
2. **Divergência de superfície: spec ≠ API implementada.** A
   especificação descreve `/v1/anonymize|pseudonymize|reversal`,
   cofre, `risk_score`, guardrails. O implementado é uma API de
   tramitação com esteira de IA. Não é defeito — é estágio — mas
   significa que hoje **não existe o produto especificado**;
   existe a infraestrutura de transporte que o hospedará.
3. **Ausência do núcleo criptográfico.** Não há cofre de
   mapeamentos (ADR-0004), nem Vault/KEK/DEK (0005), nem distinção
   operacional entre `anonimizacao` e `pseudonimizacao` — `modo` é
   transportado como metadado inerte. A reversibilidade prometida
   pelo enum não tem implementação que a sustente ou a impeça.
4. **Handshake distribuído — reconciliação parcial (emenda
   2026-10-20).** O transporte A↔B é externo à plataforma. Perda
   do envelope passou a ter saída: `NoTramitacao.reenviar` (gate
   passivo por `ttl_reenvio_s`, rota `POST
   /v1/tramitacoes/{id}/reenvio`) reemite o envelope, e `receber`
   idempotente devolve eco com `status` de B. Atenção ao limite:
   o eco **informa o cliente chamador — não altera o registro de
   A**, que só transita via `aplicar_confirmacao` invocada por B.
   Seguem abertos (registrados em `divida-tecnica.md`): perda do
   ack B→A, reconciliação ativa (sem sweeper nem consulta
   cross-node) e cancelamento (aresta `CANCELADA` inalcançável).
5. **Confiança no canal como premissa carregadora.** Envelope
   declara `origem`; ack declara `status`; confirmação declara
   `hash recomputado`. Tudo sem assinatura — a segurança real
   depende do mTLS entre nós que ainda não existe no código
   (nginx.conf não está no repo). A dívida técnica documenta;
   estruturalmente, a cadeia de custódia atual repousa em
   honestidade dos pares.
6. **Hash-chain verificável só contra adulteração parcial.** Sem
   `UNIQUE(hash_anterior)`, corridas bifurcam; sem âncora externa
   nem assinatura por linha, quem escreve no banco recomputa tudo
   (ADR-0004 exige a âncora — não implementada). Adicionalmente, a
   cadeia global do nó acopla todos os casos: ótimo para
   tamper-evidence, mas o topo de um caso depende do histórico de
   casos alheios — implicação de design para verificação seletiva.
7. **PII residual pode sair marcada como anonimizada.**
   `metricas.medir` só observa; `residuais>0` não bloqueia o
   upload nem muda o evento da trilha (dívida documentada). O gate
   existente cobre só *ilegibilidade*. Estruturalmente, o sistema
   hoje *afirma* `doc_anonimizado` sobre saída que pode conter CPF
   intacto.
8. **Identidade autorizadora fraca para o domínio.** JWT carrega
   só `orgao_id` — sem escopos/roles; qualquer credencial válida
   de um órgão exerce todos os papéis daquele órgão. RBAC é dívida
   assumida, mas é propriedade estrutural: o modelo de autorização
   é binário por órgão.
9. **Persistência da métrica é volátil** — `_registro` em memória
   + log. Nada consultável sobrevive ao processo (dívida
   documentada, mas é propriedade da arquitetura de
   observabilidade atual).

## 6. Persistência e evolução de schema

Quatro migrações contam a história: `0001` (núcleo +
`documentos_transito` com binário no banco) → `0002` (flag LGPD) →
`0003` (outbox) → `0004` (**drop `documentos_transito`** — o pivô
T9: binário sai do banco de vez e vive só no object storage).
`env.py` exige driver async declarado na URL. Em testes, sqlite
in-memory com `StaticPool` + `PRAGMA foreign_keys=ON` aproxima o
Postgres; com `TEST_DB_URL` a suíte roda contra o schema realmente
migrado — mitigação elegante de drift entre `models.py` e alembic.

Nota de modelagem: não existe tabela de **cofre de mapeamentos**
(entidade→pseudônimo por caso, ADR-0004/0005) — o `modo`
(anonimização/pseudonimização) é transportado como metadado sem
backing criptográfico.

## 7. Topologia de implantação

`deploy/compose.yaml` é tratado como **contrato verificável de
isolamento**, não mero YAML: `interna` é `internal: true` (egress
deny-all por ausência de rota — provado no spike P2), só `nginx`
toca a rede `borda` e só ele publica 443 (mTLS/TLS1.3); api/db/
vault não publicam portas; hardening baseline (`read_only`,
`cap_drop ALL`, `no-new-privileges`, uid não-root, tmpfs em `/tmp`
— não-persistência até no scratch).
`tests/smoke/test_isolamento.py` valida esse arquivo estaticamente.
`docker-compose.yml` na raiz é só infra de dev (Postgres/RabbitMQ/
MinIO).

## 8. Validação como disciplina arquitetural

- **Spikes P1–P8**: provas N1 de cada mecanismo (latência BERT em
  CPU/GPU, isolamento medido, correferência artesanal 40/40,
  hash-chain + âncora, HMAC por caso, normalização Unicode, JWT
  offline com Keycloak real, harness de métricas).
- **`docs/metricas.md`**: gates **pré-registrados** (F1 NER ≥0,85
  exact; correferência pairwise ≥0,90 com anti-merge ≤5%;
  reidentificação ≤5%; utility TAB ≥0,85) — "o que conta como
  acerto" fixado antes da medição.
- **`docs/divida-tecnica.md`**: dívida catalogada por categoria
  (demo / dados reais / produção) com referência a arquivo e risco.

## 9. Pontos fortes

1. **Anti-oráculo sistemático**: 404 para terceiro e para papel
   errado; 401 opaco; erros de validação sanitizados. A
   consistência dessa disciplina em todos os handlers é rara.
2. **At-least-once fim a fim corretamente decomposta**: outbox
   garante produtor→broker, broker+fila durável garante
   broker→consumidor, idempotência no destino absorve duplicatas —
   cada camada assume só o que pode garantir.
3. **Streaming por construção** em todo o caminho de bytes (upload
   com spool, S3 multipart, download por iterador).
4. **DI consciente de event-loop**: `repo_factory` invocado no
   lifespan porque engine asyncpg precisa nascer no loop que o usa.
5. **Topologia de fila declarada uma única vez**
   (`declarar_topologia_ia`) compartilhada entre publisher e
   worker — evita redeclare divergente, um erro real de operação
   RabbitMQ.

## 10. O que não foi possível verificar apenas lendo o código

- **Comportamento real do broker**: se a topologia quorum +
  `x-delivery-limit` + DLX funciona como lido depende da versão do
  RabbitMQ e de semântica de publisher-confirm sob falha — só
  execução prova.
- **Paridade sqlite×Postgres**: `merge()`,
  `IntegrityError`→`constraint_name` (caminhos distintos para
  asyncpg/psycopg2/sqlite), FK enforcement,
  `JSON().with_variant(JSONB)` — a leitura mostra a intenção, não
  a equivalência.
- **Concorrência real da hash-chain**: se dois
  `enviar`/`confirmar` paralelos bifurcam a cadeia depende do
  nível de isolamento efetivo — provável, não demonstrado.
- **Ausência de artefatos de implantação**: não há `Dockerfile` (a
  imagem `tramitacao-api:dev` referenciada no compose soberano não
  tem build no repo), nem `nginx.conf` (o mTLS do ingress é
  declarado mas não configurado aqui), nem `requirements.txt`/
  `pyproject.toml` (dependências e pinagem não estão no
  repositório).
- **Formato de `JWT_PUBLIC_KEY`**: PEM multi-linha via variável de
  ambiente (escapes, encoding) — comportamento real não
  verificável por leitura.
- **Semântica do `duplicado`**: no ramo dedup de
  `upload_documento`, `tmp.seek(0)` precede o retorno — `tmp.tell()`
  reportaria posição 0, não o tamanho real — possível bug pontual
  que só execução confirma; registrado como observação, não
  certeza.
- **Qualidade real do pipeline LangChain**: se
  `pdf_de_texto`/`extrair_texto` preservam conteúdo em documentos
  reais, e se o prompt anti-injection funciona — inverificável
  estaticamente.
- **Se a suíte passa**: testes não foram executados; a análise
  assume o que eles declaram provar.
- **Destino do documento em B**: como o órgão destino obtém os
  bytes (download da API de A, canal externo, re-upload manual) —
  o protocolo permite, mas nenhum código executa essa etapa; é
  coreografia do cliente.

## 11. Síntese

O projeto é, arquiteturalmente, disciplinado: hexagonal com portas
reais, atomicidade garantida estruturalmente, segurança
anti-oráculo consistente, isolamento de rede como contrato
testável, métricas pré-registradas, ADRs com emendas datadas e
dívida técnica honesta. O que está implementado — a malha de
tramitação soberana com esteira de IA assíncrona — está bem
construído dentro do seu escopo.

As três questões estruturais: (1) o núcleo científico da
especificação ainda não existe em produção — existe como spike;
(2) o único motor "real" disponível contraria frontalmente a
restrição arquitetural central do projeto (zero IA generativa +
soberania); (3) a trilha hash-chain carece das proteções que o
próprio ADR-0004 tornou obrigatórias. Nenhuma é oculta — todas
estão parcial ou totalmente registradas na documentação do
projeto, que funciona como o principal mecanismo de governança da
arquitetura.
