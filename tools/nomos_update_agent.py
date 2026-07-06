#!/usr/bin/env python3
"""
NOMOS Update Agent — Verificador de Consistência + Propositor de Diff (MC27)

Modos:
- --check         Verifica consistência (brandbook, manual, landing, links, seções,
                  secrets, git). Exit 0 se consistente, 1 se não. Ideal como gate CI.
- --check --json  Relatório JSON determinístico (para CI read-only gate).
- --diff          Propõe patches de documentação/consistência (PROPOSAL-ONLY, sem escrever).
- --diff --json   Proposta em JSON estruturado.
- --version        Imprime a versão do agente.
- --apply          BLOQUEADO (fail-closed): aplicação automática permanece desabilitada.

Garantias de segurança (verificadas por testes):
- NÃO executa processos externos (nenhuma chamada de sistema) -> incapaz de
  rodar git, publicar pacote ou fazer deploy.
- Estado do git é lido parseando .git diretamente (somente leitura).
- Nenhum modo escreve arquivos. --diff é apenas proposta.
- --apply permanece bloqueado; aplicação automática segue desabilitada.

Versão do agente: MC27.0
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Optional

AGENT_VERSION = "MC29.0"

# ANSI colors (apenas no modo humano)
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Deliverables verificados
BRANDBOOK_REL = "docs/brand/NOMOS_BRANDBOOK.md"
MANUAL_REL = "docs/installation/NOMOS_INSTALLATION_MANUAL.md"
LANDING_REL = "site/index.html"
README_REL = "README.md"
GOVERNANCE_REL = "docs/governance/NOMOS_UPDATE_AGENT.md"

# Brand/site sync (MC29): identidade congelada (docs/brand/frozen) e instalação oficial
INSTALL_MD_REL = "docs/INSTALL.md"
PYPROJECT_REL = "pyproject.toml"
INIT_REL = "src/nomos/__init__.py"
PALETA_CONGELADA = ("#5AF78E", "#0A0F0D")     # verde-neon + preto terminal (Brandbook v1.0)
TAGLINE_CANONICA = "Seu agente. Sua máquina. Suas regras."
ASSINATURA_CANONICA = "local por lei"
# `pip install nomos` puro é proibido: o nome `nomos` no PyPI é de projeto de
# terceiros. Lookahead negativo preserva formas legítimas (wheel, git+, ponto).
_PIP_NOMOS_PURO = re.compile(r"pip install nomos(?![-\w./])")

# Seções obrigatórias nos documentos
BRANDBOOK_SECOES = [
    "Essência da Marca", "Posicionamento", "Identidade Verbal",
    "Identidade Visual", "Mensagens Canônicas", "Regras de Consistência",
]
MANUAL_SECOES = [
    "Pré-requisitos", "Instalação Rápida", "Instalação para Desenvolvimento",
    "Primeira Execução Segura", "Solução de Problemas", "Desinstalação", "Segurança",
]

# Padrões de segredo de ALTO sinal (valor real de chave), montados por concatenação
# para que a string literal do gatilho não apareça no código-fonte deste arquivo.
_SECRET_REGEXES = [
    re.compile("s" + r"k-[A-Za-z0-9]{20,}"),            # OpenAI/Anthropic
    re.compile("g" + r"hp_[A-Za-z0-9]{20,}"),           # GitHub PAT
    re.compile("AK" + r"IA[0-9A-Z]{16}"),               # AWS access key id
    re.compile("xox" + r"[baprs]-[A-Za-z0-9-]{10,}"),   # Slack
    re.compile("AIz" + r"a[0-9A-Za-z_\-]{30,}"),        # Google
    re.compile("-----" + r"BEGIN [A-Z ]*PRIVATE KEY"),  # PEM
]


@dataclass
class CheckResult:
    """Resultado de uma verificação individual."""
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    """Relatório estruturado e determinístico do modo --check."""
    status: str = "ok"
    version: str = AGENT_VERSION
    checks: List[CheckResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    files_checked: List[str] = field(default_factory=list)
    git: Optional[dict] = None
    safe_mode: bool = True
    timestamp_utc: str = ""
    next_recommendation: str = ""

    def to_dict(self) -> dict:
        # Ordem de chaves fixa -> estrutura determinística.
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.ok)
        return {
            # --- campos preservados desde a MC26 ---
            "status": self.status,
            "version": self.version,
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "files_checked": list(self.files_checked),
            "git": self.git,
            "safe_mode": self.safe_mode,
            "timestamp_utc": self.timestamp_utc,
            "next_recommendation": self.next_recommendation,
            # --- campos MC27 (gate CI read-only) ---
            "agent_version": AGENT_VERSION,
            "mode": "check",
            "consistent": self.status == "ok",
            "checks_total": total,
            "checks_passed": passed,
            "checks_failed": total - passed,
            "human_approval_required": True,
            "real_execution_enabled": False,
            "auto_push_enabled": False,
            "diff_proposer_available": True,
        }


class _HrefCollector(HTMLParser):
    """Coleta hrefs de <a> para verificação de links internos."""
    def __init__(self):
        super().__init__()
        self.hrefs: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            if d.get("href"):
                self.hrefs.append(d["href"])


class NomosUpdateAgent:
    """Agente de verificação e proposta (somente leitura, fail-closed)."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.report = Report()

    # ---- utilidades ----
    def _add_check(self, name: str, ok: bool, detail: str = ""):
        self.report.checks.append(CheckResult(name=name, ok=ok, detail=detail))
        if not ok:
            self.report.errors.append(f"{name}: {detail}")

    def _read(self, rel: str) -> Optional[str]:
        p = self.repo_root / rel
        if not p.exists():
            return None
        self.report.files_checked.append(rel)
        return p.read_text(encoding="utf-8", errors="ignore")

    def _plain_read(self, rel: str) -> Optional[str]:
        """Leitura sem registrar em files_checked (para o propositor de diff)."""
        p = self.repo_root / rel
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8", errors="ignore")

    # ---- verificações (--check) ----
    def _check_existencia(self):
        for rel in (BRANDBOOK_REL, MANUAL_REL, LANDING_REL):
            p = self.repo_root / rel
            existe = p.exists() and p.stat().st_size > 0
            self._add_check(f"existe:{rel}", existe,
                            "presente" if existe else "AUSENTE ou vazio")

    def _check_secoes(self):
        brand = self._read(BRANDBOOK_REL)
        if brand is not None:
            faltando = [s for s in BRANDBOOK_SECOES if s not in brand]
            self._add_check("secoes:brandbook", not faltando,
                            "todas presentes" if not faltando else f"faltando: {faltando}")
        manual = self._read(MANUAL_REL)
        if manual is not None:
            faltando = [s for s in MANUAL_SECOES if s not in manual]
            self._add_check("secoes:manual", not faltando,
                            "todas presentes" if not faltando else f"faltando: {faltando}")

    def _check_links_landing(self):
        landing_path = self.repo_root / LANDING_REL
        if not landing_path.exists():
            self._add_check("links:landing", False, "landing ausente")
            return
        col = _HrefCollector()
        col.feed(landing_path.read_text(encoding="utf-8", errors="ignore"))
        base = landing_path.parent
        quebrados = []
        for href in col.hrefs:
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            alvo = (base / href).resolve()
            if not alvo.exists():
                quebrados.append(href)
        self._add_check("links:landing", not quebrados,
                        "todos resolvem" if not quebrados else f"quebrados: {quebrados}")

    def _check_secrets(self):
        alvos = [BRANDBOOK_REL, MANUAL_REL, LANDING_REL, README_REL,
                 "site/README.md", GOVERNANCE_REL]
        achados = []
        for rel in alvos:
            p = self.repo_root / rel
            if not p.exists():
                continue
            texto = p.read_text(encoding="utf-8", errors="ignore")
            for rgx in _SECRET_REGEXES:
                if rgx.search(texto):
                    achados.append(rel)
                    break
        self._add_check("secrets", not achados,
                        "nenhum segredo aparente" if not achados else f"suspeitos: {achados}")

    # ---- brand/site sync (MC29) ----
    def _check_brand_paleta(self):
        landing = self._read(LANDING_REL)
        if landing is None:
            self._add_check("brand:paleta", False, "landing ausente")
            return
        baixo = landing.lower()
        faltando = [hexcor for hexcor in PALETA_CONGELADA if hexcor.lower() not in baixo]
        self._add_check("brand:paleta", not faltando,
                        "paleta congelada presente" if not faltando
                        else f"cores do brandbook congelado ausentes no site: {faltando}")

    def _check_brand_tagline(self):
        problemas = []
        for rel in (README_REL, LANDING_REL):
            texto = self._read(rel)
            if texto is None:
                problemas.append(f"{rel}: ausente")
                continue
            if TAGLINE_CANONICA not in texto:
                problemas.append(f"{rel}: sem tagline canônica")
            if ASSINATURA_CANONICA not in texto.lower():
                problemas.append(f"{rel}: sem assinatura 'local por lei'")
        self._add_check("brand:tagline", not problemas,
                        "tagline e assinatura canônicas presentes" if not problemas
                        else "; ".join(problemas))

    def _check_instalacao_oficial(self):
        alvos = [README_REL, MANUAL_REL, BRANDBOOK_REL, LANDING_REL, INSTALL_MD_REL]
        ofensores = []
        for rel in alvos:
            texto = self._read(rel)
            if texto is not None and _PIP_NOMOS_PURO.search(texto):
                ofensores.append(rel)
        self._add_check("brand:instalacao_oficial", not ofensores,
                        "nenhum doc recomenda 'pip install nomos' puro (nome de "
                        "terceiros no PyPI)" if not ofensores
                        else f"docs recomendam pacote de terceiros: {ofensores}")

    def _check_versao_coerente(self):
        pyproject = self._read(PYPROJECT_REL) or ""
        init = self._read(INIT_REL) or ""
        m_py = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        m_init = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.MULTILINE)
        if not (m_py and m_init):
            self._add_check("brand:versao_coerente", False,
                            "não foi possível ler versão de pyproject/__init__")
            return
        iguais = m_py.group(1) == m_init.group(1)
        self._add_check("brand:versao_coerente", iguais,
                        f"versão única: {m_py.group(1)}" if iguais
                        else f"pyproject={m_py.group(1)} != __init__={m_init.group(1)}")

    def _check_git(self):
        """Lê estado básico do git por leitura direta de .git (somente leitura)."""
        git_dir = self.repo_root / ".git"
        info = {"is_repo": git_dir.exists(), "branch": None, "head": None}
        head_file = git_dir / "HEAD"
        if head_file.exists():
            head = head_file.read_text(encoding="utf-8", errors="ignore").strip()
            if head.startswith("ref:"):
                ref = head.split(" ", 1)[1].strip()
                info["branch"] = ref.rsplit("/", 1)[-1]
                ref_path = git_dir / ref
                if ref_path.exists():
                    info["head"] = ref_path.read_text(encoding="utf-8", errors="ignore").strip()
            else:
                info["head"] = head  # detached HEAD
        self.report.git = info
        self._add_check("git:repo", info["is_repo"],
                        f"branch={info['branch']}" if info["is_repo"] else "não é repositório git")

    # ---- orquestração --check ----
    def run_check(self) -> Report:
        self._check_existencia()
        self._check_secoes()
        self._check_links_landing()
        self._check_secrets()
        self._check_brand_paleta()
        self._check_brand_tagline()
        self._check_instalacao_oficial()
        self._check_versao_coerente()
        self._check_git()

        self.report.timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.report.status = "ok" if not self.report.errors else "inconsistent"
        if self.report.status == "ok":
            self.report.next_recommendation = (
                "Documentação consistente. Rodar em CI com --check --json como gate "
                "read-only e revisar --diff manualmente antes de qualquer commit."
            )
        else:
            self.report.next_recommendation = (
                "Corrigir os itens em 'errors' e re-executar --check antes de commit."
            )
        return self.report

    # ---- propositor de diff (--diff) — PROPOSAL-ONLY, nunca escreve ----
    def run_diff(self) -> dict:
        """Propõe patches de documentação/consistência. Não escreve, não executa git."""
        patches: List[dict] = []

        readme = self._plain_read(README_REL)
        if readme is not None:
            if "NOMOS_INSTALLATION_MANUAL" not in readme:
                patches.append({
                    "path": README_REL,
                    "reason": "documentacao_desatualizada",
                    "risk": "low",
                    "proposal": ("Adicionar no README um link para o Manual de Instalação "
                                 "completo (docs/installation/NOMOS_INSTALLATION_MANUAL.md)."),
                })
            if "NOMOS_BRANDBOOK" not in readme:
                patches.append({
                    "path": README_REL,
                    "reason": "documentacao_desatualizada",
                    "risk": "low",
                    "proposal": ("Adicionar no README um link para o Brandbook "
                                 "(docs/brand/NOMOS_BRANDBOOK.md)."),
                })

        gov = self._plain_read(GOVERNANCE_REL)
        if gov is not None and AGENT_VERSION not in gov:
            patches.append({
                "path": GOVERNANCE_REL,
                "reason": "versao_desatualizada",
                "risk": "low",
                "proposal": (f"Atualizar a referência de versão do agente para "
                             f"{AGENT_VERSION} no documento de governança."),
            })

        return {
            "agent_version": AGENT_VERSION,
            "mode": "diff",
            "proposal_only": True,
            "writes_enabled": False,
            "human_approval_required": True,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "patches": patches,
        }


