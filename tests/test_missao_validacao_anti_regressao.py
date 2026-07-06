"""Anti-regressão — Missão de Validação Ponta a Ponta do NOMOS (2026-07-05).

Blindagens de contrato (não frágeis, sem contagem exata de testes nem versões
de tag hardcoded). Destino sugerido: ``tests/test_missao_validacao_anti_regressao.py``.

Contratos protegidos:
1. Execução real do Motor Council permanece DESLIGADA (trava literal, sem API p/ ligar).
2. Brandbook congelado íntegro — SHA256SUMS confere com os arquivos reais.
3. Documentação essencial existe e não está vazia.
4. ``.gitignore`` cobre os artefatos temporários conhecidos.
5. Nenhum doc oficial recomenda ``pip install nomos`` puro — o nome ``nomos`` no
   PyPI pertence a um projeto de terceiros (dowhiledev), não ao NOMOS/Se7enpay.
   (Evidência: pypi.org/project/nomos — v0.3.7, "multi-step agent framework".)
6. Versão coerente entre ``pyproject.toml`` e ``nomos.__version__``.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# ----------------------------------------------------------------- contrato 1
def test_execucao_real_do_council_permanece_desligada():
    from nomos.council import local_harness

    assert local_harness.REAL_LOCAL_ENGINE_EXECUTION_ENABLED is False, (
        "Trava de execução real do Motor Council foi ligada — regressão de "
        "segurança. Dry-run deve ser o único modo até decisão explícita."
    )
    # A trava também é exportada no pacote público — o contrato vale nas duas portas.
    import nomos.council as council

    assert council.REAL_LOCAL_ENGINE_EXECUTION_ENABLED is False


# ----------------------------------------------------------------- contrato 2
def test_brandbook_congelado_integro():
    frozen = RAIZ / "docs" / "brand" / "frozen"
    sums = frozen / "SHA256SUMS"
    assert sums.is_file(), "SHA256SUMS do brandbook congelado sumiu"
    conferidos = 0
    for linha in sums.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        esperado, nome = linha.split(maxsplit=1)
        alvo = frozen / nome.strip().lstrip("*")
        assert alvo.is_file(), f"arquivo congelado ausente: {alvo.name}"
        real = hashlib.sha256(alvo.read_bytes()).hexdigest()
        assert real == esperado, (
            f"brandbook congelado alterado sem nova versão: {alvo.name} "
            f"(esperado {esperado[:12]}…, obtido {real[:12]}…)"
        )
        conferidos += 1
    assert conferidos >= 2, "SHA256SUMS não lista os arquivos congelados"


# ----------------------------------------------------------------- contrato 3
DOCS_ESSENCIAIS = [
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "docs/brand/frozen/BRANDBOOK_NOMOS.md",
    "docs/brand/NOMOS_BRANDBOOK.md",
    "docs/installation/NOMOS_INSTALLATION_MANUAL.md",
    "docs/governance/NOMOS_UPDATE_AGENT.md",
    "site/index.html",
    "site/404.html",
]


def test_documentacao_essencial_existe_e_nao_vazia():
    faltando = [
        rel for rel in DOCS_ESSENCIAIS
        if not (RAIZ / rel).is_file() or (RAIZ / rel).stat().st_size == 0
    ]
    assert not faltando, f"documentação essencial ausente/vazia: {faltando}"


# ----------------------------------------------------------------- contrato 4
PADROES_GITIGNORE = [
    "__pycache__/",
    "build/",
    "dist/",
    "*.egg-info/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".coverage",
    ".DS_Store",
    "/nomos-[0-9]*/",
    ".nomos/",
]


def test_gitignore_cobre_artefatos_conhecidos():
    texto = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    ausentes = [p for p in PADROES_GITIGNORE if p not in texto]
    assert not ausentes, f".gitignore perdeu cobertura de: {ausentes}"


# ----------------------------------------------------------------- contrato 5
# `pip install nomos` puro instalaria o pacote de TERCEIROS homônimo do PyPI.
# Permitidos: `pip install nomos-<versão>.whl`, `git+https://…`, `pip install .`.
_PIP_NOMOS_PURO = re.compile(r"pip install nomos(?![-\w./])")
_DOCS_OFICIAIS = ["README.md"]
_DIRS_OFICIAIS = ["docs/installation", "docs/brand", "docs/governance", "site"]
# docs/missions/ e docs/ROADMAP*.md são registros históricos — fora do contrato.


def _arquivos_oficiais():
    yield from (RAIZ / n for n in _DOCS_OFICIAIS)
    for d in _DIRS_OFICIAIS:
        base = RAIZ / d
        if base.is_dir():
            yield from base.rglob("*.md")
            yield from base.rglob("*.html")


def test_docs_oficiais_nao_recomendam_pip_install_nomos_puro():
    ocorrencias = []
    for arq in _arquivos_oficiais():
        if not arq.is_file():
            continue
        for i, linha in enumerate(
            arq.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if _PIP_NOMOS_PURO.search(linha):
                ocorrencias.append(f"{arq.relative_to(RAIZ)}:{i}")
    assert not ocorrencias, (
        "docs oficiais recomendam `pip install nomos` puro — no PyPI esse nome "
        f"é de um projeto de terceiros (dowhiledev). Ocorrências: {ocorrencias}"
    )


# ----------------------------------------------------------------- contrato 6
def test_versao_pyproject_coerente_com_pacote():
    import nomos

    m = re.search(
        r'^version\s*=\s*"([^"]+)"',
        (RAIZ / "pyproject.toml").read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert m, "pyproject.toml sem campo version"
    assert m.group(1) == nomos.__version__, (
        f"versão divergente: pyproject={m.group(1)} != nomos.__version__="
        f"{nomos.__version__}"
    )
