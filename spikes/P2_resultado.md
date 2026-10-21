# P2 — Resultado: smoke test de isolamento (internal: true)

> Spike do `docs/plano-de-validacao.md`. Executado em 2026-10-16.
> Hipótese sob teste (ADR-0007): `internal: true` no Compose ⇒ zero
> egress **por ausência de rota** — não por regra de firewall — e
> comunicação intra-rede preservada.

## Setup

- Docker Engine 29.8.0 · Docker Desktop (WSL2 backend) · Windows 11
- `docker-compose.yml`: rede `interna` (`internal: true`), rede
  `externa` (controle), `api-sim` na interna, dois probes Alpine
- `probe.sh`: testa egress HTTP/IPv4, DNS, ICMP, IPv6 + intra-rede

## Resultado bruto

| Teste | Rede interna | Rede externa (controle) |
|---|---|---|
| HTTP IPv4 → 1.1.1.1:80 | **BLOQUEADO** | EGRESS-ABERTO |
| DNS → example.com | **BLOQUEADO** | EGRESS-ABERTO |
| ICMP → 8.8.8.8 | **BLOQUEADO** | EGRESS-ABERTO |
| HTTP IPv6 → 2606::1111 | **BLOQUEADO** | BLOQUEADO* |
| ping → api-sim (intra) | **ABERTO** | — |
| nslookup → api-sim (intra) | **ABERTO** | — |

\* IPv6 falhou até na rede de controle — este host não tem IPv6
roteado. Neste ambiente IPv6 não é nem um canal possível; no
deployment alvo a verificação de IPv6 permanece obrigatória
(ADR-0007 já prevê).

## O que ficou provado

1. **`internal: true` cumpre a promessa do ADR-0007**: zero egress
   HTTP, DNS upstream e ICMP — por ausência de rota, não por ACL.
   Não há caminho a bloquear; não há bypass possível por dentro.
2. **DNS embutido do Docker se comporta exatamente como o desejado**:
   resolve nomes de containers *dentro* da rede (`api-sim` resolveu)
   e recusa upstream (`example.com` falhou) — descoberta de serviço
   intra-VLAN sem resolver externo = **sem túnel DNS de exfiltração**.
3. Intra-rede preservada: o padrão api↔pg↔vault do compose de
   referência funciona dentro do isolamento.

## Ressalvas

- Testado em Docker Desktop/WSL2. O alvo é Docker Engine em Linux
  bare-metal da VLAN — re-rodar lá (mesmo script, mesmo veredito
  esperado; mecanismo é netns sem default route, igual nos dois).
- Bind de portas do host não foi testado aqui — verificação fica a
  cargo do compose de referência (ADR-0007: nada de `0.0.0.0` no
  host; só o nginx expõe).
- IPv6: verificar no alvo.

**Status P2: ✅ provado — soberania é verificável, não declarativa.**