def print_human(report: Report):
    print(f"{BOLD}{BLUE}NOMOS Update Agent {report.version} — --check{RESET}\n")
    for c in report.checks:
        icon = f"{GREEN}✓{RESET}" if c.ok else f"{RED}✗{RESET}"
        print(f"  {icon} {c.name}: {c.detail}")
    if report.warnings:
        print(f"\n{YELLOW}Avisos:{RESET}")
        for w in report.warnings:
            print(f"  {YELLOW}!{RESET} {w}")
    print()
    if report.status == "ok":
        print(f"{GREEN}✅ Estado: CONSISTENTE{RESET}")
    else:
        print(f"{RED}❌ Estado: INCONSISTENTE ({len(report.errors)} erro(s)){RESET}")
        for e in report.errors:
            print(f"  {RED}·{RESET} {e}")
    print(f"\n{BOLD}Próximo:{RESET} {report.next_recommendation}")


def print_json(report: Report):
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


def print_diff_human(proposal: dict):
    print(f"{BOLD}{BLUE}NOMOS Update Agent {AGENT_VERSION} — --diff{RESET}\n")
    print("PROPOSTA_DIFF_ONLY")
    print("NO_WRITE")
    print("HUMAN_APPROVAL_REQUIRED")
    print()
    patches = proposal.get("patches", [])
    if not patches:
        print(f"{GREEN}Nenhuma divergência de documentação detectada. "
              f"Nenhum patch proposto.{RESET}")
    else:
        print(f"{BOLD}Patches propostos ({len(patches)}):{RESET}\n")
        for i, p in enumerate(patches, 1):
            print(f"  {YELLOW}[{i}]{RESET} {p['path']}  (risco: {p['risk']}, "
                  f"motivo: {p['reason']})")
            print(f"      → {p['proposal']}")
    print(f"\n{BOLD}Aviso:{RESET} proposta apenas. Nada foi escrito. "
          f"Aplicação requer revisão e ação humana.")


