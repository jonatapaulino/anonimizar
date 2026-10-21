"""SimuladorNo — agora ALIAS do serviço real.

Antes da implementação existir, este módulo era o oráculo de
contrato. Com o MVP, os testes de fluxo passam a guardar o serviço
real (app.service.NoTramitacao) — mesma interface, mesma máquina de
estados. O nome SimuladorNo permanece nos testes de contrato.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.service import ErroFluxo, NoTramitacao as SimuladorNo  # noqa
