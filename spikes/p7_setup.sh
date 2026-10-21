set -e
BASE=http://localhost:8080
# token de admin
AT=$(curl -s $BASE/realms/master/protocol/openid-connect/token \
  -d grant_type=password -d client_id=admin-cli \
  -d username=admin -d password=admin | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
# realm juridico com TTL curto de access token (120s) — ADR-0006
curl -s -X POST $BASE/admin/realms -H "Authorization: Bearer $AT" \
  -H "Content-Type: application/json" \
  -d '{"realm":"juridico","enabled":true,"accessTokenLifespan":120}' -o /dev/null -w "realm: %{http_code}\n"
# client confidencial com service account
curl -s -X POST $BASE/admin/realms/juridico/clients -H "Authorization: Bearer $AT" \
  -H "Content-Type: application/json" \
  -d '{"clientId":"api-anon","enabled":true,"serviceAccountsEnabled":true,"publicClient":false,"directAccessGrantsEnabled":false,"standardFlowEnabled":false}' -o /dev/null -w "client: %{http_code}\n"
# id interno do client -> secret
CID=$(curl -s "$BASE/admin/realms/juridico/clients?clientId=api-anon" -H "Authorization: Bearer $AT" | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
SECRET=$(curl -s $BASE/admin/realms/juridico/clients/$CID/client-secret -H "Authorization: Bearer $AT" | python -c "import sys,json;print(json.load(sys.stdin)['value'])")
echo "$SECRET" > spikes/p7_secret.txt
echo "client_secret salvo"
