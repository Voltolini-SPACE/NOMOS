"""NOMOS ext.skill_catalogo — catálogo de capacidades (MC29).

Responde, com dados e sem jargão, a pergunta "o que o NOMOS sabe fazer?":
cada skill instalada ou disponível vira uma entrada com os 8 campos do
contrato — nome, descrição, entrada, saída, risco, status, permissões e
exemplos. Somente leitura: este módulo nunca instala, executa ou aprova nada
(instalação/execução continuam no gate de sempre).
"""
from __future__ import annotations

import json
from pathlib import Path

from nomos.ext import skill_registry as reg

CONTRATO_CATALOGO = 1

CAMPOS = ("nome", "descricao", "entrada", "saida", "risco",
          "status", "permissoes", "exemplos")


def _entrada_de(mf: dict) -> str:
    modalidades = mf.get("modalities") or ["texto"]
    return ", ".join(str(m) for m in modalidades)


def _saida_de(mf: dict) -> str:
    return str(mf.get("output") or "resultado local da skill (stdout)")


def _capacidade(mf: dict, status: str) -> dict:
    permissoes = list(mf.get("permissions") or [])
    return {
        "nome": str(mf.get("name", "?")),
        "descricao": str(mf.get("description", "")),
        "entrada": _entrada_de(mf),
        "saida": _saida_de(mf),
        "risco": str(mf.get("risk_level") or reg.risco_de(permissoes)),
        "status": status,
        "permissoes": permissoes,
        "exemplos": [str(k) for k in (mf.get("keywords") or [])][:5],
    }


def _manifestos_instalados(skills_dir: Path) -> list[dict]:
    out: list[dict] = []
    if not skills_dir.exists():
        return out
    for child in sorted(skills_dir.iterdir()):
        mf_path = child / "skill.json"
        if not mf_path.is_file():
            continue
        try:
            out.append(json.loads(mf_path.read_text(encoding="utf-8")))
        except Exception:
            continue  # manifesto ilegível não derruba o catálogo (só some dele)
    return out


def _manifestos_do_pacote() -> list[dict]:
    """As skills que VIAJARAM com o produto — sem depender de registro.

    Antes, uma instalação nova mostrava "nenhuma skill disponível ainda" mesmo
    tendo 33 skills dentro do próprio wheel: elas só apareciam depois de alguém
    rodar `nomos skills catalogo --semear`. Exigir um comando para ENXERGAR o
    que já veio na caixa é o oposto de plug-and-play.

    Isto é DESCOBERTA, não autorização — a mesma fronteira que
    `relay.descobrir_rotas` respeita: aparecer na lista não instala nada e não
    aprova nada. Instalar continua exigindo confirmação de experimental e o
    gate A5.
    """
    import json as _json

    out: list[dict] = []
    try:
        from nomos import skills_embutidas as emb
        origens = emb.origens()
    except Exception:
        return out
    for base in origens:
        for mf_path in sorted(Path(base).glob("*/skill.json")):
            try:
                out.append(_json.loads(mf_path.read_text(encoding="utf-8")))
            except Exception:
                continue   # manifesto ilegível some da lista, não derruba ela
    return out


def capacidades(home: Path, skills_dir: Path, *,
                incluir_do_pacote: bool = False) -> list[dict]:
    """Catálogo unificado: instaladas primeiro; disponíveis sem duplicar nome.

    `incluir_do_pacote` acrescenta as skills que vieram no wheel, mesmo sem
    registro. É OPT-IN de propósito: duas suítes afirmam que uma home vazia
    devolve lista vazia, e mudar isso por baixo quebraria a expectativa de quem
    escreveu esses testes. Quem quer a visão completa pede.
    """
    itens: list[dict] = []
    vistos: set[str] = set()
    for mf in _manifestos_instalados(skills_dir):
        cap = _capacidade(mf, "instalada")
        itens.append(cap)
        vistos.add(cap["nome"])
    for mf in reg.catalogo(home):
        nome = str(mf.get("name", "?"))
        if nome in vistos:
            continue
        itens.append(_capacidade(mf, "disponível no catálogo"))
        vistos.add(nome)
    if incluir_do_pacote:
        for mf in _manifestos_do_pacote():
            nome = str(mf.get("name", "?"))
            if nome in vistos:
                continue
            itens.append(_capacidade(mf, "vem no NOMOS"))
            vistos.add(nome)
    itens.sort(key=lambda c: (c["status"] != "instalada", c["nome"]))
    return itens
