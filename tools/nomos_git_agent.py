#!/usr/bin/env python3
"""
NOMOS Git Agent — validação de working tree + sugestão de commit (MC29)

Modos:
- --check            Saúde do git: branch, HEAD, sujeira, untracked, ruído.
                     Exit 0 se é repo git legível; 1 caso contrário.
- --check --json     Relatório JSON determinístico (gate CI read-only).
- --suggest          Sugere mensagem de commit (conventional-commit) a partir
                     do estado real. NÃO commita — proposta apenas.
- --handoff DIR      Gera pacote de evidências do estado git em DIR (usa
                     nomos.kernel.evidencia; única escrita do agente, explícita).
- --version          Imprime a versão do agente.

Contrato de segurança (verificado por testes):
- git é invocado SOMENTE via allowlist de subcomandos de LEITURA
  (`_GIT_LEITURA`); qualquer outro verbo é recusado fail-closed.
- Não existe flag --push/--commit/--apply: o agente é incapaz de mutar o repo
  ou a rede. Push é decisão humana, sempre.
- `--handoff` é a única escrita (pacote de evidências em diretório indicado
  explicitamente pelo humano), nunca dentro de .git.

Versão do agente: MC29.0
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

AGENT_VERSION = "MC29.0"

# Allowlist fail-closed: somente leitura. Nada aqui muta repo, index ou rede.
_GIT_LEITURA = frozenset({
    "status", "rev-parse", "log", "diff", "ls-files", "branch", "remote",
})

# Ruído típico de working tree (não deveria ser commitado)
_PADROES_RUIDO = (
    ".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".coverage", ".egg-info", "index.lock",
)

_TIPO_POR_PASTA = (
    ("tests/", "test"), ("docs/", "docs"), ("site/", "feat"),
    ("tools/", "feat"), ("src/", "feat"), (".github/", "ci"),
)


def _git_ro(repo: Path, *args: str) -> tuple[int, str]:
    """Executa git SOMENTE com verbo da allowlist de leitura (fail-closed)."""
    if not args or args[0] not in _GIT_LEITURA:
        raise PermissionError(
            f"verbo git fora da allowlist de leitura: {args[:1]}")
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )
    return proc.returncode, proc.stdout


def coletar_estado(repo: Path) -> dict:
    """Estado read-only do repositório (determinístico nos campos)."""
    rc, _ = _git_ro(repo, "rev-parse", "--git-dir")
    if rc != 0:
        return {"is_repo": False}
    _, branch = _git_ro(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _, head = _git_ro(repo, "rev-parse", "--short", "HEAD")
    _, status = _git_ro(repo, "status", "--short")
    modificados, untracked = [], []
    for linha in status.splitlines():
        if not linha.strip():
            continue
        caminho = linha[3:].strip()
        (untracked if linha.startswith("??") else modificados).append(caminho)
    ruido = sorted({c for c in modificados + untracked
                    if any(p in c for p in _PADROES_RUIDO)})
    return {
        "is_repo": True,
        "branch": branch.strip(),
        "head": head.strip(),
        "clean": not (modificados or untracked),
        "modificados": sorted(modificados),
        "untracked": sorted(untracked),
        "ruido": ruido,
    }


def sugerir_mensagem(repo: Path, estado: dict) -> dict:
    """Proposta de mensagem de commit a partir do estado real. Nunca commita."""
    arquivos = estado.get("modificados", []) + estado.get("untracked", [])
    if not arquivos:
        return {"has_suggestion": False,
                "motivo": "working tree limpa — nada a commitar"}
    tipo = "chore"
    for prefixo, t in _TIPO_POR_PASTA:
        if any(a.startswith(prefixo) for a in arquivos):
            tipo = t
            break
    if any(a.startswith("src/") for a in arquivos):
        tipo = "feat"
    escopos = sorted({Path(a).parts[0] for a in arquivos})[:3]
    escopo = ",".join(e.rstrip("/") for e in escopos) or "repo"
    _, diffstat = _git_ro(repo, "diff", "--stat")
    resumo_stat = diffstat.strip().splitlines()[-1].strip() if diffstat.strip() else ""
    titulo = f"{tipo}({escopo}): descrever a mudança em uma linha imperativa"
    corpo = [f"- arquivos tocados ({len(arquivos)}): "
             + ", ".join(arquivos[:8]) + ("…" if len(arquivos) > 8 else "")]
    if resumo_stat:
        corpo.append(f"- diffstat: {resumo_stat}")
    if estado.get("ruido"):
        corpo.append(f"- ATENÇÃO: ruído detectado (não commitar): {estado['ruido']}")
    return {"has_suggestion": True, "titulo": titulo, "corpo": corpo,
            "arquivos": arquivos}


def relatorio(repo: Path) -> dict:
    estado = coletar_estado(repo)
    return {
        "agent_version": AGENT_VERSION,
        "mode": "check",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **estado,
        "read_only": True,
        "mutations_enabled": False,
        "auto_push_enabled": False,
        "human_approval_required": True,
    }


def _handoff(repo: Path, destino: Path) -> int:
    """Única escrita do agente: pacote de evidências do estado git (explícito)."""
    try:
        from nomos.kernel import evidencia as ev
    except ImportError:
        print("nomos não instalado neste Python — instale com `pip install -e .` "
              "para gerar handoff.", file=sys.stderr)
        return 1
    estado = coletar_estado(repo)
    if not estado["is_repo"]:
        print("não é um repositório git.", file=sys.stderr)
        return 1
    _, logs = _git_ro(repo, "log", "--oneline", "-10")
    comandos = [
        {"comando": "git status --short", "retorno": 0,
         "resultado": f"{len(estado['modificados'])} modificados, "
                      f"{len(estado['untracked'])} untracked"},
        {"comando": "git log --oneline -10", "retorno": 0,
         "resultado": logs.strip().replace("\n", " | ")[:400]},
    ]
    pacote = ev.gerar_pacote(
        Path(destino), f"handoff-git-{estado['branch']}",
        status="CLEAN" if estado["clean"] else "DIRTY",
        comandos=comandos,
        notas=f"branch={estado['branch']} head={estado['head']} "
              f"ruido={estado['ruido'] or 'nenhum'}")
    ok, problemas = ev.verificar_pacote(pacote)
    print(f"handoff criado: {pacote}")
    print("verificação: " + ("OK ✓" if ok else f"FALHOU: {problemas}"))
    return 0 if ok else 1


def print_check_humano(rel: dict) -> None:
    print(f"NOMOS Git Agent {AGENT_VERSION} — --check\n")
    if not rel["is_repo"]:
        print("✗ não é um repositório git")
        return
    print(f"  branch: {rel['branch']}   HEAD: {rel['head']}")
    print(f"  working tree: {'limpa ✓' if rel['clean'] else 'SUJA'}")
    if rel["modificados"]:
        print(f"  modificados ({len(rel['modificados'])}): "
              + ", ".join(rel["modificados"][:6])
              + ("…" if len(rel["modificados"]) > 6 else ""))
    if rel["untracked"]:
        print(f"  untracked ({len(rel['untracked'])}): "
              + ", ".join(rel["untracked"][:6])
              + ("…" if len(rel["untracked"]) > 6 else ""))
    if rel["ruido"]:
        print(f"  ⚠ ruído (não commitar): {', '.join(rel['ruido'])}")
    print("\n  push automático: DESABILITADO — push é sempre decisão humana.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="nomos_git_agent",
        description="Agente git seguro do NOMOS: leitura, diagnóstico e "
                    "sugestão. Incapaz de commit/push.")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--suggest", action="store_true")
    parser.add_argument("--handoff", metavar="DIR")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--repo", default=None,
                        help="raiz do repo (default: raiz deste projeto)")
    args = parser.parse_args(argv)

    if args.version:
        print(AGENT_VERSION)
        return 0

    repo = Path(args.repo) if args.repo else Path(__file__).resolve().parent.parent

    if args.suggest:
        estado = coletar_estado(repo)
        if not estado["is_repo"]:
            print("não é um repositório git.", file=sys.stderr)
            return 1
        sug = sugerir_mensagem(repo, estado)
        if args.json:
            print(json.dumps({"agent_version": AGENT_VERSION, "mode": "suggest",
                              "proposal_only": True, "mutations_enabled": False,
                              **sug}, ensure_ascii=False, indent=2))
            return 0
        print(f"NOMOS Git Agent {AGENT_VERSION} — --suggest (proposta apenas)\n")
        if not sug["has_suggestion"]:
            print(sug["motivo"])
            return 0
        print("mensagem sugerida:\n")
        print(f"  {sug['titulo']}\n")
        for linha in sug["corpo"]:
            print(f"  {linha}")
        print("\ncommit e push são SEMPRE ações humanas — revise e execute você.")
        return 0

    if args.handoff:
        return _handoff(repo, Path(args.handoff))

    # padrão: --check
    rel = relatorio(repo)
    if args.json:
        print(json.dumps(rel, ensure_ascii=False, indent=2))
    else:
        print_check_humano(rel)
    return 0 if rel["is_repo"] else 1


if __name__ == "__main__":
    sys.exit(main())
