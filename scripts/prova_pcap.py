"""Assert sobre os pcaps das redes `interna` — prova de NIC.

Capturado pelo sniffer (tcpdump -i eth0 -s0) durante o round-trip
real. Veredito:

  PASS: handshake TLS presente nos links internos E nenhum
        byte legível do payload (sentinela, caso_cnj, JSON,
        envelopes amqp/JSON) aparece no fio.
  FAIL: qualquer sentinela/JSON de domínio legível, ou zero
        handshakes TLS (link interno em claro).

Detalhe de modelo: o hop nginx->api é HTTP em claro na `interna`
(o TLS termina na borda — o envelope E2E segue cifrado dentro
dele). Headers HTTP aparecem legíveis; o que NÃO pode aparecer
é payload de negócio — é isso que este script prova.
"""
import sys

TLS_RECORD = b"\x16\x03"

# bytes que, se aparecerem, provam claro na rede interna
PROIBIDOS = [
    b"SENTINELA-PII-malha-0001",   # PII do payload
    b"0000001-01.2026.8.00.0001",  # caso_cnj
    b'"caso_cnj"',                 # JSON de domínio
    b'"idempotency_key"',
    b'"hash_documento_sha256"',
    b"amqps",                      # credenciais/urls legíveis
    b"edvar_dev",
]


def analisar(pcap: str) -> int:
    dados = open(pcap, "rb").read()
    tls = dados.count(TLS_RECORD)
    vistos = [p.decode() for p in PROIBIDOS if p in dados]
    # quadros E2E só são visíveis no hop nginx->api (HTTP claro
    # dentro da interna): magia 0xE2 0x02 como evidência extra
    e2e = dados.count(b"\xe2\x02")
    print(f"{pcap}: {len(dados)} bytes, "
          f"{tls} registros TLS, {e2e} magias E2E")
    if tls == 0:
        print("  FAIL: nenhum handshake/registro TLS — link "
              "interno possivelmente em claro")
        return 1
    if vistos:
        print("  FAIL: bytes legíveis no fio:", vistos)
        return 1
    print("  PASS: TLS nos links internos; zero payload legível")
    return 0


if __name__ == "__main__":
    rc = 0
    for p in sys.argv[1:]:
        rc |= analisar(p)
    sys.exit(rc)
