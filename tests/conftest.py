"""Conftest raiz — ambiente da suíte.

A autenticação de borda é mTLS + header X-Cliente-Orgao (ver
app/deps.py e deploy/nginx.conf): os testes injetam o header via
tests.identidade.hdr — nenhuma fixture de ambiente é necessária.
JWT não existe mais na suíte (mecanismo reprovado — XSS).
"""
