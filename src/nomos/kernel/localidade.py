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
_LOOPBACK_NOMES = {"localhost", "ip6-localhost", "ip6-loopback"}


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


PORTAS_DE_RELAY = frozenset({20128})
"""Portas de loopback que NÃO são motor local: elas ROTEIAM para a internet.

A isenção de loopback (ver o cabeçalho deste módulo) assume que todo serviço
em 127.0.0.1 é TERMINAL — Ollama, Stable Diffusion, ComfyUI, piper executam na
máquina e param ali. Um roteador de LLM instalado em loopback quebra essa
premissa: falar com ele é falar com a internet, com um salto de disfarce no
meio. Sem esta lista, `bloqueia_egress` deixaria passar e a decisão cairia em
REQUIRE_APPROVAL — e o operador leria "127.0.0.1:20128" no prompt, que parece
um motor local.

20128 = OmniRoute (instalado em 23/08/2026).

LIMITE DECLARADO, não escondido: isto fecha o relay DECLARADO. Um proxy em
porta não listada continua invisível para o cadeado, porque o modelo de egresso
é de UM SALTO e sintático — classifica a string do primeiro destino, não o
destino final. Fechar a classe inteira exigiria inverter o default (loopback
isento só por allowlist de portas de motor local), o que quebra testes e portas
customizadas: é decisão do dono, registrada como fase 2.
"""


def _extrair_porta(target: str) -> int | None:
    """Porta de 'host:porta', 'http://host:porta/...' ou '[::1]:porta'."""
    t = (target or "").strip()
    try:
        if "://" in t:
            return urlparse(t).port
        if t.startswith("[") and "]:" in t:
            return int(t.rsplit("]:", 1)[1].split("/")[0])
        if t.count(":") == 1:
            return int(t.rsplit(":", 1)[1].split("/")[0])
    except (ValueError, TypeError):
        return None
    return None


def eh_relay_declarado(target: str) -> bool:
    """True se o alvo é loopback MAS roteia para fora (ver PORTAS_DE_RELAY)."""
    porta = _extrair_porta(target)
    return porta in PORTAS_DE_RELAY if porta is not None else False


def eh_loopback(target: str) -> bool:
    """True se o alvo é a própria máquina (motor local), não a internet."""
    host = _extrair_host(target)
    if not host:
        # alvo vazio/não-parseável NÃO é "seguro": trata como remoto, para
        # o cadeado bloquear (fail-closed) em vez de liberar por engano
        return False
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
    """True se este egress deve ser NEGADO por causa do modo só-local.

    Relay declarado em loopback é tratado como REMOTO: falar com ele é falar
    com a internet. Ver `PORTAS_DE_RELAY`.
    """
    if not esta_ligado(home):
        return False
    if eh_relay_declarado(target):
        return True
    return not eh_loopback(target)
