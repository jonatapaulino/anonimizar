"""Demonstração executável — jornada do documento A -> B (malha real).

Roda DENTRO do contêiner `peer` (rede `borda`); é invocado passo a
passo pelo orquestrador `scripts/demo_coordenador.py` no host. Cada
etapa imprime o que aconteceu e a evidência que a prova — o estado
(tid/caso) persiste em /run/demo_state.json entre invocações.

  criar     A registra a tramitação — metadados + hash (nunca bytes)
  upload    A sobe o documento — hash conferido, magic bytes, MinIO
  envio     A emite o envelope A->B — SÓ metadados + assinatura Ed25519
  adulterar prova negativa: hash adulterado em trânsito -> B recusa
  receber   B ingressa o envelope legítimo — identidade mTLS + assinatura
  download  B baixa os bytes de A — mesmos bytes, hash revalidado
  upload_b  B arquiva a própria cópia no storage soberano de B
  confirmar B recomputa o SHA-256 no storage e emite ack ASSINADO
  ack       A aplica o ack — ciclo de custódia fechado
  trilha    hash-chain de B — eventos append-only do caso
  esperar   polling até a esteira de B marcar doc_anonimizado
  anon      objeto anonimizado em B — PII visivelmente removido
  verificar replay elo a elo da hash-chain em A e em B
  replay    prova de reenvio: mesmo quadro E2E 2x -> 2ª é rejeitada

Uso direto:  python /run/demo_fluxo_peer.py <etapa>
"""
import asyncio
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, "/srv")
from app.cliente_e2e import ClienteE2E          # noqa: E402

ESTADO = "/run/demo_state.json"
CASO = f"{int(time.time()) % 10_000_000:07d}-02.2026.8.00.0001"

# Documento de demonstração — texto UTF-8 em formato de petição.
# Texto puro de propósito: todos os gates (magic bytes, legibilidade
# e PII residual) executam de verdade e a saída anonimizada fica
# legível no terminal para a plateia. Derivado do `caso` gravado no
# estado — cada invocação do script reconstrói os MESMOS bytes.
def _doc_texto(caso: str) -> bytes:
    return f"""\
PETICAO INICIAL — Processo {caso}
Vara Civel da Comarca — envio eletronico sigiloso

Requerente: MARIA EDUARDA NASCIMENTO, cpf 123.456.789-00
E-mail de contato: maria.eduarda@exemplo.com.br
Telefone: (91) 98765-4321

DOS FATOS: a requerente narra que, em janeiro de 2026, ...
DOS PEDIDOS: requer a procedencia do pedido com condenacao
do reu, nos termos da fundamentacao. — DEMO-COORDENADOR-7X9
""".encode()


def _doc() -> bytes:
    return _doc_texto(_estado().get("caso", CASO))

CERT_TJPA = ("/run/certs/tjpa.crt", "/run/certs/tjpa.key")
CERT_MFPA = ("/run/certs/mpfpa.crt", "/run/certs/mpfpa.key")
CA = "/run/certs/ca.crt"


def _estado() -> dict:
    try:
        return json.load(open(ESTADO))
    except Exception:
        return {}


def _salvar(**kw) -> None:
    st = _estado()
    st.update(kw)
    json.dump(st, open(ESTADO, "w"))


def _prog(etapa: str, titulo: str, detalhe: str, **extra) -> None:
    """Marco de progresso para o visualizador web — o orquestrador
    `demo_web.py` lê `progresso[]` e anima a jornada na tela.
    `extra` pode levar: lado ('A'|'B'), movimento ('A->B'|'B->A'),
    tipo ('doc'|'envelope'|'ack'|'ataque'), prova (id de garantia)."""
    st = _estado()
    prog = st.setdefault("progresso", [])
    entrada = {"n": len(prog) + 1, "etapa": etapa,
               "titulo": titulo, "detalhe": detalhe,
               "ts": time.time()}
    entrada.update(extra)
    prog.append(entrada)
    json.dump(st, open(ESTADO, "w"))


def _tid() -> str:
    tid = _estado().get("tid")
    if not tid:
        sys.exit("execute primeiro a etapa 'criar'")
    return tid


def ok(cond, msg=""):
    if not cond:
        sys.exit(f"  FALHOU: {msg}")


