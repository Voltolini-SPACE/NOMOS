#!/usr/bin/env python3
"""NOMOS — propagação de capacidades a partir de uma FONTE ÚNICA.

Fluxo: você adiciona uma capacidade em ``docs/CAPACIDADES.json`` e roda
``python tools/propagar.py --apply``. O bloco entre marcadores
``<!-- NOMOS:CAPS:START -->…<!-- NOMOS:CAPS:END -->`` é regenerado no README e no
site — em todos os lugares de uma vez. O painel reflete o código sozinho.

Garantia (lei da casa): ``--check`` falha se algo ficou dessincronizado, e o
teste ``tests/test_propagar.py`` roda esse check na suíte — então a **CI quebra**
se você esquecer de propagar. Nada de marketing derivando do produto em silêncio.

Governança: NADA é commitado/enviado sozinho. ``--commit`` (opt-in, você roda)
faz apenas um commit LOCAL dos arquivos gerados; o push continua sendo seu.

Uso:
    python tools/propagar.py --check      # gate: 0 se em dia, 1 se dessincronizado
    python tools/propagar.py --apply      # regenera README + site a partir do JSON
    python tools/propagar.py --report     # tabela do que existe e onde
    python tools/propagar.py --apply --commit   # + commit LOCAL (sem push)
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "docs" / "CAPACIDADES.json"
README = RAIZ / "README.md"
SITE = RAIZ / "site" / "index.html"

START = "<!-- NOMOS:CAPS:START -->"
END = "<!-- NOMOS:CAPS:END -->"
ALVOS = ("README.md", "site/index.html")


def carregar() -> list[dict]:
    dados = json.loads(REGISTRO.read_text(encoding="utf-8"))
    caps = dados.get("capacidades", [])
    if not caps:
        raise SystemExit("registro vazio: docs/CAPACIDADES.json")
    return caps


def render_site(caps: list[dict]) -> str:
    e = html.escape
    linhas = []
    for c in caps:
        cmd = (f' <span class="k">{e(c["comando"])}</span>'
               if c.get("comando") else "")
        linhas.append(f'              <li><b>{e(c["nome"])}</b> — {e(c["resumo"])}{cmd}</li>')
    itens = "\n".join(linhas)
    return (
        "\n            <details class=\"grupo\"><summary class=\"grupo-recursos\">"
        f"<span aria-hidden=\"true\">🗂️</span> Índice de capacidades "
        f"(gerado automaticamente — {len(caps)} itens)</summary>\n"
        "            <ul class=\"caps-index\">\n"
        f"{itens}\n"
        "            </ul>\n            </details>\n            "
    )


def render_readme(caps: list[dict]) -> str:
    linhas = ["", "", "| Capacidade | O que faz | Como |", "|---|---|---|"]
    for c in caps:
        como = f"`{c['comando']}`" if c.get("comando") else "—"
        linhas.append(f"| {c['nome']} | {c['resumo']} | {como} |")
    linhas.append("")
    return "\n".join(linhas)


def _entre(texto: str) -> str | None:
    m = re.search(re.escape(START) + r"(.*?)" + re.escape(END), texto, re.S)
    return m.group(1) if m else None


def _substituir(texto: str, novo: str) -> str:
    m = re.search(re.escape(START) + r"(.*?)" + re.escape(END), texto, re.S)
    return texto[: m.start(1)] + novo + texto[m.end(1):]


def _pares(caps: list[dict]):
    return ((README, render_readme(caps)), (SITE, render_site(caps)))


def check(caps: list[dict]) -> list[str]:
    """Lista de problemas (vazia = tudo sincronizado)."""
    probs = []
    for path, esperado in _pares(caps):
        atual = _entre(path.read_text(encoding="utf-8"))
        if atual is None:
            probs.append(f"{path.name}: marcadores NOMOS:CAPS ausentes")
        elif atual != esperado:
            probs.append(f"{path.name}: bloco de capacidades desatualizado "
                         f"(rode: python tools/propagar.py --apply)")
    return probs


def apply(caps: list[dict]) -> list[str]:
    mudados = []
    for path, esperado in _pares(caps):
        texto = path.read_text(encoding="utf-8")
        if _entre(texto) is None:
            raise SystemExit(f"{path.name}: adicione os marcadores "
                             f"{START} … {END} antes de propagar")
        novo = _substituir(texto, esperado)
        if novo != texto:
            path.write_text(novo, encoding="utf-8")
            mudados.append(path.name)
    return mudados


def _commit_local(mudados: list[str]) -> None:
    # opt-in; SÓ commit local (nunca push). Import local: git só existe aqui.
    import subprocess  # noqa: S404 - ferramenta de dev, fora do runtime local-first
    if not mudados:
        print("nada mudou — sem commit")
        return
    subprocess.run(["git", "add", *ALVOS], cwd=RAIZ, check=True)
    subprocess.run(["git", "commit", "-m",
                    "chore(propagar): capacidades sincronizadas (README + site)"],
                   cwd=RAIZ, check=True)
    print("commit LOCAL feito · o push continua seu: git push origin main")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="propagar", description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="gate: falha se dessincronizado")
    g.add_argument("--apply", action="store_true", help="regenera README + site")
    g.add_argument("--report", action="store_true", help="tabela do registro")
    p.add_argument("--commit", action="store_true", help="(com --apply) commit LOCAL, sem push")
    args = p.parse_args(argv)
    caps = carregar()

    if args.report:
        print(f"NOMOS — {len(caps)} capacidades no registro:")
        for c in caps:
            print(f"  · {c['nome']:38} [{c.get('area','')}] "
                  f"{c.get('comando','') or ''}")
        return 0

    if args.check:
        probs = check(caps)
        if probs:
            print("DESSINCRONIZADO:")
            for x in probs:
                print(f"  ✗ {x}")
            return 1
        print(f"OK — capacidades sincronizadas em {', '.join(ALVOS)} ({len(caps)} itens)")
        return 0

    # --apply
    mudados = apply(caps)
    print("atualizado: " + (", ".join(mudados) if mudados else "nada (já em dia)"))
    if args.commit:
        _commit_local(mudados)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
