# ADR-0007: Topologia de rede isolada, mTLS no ingress, túneis site-to-site

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

LGPD, Resolução CNJ 615/2025 e art. 189 do CPC implicam operação soberana:
documentos sob sigilo não podem transitar ou depender de serviços externos.
Sistemas consumidores podem estar no mesmo órgão (rede interna) ou em outro
órgão (ex.: iSACI ↔ TJPA) — o segundo caso exige canal entre redes.

Ponto conceitual fixado na análise: **túnel é fronteira de alcançabilidade,
não criptografia** — TLS 1.3 já confidencia; o valor do túnel é a API não
existir na rede para quem está fora dele.

## Decisão

```
[Consumidor mesmo órgão]            [Consumidor outro órgão]
        │                                     │
   rede interna                    WireGuard/IPsec site-to-site
        │                              (UDP — evita TCP meltdown)
        └──────────────┬──────────────────────┘
                       ▼
              Ingress: nginx (mTLS)
              · exige certificado cliente da CA do órgão
              · termina TLS 1.3; repassa fingerprint do cert à app
                (suporte a RFC 8705 — ver ADR-0006)
                       ▼
              FastAPI/uvicorn — VLAN isolada, SEM rota p/ internet
              · JWT OIDC offline · rate limit por client_id
                       ▼
              process pool NLP
              Postgres + Vault + Keycloak — mesma VLAN, egress deny-all

[Admin] → SSH bastion (jump host) → hosts internos
```

Componentes e régua:

| Componente | Escolha | Release | Régua |
|-----------|---------|---------|-------|
| Ingress | **nginx** (`ssl_verify_client` mTLS) | 2004 | ✅ |
| Túnel site-to-site | **WireGuard** preferido / **IPsec** fallback | 2020 / ~2000 | ✅ |
| Bastion admin | OpenSSH jump host | 1999 | ✅ |
| CA para certs mTLS | CA do órgão ou **step-ca** | 2018 | ✅ |
| Alternativa ingress | Traefik (se futuro k8s) | 2016 | ✅ |

Regras complementares:

1. **Egress deny-all** nos containers: sem rota de saída → nenhum download
   de modelo em runtime, nenhuma telemetria. Modelos embarcam na imagem
   (ADR-0008). É o que torna a soberania **verdadeira**, não declarativa.
   Implementação precisa: redes docker `internal: true` — sem default route
   e sem forward de DNS upstream — cobrindo IP, **DNS** (UDP/TCP 53 seria
   canal de exfiltração por túnel) e **IPv6** (regra só-IPv4 é bypass
   clássico). Nenhuma porta de serviço binda no host além do nginx; a API
   só existe na rede interna do compose. Smoke test de isolamento entra no
   pipeline de release.
2. **NTP interno obrigatório**: trilha de auditoria depende de timestamp
   confiável — rede isolada precisa de servidor NTP próprio.
3. TLS termina no ingress; hop ingress→API é HTTP dentro da VLAN
   (aceitável em segmento isolado; re-cifragem interna fica como opção do
   estudo de implantação).
4. SSH jamais exposto diretamente nos hosts da aplicação — só via bastion.
5. **Ciclo de vida de certificados mTLS**: rede isolada não tem OCSP —
   revogação via CRL publicada pela CA interna (step-ca) ou, preferido,
   certificados de vida curta (horas/dias) com renovação automática.
   Certificado roubado deve expirar antes de virar problema.

## Consequências

- **Positivas**: defesa em profundidade real — isolamento de rede + mTLS na
  borda + JWT na aplicação; cada camada cobre falha das outras; WireGuard é
  minimal e auditado; IPsec interoperável com infra existente de tribunais.
- **Custo**: operar CA interna (ou adotar a do órgão) é pré-requisito;
  firewalls restritivos podem impor IPsec no lugar de WireGuard — ambos
  documentados.
- Payload grande via UDP-tunnel evita o problema clássico de TCP-over-TCP
  (meltdown) — latência é métrica do projeto.

## Emenda 2026-10-16

- Egress deny-all especificado como redes docker `internal: true` (sem
  default route, sem DNS upstream), cobrindo explicitamente DNS e IPv6 —
  as duas rotas de fuga clássicas de regra só-IPv4.
- Bind de portas restrito à rede interna do compose: nginx é a única face
  exposta do sistema.
- Incluído ciclo de vida de certificados mTLS (CRL interna ou certs de
  vida curta) — revogação em rede isolada não existia no desenho.
