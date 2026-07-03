"""NOMOS cognition.feedback — o roteador aprende com VOCÊ, localmente.

Cada 👍/👎 vira um contador por motor em NOMOS_HOME/feedback.json (0600).
Zero telemetria: os votos nunca saem da máquina; servem só para o roteador
ordenar melhor os motores e ajustar a confiança — de forma explicável.
"""
from __future__ import annotations

import json
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

ARQUIVO = "feedback.json"
MINIMO_VOTOS = 3      # abaixo disso não há sinal — não julga motor por 1 voto


def _caminho(home: Path) -> Path:
    return Path(home) / ARQUIVO


def _ler(home: Path) -> dict:
    p = _caminho(home)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def registrar(home: Path, motor_id: str, bom: bool) -> dict:
    dados = _ler(home)
    m = dados.setdefault(motor_id, {"bom": 0, "ruim": 0})
    m["bom" if bom else "ruim"] += 1
    p = _caminho(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dados, ensure_ascii=False, indent=2))
    chmod_privado(p, 0o600)
    return dict(m)


def taxa(home: Path, motor_id: str) -> float | None:
    """Fração de votos bons (0..1) ou None se ainda não há sinal suficiente."""
    m = _ler(home).get(motor_id)
    if not m:
        return None
    total = int(m.get("bom", 0)) + int(m.get("ruim", 0))
    if total < MINIMO_VOTOS:
        return None
    return m.get("bom", 0) / total


def resumo(home: Path) -> dict:
    return _ler(home)
