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

# AppRole do nó (caminho de produção): policy de leitura só no
# path do segredo E2E + role com token de vida curta. O root
# token é escopo do init/seed — a api/worker NÃO o recebe mais;
# levam só role_id/secret_id em arquivos montados ro.
vault policy write e2e-leitura - <<'EOF'
path "secret/data/isaci/e2e" {
  capabilities = ["read"]
}
EOF
vault auth enable approle 2>/dev/null || true
vault write auth/approle/role/no-a \
  token_policies="e2e-leitura" \
  token_ttl="60s" token_max_ttl="120s" \
  secret_id_ttl="0" secret_id_num_uses=0
vault read -field=role_id auth/approle/role/no-a/role-id \
  > /segredos/role_id
vault write -f -field=secret_id auth/approle/role/no-a/secret-id \
  > /segredos/secret_id
chmod 600 /segredos/role_id /segredos/secret_id
echo "vault-init: secret/isaci/e2e semeado + approle no-a criado"