async def cli(url, cert):
    return ClienteE2E(url, bytes.fromhex(os.environ["E2E_CHAVE"]),
                      cert=cert, verify=CA)


# ---------------- etapas ----------------

async def criar():
    a = await cli("https://nginx-a", CERT_TJPA)
    doc = _doc_texto(CASO)          # caso fresco desta execução
    r = await a.post("/v1/tramitacoes", dict(
        caso_cnj=CASO, destino="mpfpa", modo="pseudonimizacao",
        hash_documento_sha256=hashlib.sha256(doc).hexdigest(),
        metadados={"classe": "peticao_inicial",
                   "sigilo": "demonstracao"},
        idempotency_key=f"demo-{CASO}",
        requer_anonimizacao_lgpd=True))
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    ok(r.status_code == 201, r.content[:200])
    _salvar(tid=r.json()["id"], caso=CASO,
            hash_doc=hashlib.sha256(doc).hexdigest(),
            doc_texto=doc.decode("utf-8", errors="replace"),
            progresso=[])
    _prog("criar", "A registra o caso",
          "metadados + hash declarado — o binário não sai daqui",
          lado="A", prova="sem-bytes",
          narr="A abertura registra só a 'capa' e a impressão "
              "digital do documento — o conteúdo fica dentro "
              "da instituição.")
    await a.fechar()
    print(f"\n  -> status CRIADA; hash declarado = âncora de"
          f" integridade (o PDF/texto em si NÃO saiu daqui)")


async def upload():
    a = await cli("https://nginx-a", CERT_TJPA)
    r = await a.post_multipart(
        f"/v1/documentos/{_tid()}/upload",
        "arquivo", "peticao.txt", _doc(), "text/plain")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    ok(r.status_code == 201, r.content[:200])
    _prog("upload", "A arquiva o documento",
          "SHA-256 conferido byte a byte; objeto E2E no MinIO de A",
          lado="A", prova="cifrado",
          narr="O arquivo é guardado trancado no cofre da própria "
              "instituição — nem o banco de dados guarda o "
              "documento em si.")
    await a.fechar()
    print("\n  -> SHA-256 conferido byte a byte; magic bytes do"
          " formato validados; objeto gravado no MinIO do nó A"
          " (quadros E2E — só ciphertext em repouso)")


async def envio():
    a = await cli("https://nginx-a", CERT_TJPA)
    r = await a.post(f"/v1/tramitacoes/{_tid()}/envio", {})
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    ok(r.status_code in (200, 201), r.content[:200])
    _salvar(envio=r.json())
    _prog("envio", "Envelope A → B emitido",
          "só metadados + hash + assinatura Ed25519 de A — "
          "zero bytes do documento",
          movimento="A->B", tipo="envelope", prova="sem-bytes",
          narr="O que atravessa a fronteira é só um aviso: "
              "'existe este documento, com esta impressão "
              "digital' — o papel em si não viaja.")
    await a.fechar()
    print("\n  -> O ENVELOPE É SÓ METADADOS: hash + assinatura"
          " Ed25519 de A. Nenhum byte do documento atravessa"
          " aqui — prove: o campo 'assinatura' assina TODOS os"
          " demais campos.")


async def adulterar():
    env = dict(_estado()["envio"])
    env["hash_documento_sha256"] = "0" * 64
    b = await cli("https://nginx-b", CERT_TJPA)
    r = await b.post("/v1/recebimentos", env)
    print(f"  POST /v1/recebimentos (hash adulterado) -> "
          f"{r.status_code}")
    print(f"  resposta: {r.content[:160].decode(errors='replace')}")
    ok(r.status_code >= 400,
       f"B ACEITOU envelope adulterado ({r.status_code})")
    _prog("adulterar", "ATAQUE: hash adulterado em trânsito",
          f"B recusou ({r.status_code}) — assinatura Ed25519 "
          "inválida; o envelope não vira registro",
          movimento="A->B", tipo="ataque", prova="adulteracao",
          narr="Alguém mexeu no aviso no caminho — a assinatura "
              "não confere e B joga a cópia fora. Ela não vira "
              "registro em lugar nenhum.")
    await b.fechar()
    print("\n  -> B verificou a assinatura Ed25519 de A sobre os"
          " campos ANTES de persistir — o campo adulterado quebra"
          " o selo e o envelope é recusado. Fail-closed.")


