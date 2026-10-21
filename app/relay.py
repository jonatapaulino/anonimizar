"""Relay outbox -> broker (ADR-0013).

O padrão: o evento já está commitado no Postgres; o relay lê os
elegíveis, reclama cada um por UPDATE condicional (claim atômico
— seguro para N réplicas: a linha serializa a corrida), publica
no broker e marca PROCESSADO **só depois** do publisher-confirm.
Falha => `outbox_falhar`: tentativas++ e retry com backoff
exponencial até esgotar — aí vira ESGOTADO + `falha_outbox:{tid}`
na hash-chain. Relay que cai no meio não trava a linha: o lease
(PUBLICANDO + proximo_retry_em) expira e outro reclama.

`relay_pass` é chamável diretamente nos testes com
PublicadorMemoria — o ciclo inteiro é verificável sem broker;
`agora` é injetável para exercitar o backoff sem sleep.
"""
from __future__ import annotations

import asyncio
import logging

from app.models import StatusOutbox
from app.repository import _agora

log = logging.getLogger("tramitacao.relay")


async def relay_pass(repo, publicador, limite: int = 50, *,
                     agora=None, lease_s: float = 60.0,
                     backoff_base_s: float = 5.0,
                     backoff_cap_s: float = 900.0,
                     max_tentativas: int = 8) -> int:
    """Uma drenagem da outbox. Retorna quantos foram confirmados."""
    agora = agora or _agora()
    n = 0
    for ev in await repo.outbox_elegiveis(limite, agora):
        if not await repo.outbox_reservar(ev.id, agora, lease_s):
            continue                  # outro relay reclamou antes
        try:
            await publicador.publicar(ev.payload)   # ACK do broker
            await repo.outbox_marcar(ev.id,
                                     StatusOutbox.PROCESSADO)
            n += 1
        except Exception as e:
            log.warning("relay: publish falhou (%s) — "
                        "evento %s segue na outbox", e, ev.id)
            await repo.outbox_falhar(ev.id, agora, backoff_base_s,
                                     backoff_cap_s, max_tentativas)
    return n


async def relay_loop(repo, publicador, intervalo: float = 1.0,
                     **cfg):
    """Polling contínuo — task de background do lifespan. `cfg`
    propaga os parâmetros de retry para `relay_pass`."""
    while True:
        try:
            await relay_pass(repo, publicador, **cfg)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("relay_pass falhou — próxima passada")
        await asyncio.sleep(intervalo)
