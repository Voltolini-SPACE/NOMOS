"""NOMOS kernel.plataforma — utilidades que fazem o NOMOS rodar em qualquer SO.

Objetivo: o núcleo (chat, memória, cofre, chaves, motores, cadeado local)
funciona igual em Linux, macOS e Windows. Recursos que dependem do sistema
(execução isolada de código via namespaces do Linux) degradam com mensagem
clara em vez de quebrar.
"""
from __future__ import annotations

import os
import platform
import sys

SISTEMA = platform.system()          # 'Linux' | 'Darwin' | 'Windows'
EH_WINDOWS = SISTEMA == "Windows"
EH_MAC = SISTEMA == "Darwin"
EH_LINUX = SISTEMA == "Linux"


def nome_amigavel_so() -> str:
    return {"Darwin": "Mac", "Windows": "Windows", "Linux": "Linux"}.get(SISTEMA, SISTEMA)


def chmod_privado(caminho, modo: int = 0o600) -> None:
    """Restringe permissões a 'só o dono'. No Windows, os bits Unix não se
    aplicam da mesma forma — a proteção vem das permissões do perfil do
    usuário; tentamos assim mesmo e ignoramos se não for suportado."""
    try:
        os.chmod(caminho, modo)
    except (OSError, NotImplementedError):
        pass


def execucao_isolada_disponivel() -> bool:
    """True apenas onde há como isolar rede de verdade (Linux + user
    namespaces). Em Mac/Windows a execução de código em sandbox S0 é recusada
    fail-closed — o resto do NOMOS funciona normalmente."""
    if not EH_LINUX:
        return False
    try:
        import resource  # noqa: F401
    except ImportError:
        return False
    from shutil import which
    return which("unshare") is not None


def resumo() -> dict:
    return {
        "sistema": nome_amigavel_so(),
        "python": sys.version.split()[0],
        "execucao_isolada": execucao_isolada_disponivel(),
    }
