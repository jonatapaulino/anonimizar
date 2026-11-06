"""Demonstração narrada para apresentação — iSACI/Anonimizar.

Executa a jornada COMPLETA de um documento jurídico entre dois nós
soberanos reais (malha Docker: tjpa + mpfpa), imprimindo em cada
ato o que aconteceu e a EVIDÊNCIA que o prova — não é um vídeo nem
uma simulação: são chamadas reais à API, ao MinIO e ao Postgres.

Pré-requisito: malha de pé —
  docker compose -f deploy/malha/compose.malha.yaml up -d

Uso:
  python scripts/demo_coordenador.py            # roda tudo
  python scripts/demo_coordenador.py --pausar   # pausa entre atos
  python scripts/demo_coordenador.py --sem-preparo  # não mexe nos workers

Estrutura: os passos de protocolo rodam no contêiner `peer`
(scripts/demo_fluxo_peer.py); as evidências de infra (schema do
Postgres, objeto cru no MinIO) rodam aqui via docker exec.

Ressalva honesta impressa no fim: o motor em execução é o
DemoMotorIA (regex LGPD determinística) — escolhido para que a
remoção de PII seja VISÍVEL nesta demo. A qualidade medida do
modelo real (cascata v2, NER F1 0,953 no corpus sintético) está
em docs/metricas.md e ainda não está na porta MotorIA.
"""
import argparse
import json
import subprocess
import sys
import time

COMPOSE = "deploy/malha/compose.malha.yaml"
DEMO_OV = "deploy/malha/compose.demo.yaml"
PEER = "isaci-malha-peer-1"
LINHA = "=" * 72


def sh(cmd: list[str], mostra: bool = True) -> str:
    """Roda comando no host; devolve stdout. Falha aborta a demo.
    stdout do contêiner chega em UTF-8 — decodifica explicitamente
    (o locale do console Windows não é UTF-8 por padrão)."""
    r = subprocess.run(cmd, capture_output=True)
    out = r.stdout.decode("utf-8", errors="replace")
    err = r.stderr.decode("utf-8", errors="replace")
    if mostra and out.strip():
        for ln in out.rstrip().splitlines():
            print("  " + ln)
    if r.returncode != 0:
        print(err)
        sys.exit(f"\nFALHOU: {' '.join(cmd)}")
    return out


def peer(etapa: str) -> str:
    return sh(["docker", "exec", PEER,
               "python", "/run/demo_fluxo_peer.py", etapa])


def estado() -> dict:
    out = sh(["docker", "exec", PEER, "cat", "/run/demo_state.json"],
             mostra=False)
    return json.loads(out)


def ato(n: int, titulo: str, explicacao: list[str], pausar: bool):
    print(f"\n{LINHA}\nATO {n} — {titulo}\n{LINHA}")
    for ln in explicacao:
        print("  " + ln)
    if pausar:
        input("\n  [Enter para executar]")
    print()


def evidencia(titulo: str):
    print(f"  --- EVIDÊNCIA: {titulo}")


def minio_hex(container: str, bucket: str, tid: str, label: str):
    """Lê o objeto CRU do MinIO (sem decifrar): prova que o que
    está em repouso é ciphertext E2E, não o documento."""
    code = (
        "import asyncio,os,aioboto3\n"
        "async def go():\n"
        " s=aioboto3.Session();cm=s.client('s3',"
        "endpoint_url=os.environ['MINIO_URL'],"
        "aws_access_key_id=os.environ['MINIO_USER'],"
        "aws_secret_access_key=os.environ['MINIO_PASS'],"
        "verify=os.environ.get('TLS_CA_BUNDLE'))\n"
        " c=await cm.__aenter__()\n"
        f" r=await c.get_object(Bucket='{bucket}',Key='{tid}')\n"
        " b=await r['Body'].read()\n"
        " print('tamanho:',len(b),'bytes')\n"
        " print('primeiros 48 bytes:',b[:48].hex(' '))\n"
        " print('magia E2 (0xE2=quadro, 0x02=v2):',"
        " b[:2]==bytes([0xE2,0x02]))\n"
        " print('sentinela legivel no objeto:',"
        " b'DEMO-COORDENADOR' in b or b'MARIA' in b)\n"
        " await cm.__aexit__(None,None,None)\n"
        "asyncio.run(go())\n")
    evidencia(f"objeto cru no MinIO {label} (leitura S3 direta,"
              " sem decifrar)")
    sh(["docker", "exec", container, "python", "-c", code])


def psql_schema():
    evidencia("schema real do Postgres do nó A — "
              "não existe coluna para bytes de documento")
    sh(["docker", "exec", "isaci-malha-db-a-1",
        "psql", "-U", "edvar", "-d", "tramitacao",
        "-c", "\\d tramitacoes"])
    print("  -> note: NENHUMA coluna bytea/oid — o invariante é"
          " estrutural, não disciplinar.\n")


