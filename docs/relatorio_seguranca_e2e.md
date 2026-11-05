# Relatório Técnico — Blindagem E2E e Substituição de JWT

> Data: 2026-11-04 · Commits: `6036402` (implementação),
> `7a7e074` (sniffer), `89ae7cb` (cobertura + mTLS real).
> Base: pedido do usuário — "hash ponta a ponta em cada
> contêiner, rede só vê tráfego protegido, JWT fora (risco XSS)".
> Convenção do projeto: **medido** × **contrato** × **não avaliado**.

## Veredicto

**O mecanismo está provado; a arquitetura como malha de produção
não está — e isso é o correto neste estágio.** A distinção:

- **Provado (medido, teste dinâmico real):** todo request `/v1/` é
  decifrado antes da regra de negócio; toda response sai cifrada —
  inclusive erros 4xx/5xx; o fio só carrega quadros `0xE2`;
  identidade vem de certificado de cliente em handshake TLS 1.3
  real; broker e storage só transportam/persistem ciphertext.
- **Contrato (configuração verificada estaticamente, não
  executada):** topologia do compose, `nginx.conf`, URLs TLS dos
  clientes internos, `E2E_OBRIGATORIO=1`.
- **Não avaliado:** prova de NIC na rede `interna` com contêineres
  reais, latência da cifragem, rotação de chaves, trânsito A↔B
  entre dois nós completos.

## Esclarecimento técnico aplicado

"Hash ponta a ponta" literal não existe: hash é irreversível e o
receptor não recupera o dado. A propriedade pedida (claro só em
memória, ciphertext na rede) exige **cifra autenticada (AEAD)**.
Implementado **ChaCha20-Poly1305** (RFC 8439): confidencialidade +
integridade + detecção de adulteração num selo. SHA-256 segue onde
sempre esteve: integridade de documento na trilha de auditoria.

## O que foi feito

### 1. Remoção completa do JWT

| Artefato | Ação |
|---|---|
| `app/deps.py` | reescrito — `jwt.decode`/PyJWT/`JWT_PUBLIC_KEY` fora; identidade = header `X-Cliente-Orgao` do terminador mTLS |
| `tests/jwthelper.py` | **deletado** — par RSA e emissor RS256 fora da suíte |
| `tests/smoke/test_auth_jwt.py` | substituído por `test_auth_borda.py` (mesma disciplina: 401 opaco, oráculo fechado, 401≠409) |
| 6 arquivos de teste | `tests.jwthelper.hdr` → `tests.identidade.hdr` (mesma assinatura, header em vez de token) |
| `WWW-Authenticate: Bearer` | removido do handler de 401 |

Motivo documentado no código: Bearer JWT vive no cliente e é
exfiltrável (XSS/`localStorage`); certificado de cliente fica no
SO/HSM do órgão — script não o copia para fora. A API confia no
header **porque** o compose garante que só o nginx alcança a rede
`interna` (API não publica porta).

### 2. Núcleo criptográfico — `app/crypto_e2e.py`

- Quadro v2: `0xE2 | ver 0x02 | nonce 12B | len 4B | ts_ms 8B |
  ciphertext+tag 16B`
- AAD = índice‖ts do quadro → reordenação/supressão quebram o
  selo e o carimbo não pode ser adulterado sem invalidá-lo
- Terminador `0xE2|0x02+24×0x00` → truncamento de stream detectável
- Anti-replay: frescura `E2E_JANELA_MS` (padrão 300 s) rejeita
  envelope velho/futuro; `ReplayCache` de nonces do quadro 0
  bloqueia reenvio do mesmo envelope no ingresso HTTP. AMQP usa
  só frescura (a redelivery legítima do broker repete o mesmo
  envelope); S3/DLQ abrem sem janela — dado em repouso e
  drenagem forense não expiram
- `FluxoSelador`/`_abrir_quadros`/`abrir_stream_async` — streaming
  real (bloco a bloco, sem materializar arquivo em RAM)