async def receber():
    b = await cli("https://nginx-b", CERT_TJPA)
    r = await b.post("/v1/recebimentos", _estado()["envio"])
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    ok(r.status_code in (200, 201), r.content[:200])
    _prog("receber", "B recebe o envelope",
          "CN do certificado mTLS = origem; assinatura válida; "
          "destino = este nó",
          lado="B", movimento="A->B", tipo="envelope",
          narr="O aviso verdadeiro atravessa de novo e B confere "
              "a assinatura — agora sim vira registro.")
    await b.fechar()
    print("\n  -> B conferiu: CN do certificado mTLS = 'tjpa' ="
          " envelope.origem; destino = 'mpfpa' = este nó;"
          " assinatura válida => projeção RECEBIDA registrada"
          " na trilha de B.")


async def download():
    a = await cli("https://nginx-a", CERT_TJPA)
    r = await a.get(f"/v1/documentos/{_tid()}/download")
    ok(r.status_code == 200, f"download {r.status_code}")
    h = hashlib.sha256(r.content).hexdigest()
    print(f"  bytes recebidos: {len(r.content)} | sha256: {h[:24]}...")
    ok(h == _estado()["hash_doc"], "hash diverge do declarado")
    _prog("download", "B baixa os bytes de A",
          "canal E2E decifrado no cliente — bytes idênticos "
          "ao hash declarado no passo 1",
          movimento="A->B", tipo="doc",
          narr="B busca o documento direto na fonte, por canal "
              "trancado de ponta a ponta, e confere a impressão "
              "digital.")
    await a.fechar()
    print("\n  -> B baixou de A pelo canal E2E: o storage de A"
          " guarda ciphertext; a API decifra em streaming; o"
          " envelope cifra de volta no fio; o cliente decifra"
          " — e os bytes batem com o hash declarado no passo 1.")


async def upload_b():
    b = await cli("https://nginx-b", CERT_TJPA)
    r = await b.post_multipart(
        f"/v1/documentos/{_tid()}/upload",
        "arquivo", "peticao.txt", _doc(), "text/plain")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    ok(r.status_code == 201, r.content[:200])
    _prog("upload_b", "B arquiva a própria cópia",
          "hash conferido; ciphertext E2E no MinIO de B — "
          "soberania de storage",
          lado="B", prova="cifrado",
          narr="B tranca a própria cópia no próprio cofre — "
              "cada instituição é dona dos seus objetos.")
    await b.fechar()
    print("\n  -> mesma disciplina do nó A: hash conferido contra"
          " o registrado, formato validado, cópia de B cifrada"
          " no MinIO de B — SOBERANIA: cada instituição guarda"
          " a sua cópia no seu próprio storage.")


async def confirmar():
    b = await cli("https://nginx-b", CERT_MFPA)
    r = await b.post(f"/v1/tramitacoes/{_tid()}/confirmacao", dict(
        tramitacao_id=_tid(), decisao="aceita",
        hash_documento_recebido=_estado()["hash_doc"]))
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    ok(r.status_code in (200, 201), r.content[:200])
    _salvar(ack=r.json())
    _prog("confirmar", "B confirma e assina o recebimento",
          "SHA-256 recomputado no storage de B; ack sai "
          "assinado Ed25519",
          lado="B",
          narr="B não apenas 'diz que recebeu': recalcula a "
              "impressão digital do que guardou e assina o "
              "recibo.")
    await b.fechar()
    print("\n  -> 'dizer que recebeu' não basta: B recomputou o"
          " SHA-256 dos bytes no PRÓPRIO MinIO e exigiu que"
          " confira com o declarado antes de assinar o ack."
          " O ack sai assinado Ed25519 — a decisão só vale com"
          " a chave de B.")


