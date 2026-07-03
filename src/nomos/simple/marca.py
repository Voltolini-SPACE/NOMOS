"""NOMOS simple.marca — o banner da marca (logo ASCII) para o terminal.

Aplica a identidade do brandbook v1.0: logo em blocos, verde-neon, tagline.
A cor respeita o tema escolhido pelo usuário (simple.tema).
"""
from __future__ import annotations

from nomos.simple.tema import Tema

LOGO = r"""
███╗   ██╗ ██████╗ ███╗   ███╗ ██████╗ ███████╗
████╗  ██║██╔═══██╗████╗ ████║██╔═══██╗██╔════╝
██╔██╗ ██║██║   ██║██╔████╔██║██║   ██║███████╗
██║╚██╗██║██║   ██║██║╚██╔╝██║██║   ██║╚════██║
██║ ╚████║╚██████╔╝██║ ╚═╝ ██║╚██████╔╝███████║
╚═╝  ╚═══╝ ╚═════╝ ╚═╝     ╚═╝ ╚═════╝ ╚══════╝"""

TAGLINE = "seu agente · sua máquina · suas regras"


def banner(perfil: dict | None = None) -> str:
    t = Tema(perfil or {})
    linhas = [t.c("destaque", ln) if ln.strip() else ln for ln in LOGO.splitlines()]
    linhas.append(t.c("fraco", "  " + TAGLINE))
    return "\n".join(linhas)