- Chave: `E2E_CHAVE` (hex 32B, via Vault em runtime); ausente →
  bypass de dev; malformada → `ErroCripto` (fail closed)

### 3. Os três interceptadores

| Fronteira | Código | Prova medida |
|---|---|---|
| HTTP | `app/middleware_e2e.py` (ASGI puro) | decifra body **antes** do roteador; cifra response quadro a quadro; `E2E_OBRIGATORIO=1` → plaintext em `/v1/` = **415 opaco**; selo inválido = **400 opaco** |
| Broker | `app/events.py` + `app/worker.py` | `PublicadorRabbitMQ` sela `Message.body` (`content-type: x-e2e`); `payload_de_mensagem` decifra — RabbitMQ só carrega ciphertext |
| Storage | `app/storage.py::ArmazenamentoCifrado` | wrapper sobre `ArmazenamentoPort`: MinIO/memória só persiste quadros; `abrir` decifra do stream — claro nunca toca disco S3 |

Bugs achados e corrigidos no caminho: flag `secure` do MinIO era
ignorado (`endpoint_url` idêntico nos dois ramos) → agora força
`https`; bloco vazio geraria quadro ambíguo com o terminador →
proibido na fonte; `shutdown(SHUT_WR)` precoce derruba a conexão
no h11 → sniffer usa `Connection: close`.

### 4. Configuração — `deploy/`

- **`nginx.conf`**: TLS 1.3 apenas, `ssl_verify_client on`,
  `ssl_client_certificate` = CA dos pares, `map` extrai CN do
  `ssl_client_s_dn` → `X-Cliente-Orgao`, `Authorization` zerado no
  proxy, headers reforçados, `proxy_request_buffering off`
  (streaming preservado ponta a ponta)
- **`compose.yaml`**: nginx monta conf+certs `:ro`; api com
  `E2E_OBRIGATORIO=1` + `E2E_CHAVE` passthrough do Vault;
  contrato de topologia intacto (só nginx na `borda`, só 443,
  `interna` internal:true)
- **`scripts/gerar_certs_mtls.py`**: CA dev + cert do nó + certs
  de cliente por órgão (CN = id do órgão) — dev only; produção
  usa a PKI de cada instituição e troca só `ca.crt`

## O que foi medido (provas executadas)

| # | Prova | Método | Resultado |
|---|---|---|---|
| 1 | Fio só carrega ciphertext | socket TCP real logando cada byte, request+response | sentinela PII e `caso_cnj` **ausentes** de 100% do fio; ambos os lados são quadros `0xE2` decifráveis |
| 2 | Sniffer não é vacuoso | mesma app sem `E2E_CHAVE` (controle negativo) | sentinela e JSON de domínio **legíveis** no fio |
| 3 | Cobertura de rotas | dispara TODA rota `/v1/` (todos os métodos) | toda resposta no fio = E2E, **inclusive 4xx** (a blindagem é do transporte) |
| 4 | Nenhuma rota escapa | inventário estático de `app.routes` | todo path é `/v1/` ou whitelist pública (`/healthz`, docs) |
| 5 | Adulteração | bit-flip no ciphertext | `ErroCripto` → 400 opaco |
| 6 | Chave errada | envelope selado com outra chave | 400 opaco |
| 7 | Reordenação/truncamento | quadros trocados / terminador removido | `ErroCripto` (AAD=índice + terminador) |
| 8 | Storage só persiste quadros | captura do que `guardar` entrega ao backend | sentinela ausente; adulteração detectada; multi-quadro >64KB íntegro; truncamento detectado |
| 9 | AMQP só carrega ciphertext | captura de `Message.body` | `content-type x-e2e`, magia `0xE2`, sentinela ausente, roundtrip ok |
| 10 | mTLS real | handshake TLS 1.3 com certs do `gerar_certs_mtls.py` | CN=tjpa extraído do cert (= `X-Cliente-Orgao`); sem cert rejeitado; cert de **CA forjada** rejeitado (nome certo, cadeia errada não passa) |
| 11 | Plaintext recusado | request legível com `E2E_OBRIGATORIO=1` | 415 opaco, antes da auth |
| 12 | Opaque 401 mantido | `test_auth_borda.py` | mesma mensagem para ausente/vazio; sem motivo fino |
| 13 | Contrato estático | `test_isolamento.py` | só nginx na `borda`/só 443, `interna` internal:true, `E2E_OBRIGATORIO=1`, mounts `:ro`, hardening baseline |