async def ack():
    a = await cli("https://nginx-a", CERT_MFPA)
    r = await a.post(f"/v1/tramitacoes/{_tid()}/acks",
                     _estado()["ack"])
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    ok(r.status_code == 200, r.content[:200])
    _prog("ack", "A aplica o ack assinado de B",
          "assinatura verificada contra a chave pública de B — "
          "status CONFIRMADA; custódia fechada",
          movimento="B->A", tipo="ack", prova="custodia",
          narr="O recibo assinado volta para A e fecha o ciclo: "
              "A entregou, B confirmou — com prova nas duas "
              "pontas.")
    await a.fechar()
    print("\n  -> A verificou a assinatura do ack contra a chave"
          " pública de B e aplicou: status CONFIRMADA — ciclo de"
          " custódia A->B->A fechado com evidência.")


async def trilha():
    trilhas = {}
    for nome, url in (("A (tjpa)", "https://nginx-a"),
                      ("B (mpfpa)", "https://nginx-b")):
        c = await cli(url, CERT_TJPA)
        r = await c.get(f"/v1/tramitacoes/{_tid()}")
        ok(r.status_code == 200, r.content[:160])
        j = r.json()
        trilhas[nome.split()[0].lower()] = {
            "status": j["status"],
            "eventos": [e["evento"] for e in j.get("trilha", [])]}
        print(f"  Nó {nome} — status={j['status']} "
              f"topo={j['hash_cadeia'][:20]}...")
        for e in j.get("trilha", []):
            print(f"    seq={e['seq']:>2}  {e['evento']:<44} "
                  f"{e['hash_cadeia'][:16]}...")
        await c.fechar()
    _salvar(trilhas=trilhas)
    _prog("trilha", "Hash-chain append-only nos dois nós",
          f"A: {len(trilhas['a']['eventos'])} elos | "
          f"B: {len(trilhas['b']['eventos'])} elos — "
          "sha256(elo anterior | evento)",
          prova="cadeia",
          narr="Cada acontecimento vira um elo numa corrente "
              "que não pode ser apagada nem reescrita depois.")
    print("\n  -> cada elo = sha256(elo anterior | evento):"
          " append-only, sem UPDATE/DELETE (trigger no Postgres)."
          " Adulterar uma linha quebra todos os elos seguintes.")


async def anon():
    b = await cli("https://nginx-b", CERT_TJPA)
    r = await b.get(f"/v1/documentos/{_tid()}/download-anonimizado")
    ok(r.status_code == 200, f"{r.status_code} — a esteira de B"
       " ainda não produziu o objeto; aguarde e rode de novo")
    txt = r.content.decode("utf-8", errors="replace")
    print("  ---------- CONTEÚDO ANONIMIZADO (bucket de B) -----")
    for ln in txt.splitlines():
        print("  | " + ln)
    print("  ---------------------------------------------------")
    tags = txt.count("[ANONIMIZADO_LGPD]")
    print(f"  tags [ANONIMIZADO_LGPD] no lugar do PII: {tags}")
    ok(tags >= 3 and "MARIA EDUARDA" not in txt
       and "123.456.789-00" not in txt
       and "maria.eduarda@" not in txt,
       "PII ainda visível na saída")
    _salvar(anon_texto=txt)
    _prog("anon", "Documento anonimizado em B",
          f"{tags} trechos de PII substituídos por "
          "[ANONIMIZADO_LGPD] — objeto publicado no bucket "
          "anonimizados de B",
          lado="B", prova="anonimizacao",
          narr="Nome, CPF, e-mail e telefone viraram tarjas "
              "[ANONIMIZADO_LGPD] no objeto público de B.")
    await b.fechar()
    print("\n  -> worker de B baixou a cópia de B, aplicou o motor"
          " e só gravou depois do gate de PII residual (nome, CPF,"
          " e-mail e telefone removidos do objeto publicado).")


