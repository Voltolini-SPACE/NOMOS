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

# Duplicado de `adapters.supervisor.SANDBOX` de propósito: o kernel não importa
# adapter (a dependência é no sentido contrário), e um `import` só para ler uma
# constante arrastaria o supervisor inteiro para dentro do kernel.
SANDBOX_EXEC = "/usr/bin/sandbox-exec"


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


def capacidade_git_governada_disponivel() -> bool:
    """True apenas onde há `sandbox-exec` (macOS), que é o confinamento das
    capacidades Git governadas (C1 leitura, C2a tag, C2b push).

    Fora do macOS elas são INDISPONÍVEIS **por desenho**, não por defeito — ver
    `adapters/supervisor.py`, seção "Fail-closed, sem exceção": a alternativa a
    recusar seria executar código de repositório desconhecido com a autoridade
    do usuário.

    Simétrico de `execucao_isolada_disponivel`, que é só-Linux: os dois
    confinamentos do NOMOS cobrem plataformas diferentes, e cada um recusa
    fail-closed fora da sua.

    Existe como função (e não como comparação solta espalhada) porque a decisão
    já estava replicada em dezenas de `skipif` da suíte, e uma delas condicionava
    ao caminho ERRADO — `/usr/bin/git`, que existe no Linux —, o que fazia a
    suíte afirmar sucesso numa plataforma onde a capacidade não existe.
    """
    return EH_MAC and os.path.exists(SANDBOX_EXEC)


def resumo() -> dict:
    return {
        "sistema": nome_amigavel_so(),
        "python": sys.version.split()[0],
        "execucao_isolada": execucao_isolada_disponivel(),
        "git_governado": capacidade_git_governada_disponivel(),
    }
