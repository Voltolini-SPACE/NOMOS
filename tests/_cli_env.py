"""Ambiente para rodar o CLI/servidor do NOMOS em subprocesso nos testes.

Os testes de localidade rodam o CLI com ``PATH`` vazio de propósito — para
provar que ele NÃO depende do PATH do usuário (usa o caminho absoluto do
Python). Só que um ``env`` mínimo demais quebra o Windows: sem
``SystemRoot`` (e afins), o interpretador Python filho morre no arranque
com ``_Py_HashRandomization_Init: failed to get random numbers to
initialize Python`` — porque não consegue acessar o RNG do sistema.

``cli_env`` mantém a intenção (PATH vazio) e preserva SÓ as variáveis que o
próprio Python precisa para bootar. No Linux/macOS essas variáveis não
existem no ambiente, então o resultado é idêntico ao dict antigo — zero
mudança de comportamento; no Windows, o filho passa a bootar.
"""
from __future__ import annotations

import os

# Variáveis essenciais para o interpretador subir (sobretudo no Windows).
# Em POSIX a maioria não existe e é simplesmente ignorada.
_ESSENCIAIS = (
    "SystemRoot", "SYSTEMROOT", "SystemDrive", "windir", "TEMP", "TMP",
    "PATHEXT", "COMSPEC", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER", "APPDATA", "LOCALAPPDATA",
    "PYTHONUTF8", "PYTHONIOENCODING", "LANG", "LC_ALL",
)


def cli_env(nomos_home, **extra) -> dict[str, str]:
    """Env de subprocesso: NOMOS_HOME + PATH vazio + essenciais do SO."""
    env = {"NOMOS_HOME": str(nomos_home), "PATH": ""}
    for chave in _ESSENCIAIS:
        val = os.environ.get(chave)
        if val is not None:
            env[chave] = val
    env.update({k: str(v) for k, v in extra.items()})
    return env
