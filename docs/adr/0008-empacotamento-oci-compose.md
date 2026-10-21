# ADR-0008: Imagem OCI com modelo embutido; deploy via docker compose

**Status**: Aceito · **Data**: 2026-10-07 · **Régua**: ADR-0000

## Contexto

Proposta obriga "empacotamento em container". Implantação alvo: on-premises
em órgão do sistema jurídico (TI de tribunal), em rede isolada sem saída
(ADR-0007) — logo, **nada pode ser baixado em runtime**. O projeto é
pesquisa (DSR): reprodutibilidade e versionamento de modelo são requisitos
de auditoria, não conveniência.

## Opções consideradas

| Opção | Régua | Avaliação |
|-------|-------|-----------|
| **Docker/OCI + docker compose** | ✅ 2013/2014 | Referência da proposta; suficiente p/ 4–5 serviços num host |
| Kubernetes | ✅ 2014 | Maduro mas **errado em tamanho**: orquestrar k8s em tribunal p/ um módulo é overengineering; fica como caminho futuro no white paper |
| Podman | ✅ 2018 | Alternativa válida (rootless); compose compatível |
| Modelo baixado em runtime (HF Hub) | — | Viola egress deny-all — descartado |
| Registry de modelos (MLflow) | ✅ 2018 | Serviço a mais; imagem pinada resolve |

## Decisão

1. **Imagem OCI única da aplicação** com pesos do modelo **embutidos no
   build**: modelo baixado do HF Hub **pinado por SHA de revisão** durante
   o build (único momento com internet). Tag da imagem codifica
   `versão-do-código + versão-do-modelo`.
2. **docker compose** como orquestrador de referência: api, nginx, postgres,
   vault, keycloak — um `compose.yml` reproduz o sistema inteiro isolado.
   Systemd units para auto-start no host.
3. **Versão do modelo na trilha**: cada request registra `model_version` no
   audit row — rastreabilidade "qual modelo anonimizou este documento".
4. **SBOM (syft, 2020 ✅) + assinatura de imagem (cosign, 2021 ✅)** gerados
   no CI — proveniência verificável do artefato, coerente com a "validação
   de proveniência" que a própria API oferece.
5. Variante `-gpu` opcional da imagem; referência é **CPU-first** (ADR-0001).
6. **Somente `safetensors`**: pesos embutidos na imagem devem estar em
   formato safetensors — checkpoints pickle executam código arbitrário no
   `load`; o formato seguro elimina a classe inteira de risco, e o pin por
   SHA já cobre a integridade do artefato.
7. **Hardening baseline no compose**: rootfs read-only, `cap_drop: ALL`,
   `no-new-privileges`, usuário não-root, seccomp — o default do docker é
   permissivo demais para um nó que guarda segredo de justiça.

## Consequências

- **Positivas**: deploy reproduzível bit-a-bit (imagem contém código +
  modelo); zero dependência de rede em runtime; auditoria consegue
  vincular saída a artefato exato; compose é operável por TI de tribunal.
- **Custo**: imagem pesada (~400MB–1,3GB de pesos) — aceitável;
  atualização de modelo = nova imagem = novo deploy (na verdade uma
  qualidade: muda-se modelo só por release auditada).
- Compose não escala horizontal — escala não é requisito do módulo;
  documentado como limitação aceita no estudo de implantação.

## Emenda 2026-10-16

- Adotada política safetensors-only para pesos embutidos (pickle em
  checkpoint é vetor de RCE no load).
- Definido baseline de hardening de container no compose de referência
  (rootfs read-only, cap_drop, no-new-privileges, não-root, seccomp) —
  ausente do desenho original.
