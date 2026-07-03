"""NOMOS kernel.localidade — o cadeado que mantém o sistema 100% local.

Princípio: o NOMOS roda inteiramente na máquina do usuário. A nuvem e
qualquer serviço externo são MOTORES OPCIONAIS que só funcionam se o usuário
'desplugar o cadeado' de propósito.

Modo só-local (padrão LIGADO):
- toda tentativa de egress para um alvo NÃO-loopback é NEGADA já na política
  (efeito DENY), antes mesmo do gate de aprovação — não há como sair;
- alvos loopback (127.0.0.1, ::1, localhost) continuam livres: são os motores
  locais (Ollama, Stable Diffusion, ComfyUI, piper) rodando na sua máquina;
- desligar exige ação consciente e fica na auditoria; ligar de volta é sempre
  permitido (o caminho mais seguro nunca é barrado).

Estado em NOMOS_HOME/localidade.json (0600). Ausência = LIGADO (fail-closed
a favor da privacidade).
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import ipaddress
import json
from pathlib import Path
from urllib.parse import urlparse

ARQUIVO = "localidade.json"
_LOOPBACK_NOMES = {"localhost", "ip6-localhost", "ip6-loopback", ""}


def _extrair_host(target: str) -> str:
    """Extrai o host de 'host', 'host:porta' ou 'http://host:porta/...'."""
    t = (target or "").strip()
    if "://" in t:
        t = urlparse(t).hostname or ""
    elif t.count(":") == 1:
        t = t.rsplit(":", 1)[0]
    elif t.startswith("[") and "]" in t:      # [::1]:porta
        t = t[1:t.index("]")]
    return t.strip().lower()


def eh_loopback(target: str) -> bool:
    """True se o alvo é a própria máquina (motor local), não a internet."""
    host = _extrair_host(target)
    if host in _LOOPBACK_NOMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _caminho(home: Path) -> Path:
    return Path(home) / ARQUIVO


def esta_ligado(home: Path) -> bool:
    """Modo só-local ligado? Padrão e falha => True (privacidade primeiro)."""
    p = _caminho(home)
    if not p.exists():
        return True
    try:
        return bool(json.loads(p.read_text()).get("local_only", True))
    except Exception:
        return True


def definir(home: Path, ligado: bool) -> bool:
    p = _caminho(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"local_only": bool(ligado)}, indent=2))
    chmod_privado(tmp, 0o600)
    tmp.replace(p)
    chmod_privado(p, 0o600)
    return ligado


def bloqueia_egress(home: Path, target: str) -> bool:
    """True se este egress deve ser NEGADO por causa do modo só-local."""
    return esta_ligado(home) and not eh_loopback(target)