def psql_trilha_trigger():
    evidencia("trilha_auditoria — trigger append-only no banco")
    out = sh(["docker", "exec", "isaci-malha-db-a-1",
              "psql", "-U", "edvar", "-d", "tramitacao",
              "-t", "-c",
              "select tgname from pg_trigger where "
              "tgrelid='trilha_auditoria'::regclass "
              "and not tgisinternal;"])
    print(f"  -> trigger ativa: {out.strip() or 'NENHUMA'}"
          " — UPDATE/DELETE na trilha é barrado pelo próprio"
          " banco, não pela aplicação.\n")


def preparar():
    print(f"{LINHA}\nPREPARAÇÃO — malha real + motor de demonstração\n{LINHA}")
    st = sh(["docker", "ps", "--format", "{{.Names}}"], mostra=False)
    for svc in (PEER, "isaci-malha-api-a-1", "isaci-malha-api-b-1",
                "isaci-malha-worker-a-1", "isaci-malha-worker-b-1"):
        if svc not in st:
            sys.exit(f"container {svc} não está de pé — suba a malha:\n"
                     f"  docker compose -f {COMPOSE} up -d")
    print("  workers -> IA_ENGINE=demo (regex LGPD determinística —"
          "\n  anonimização VISÍVEL; NÃO é o motor medido nem o de"
          "\n  produção — ressalva explícita no encerramento)")
    sh(["docker", "compose",
        "-f", COMPOSE, "-f", DEMO_OV,
        "up", "-d", "worker-a", "worker-b"])
    print("  aguardando workers estabilizarem...")
    time.sleep(6)
    verificar_peer()
    print("  ok — demo pronta para iniciar\n")


