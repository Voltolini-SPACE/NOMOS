"""NOMOS ext.skill_status — estado das skills instaladas, em linguagem de status.

Estados possíveis por skill:
- ativa / inativa: liga/desliga local (skills_estado.json, 0600) — desativar
  nunca apaga arquivos;
- quebrada: manifesto ilegível/ inválido, entry ausente ou checksum divergente;
- confiável: assinatura íntegra de publicador presente no trust store;
- experimental: não assinada ou risco alto.

Nada aqui concede permissão: o gate continua na política. Este módulo só observa.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from nomos.ext import skills as _skills
from nomos.ext import skill_registry as reg
from nomos.ext.signing import SigningError, TrustStore, verify_signed_manifest
from nomos.kernel.plataforma import chmod_privado

ARQUIVO_ESTADO = "skills_estado.json"


def _caminho(home: Path) -> Path:
    return Path(home) / ARQUIVO_ESTADO


def _ler(home: Path) -> dict:
    p = _caminho(home)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _gravar(home: Path, dados: dict) -> None:
    p = _caminho(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dados, ensure_ascii=False, indent=2))
    chmod_privado(p, 0o600)


def esta_ativa(home: Path, name: str) -> bool:
    """Padrão: ativa (instalou, funciona). Desativação é explícita."""
    return bool(_ler(home).get(name, {}).get("ativa", True))


def ativar(home: Path, name: str, ativa: bool = True) -> None:
    dados = _ler(home)
    dados.setdefault(name, {})["ativa"] = bool(ativa)
    _gravar(home, dados)


def marcar_uso(home: Path, name: str) -> None:
    dados = _ler(home)
    dados.setdefault(name, {})["ultimo_uso"] = int(time.time())
    _gravar(home, dados)


def ultimo_uso(home: Path, name: str) -> int | None:
    return _ler(home).get(name, {}).get("ultimo_uso")


def _quebrada(dest: Path, mf: dict) -> str | None:
    """Devolve o defeito (str) ou None se íntegra."""
    problemas = reg.validar_manifesto(mf)
    if problemas:
        return "manifesto inválido: " + problemas[0]
    entry = mf.get("entry") or mf.get("entrypoint") or ""
    if not (dest / entry).exists():
        return f"entry ausente: {entry}"
    try:
        _skills.verify_files(dest, mf)
    except _skills.SkillError as exc:
        return str(exc)
    return None


def _confiavel(mf: dict, trust: TrustStore | None) -> bool:
    if trust is None or "signature" not in mf:
        return False
    try:
        verify_signed_manifest(mf, trust)
        return True
    except SigningError:
        return False


def status_skill(home: Path, dest: Path, trust: TrustStore | None = None) -> dict:
    """Status completo de UMA skill instalada (diretório dest)."""
    mf_path = dest / "skill.json"
    base = {"name": dest.name, "version": "?", "permissions": [],
            "risco": "alto", "requer_aprovacao": True, "publisher": "desconhecido",
            "modalities": [], "ativa": esta_ativa(home, dest.name),
            "ultimo_uso": ultimo_uso(home, dest.name)}
    try:
        mf = json.loads(mf_path.read_text())
    except Exception:
        return {**base, "estado": "quebrada", "defeito": "manifesto ilegível",
                "confiavel": False,
                "acao": "reinstale a skill (nomos skills instalar <caminho>)"}
    mfn = reg.normalizar_manifesto(mf)
    defeito = _quebrada(dest, mf)
    confiavel = _confiavel(mf, trust)
    if defeito:
        estado = "quebrada"
        acao = "reinstale a skill (nomos skills instalar <caminho>)"
    elif not base["ativa"]:
        estado = "inativa"
        acao = f"reative quando quiser: nomos skills ativar {dest.name}"
    elif not confiavel:
        estado = "ativa (não confiável)"
        acao = "peça ao publicador uma versão assinada, ou siga por sua conta"
    else:
        estado = "ativa"
        acao = "tudo certo"
    return {**base,
            "version": mfn.get("version", "?"),
            "permissions": mfn.get("permissions", []),
            "risco": mfn.get("risk_level", "alto"),
            "requer_aprovacao": mfn.get("requires_approval", True),
            "publisher": mfn.get("publisher", "desconhecido"),
            "modalities": mfn.get("modalities", []),
            "estado": estado, "defeito": defeito, "confiavel": confiavel,
            "acao": acao}


def status_todas(home: Path, skills_dir: Path,
                 trust: TrustStore | None = None) -> list[dict]:
    skills_dir = Path(skills_dir)
    if not skills_dir.exists():
        return []
    out = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir():
            out.append(status_skill(Path(home), child, trust))
    return out
