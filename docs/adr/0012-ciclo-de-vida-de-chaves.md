# ADR-0012: Ciclo de vida de chaves e cerimônias de segurança

**Status**: Aceito · **Data**: 2026-10-16 · **Régua**: ADR-0000

## Contexto

ADR-0004 define o cofre (HMAC por caso + AES-GCM com DEK/KEK) e a trilha
hash-chained; ADR-0005 define o Vault Transit. Ficaram de fora as decisões
operacionais que sustentam essas propriedades: quem destranca o Vault num
nó edge sem KMS externo, como a aplicação recebe seu primeiro segredo, e
quando/como a chave HMAC de um caso morre — evento que *é* a
irreversibilidade demonstrável do modo anonimização, não detalhe
administrativo.

Sem este ADR, três propriedades declaradas ficam suspensas em procedimento
indefinido: a separação dados↔chaves (depende de unseal distribuído e
bootstrap correto), a irreversibilidade (depende da cerimônia de
destruição) e a integridade da trilha (depende da âncora externa —
ADR-0004, emenda 2026-10-16).

## Opções consideradas — unseal e bootstrap

| Opção | Avaliação |
|-------|-----------|
| **Shamir manual distribuído** | Escolhido: único caminho compatível com isolamento total |
| Auto-unseal via KMS externo | Viola soberania — descartado (mesmo motivo de ADR-0005) |
| Unseal key em arquivo no host | Equivale a não ter Vault — só aceitável como fallback declarado |
| AppRole com secret_id em variável de ambiente | Secret-zero em texto claro — descartado |

## Decisão

1. **Destruição cerimonial da chave HMAC por caso** — o encerramento do
   caso (ou o TTL da política de retenção do órgão) dispara cerimônia
   documentada de destruição da chave derivada do caso, registrada como
   evento na própria trilha hash-chained. Enquanto a chave vive, o cofre
   permanece um oráculo de dicionário — o TTL é mecanismo de segurança,
   não conveniência.
2. **Unseal Shamir distribuído** — shares repartidos entre papéis
   institucionais distintos (ex.: TI do órgão + autoridade de segurança),
   com quórum k > 1; restart do Vault exige cerimônia de unseal. Custo
   aceito e declarado: restart não-autônomo do serviço de chaves.
3. **Bootstrap secret-zero** — a aplicação autentica no Vault via AppRole
   cujo `secret_id` chega como docker secret montado em arquivo, nunca
   variável de ambiente. Alternativa válida: auth JWT/OIDC com
   client_secret em arquivo montado. O compose de referência
   (ADR-0008) materializa uma das duas.
4. **Rotação** — KEK rotacionável sem recifrar o banco (rewrap do
   Transit); DEKs rotacionam por caso ou por política. Rotacionar a chave
   HMAC de um caso invalida a consistência futura daquele caso — logo a
   rotação de HMAC coincide naturalmente com a destruição no fim do caso.
5. **Fallback declara degradação** — o caminho mínimo (KEK em arquivo
   montado, ADR-0005) registra explicitamente que abre mão da separação
   dados↔chaves; a escolha do fallback é registrada como evento na trilha
   de auditoria do próprio nó.

## Consequências

- **Positivas**: as três propriedades de segurança mais citadas do projeto
  passam a ter mecanismo operacional definido e auditável; insiders com
  acesso legítimo deixam de concentrar poder (unseal exige quórum);
  destruição de chave vira evento auditável, não procedimento verbal.
- **Custos aceitos**: Vault exige cerimônia humana a cada restart —
  disponibilidade do serviço de chaves depende de procedimento do órgão;
  documentado como requisito operacional no estudo de implantação.
- **Relação com demais ADRs**: complementa ADR-0004 (âncora externa e
  HMAC por caso) e ADR-0005 (operação do Vault); não substitui nenhum.