def print_diff_json(proposal: dict):
    print(json.dumps(proposal, ensure_ascii=False, indent=2))


HELP = """NOMOS Update Agent {v} — Consistência + Propositor de Diff (CI-safe, fail-closed)

SINTAXE:
  python tools/nomos_update_agent.py [ACTION] [FLAGS]

ACTIONS:
  --check      Verifica consistência. Exit 0 se OK, 1 se inconsistente. (padrão)
  --diff       Propõe patches de documentação (PROPOSAL-ONLY; nunca escreve).
  --version    Imprime a versão do agente ({v}) e sai.
  --apply      [BLOQUEADO] Aplicação automática permanece desabilitada (fail-closed).

FLAGS:
  --json       Emite saída JSON determinística (para CI). Sem cores.
  --dry-run    Padrão: nada é escrito.
  --help       Mostra esta ajuda.

SEGURANÇA:
  - Não executa processos externos -> incapaz de push/tag/release/deploy.
  - Estado do git lido por leitura direta de .git (somente leitura).
  - Nenhum modo escreve arquivos; --diff é apenas proposta.

Ver: docs/governance/NOMOS_UPDATE_AGENT.md
""".format(v=AGENT_VERSION)


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--i-understand-this-writes-files", action="store_true")
    parser.add_argument("--i-understand-this-is-disabled", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--help", "-h", action="store_true")

    args = parser.parse_args(argv)

    if args.help:
        print(HELP)
        return 0

    if args.version:
        print(AGENT_VERSION)
        return 0

    if args.apply:
        # Fail-closed em qualquer combinação: aplicação automática segue desabilitada.
        if not args.i_understand_this_writes_files:
            print(f"{RED}❌ --apply requer flag de risco: "
                  f"--i-understand-this-writes-files. Aplicação automática continua "
                  f"desabilitada; nenhuma escrita realizada.{RESET}")
            return 1
        print(f"{RED}⚠ Modo --apply não implementado (fail-closed). "
              f"Aplicação automática continua desabilitada; nenhuma escrita realizada.{RESET}")
        return 1

    repo_root = Path(__file__).resolve().parent.parent
    agent = NomosUpdateAgent(repo_root)

    if args.diff:
        proposal = agent.run_diff()
        if args.json:
            print_diff_json(proposal)
        else:
            print_diff_human(proposal)
        return 0  # proposta é sempre bem-sucedida (não é gate de falha)

    # Padrão: --check
    report = agent.run_check()
    if args.json:
        print_json(report)
    else:
        print_human(report)
    return 0 if report.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
