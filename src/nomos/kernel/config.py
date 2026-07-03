"""NOMOS kernel.config — caminhos, home seguro e identidade do agente."""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import json
import os
import re
import time
from pathlib import Path

SCHEMA_VERSION = 1
AGENT_FILE = "agent.json"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,31}$")
RESERVED_NAMES = {"nomos", "root", "admin", "system", "sudo"}


class ConfigError(Exception):
    pass


def nomos_home() -> Path:
    """Home de dados do NOMOS. NOMOS_HOME permite isolamento em testes."""
    return Path(os.environ.get("NOMOS_HOME", str(Path.home() / ".nomos")))


def ensure_home() -> Path:
    home = nomos_home()
    for sub in ("", "logs", "skills", "sandbox", "backups"):
        (home / sub if sub else home).mkdir(parents=True, exist_ok=True)
    chmod_privado(home, 0o700)
    return home


def validate_agent_name(name: str) -> str:
    name = name.strip()
    if not NAME_RE.match(name):
        raise ConfigError(
            "nome de agente inválido: use 2-32 caracteres, iniciando por letra "
            "(letras, dígitos, '-' ou '_')"
        )
    if name.lower() in RESERVED_NAMES:
        raise ConfigError(f"nome reservado pela plataforma: {name!r}")
    return name


def save_agent(name: str) -> dict:
    ensure_home()
    name = validate_agent_name(name)
    data = {
        "schema": SCHEMA_VERSION,
        "agent_name": name,
        "created_at": int(time.time()),
        "mode": "local",  # local-first; cloud é opt-in por política
    }
    path = nomos_home() / AGENT_FILE
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    chmod_privado(path, 0o600)
    return data


def load_agent() -> dict | None:
    path = nomos_home() / AGENT_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text())
