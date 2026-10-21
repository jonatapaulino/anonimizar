# ADR-0013: Estratégia de mensageria para o barramento de IA

**Status**: Aceito · **Data**: 2026-10-19 · **Régua**: ADR-0000
(emenda de registro sobre a proposta original: Outbox deixa de ser
opção e vira obrigação — ver §Decisão)

## Contexto

O handoff da API de tramitação para a esteira de IA (NER,
anonimização LGPD) não pode ocupar o ciclo HTTP — o P1 mediu
~181ms/janela de 512 tokens em CPU, e documentos reais têm
dezenas de janelas: NER síncrono = timeout garantido. A Tarefa 6
do MVP criou o contrato `PublicadorEventos` com dois adaptadores
(memória para testes, log para dev) e disparo pós-commit quando
`requer_anonimizacao_lgpd == True`.

O que falta é a malha de produção: perder um documento marcado
para anonimização é violação de LGPD silenciosa — o requisito de
entrega é **at-least-once fim a fim**, e é aí que mora o detalhe
técnico que a proposta original deixava ambíguo.

## Opções consideradas

| Opção | Avaliação |
|-------|-----------|
| **RabbitMQ (AMQP)** | Escolhido: self-hosted (soberania), filas/quorum duráveis, acks de consumidor, DLQ, publisher confirms, roteamento por exchange |
| Redis Streams | Já presente na topologia interna, mais leve; mas semântica de consumer groups/durabilidade mais fraca e sem roteamento rico — aceitável como fallback declarado |
| Kafka | Durabilidade excelente, mas operação (ZooKeeper/KRaft, partições, tuning) desproporcional ao volume de um nó edge — overkill descartado pela régua de complexidade |
| Post-commit hook direto no broker (sem outbox) | **At-most-once**: crash entre commit do Postgres e publish no broker perde o evento em silêncio — o broker nunca o vê. Inaceitável como garantia LGPD |

## Decisão

1. **RabbitMQ** como broker — exchange `tramitacao` (topic),
   filas duráveis/quorum por consumidor, `persistent` nas
   mensagens, ack manual, DLQ para poison messages, publisher
   confirms no produtor.
2. **Outbox transacional OBRIGATÓRIA** — o evento é gravado numa
   tabela `outbox` na MESMA transação da mudança de estado; um
   relay separado lê, publica e marca. A garantia at-least-once
   fim a fim vem do outbox + retry do relay, não do broker: o
   RabbitMQ garante broker→consumidor; só o outbox garante
   produtor→broker. *O post-commit hook atual (Tarefa 6) fica
   como modo de dev/teste, não como caminho de produção.*
3. **Consumidores idempotentes** — at-least-once implica
   duplicatas possíveis; a esteira dedup por `id_documento`.
4. **Eventos carregam só identificadores** — documento e PII
   nunca viajam no barramento; o consumidor busca pelo id no nó
   soberano (já implementado no MVP).

## Consequências

- (+) At-least-once fim a fim: evento sobrevive a crash da API
  (está commitado no Postgres) e a crash do broker (fila durável).
- (+) Roteamento condicional por exchange — hoje o serviço já só
  publica quando a flag pede; a topologia permite fan-out futuro
  (esteira, auditoria, notificações) sem mudar o produtor.
- (+) Soberania mantida: broker self-hosted na rede `interna`
  (ADR-0007), sem dependência de nuvem.
- (−) Mais um componente stateful no deploy soberano: cluster
  RabbitMQ com quorum queues exige cerimônia operacional
  (análoga ao Vault do ADR-0012).
- (−) Relay do outbox é um processo a mais para operar e
  monitorar (lag outbox→broker vira métrica de saúde).
- (−) Duplicatas chegam ao consumidor — dedup é obrigatório,
  não opcional.

## Interface com o MVP

`app/events.py` já é o ponto de injeção: produção troca
`PublicadorLog` pelo adaptador outbox (write na tx) + relay AMQP.
O teste de rollback da suíte (`test_rollback_zero_eventos`)
permanece a prova da invariante: estado não commitado nunca vira
evento.
