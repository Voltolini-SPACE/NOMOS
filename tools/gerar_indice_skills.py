#!/usr/bin/env python3
"""Gera `src/nomos/skills_do_dono/INDICE.md` a partir do catálogo.

POR QUE ISTO EXISTE. O índice era escrito à mão e afirmava, na abertura,
"Estado medido nesta máquina — não é promessa, é medição". Medido em 23/08:
**13 linhas diziam "falta chave"** para skills às quais falta o CÓDIGO, e
`higgsfield-bootstrap` aparecia como "pronta" sem ter um `.py` sequer. Um
documento que se declara medição e descreve outra coisa é pior que um sem
declaração nenhuma — ele gasta a confiança que pede.

O catálogo (`skill_catalogo.capacidades`) já calcula o estado certo, porque
deriva de `files` do manifesto. Então o índice deixa de ser afirmação humana
e passa a ser projeção do que o produto sabe. O texto humano que VALE — os
avisos "GASTA DINHEIRO", "dado biometrico" — sobrevive, porque vem da
`description` do próprio manifesto.

Uso:
    python3 tools/gerar_indice_skills.py            # escreve o arquivo
    python3 tools/gerar_indice_skills.py --check    # só confere (CI/teste)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "src" / "nomos" / "skills_do_dono" / "INDICE.md"


def _capacidades() -> list[dict]:
    """Lê o catálogo numa HOME temporária: o índice descreve o PRODUTO, não a
    máquina de quem gera. Com a home real, uma skill instalada aqui mudaria o
    arquivo versionado — e o índice passaria a variar por máquina."""
    from nomos.ext import skill_catalogo as sc

    home = Path(tempfile.mkdtemp())
    return sc.capacidades(home, home / "skills", incluir_do_pacote=True)


def _linha(c: dict) -> str:
    def limpo(v) -> str:
        # `|` dentro de célula quebra a tabela — e há descrições com
        # "curl | sh". Escapa em vez de perder o aviso.
        return str(v or "").replace("|", "\\|").replace("\n", " ").strip()

    perms = ", ".join(c.get("permissoes") or []) or "—"
    return (f"| `{limpo(c.get('nome'))}` | {limpo(c.get('risco'))} "
            f"| {limpo(c.get('status'))} | {limpo(perms)} "
            f"| {limpo(c.get('descricao'))} |")


def render() -> str:
    caps = sorted(_capacidades(), key=lambda c: str(c.get("nome", "")))
    prontas = [c for c in caps if "prepara" not in str(c.get("status", "")).lower()]
    preparo = [c for c in caps if "prepara" in str(c.get("status", "")).lower()]
    linhas = [
        "# Skills do dono, convertidas para o NOMOS",
        "",
        "<!-- ARQUIVO GERADO. Não edite à mão:",
        "     python3 tools/gerar_indice_skills.py",
        "     O estado vem de `skill_catalogo.capacidades`, que o deriva do",
        "     manifesto. Editar aqui faz o índice divergir do produto — foi",
        "     exatamente o que aconteceu antes, com 13 linhas dizendo",
        "     'falta chave' onde faltava o código. -->",
        "",
        f"**{len(caps)} capacidades** no catálogo: **{len(prontas)}** com código "
        f"publicado e **{len(preparo)}** em preparação.",
        "",
        "Estado e risco NÃO são escritos aqui: vêm do catálogo, que os deriva",
        "do manifesto. *Em preparação* significa que o manifesto ainda não",
        "publica arquivo com checksum — sem isso não há o que verificar, e o",
        "instalador recusa. Não é falta de chave nem de conta paga.",
        "",
        "| skill | risco | estado | permissões | o que faz |",
        "|---|---|---|---|---|",
    ]
    linhas += [_linha(c) for c in caps]
    linhas += [
        "",
        "Risco é **derivado das permissões** quando o manifesto não declara",
        "`risk_level` — hoje nenhum declara. A2 (rede) e A3 (credencial)",
        "puxam para `alto`, então quase tudo que sai da máquina é alto.",
        "",
    ]
    return "\n".join(linhas)


def main(argv: list[str]) -> int:
    novo = render()
    if "--check" in argv:
        atual = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else ""
        if atual != novo:
            print("INDICE.md divergiu do catálogo. Rode: "
                  "python3 tools/gerar_indice_skills.py", file=sys.stderr)
            return 1
        print("INDICE.md em dia com o catálogo.")
        return 0
    DESTINO.write_text(novo, encoding="utf-8")
    print(f"escrito: {DESTINO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
