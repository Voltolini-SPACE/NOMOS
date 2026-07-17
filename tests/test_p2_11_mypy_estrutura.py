"""P2-11 (auditoria de 2026-07-17): bloqueio estrutural do mypy.

Dois problemas reais confirmados por reprodução direta:

1. `mypy` sobre qualquer escopo que inclua `conectores/mcp/` ABORTAVA com
   "Duplicate module named 'servidor'" — os 7 conectores MCP têm cada um
   seu próprio `servidor.py`, sem `__init__.py` nos diretórios (de
   propósito: cada um roda como script standalone via subprocess, nunca é
   importado como pacote). Corrigido via `[tool.mypy] exclude` em
   `pyproject.toml`, não `__init__.py` (que criaria um caminho de import
   nunca usado, quebrando o isolamento deliberado desses conectores).

2. `kernel/evidencia.py:123` tinha um falso-positivo de tipo (dict
   heterogêneo inferido como `dict[str, object]`) — corrigido com
   `str(manifesto["notas"])`, uma mudança de uma linha sem efeito em
   runtime (o valor já é sempre `str`, vindo de `redact_text(str) -> str`).

Estes testes rodam mypy de verdade (subprocess) e conferem o código de
saída REAL — nunca declaram sucesso sem executar o comando.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytest.importorskip("mypy", reason="mypy é ferramenta de dev, não dependência do pacote")


def _mypy(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "mypy", *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )


def test_mypy_kernel_limpo_codigo_de_saida_real():
    """Comando EXATO usado pelo job 'tipos' do CI — o achado original
    (evidencia.py:123) fazia isso retornar 1; agora deve ser 0 de verdade,
    não um 0 mascarado por '|| true' do shell."""
    r = _mypy("src/nomos/kernel", "--ignore-missing-imports")
    assert r.returncode == 0, f"mypy retornou {r.returncode}:\n{r.stdout}\n{r.stderr}"
    assert "Success" in r.stdout


def test_mypy_evidencia_py_sem_o_falso_positivo_da_linha_123():
    r = _mypy("src/nomos/kernel/evidencia.py", "--ignore-missing-imports")
    assert r.returncode == 0
    assert "evidencia.py:123" not in r.stdout


def test_mypy_nao_colide_mais_em_conectores_mcp():
    """Antes do exclude em pyproject.toml: 'Duplicate module named
    "servidor"' e mypy abortava (código de saída 2, 'errors prevented
    further checking') antes de checar qualquer coisa nesta pasta."""
    r = _mypy("src/nomos/conectores/mcp")
    saida = r.stdout + r.stderr
    assert "Duplicate module" not in saida
    assert "found twice" not in saida
    assert r.returncode in (0, 1)   # nunca 2 (abortado por config/colisão)


def test_mypy_src_nomos_inteiro_nao_aborta_mais(tmp_path):
    """Escopo total (o que a auditoria original tentou rodar): antes,
    abortava em 1 arquivo ('errors prevented further checking'). Agora
    processa o pacote inteiro — pode reportar erros reais pré-existentes
    (fora do escopo mínimo deste achado, catalogados no relatório do
    Horizonte 2), mas não pode mais abortar sem checar nada."""
    r = _mypy("src/nomos")
    saida = r.stdout + r.stderr
    assert "Duplicate module" not in saida
    assert "errors prevented further checking" not in saida
    assert "checked 1 source file" not in saida    # sinal de abort prematuro
    assert "checked " in saida                       # processou o pacote de verdade


def test_pyproject_declara_exclude_do_servidor_mcp():
    """Config estrutural presente (não depende de flag manual de CLI)."""
    conteudo = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.mypy]" in conteudo
    assert "servidor" in conteudo
    assert "conectores/mcp" in conteudo


def test_conectores_mcp_nao_tem_init_py():
    """Confirma que a correção foi por exclude, NÃO por __init__.py — os
    conectores continuam scripts standalone, não pacotes importáveis."""
    base = ROOT / "src" / "nomos" / "conectores" / "mcp"
    subpastas = [p for p in base.iterdir() if p.is_dir() and p.name != "__pycache__"]
    assert len(subpastas) == 7, subpastas
    for p in subpastas:
        assert not (p / "__init__.py").exists(), f"{p} ganhou __init__.py"
        assert (p / "servidor.py").exists()
