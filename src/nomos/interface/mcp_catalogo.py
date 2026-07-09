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
    """Onde vivem os conectores de exemplo.

    Ordem: (1) ``examples/mcp`` do repositório/sdist (o caminho documentado no
    site/docs); (2) a cópia EMPACOTADA em ``nomos/conectores/mcp`` — que vai no
    wheel, então ``nomos mcp exemplos``/``doutor`` funcionam também para quem
    instala por pip. As duas cópias são idênticas (garantido por teste).
    """
    if raiz is not None:
        # raiz explícita é soberana: sem fallback (o chamador sabe onde é)
        r = Path(raiz)
        return r if r.is_dir() else None
    candidatos = [
        Path.cwd() / "examples" / "mcp",
        # raiz do projeto relativa a este arquivo (repo/sdist)
        Path(__file__).resolve().parents[3] / "examples" / "mcp",
        # cópia empacotada, ao lado deste pacote (repo -e . e wheel instalado)
        Path(__file__).resolve().parent.parent / "conectores" / "mcp",
    ]
    for c in candidatos:
        if c.is_dir():
            return c
    return None


def nivel_exibicao(manifesto: dict) -> str:
    """O nível que representa HONESTAMENTE o que o conector faz: o **maior risco**
    entre as tools DECLARADAS (A0<A1<…<A6). Sem tools declaradas, cai no
    ``nivel_padrao``. Isto evita mostrar o ``nivel_padrao`` (que é a trava
    fail-closed para tools DESCONHECIDAS) como se fosse o risco real — p.ex. um
    conector que só LÊ um arquivo local tem tools A0 e deve aparecer como A0,
    mesmo que seu padrão para o desconhecido seja A5."""
    tools = manifesto.get("tools") or {}
    niveis = [str(n) for n in tools.values()
              if str(n)[:1] == "A" and str(n)[1:].isdigit()]
    if not niveis:
        return str(manifesto.get("nivel_padrao", ""))
    return max(niveis, key=lambda n: int(n[1:]))


def conectores_exemplo(home: Path, raiz: Path | None = None) -> list[dict]:
    """Os conectores MCP que acompanham o NOMOS, com o estado de confiança.

    Cada item: nome, status ('confiavel'|'experimental'|'revogado'), o nível de
    exibição (maior risco das tools declaradas), descricao, e o caminho do
    manifesto para ligar. Manifesto inválido é ignorado (fail-closed) — nunca
    derruba quem chama. Sem a pasta de exemplos (ex.: wheel instalado), devolve
    lista vazia.
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
                      "nivel": nivel_exibicao(manifesto),   # risco real das tools
                      "descricao": descricao,
                      "dir": mf.parent.name,        # nome curto p/ `confiar <nome>`
                      "manifesto": rel.as_posix()})
    return itens


def _sem_acento(s: str) -> str:
    """minúsculas + sem acento — para busca tolerante ('calendario'≈'calendário')."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(s).lower())
                   if not unicodedata.combining(c))


def buscar_conectores(home: Path, termo: str,
                      raiz: Path | None = None) -> list[dict]:
    """Descoberta curada: filtra os conectores EMBARCADOS por ``termo`` (casa em
    nome, pasta ou descrição, sem acento e sem caso). Vários termos = E (todos
    precisam bater). Só lista os oficiais; confiar segue manual (não afrouxa
    nada). Termo vazio devolve todos."""
    termos = [t for t in _sem_acento(termo).split() if t]
    itens = conectores_exemplo(home, raiz=raiz)
    if not termos:
        return itens
    achados = []
    for c in itens:
        alvo = _sem_acento(f"{c['nome']} {c.get('dir', '')} {c.get('descricao', '')}")
        if all(t in alvo for t in termos):
            achados.append(c)
    return achados


def resolver_conector(arg, raiz: Path | None = None) -> Path | None:
    """Resolve um manifesto por CAMINHO (arquivo existente) OU por NOME do
    conector (a pasta em ``examples/mcp`` ou na cópia empacotada). Assim o
    usuário instalado por pip escreve ``nomos mcp confiar telegram`` em vez do
    caminho longo do site-packages. Devolve o ``Path`` do manifesto, ou ``None``
    (o chamador decide a mensagem)."""
    p = Path(str(arg))
    if p.is_file():
        return p
    base = _raiz_exemplos(raiz)
    if base is not None:
        cand = base / str(arg) / "manifesto.json"
        if cand.is_file():
            return cand
    return None


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
                "nivel": nivel_exibicao(manifesto),   # risco real das tools
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