**Suite: 217 testes passando** (5 skipped — dependem de PG/
docker reais; 4 xfailed — pré-existentes).

## Limitações honestas (riscos de desenho, não bugs)

1. **Chave simétrica por par de nós.** `E2E_CHAVE` compartilhada
   = quem vaza a chave decifra **e forja** tráfego nos dois
   sentidos. Sem **forward secrecy**: ciphertext gravado hoje +
   chave vazada amanhã = legível. TLS de transporte mitiga o hop,
   a camada E2E não tem PFS.
2. ~~AEAD não impede replay~~ — **mitigado no quadro v2**
   (04/11/2026): `ts_ms` no AAD + janela de frescura
   (`E2E_JANELA_MS`, 300 s) + `ReplayCache` de nonces no ingresso
   HTTP. Limites que permanecem: o cache é **processo-local**
   (deployment multi-réplica exige store compartilhado) e a
   janela exige **NTP sincronizado** entre os pares.
3. **`X-Cliente-Orgao` é confiança de perímetro.** Quem já está
   dentro da `interna` pode forjar o header — ameaça interna está
   fora do modelo de borda. Mitigação futura: o próprio envelope
   E2E pode carregar a identidade (assinatura/chave por órgão) em
   vez de depender do header.
4. **XSS: mitigado, não eliminado.** Remover JWT tira o token de
   `localStorage`; mas se o cliente web rodar no navegador, o
   certificado de cliente exige instalação no SO — e um XSS ainda
   pode fazer o navegador *disparar* requests autenticados
   (o segredo não vaza, a sessão é usada). O ganho real: a
   credencial não é mais copiável.
5. **`abrir` materializa corpo do request.** Adequado para JSON
   de controle; upload multipart de documento passa inteiro por
   um quadro — para docs grandes o ideal é envelope por stream
   (formato já suporta; o middleware de ingresso não).

## Não avaliado

- **NIC/tcpdump na rede `interna`** com o compose de pé — bytes
  do socket provam o payload; a malha contêiner-a-contêiner não.
- **TLS dos clientes internos**: `amqps://`, `sslmode=require`,
  `https` S3 — contrato de URL, nenhum handshake medido.
- **`nginx.conf` executada** — a primitiva foi provada no
  handshake real; a config em si é assert estático.
- **Trânsito A↔B entre nós reais** — não existe cliente E2E
  no repo (quem chama a API par com envelope); falta o lado
  emissor.
- **Latência/overhead da cifragem** — não medida.
- **Rotação/revogação de `E2E_CHAVE`** — depende do Vault
  (próximo passo #3 da fila) + decisão jurídica de reidentificação.

## Resposta à pergunta "validamos a arquitetura?"

- **Camada de dados**: sim — invariantes antigas mantidas (binário
  nunca em envelope/broker/DB; agora também nunca legível em
  repouso nem no fio), provadas com medição.
- **Camada de transporte E2E**: mecanismo provado em toda a
  superfície da API; **falta a malha** (nó↔nó, serviços internos,
  NIC).
- **Identidade/autenticação**: mecanismo provado em handshake real;
  **falta executar o nginx** e os certs de produção.
- **Conclusão de engenharia**: a blindagem funciona e está onde o
  desenho mandou; chamar "arquitetura validada" só depois do
  tcpdump na `interna`, dos handshakes internos medidos e do
  round-trip A↔B entre nós de verdade.