async def esperar():
    """Aguarda a esteira assíncrona de B: outbox -> relay -> fila
    RabbitMQ TLS -> worker -> MinIO + trilha. Polling na consulta
    pública até o evento aparecer (sem sleep cego)."""
    import time
    b = await cli("https://nginx-b", CERT_TJPA)
    t0 = time.time()
    while time.time() - t0 < 90:
        r = await b.get(f"/v1/tramitacoes/{_tid()}")
        ok(r.status_code == 200, r.content[:160])
        trilha = [e["evento"] for e in r.json().get("trilha", [])]
        if any(e.startswith("doc_anonimizado:") for e in trilha):
            print(f"  doc_anonimizado na trilha de B após "
                  f"{time.time() - t0:.0f}s de espera")
            _prog("esperar", "Esteira assíncrona de B concluída",
                  "outbox → relay → fila RabbitMQ TLS → worker → "
                  "gate de PII residual → bucket anonimizados",
                  lado="B",
                  narr="A anonimização roda em segundo plano "
                      "dentro do próprio B — o documento não "
                      "precisa sair de lá para ser tratado.")
            await b.fechar()
            return
        if any(e.startswith("falha_anonimizacao:") for e in trilha):
            await b.fechar()
            sys.exit(f"  FALHOU: esteira marcou {trilha}")
        print(f"  ... aguardando worker de B "
              f"({int(time.time() - t0)}s): {trilha[-1] if trilha else '-'}")
        await asyncio.sleep(3)
    await b.fechar()
    sys.exit("  FALHOU: esteira de B não concluiu em 90s")


async def verificar():
    for nome, url in (("A", "https://nginx-a"),
                      ("B", "https://nginx-b")):
        c = await cli(url, CERT_TJPA)
        r = await c.get(f"/v1/tramitacoes/{_tid()}/verificar")
        ok(r.status_code == 200, r.content[:160])
        j = r.json()
        print(f"  nó {nome}: integro={j['integro']} "
              f"linhas_rejogadas={j['linhas']} "
              f"topo={j['topo_recomputado'][:24]}...")
        ok(j["integro"], f"cadeia de {nome} NÃO íntegra")
        await c.fechar()
    _prog("verificar", "Cadeia rejogada elo a elo",
          "integro=True nos dois nós — cada elo recomputado "
          "do GENESIS e comparado ao gravado",
          prova="cadeia",
          narr="As duas correntes são refeitas do zero e "
              "conferem — qualquer mexida teria quebrado os "
              "elos seguintes.")
    print("\n  -> auditoria AUTÔNOMA: cada elo foi recomputado do"
          " GENESIS e comparado ao gravado — a prova não é o topo,"
          " é o replay da cadeia inteira, nos DOIS nós.")


async def replay():
    """Mesma request E2E enviada 2x: o nonce do quadro já foi
    visto -> a 2ª é rejeitada (400) antes de tocar a aplicação."""
    import ssl
    import httpx
    from app.crypto_e2e import CT_E2E, selar
    chave = bytes.fromhex(os.environ["E2E_CHAVE"])
    dados = selar(chave, b"{}")          # um selo = um nonce único
    h = {"Content-Type": CT_E2E, "X-E2E-CT": "application/json"}
    ctx = ssl.create_default_context(cafile=CA)
    ctx.load_cert_chain(*CERT_TJPA)
    async with httpx.AsyncClient(verify=ctx) as c:
        r1 = await c.request(
            "GET", f"https://nginx-a/v1/tramitacoes/{_tid()}",
            content=dados, headers=h)
        r2 = await c.request(
            "GET", f"https://nginx-a/v1/tramitacoes/{_tid()}",
            content=dados, headers=h)
    print(f"  1ª entrega do quadro -> {r1.status_code} | "
          f"2ª entrega IDÊNTICA -> {r2.status_code}")
    ok(r1.status_code == 200 and r2.status_code == 400,
       f"esperado 200/400, obtido {r1.status_code}/{r2.status_code}")
    _prog("replay", "Pacote copiado é rejeitado",
          "1ª entrega 200 — 2ª idêntica 400: o nonce do quadro "
          "já foi reivindicado no Postgres",
          prova="replay",
          narr="Copiar e reenviar o mesmo pacote não funciona: "
              "o carimbo único dele já foi gasto.")
    print("\n  -> o nonce do quadro AEAD é reivindicado"
          " atomicamente no Postgres (replay_nonces): um pacote"
          " copiado no fio e reentregue não executa a operação"
          " uma segunda vez — mesmo dentro da janela de frescura.")


ETAPAS = {k: v for k, v in list(globals().items())
          if callable(v) and k in (
              "criar", "upload", "envio", "adulterar", "receber",
              "download", "upload_b", "confirmar", "ack", "trilha",
              "esperar", "anon", "verificar", "replay")}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ETAPAS:
        sys.exit(f"uso: {sys.argv[0]} <{'|'.join(ETAPAS)}>")
    asyncio.run(ETAPAS[sys.argv[1]]())
