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


def _raiz_exemplos(raiz: Path | None = None) -> Path | None:
    """Onde vivem os conectores de exemplo (examples/mcp).

    Procura a partir do diretório de trabalho (o repositório/sdist) — no
    wheel instalado o pacote NÃO carrega ``examples/``, então aqui é
    honesto retornar None em vez de apontar para dentro do site-packages.
    """
    if raiz is not None:
        # raiz explícita é soberana: sem fallback (o chamador sabe onde é)
        r = Path(raiz)
        return r if r.is_dir() else None
    candidatos = [
        Path.cwd() / "examples" / "mcp",
        # raiz do projeto relativa a este arquivo (repo/sdist)
        Path(__file__).resolve().parents[3] / "examples" / "mcp",
    ]
    for c in candidatos:
        if c.is_dir():
            return c
    return None


def conectores_exemplo(home: Path, raiz: Path | None = None) -> list[dict]:
    """Os conectores MCP que acompanham o NOMOS, com o estado de confiança.

    Cada item: nome, status ('confiavel'|'experimental'|'revogado'),
    descricao, e o caminho do manifesto para ligar. Manifesto inválido é
    ignorado (fail-closed) — nunca derruba quem chama. Sem a pasta de
    exemplos (ex.: wheel instalado), devolve lista vazia.
    """
    from nomos.interface import mcp_client as mc
    base = _raiz_exemplos(raiz)
    if base is None:
        return []
    itens = []
    for mf in sorted(base.glob("*/manifesto.json")):
        try:
            manifesto = mc.carregar_manifesto(mf)
        except Exception:
            continue                       # manifesto torto: fora, fail-closed
        try:
            bruto = json.loads(mf.read_text(encoding="utf-8"))
            descricao = str(bruto.get("descricao", ""))
        except Exception:
            descricao = ""
        # caminho relativo ao cwd quando possível (o que o usuário digita).
        # SEMPRE com barra normal — o mesmo comando funciona em Win/Mac/Linux
        # e bate com a doc; str(Path) no Windows sairia com "\".
        try:
            rel = mf.relative_to(Path.cwd())
        except ValueError:
            rel = mf
        itens.append({"nome": manifesto["nome"],
                      "status": status(home, manifesto),
                      "nivel_padrao": manifesto["nivel_padrao"],
                      "descricao": descricao,
                      "manifesto": rel.as_posix()})
    return itens


def diagnostico_conectores(home: Path, raiz: Path | None = None) -> dict:
    """Check-up SÓ-LEITURA dos conectores de exemplo (MC48).

    Para cada conector: estado de confiança, se o interpretador do ``comando``
    existe, e se as credenciais que o manifesto declara (campo opcional ``env``)
    estão PRESENTES no ambiente — apenas a presença (bool), **nunca o valor**.
    Não executa o conector, não toca rede, não grava nada.
    """
    import os
    import shutil

    from nomos.interface import mcp_client as mc
    base = _raiz_exemplos(raiz)
    itens: list[dict] = []
    if base is not None:
        for mf in sorted(base.glob("*/manifesto.json")):
            try:
                manifesto = mc.carregar_manifesto(mf)
            except Exception:
                continue                       # manifesto torto: fora, fail-closed
            try:
                bruto = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                bruto = {}
            envs = [e for e in (bruto.get("env") or []) if isinstance(e, str)]
            # SÓ presença — o valor jamais é lido, guardado ou devolvido
            faltando = [e for e in envs if not os.environ.get(e)]
            comando = manifesto["comando"]
            interp = comando[0] if comando else ""
            itens.append({
                "nome": manifesto["nome"],
                "nivel_padrao": manifesto["nivel_padrao"],
                "status": status(home, manifesto),
                "env": envs,
                "env_faltando": faltando,
                "credenciais_ok": not faltando,
                "interpretador": interp,
                "interpretador_ok": bool(shutil.which(interp)) if interp else False,
            })
    snap = listar(home)
    return {"raiz": str(base) if base is not None else None,
            "conectores": itens,
            "confiaveis": len(snap["confiaveis"]),
            "revogados": snap["revogadas"]}
