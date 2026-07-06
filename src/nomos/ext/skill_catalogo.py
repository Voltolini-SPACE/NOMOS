"""NOMOS ext.skill_catalogo — catálogo de capacidades (MC29).

Responde, com dados e sem jargão, a pergunta "o que o NOMOS sabe fazer?":
cada skill instalada ou disponível vira uma entrada com os 8 campos do
contrato — nome, descrição, entrada, saída, risco, status, permissões e
exemplos. Somente leitura: este módulo nunca instala, executa ou aprova nada
(instalação/execução continuam no gate de sempre).
"""
from __future__ import annotations

import json
from pathlib import Path

from nomos.ext import skill_registry as reg

CONTRATO_CATALOGO = 1

CAMPOS = ("nome", "descricao", "entrada", "saida", "risco",
          "status", "permissoes", "exemplos")


def _entrada_de(mf: dict) -> str:
    modalidades = mf.get("modalities") or ["texto"]
    return ", ".join(str(m) for m in modalidades)


def _saida_de(mf: dict) -> str:
    return str(mf.get("output") or "resultado local da skill (stdout)")


def _capacidade(mf: dict, status: str) -> dict:
    permissoes = list(mf.get("permissions") or [])
    return {
        "nome": str(mf.get("name", "?")),
        "descricao": str(mf.get("description", "")),
        "entrada": _entrada_de(mf),
        "saida": _saida_de(mf),
        "risco": str(mf.get("risk_level") or reg.risco_de(permissoes)),
        "status": status,
        "permissoes": permissoes,
        "exemplos": [str(k) for k in (mf.get("keywords") or [])][:5],
    }


def _manifestos_instalados(skills_dir: Path) -> list[dict]:
    out = []
    if not skills_dir.exists():
        return out
    for child in sorted(skills_dir.iterdir()):
        mf_path = child / "skill.json"
        if not mf_path.is_file():
            continue
        try:
            out.append(json.loads(mf_path.read_text(encoding="utf-8")))
        except Exception:
            continue  # manifesto ilegível não derruba o catálogo (só some dele)
    return out


def capacidades(home: Path, skills_dir: Path) -> list[dict]:
    """Catálogo unificado: instaladas primeiro; disponíveis sem duplicar nome."""
    itens: list[dict] = []
    vistos: set[str] = set()
    for mf in _manifestos_instalados(skills_dir):
        cap = _capacidade(mf, "instalada")
        itens.append(cap)
        vistos.add(cap["nome"])
    for mf in reg.catalogo(home):
        nome = str(mf.get("name", "?"))
        if nome in vistos:
            continue
        itens.append(_capacidade(mf, "disponível no catálogo"))
        vistos.add(nome)
    itens.sort(key=lambda c: (c["status"] != "instalada", c["nome"]))
    return itens
