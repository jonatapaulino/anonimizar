# ADR-0004: PostgreSQL para cofre de mapeamentos e trilha de auditoria

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

A Etapa 5 exige substituição consistente "ao longo do documento **e entre
documentos do mesmo caso**" → mapeamento persistente entidade→pseudônimo por
`case_id`. A Etapa 7 exige trilhas de auditoria com ID único de requisição e
política de retenção. LGPD exige distinguir anonimização irreversível de
pseudonimização reversível.

São três armazenamentos com requisitos distintos:

| Store | Conteúdo | Requisito crítico |
|-------|----------|-------------------|
| Cofre de mapeamentos | entidade real → pseudônimo, por caso | cifrado; reversível só se autorizado |
| Trilha de auditoria | quem, quando, hash do doc, contagens, versão do modelo | consultável, inviolável |
| Logs operacionais | eventos técnicos | estruturados OTLP/JSON (fora do escopo deste ADR) |

## Opções consideradas

| Opção | Régua | Avaliação |
|-------|-------|-----------|
| **PostgreSQL** | ✅ 30 anos | pgcrypto, pgaudit, JSONB; padrão on-prem; todos sabem operar |
| MongoDB | ✅ | Sem ganho real; JSONB cobre documentos |
| Elasticsearch/OpenSearch p/ auditoria | ✅ | Ops pesado demais para a escala |
| SQLite | ✅ | Dev ok; produção limita concorrência e multi-instância |
| Banco de nuvem gerenciado | — | Soberania — descartado |

## Decisão

**PostgreSQL único para cofre + auditoria**, com duas técnicas-chave:

1. **Uma tabela de mapeamentos, dois modos** — implementa a distinção LGPD:
   - `case_id | HMAC(entidade ∥ case_id) | pseudônimo | ciphertext_opcional`
   - **Modo anonimização (irreversível)**: persiste apenas o HMAC, com a
     entrada derivada por caso — suficiente para consistência
     inter-documento, impossível de reverter; destruir a chave do caso =
     irreversibilidade demonstrável (cerimônia em ADR-0012).
   - **Modo pseudonimização**: persiste ciphertext AES-GCM reversível via
     DEK por caso, embrulhada por KEK no Vault (ADR-0005).
   - O HMAC **incorpora `case_id` na entrada** (equivalente a subchave por
     caso): uma chave global produziria o mesmo HMAC para a mesma entidade
     em casos distintos — correlação transversal legível por qualquer
     leitor do cofre, contradizendo o isolamento por caso que o pseudônimo
     promete.
2. **Trilha hash-chained**: cada linha de auditoria inclui hash da linha
   anterior → adulteração retroativa detectável. Consultável por SQL
   (relatórios CNJ 615/2025). `pgaudit` registra acesso aos dados.
   **Ancoragem externa obrigatória**: o hash de topo é exportado e assinado
   periodicamente para fora do host. Sem âncora, um atacante com escrita
   total no banco reescreve e recomputa a cadeia inteira de forma
   indetectável — a âncora é o ponto fixo que torna o tamper-evidence
   verificável de fato.

Retenção: TTL por política em `case_id`/`request_id` + job de purge
documentado (princípio da necessidade, LGPD).

## Consequências

- **Positivas**: um SGBD só para operar; consultas SQL diretas para
  prestação de contas; hash-chain dá tamper-evidence sem blockchain nem
  infra extra.
- **Custo**: Postgres não tem TDE nativo → cifragem em nível de aplicação
  nas colunas sensíveis (que faríamos de qualquer forma) + volume cifrado.
- O mapeamento é **escopo por caso**: pseudônimo estável dentro do caso,
  diferente entre casos — regra da coerência processual.
- Payload do documento **não** é persistido — só metadados e hashes
  (minimização LGPD).

## Emenda 2026-10-16

- HMAC passa a incorporar `case_id` na entrada (derivação por caso): o
  esquema original com chave global permitia correlação transversal de
  entidades por leitura direta do cofre.
- Trilha hash-chained passa a exigir ancoragem externa periódica do hash
  de topo: cadeia sem ponto fixo externo é recomputável por quem detém
  escrita total no banco.
- Cerimônias de ciclo de vida de chaves (destruição do HMAC, unseal do
  Vault, rotação): consolidadas em ADR-0012.