def verificar_peer():
    """O compose monta o script + certs (ro) no peer — aqui só
    conferimos que estão presentes no contêiner em execução."""
    out = sh(["docker", "exec", PEER, "ls", "/run/certs",
              "/run/demo_fluxo_peer.py"], mostra=False)
    falta = [f for f in ("demo_fluxo_peer.py", "tjpa.crt",
                         "mpfpa.crt", "ca.crt") if f not in out]
    if falta:
        sys.exit(f"peer sem {falta} — recrie o contêiner com o "
                 f"compose atual:\n  docker compose -f {COMPOSE} "
                 f"up -d --force-recreate peer")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pausar", action="store_true",
                    help="pausa entre atos (apresentação guiada)")
    ap.add_argument("--sem-preparo", action="store_true",
                    help="pula a troca dos workers p/ IA_ENGINE=demo")
    a = ap.parse_args()
    p = a.pausar

    print(f"""
{LINHA}
  iSACI / ANONIMIZAR — demonstração executável da arquitetura
{LINHA}
  Cenário: uma petição com dados pessoais tramita do órgão A
  (tjpa) para o órgão B (mpfpa) e é anonimizada no destino.

  Dois nós REAIS em Docker, cada um com sua API, Postgres,
  RabbitMQ (TLS), MinIO (HTTPS) e borda nginx com mTLS.
  Todo payload atravessa envelopes AEAD ChaCha20-Poly1305 (E2E);
  envelopes de tramitação são assinados Ed25519; a auditoria é
  uma hash-chain append-only em cada nó.

  O que você vai ver NÃO é descrição: cada passo executa a
  chamada real e imprime a evidência que a prova.""")
    if not a.sem_preparo:
        preparar()
    else:
        verificar_peer()

    # ---------------- ATO 1 ----------------
    ato(1, "REGISTRO E ARQUIVO NO NÓ ORIGEM", [
        "A tramitação nasce com METADADOS + o SHA-256 declarado",
        "do documento — o binário nunca entra nesta chamada.",
        "Depois o upload: a API confere o hash byte a byte,",
        "valida o formato e grava cifrado no MinIO de A."], p)
    print("[passo 1] A registra o caso (metadados + hash):")
    peer("criar")
    print("\n[passo 2] A sobe o documento:")
    peer("upload")
    psql_schema()

    # ---------------- ATO 2 ----------------
    ato(2, "TRÂNSITO COM CUSTÓDIA — O QUE ATRAVESSA A FRONTEIRA", [
        "O 'envelope' A->B carrega apenas metadados + hash +",
        "assinatura Ed25519 de A — nunca bytes do documento.",
        "Primeiro a prova negativa: adulteramos o hash em",
        "trânsito e B deve recusar. Depois o envelope real."], p)
    print("[passo 3] A emite o envelope (só metadados):")
    peer("envio")
    print("\n[passo 4] ATAQUE: hash adulterado em trânsito -> B:")
    peer("adulterar")
    print("\n[passo 5] envelope legítimo -> B recebe:")
    peer("receber")

    # ---------------- ATO 3 ----------------
    ato(3, "ARQUIVO SOBERANO NO NÓ DESTINO", [
        "B baixa os bytes de A pelo canal E2E e arquiva a",
        "PRÓPRIA cópia no MinIO de B — cada instituição detém",
        "o seu storage: é a soberania do desenho."], p)
    print("[passo 6] B baixa o documento de A:")
    peer("download")
    tid = estado()["tid"]
    minio_hex("isaci-malha-api-a-1", "tjpa-docs", tid, "do nó A")
    print("  -> o objeto em repouso começa com a magia do quadro"
          "\n     E2E (0xE2 0x02): ciphertext AEAD — a sentinela do"
          "\n     documento NÃO aparece. O claro só existe dentro"
          "\n     do processo que decifra.\n")
    print("[passo 7] B arquiva a própria cópia:")
    peer("upload_b")
    minio_hex("isaci-malha-api-b-1", "mpfpa-docs", tid, "do nó B")

    # ---------------- ATO 4 ----------------
    ato(4, "FECHAMENTO DE CUSTÓDIA B -> A", [
        "B recomputa o SHA-256 dos bytes no PRÓPRIO storage antes",
        "de assinar o recebimento — evidência, não declaração.",
        "A só aceita o ack se a assinatura for de B (Ed25519)."], p)
    print("[passo 8] B confirma com hash recomputado + assinatura:")
    peer("confirmar")
    print("\n[passo 9] A aplica o ack assinado de B:")
    peer("ack")

    # ---------------- ATO 5 ----------------
    ato(5, "ANONIMIZAÇÃO SOBERANA EM B", [
        "O upload em B também disparou um evento LGPD na outbox",
        "de B: relay -> fila RabbitMQ TLS -> worker de B.",
        "O worker baixa a cópia de B, anonimiza e só grava no",
        "bucket 'anonimizados' depois do gate de PII residual.",
        "Motor nesta demo: regex LGPD determinística — a remoção",
        "é real e VISÍVEL no objeto de saída (ressalva no fim)."], p)
    print("[passo 10] aguardando a esteira assíncrona de B:")
    peer("esperar")
    print("\n[passo 11] trilha do caso nos dois nós:")
    peer("trilha")
    print("\n[passo 12] o objeto ANONIMIZADO no bucket de B:")
    peer("anon")

    # ---------------- ATO 6 ----------------
    ato(6, "PROVAS FINAIS — AUDITORIA E RESISTÊNCIA", [
        "1) replay da hash-chain elo a elo nos DOIS nós;",
        "2) append-only: trigger no Postgres barra UPDATE/DELETE;",
        "3) reenvio de pacote copiado: nonce E2E já visto -> 400."], p)
    print("[passo 13] verificação da cadeia em A e em B:")
    peer("verificar")
    psql_trilha_trigger()
    print("[passo 14] prova de replay — mesmo quadro E2E 2x:")
    peer("replay")

    # ---------------- encerramento ----------------
    print(f"""
{LINHA}
  RESUMO — o que ficou PROVADO em execução real
{LINHA}
  [x] bytes nunca em envelopes/banco: envelope = metadados+hash;
      schema do Postgres NÃO tem coluna binária
  [x] confidencialidade: objeto cru no MinIO é ciphertext E2E
      (magia 0xE2); TLS/mTLS em todos os links; E2E atravessa a borda
  [x] integridade: SHA-256 conferido no upload, no download e
      recomputado por B antes de assinar o recebimento
  [x] autenticidade: envelope adulterado recusado (Ed25519);
      ack só vale com a chave do destino; mTLS na borda
  [x] soberania: cada nó guarda a própria cópia cifrada; B
      anonimiza a SUA cópia no SEU storage
  [x] anonimização: PII visivelmente removido do objeto publicado
      (tags [ANONIMIZADO_LGPD]); gate residual fail-closed
  [x] auditoria: hash-chain íntegra rejogada nos dois nós;
      trigger append-only no Postgres
  [x] resistência: replay de pacote rejeitado pelo cache de
      nonces no Postgres

  RESSALVAS (o que a demo NÃO prova — honestidade técnica):
  - o motor em execução é o DemoMotorIA (regex determinística):
    prova a ESTEIRA completa, não a qualidade do modelo. O
    resultado medido da cascata v2 (NER F1 0,953; reidentificação
    0/360 — corpus sintético) está em docs/metricas.md e ainda
    não está plugado na porta MotorIA (próximo passo do projeto).
  - re-entrega/reconciliação do ack B->A: a assinatura existe e
    foi exercida; o mecanismo de re-entrega é item do roadmap.
  - corpus real, gates de utility/latência e decisões jurídicas
    (reidentificação, caso_cnj em claro) permanecem abertos.
{LINHA}
""")


if __name__ == "__main__":
    main()
