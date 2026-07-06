"""NOMOS interface.mcp_catalogo — catálogo + confiança de servers MCP (MC32/M2).

Servers MCP (ao contrário de skills) não vêm assinados pelos autores. Então a
confiança aqui é por **registro explícito**: você inspeciona um manifesto, e ao
`confiar` dele o NOMOS grava a **impressão digital** (SHA-256 do manifesto
canônico) num catálogo local (0600). Conectar depois:

- manifesto cuja impressão está registrada **e não revogada** ⇒ **confiável**;
- manifesto alterado (impressão diferente) ⇒ volta a **experimental**;
- manifesto revogado ⇒ **bloqueado** mesmo que idêntico.

Isto NÃO é assinatura criptográfica de autor (nenhum server MCP oferece isso
hoje) — é confiança-por-registro auditável, honesta sobre o que garante:
"este é exatamente o manifesto que EU aprovei, e ninguém o trocou".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

ARQUIVO = "mcp_catalogo.json"


class CatalogoErro(Exception):
    pass


def impressao(manifesto: dict) -> str:
    """SHA-256 do manifesto canônico (ordem estável, sem espaços supérfluos)."""
    canon = json.dumps(manifesto, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canon).hexdigest()


def _caminho(home: Path) -> Path:
    return Path(home) / ARQUIVO


def _ler(home: Path) -> dict:
    p = _caminho(home)
    if not p.exists():
        return {"confiaveis": {}, "revogadas": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raise CatalogoErro("catálogo MCP corrompido — recusa fail-closed") from None
    if not (isinstance(d.get("confiaveis"), dict)
            and isinstance(d.get("revogadas"), list)):
        raise CatalogoErro("catálogo MCP corrompido — recusa fail-closed")
    return d


def _gravar(home: Path, d: dict) -> None:
    p = _caminho(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    chmod_privado(tmp, 0o600)
    tmp.replace(p)
    chmod_privado(p, 0o600)


def confiar(home: Path, manifesto: dict) -> str:
    """Registra a impressão do manifesto como confiável. Devolve a impressão."""
    fp = impressao(manifesto)
    d = _ler(home)
    if fp in d["revogadas"]:
        raise CatalogoErro("este manifesto foi REVOGADO — não confio de novo "
                           "sem você tirar da lista de revogações à mão")
    d["confiaveis"][fp] = {"nome": manifesto.get("nome", "?"),
                           "comando": manifesto.get("comando", [])}
    _gravar(home, d)
    return fp


def revogar(home: Path, manifesto: dict) -> bool:
    """Remove a confiança e marca a impressão como revogada (bloqueio duro)."""
    fp = impressao(manifesto)
    d = _ler(home)
    tinha = d["confiaveis"].pop(fp, None) is not None
    if fp not in d["revogadas"]:
        d["revogadas"].append(fp)
    _gravar(home, d)
    return tinha


def status(home: Path, manifesto: dict) -> str:
    """'confiavel' | 'revogado' | 'experimental' para o manifesto dado."""
    fp = impressao(manifesto)
    d = _ler(home)
    if fp in d["revogadas"]:
        return "revogado"
    if fp in d["confiaveis"]:
        return "confiavel"
    return "experimental"


def listar(home: Path) -> dict:
    """Snapshot do catálogo (confiáveis com nome/comando + nº de revogadas)."""
    d = _ler(home)
    return {"confiaveis": [{"impressao": fp[:16] + "…", **info}
                           for fp, info in d["confiaveis"].items()],
            "revogadas": len(d["revogadas"])}
