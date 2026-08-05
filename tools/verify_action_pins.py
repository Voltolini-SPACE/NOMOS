#!/usr/bin/env python3
"""Verifica pins de GitHub Actions: comentário `# vX.Y.Z` vs SHA remoto.

Uso
---
    python tools/verify_action_pins.py [--offline]

Comportamento
-------------
- Escaneia `.github/workflows/*.yml` e `.github/dependabot.yml` (se existir).
- Para cada `uses: owner/repo@<SHA> # vX.Y.Z`:
    1. Ignora se não tiver comentário de versão (registra WARN).
    2. Ignora se o pin não parecer SHA de 40 hex (registra WARN
       "mutable ref" — não deveria acontecer depois de H4.9).
    3. Consulta `git ls-remote https://github.com/owner/repo.git
       refs/tags/vX.Y.Z` e resolve o commit peeled (^{}) quando aplicável.
    4. Compara com o SHA pinado. Match → OK; mismatch → FAIL.
- Se o GitHub estiver indisponível (network erro, timeout), o script sai
  com código 0 (informativo) e um WARN por linha não resolvida — NÃO
  bloqueia builds. Use `--strict` para converter WARN em FAIL.
- `--offline` pula toda a checagem remota; útil em CI onde só se quer
  auditar formato dos pins.

Códigos de saída
----------------
- 0: tudo bate ou apenas WARNs (modo padrão).
- 1: pelo menos um FAIL de mismatch (o SHA pinado não é o SHA do
     release da tag comentada).
- 2: `--strict` transformou WARNs em FAIL.

Este script é DELIBERADAMENTE stdlib-only: não pode virar mais um vetor
de supply-chain (curl/requests/…). Usa `subprocess` sobre `git ls-remote`,
que é a mesma ferramenta que o próprio workflow usaria para descobrir
qualquer SHA público.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO / ".github" / "workflows"
DEPENDABOT = REPO / ".github" / "dependabot.yml"

# uses: owner/repo@<REF> [# vX.Y.Z]  (aceita `-` uses: e     uses:)
_RE_USES = re.compile(
    r"""^\s*(?:-\s*)?uses:\s*
        (?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)
        @(?P<ref>[^\s#]+)
        (?:\s*\#\s*(?P<comment>v[\w.\-+]+))?
        \s*$""",
    re.VERBOSE,
)

_RE_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class Finding:
    __slots__ = ("level", "file", "line", "owner", "repo", "ref", "comment", "detail")

    def __init__(
        self,
        level: str,
        file: str,
        line: int,
        owner: str,
        repo: str,
        ref: str,
        comment: str | None,
        detail: str,
    ) -> None:
        self.level = level
        self.file = file
        self.line = line
        self.owner = owner
        self.repo = repo
        self.ref = ref
        self.comment = comment
        self.detail = detail

    def __str__(self) -> str:
        cm = f" # {self.comment}" if self.comment else ""
        return (
            f"[{self.level}] {self.file}:{self.line}  "
            f"{self.owner}/{self.repo}@{self.ref[:12]}{cm}  — {self.detail}"
        )


def _collect_uses() -> list[tuple[str, int, re.Match[str]]]:
    files: list[Path] = []
    if WORKFLOWS_DIR.is_dir():
        files.extend(sorted(WORKFLOWS_DIR.glob("*.yml")))
        files.extend(sorted(WORKFLOWS_DIR.glob("*.yaml")))
    if DEPENDABOT.is_file():
        files.append(DEPENDABOT)
    hits: list[tuple[str, int, re.Match[str]]] = []
    for f in files:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = _RE_USES.match(line)
            if m:
                hits.append((str(f.relative_to(REPO)), i, m))
    return hits


def _resolve_remote(owner: str, repo: str, tag: str) -> tuple[str | None, str]:
    """Retorna (SHA_esperado, motivo). SHA=None ⇒ falha de resolução."""
    url = f"https://github.com/{owner}/{repo}.git"
    try:
        proc = subprocess.run(
            ["git", "ls-remote", url, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return None, f"network/tool error: {e}"
    if proc.returncode != 0:
        return None, f"git ls-remote returned {proc.returncode}: {proc.stderr.strip()}"
    peeled = None
    tag_obj = None
    for line in proc.stdout.splitlines():
        sha, ref = (line.split("\t", 1) + [""])[:2]
        if ref == f"refs/tags/{tag}^{{}}":
            peeled = sha.strip()
        elif ref == f"refs/tags/{tag}":
            tag_obj = sha.strip()
    commit = peeled or tag_obj
    if commit is None:
        return None, f"tag {tag} not found in remote"
    return commit, ("annotated (peeled)" if peeled else "lightweight tag")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="pula resolução remota; audita só o formato dos pins")
    ap.add_argument("--strict", action="store_true",
                    help="WARNs viram FAILs")
    args = ap.parse_args()

    findings: list[Finding] = []
    uses = _collect_uses()
    for fpath, ln, m in uses:
        owner, repo, ref, comment = (
            m.group("owner"),
            m.group("repo"),
            m.group("ref"),
            m.group("comment"),
        )
        # 1) Formato do pin
        if not _RE_SHA40.match(ref):
            findings.append(Finding(
                "WARN", fpath, ln, owner, repo, ref, comment,
                "mutable ref (not a 40-hex SHA)",
            ))
            continue
        # 2) Comentário de versão
        if not comment:
            findings.append(Finding(
                "WARN", fpath, ln, owner, repo, ref, comment,
                "pin sem comentário `# vX.Y.Z` — Dependabot pode não bumpear",
            ))
        # 3) Resolução remota
        if args.offline:
            continue
        if not comment:
            continue  # sem comentário, não há alvo para comparar
        expected, detail = _resolve_remote(owner, repo, comment)
        if expected is None:
            findings.append(Finding(
                "WARN", fpath, ln, owner, repo, ref, comment,
                f"resolução remota falhou ({detail}); informativo",
            ))
        elif expected != ref:
            findings.append(Finding(
                "FAIL", fpath, ln, owner, repo, ref, comment,
                f"pin diverge do release remoto: esperado {expected[:12]} "
                f"(tag {comment}, {detail})",
            ))

    fail = sum(1 for f in findings if f.level == "FAIL")
    warn = sum(1 for f in findings if f.level == "WARN")
    total = len(uses)
    for f in findings:
        print(str(f))
    print(f"\nSummary: total_uses={total}  fail={fail}  warn={warn}")
    if fail > 0:
        return 1
    if args.strict and warn > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
