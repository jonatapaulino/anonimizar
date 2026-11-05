#!/bin/sh
# One-shot: init + unseal + seed do KV E2E — prova o caminho
# E2E_FONTE=vault de ponta a ponta (FonteVaultKV le
# {atual, anterior_N} em secret/isaci/e2e). Escreve
# /segredos/vault_token para a api (VAULT_TOKEN_FILE).
set -e
export VAULT_ADDR="https://vault-a:8200"
export VAULT_CACERT="/vault/certs/ca.crt"

echo "vault-init: aguardando vault alcancavel..."
# rc do `vault status`: 0 = pronto, 2 = selado/nao-init (ambos
# ALCANCAVEIS), 1 = inacessivel -> continua tentando
while true; do
  vault status >/dev/null 2>&1 || rc=$?
  rc=${rc:-0}
  if [ "$rc" != "1" ]; then break; fi
  sleep 1
done

if [ ! -s /segredos/init.json ]; then
  vault operator init -key-shares=1 -key-threshold=1 \
    -format=json > /segredos/init.json
  chmod 600 /segredos/init.json
fi
# o JSON do init é pretty (key na linha seguinte ao campo)
KEY=$(grep -A1 unseal_keys_b64 /segredos/init.json \
      | grep -o '"[^"]*"' | tail -1 | tr -d '"')
TOK=$(sed -n 's/.*"root_token": *"\([^"]*\)".*/\1/p' \
      /segredos/init.json)

vault operator unseal "$KEY"
export VAULT_TOKEN="$TOK"
vault secrets enable -path=secret kv-v2 2>/dev/null || true
vault kv put secret/isaci/e2e atual="$E2E_SEED"
printf '%s' "$TOK" > /segredos/vault_token
chmod 600 /segredos/vault_token
echo "vault-init: secret/isaci/e2e semeado (atual rotacionavel)"
