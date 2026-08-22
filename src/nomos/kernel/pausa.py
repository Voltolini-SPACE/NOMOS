"""NOMOS kernel.pausa — o freio gracioso da execução autônoma (NH-026).

`panic` é o corte instantâneo: revoga consentimentos, nega aprovações
pendentes e tranca a localidade. A pausa é o irmão calmo dele: a ocorrência
que já começou TERMINA; nenhuma nova começa. Quem consulta é o Ticker (a
única porta onde ocorrência autônoma nasce) e `rotinas.executar_devidas`
(a outra porta autônoma). `nomos orquestrar` no terminal NÃO consulta —
o dono presente no TTY é a autoridade, não precisa de freio contra si.

Doutrina de fricção assimétrica:
- PAUSAR nunca tem gate — freio não pode ter fricção (mesma regra do panic);
- RETOMAR passa pelo gate A1 no CLI — religar a autonomia exige o dono
  presente (seria o único "des-panic" parcial sem humano).

Estado em NOMOS_HOME/pausa.json (0600). Ausente = ATIVO (pausa é exceção);
presente e ILEGÍVEL = PAUSADO (freio nunca é fail-open).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

ARQUIVO = "pausa.json"


def _caminho(home: Path) -> Path:
    return Path(home) / ARQUIVO


def esta_pausado(home: Path) -> bool:
    """Pausado? Ausente ⇒ False. Presente e ilegível/estranho ⇒ True."""
    p = _caminho(home)
    if not p.exists():
        return False
    try:
        dados = json.loads(p.read_text())
        if not isinstance(dados, dict):
            return True
        return bool(dados.get("pausado", True))
    except Exception:
        return True


def estado(home: Path) -> dict:
    """Estado legível para status/batimento. Nunca levanta exceção."""
    p = _caminho(home)
    if not p.exists():
        return {"pausado": False, "desde": None, "motivo": "",
                "origem": "", "ilegivel": False}
    try:
        dados = json.loads(p.read_text())
        if not isinstance(dados, dict):
            raise ValueError("pausa.json não é objeto")
        return {"pausado": bool(dados.get("pausado", True)),
                "desde": dados.get("desde"),
                "motivo": str(dados.get("motivo", ""))[:200],
                "origem": str(dados.get("origem", "")),
                "ilegivel": False}
    except Exception:
        # ilegível conta como PAUSADO (coerente com esta_pausado) e o campo
        # `ilegivel` deixa o status explicar POR QUE está pausado
        return {"pausado": True, "desde": None, "motivo": "",
                "origem": "", "ilegivel": True}


def _gravar(home: Path, dados: dict) -> dict:
    p = _caminho(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False))
    chmod_privado(tmp, 0o600)
    tmp.replace(p)
    chmod_privado(p, 0o600)
    return dados


def pausar(home: Path, motivo: str = "", origem: str = "cli") -> dict:
    """Liga a pausa (idempotente). Sem gate — freio não tem fricção."""
    return _gravar(home, {
        "pausado": True,
        "desde": datetime.now(timezone.utc).isoformat(),
        "motivo": str(motivo or "")[:200],
        "origem": str(origem or "cli"),
    })


def retomar(home: Path) -> dict:
    """Desliga a pausa. O GATE mora no caller (CLI) — aqui é só estado."""
    return _gravar(home, {"pausado": False,
                          "desde": datetime.now(timezone.utc).isoformat(),
                          "motivo": "", "origem": "cli"})
