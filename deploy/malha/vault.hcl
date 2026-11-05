# Vault do nó — modo produto com TLS (HTTP vazaria a E2E_CHAVE
# na rede interna; dev-mode não aceita TLS). Storage em arquivo
# local — a persistência do nó soberano fica no volume da
# implantação.
listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/vault/certs/server.crt"
  tls_key_file  = "/vault/certs/server.key"
}
storage "file" {
  path = "/vault/file"       # dir padrão da imagem — já é de uid 100
}
ui            = false
disable_mlock = true
