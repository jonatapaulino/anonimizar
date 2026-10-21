#!/bin/sh
# P2 - probe de egress para smoke test de isolamento (ADR-0007).
# rede interna (internal:true) -> tudo BLOQUEADO
# rede externa (controle)      -> tudo EGRESS-ABERTO
NET="${1:-desconhecida}"
VIZINHO="${2:-}"

echo "=== probe rede: $NET ==="

check() {
  if sh -c "$2" >/dev/null 2>&1; then
    echo "EGRESS-ABERTO  $1"
  else
    echo "BLOQUEADO      $1"
  fi
}

check "http-ipv4  1.1.1.1:80"  "wget -T 5 -q -O /dev/null http://1.1.1.1/"
check "dns        example.com" "nslookup example.com"
check "icmp       8.8.8.8"     "ping -c1 -W3 8.8.8.8"
check "http-ipv6  [2606::1111]" "wget -T 5 -q -O /dev/null 'http://[2606:4700:4700::1111]/'"

if [ -n "$VIZINHO" ]; then
  echo "--- comunicacao intra-rede ---"
  check "intra      ping $VIZINHO" "ping -c1 -W3 $VIZINHO"
  check "intra-dns  nslookup $VIZINHO" "nslookup $VIZINHO"
fi

echo "=== fim $NET ==="
