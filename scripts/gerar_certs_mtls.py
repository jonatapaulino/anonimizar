"""Gera CA de desenvolvimento + certificados mTLS para o nó.

DEV ONLY — em produção cada órgão emite pela sua própria PKI e
troca as chaves públicas da CA dos pares (o nginx só confia na
ca.crt montada). Uso:

    python scripts/gerar_certs_mtls.py --out deploy/certs \
        --node tjpa --peers mpf.pa tre-pa

Gera:
    ca.crt / ca.key        — CA de dev (guarde a key fora do repo)
    node.crt / node.key    — certificado do servidor nginx
    <par>.crt / <par>.key  — certificado de cliente por órgão par
                             (CN = id do órgão = X-Cliente-Orgao)
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _chave():
    return rsa.generate_private_key(public_exponent=65537,
                                    key_size=2048)


def _pem_priv(k):
    return k.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())


def _pem_cert(c):
    return c.public_bytes(serialization.Encoding.PEM)


def _nome(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn),
                      x509.NameAttribute(
                          NameOID.ORGANIZATION_NAME, "iSACI-dev")])


def _assinar(subj, pub, issuer, issuer_key, dias, *,
             ca=False, client=False, server=False):
    agora = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(subj).issuer_name(issuer)
         .public_key(pub).serial_number(x509.random_serial_number())
         .not_valid_before(agora - dt.timedelta(minutes=5))
         .not_valid_after(agora + dt.timedelta(days=dias))
         .add_extension(x509.BasicConstraints(ca=ca, path_length=None),
                        critical=True))
    if not ca:
        uso = ([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH] if client
               else [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH])
        b = b.add_extension(x509.ExtendedKeyUsage(uso),
                            critical=True)
        if server:
            b = b.add_extension(x509.SubjectAlternativeName(
                [x509.DNSName("localhost"),
                 x509.DNSName("nginx"),
                 x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                critical=False)
    return b.sign(issuer_key, hashes.SHA256())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="deploy/certs")
    ap.add_argument("--node", default="node-local")
    ap.add_argument("--peers", nargs="*", default=[])
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    ca_key, ca_name = _chave(), _nome("iSACI-dev-CA")
    ca = _assinar(ca_name, ca_key.public_key(), ca_name, ca_key,
                  3650, ca=True)
    (out / "ca.key").write_bytes(_pem_priv(ca_key))
    (out / "ca.crt").write_bytes(_pem_cert(ca))

    node_key = _chave()
    node = _assinar(_nome(a.node), node_key.public_key(),
                    ca_name, ca_key, 825, server=True)
    (out / "node.key").write_bytes(_pem_priv(node_key))
    (out / "node.crt").write_bytes(_pem_cert(node))

    for par in a.peers:
        k = _chave()
        c = _assinar(_nome(par), k.public_key(), ca_name, ca_key,
                     825, client=True)
        (out / f"{par}.key").write_bytes(_pem_priv(k))
        (out / f"{par}.crt").write_bytes(_pem_cert(c))
        print(f"cert de cliente: {par}")

    print(f"CA + certs em {out}/ — DEV ONLY; producao usa PKI "
          f"de cada orgao e troca so as ca.crt publicas")


if __name__ == "__main__":
    main()
