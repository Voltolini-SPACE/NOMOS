"""Horizonte 3/item 5 (auditoria de 2026-07-17): promoção dos jobs de CI
"tipos" (mypy kernel) e "dependencias" (pip-audit) de informativos para
bloqueantes.

Contexto real, confirmado por execução (não suposição) antes de promover:

- `tipos` rodava `mypy src/nomos/kernel --ignore-missing-imports || true`
  com `continue-on-error: true`. Desde o P2-11 (Horizonte 2) o comando em
  si já retornava 0 de verdade — `tests/test_p2_11_mypy_estrutura.py::
  test_mypy_kernel_limpo_codigo_de_saida_real` já prova isso por
  subprocess real. O job só continuava rotulado "informativo" por nunca
  ter sido promovido; reconfirmado agora (mesmo comando, mesmo escopo)
  que promover não quebra nada hoje.

- `dependencias` rodava `pip_audit || true` com `continue-on-error: true`.
  Reproduzido o comando exato do job num venv limpo (equivalente ao
  bootstrap do job — ressalva: em Python 3.10, já que o job pina 3.12 e
  este ambiente de auditoria só tem 3.10 disponível; ver o relatório do
  item para a limitação documentada), o único achado era `setuptools
  59.6.0` — a versão que `python -m venv` semeia por padrão neste
  interpretador, NÃO uma dependência declarada do NOMOS
  (`pyproject.toml` não fixa `setuptools`; é só requisito de
  `[build-system]`, satisfeito por isolamento PEP 517 no build, não no
  ambiente de instalação do job). Corrigido incluindo `setuptools` na
  mesma linha de upgrade que já instalava `pip`/`pip-audit` —
  reproduzido: 0 vulnerabilidades depois do fix.

Os testes abaixo checam a CONFIGURAÇÃO do CI (sem `continue-on-error`,
sem `|| true`, `setuptools` presente no upgrade de `dependencias`) — de
propósito, NÃO chamam `pip_audit` de verdade aqui: isso bateria numa
base de dados de vulnerabilidades externa pela rede a cada rodada da
suíte padrão, o que tornaria `pytest -q` dependente de rede e de um
serviço de terceiros — exatamente o tipo de fragilidade que o restante
do projeto evita (ver Fase 7, achados de resiliência/circuit breaker).
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _bloco_do_job(texto: str, job: str, proximo_job: str) -> str:
    ini = texto.index(f"\n  {job}:\n")
    fim = texto.index(f"\n  {proximo_job}:\n")
    return texto[ini:fim]


def test_job_tipos_promovido_a_bloqueante():
    texto = CI_YML.read_text(encoding="utf-8")
    bloco = _bloco_do_job(texto, "tipos", "dependencias")
    assert "name: mypy kernel (bloqueante)" in bloco
    assert "continue-on-error" not in bloco, (
        "job 'tipos' ainda tem continue-on-error — não é bloqueante de verdade")
    assert "|| true" not in bloco, (
        "comando ainda mascara o código de saída real do mypy")
    # escopo inalterado (item 3 do Horizonte 3 já cortou e documentou os
    # 77 erros remanescentes fora de src/nomos/kernel como débito à parte)
    assert "mypy src/nomos/kernel --ignore-missing-imports" in bloco


def test_job_dependencias_promovido_a_bloqueante_com_setuptools_no_upgrade():
    texto = CI_YML.read_text(encoding="utf-8")
    bloco = _bloco_do_job(texto, "dependencias", "smoke")
    assert "name: pip-audit (bloqueante)" in bloco
    assert "continue-on-error" not in bloco, (
        "job 'dependencias' ainda tem continue-on-error — não é bloqueante de verdade")
    assert "|| true" not in bloco, (
        "comando ainda mascara o código de saída real do pip-audit")
    assert "pip install --upgrade pip setuptools pip-audit" in bloco, (
        "setuptools precisa estar na linha de upgrade do bootstrap deste "
        "job — sem isso, o setuptools semeado pelo venv (59.6.0 no "
        "ambiente desta auditoria) tem CVEs conhecidas e derruba o job "
        "à toa (achado real do item 5, não hipotético)")


def test_job_cobertura_nao_foi_tocado_por_este_item():
    """Anti-regressão de escopo: item 5 só toca tipos/dependencias —
    cobertura já foi resolvido no P2-4 e não deveria mudar aqui."""
    texto = CI_YML.read_text(encoding="utf-8")
    bloco = _bloco_do_job(texto, "cobertura", "tipos")
    assert "name: cobertura (bloqueante)" in bloco
    assert "--cov-fail-under=80" in bloco
    assert "--cov-fail-under=90" in bloco


def test_ci_yml_continua_yaml_valido_com_os_tres_jobs_bloqueantes():
    yaml = pytest.importorskip("yaml", reason="PyYAML não é dependência do projeto")
    doc = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    for job in ("cobertura", "tipos", "dependencias"):
        assert "continue-on-error" not in doc["jobs"][job], job
    assert doc["jobs"]["tipos"]["name"] == "mypy kernel (bloqueante)"
    assert doc["jobs"]["dependencias"]["name"] == "pip-audit (bloqueante)"
    # testes/smoke nunca tiveram continue-on-error — confirma que a leitura
    # do YAML por chave está correta e não está sempre "passando à toa"
    assert "continue-on-error" not in doc["jobs"]["testes"]
    assert "continue-on-error" not in doc["jobs"]["smoke"]


def test_mypy_kernel_comando_exato_do_job_promovido_retorna_0():
    """Mesmo comando do job 'tipos', rodado de verdade agora — não só a
    configuração, mas a prova de que promover não quebra CI hoje.
    (Complementa, não duplica, test_p2_11_mypy_estrutura.py — aquele
    arquivo prova a limpeza pós-P2-11; este confirma o mesmo fato no
    ponto exato em que o job passou a ser bloqueante.)"""
    import subprocess
    import sys

    pytest.importorskip("mypy", reason="mypy é ferramenta de dev, não dependência do pacote")
    r = subprocess.run(
        [sys.executable, "-m", "mypy", "src/nomos/kernel", "--ignore-missing-imports"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    assert r.returncode == 0, f"mypy retornou {r.returncode}:\n{r.stdout}\n{r.stderr}"


def test_setuptools_desatualizado_e_a_causa_raiz_documentada_nao_hipotese():
    """Prova, por leitura do próprio pyproject.toml, que `setuptools` NÃO
    é uma dependência declarada do NOMOS (nem em `dependencies` nem em
    `optional-dependencies`) — reforça, por código (não só comentário),
    que a vulnerabilidade encontrada no item 5 era um artefato do
    ambiente de instalação do job, não uma escolha de dependência do
    projeto que precisaria de uma decisão de produto para mudar."""
    conteudo = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dependencies = ["cryptography>=46.0.7", "argon2-cffi>=23.1"]' in conteudo
    assert "setuptools" not in conteudo.split("[project.optional-dependencies]")[1].split(
        "[project.urls]")[0]
