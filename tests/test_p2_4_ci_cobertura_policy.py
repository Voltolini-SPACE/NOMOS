"""P2-4 (auditoria de 2026-07-17): política de cobertura no CI — nome
precisa bater com comportamento real.

Achado: o job de cobertura em `.github/workflows/ci.yml` se chamava
"cobertura (informativa)", mas nunca teve `continue-on-error` — ao
contrário dos jobs `tipos` (mypy) e `dependencias` (pip-audit), que TÊM
essa flag de propósito (rollout gradual documentado em comentário). Uma
falha de `--cov-fail-under` sempre marcou o job/commit como falho de
verdade — comportamento bloqueante com rótulo de "informativa".

Decisão (POLICY_A=COBERTURA_BLOQUEANTE): o nome passa a refletir o
comportamento real, que não mudou (nenhum piso foi reduzido). Este teste
confere, por leitura direta do YAML (texto, sem dependência nova de
parser — PyYAML não é dependência declarada do projeto), que:
- o rótulo enganoso sumiu e o novo é coerente com a realidade;
- o job de cobertura continua sem `continue-on-error` (bloqueante de
  verdade, não um 0 mascarado);
- os pisos de cobertura (80% geral, 90% dirigido) não foram reduzidos;
- `tipos`/`dependencias` continuam informativos de verdade (com
  `continue-on-error: true` real) — não regrediram para bloqueantes por
  engano nesta mudança.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CI_YML = ROOT / ".github" / "workflows" / "ci.yml"


def _bloco_do_job(texto: str, job: str, proximo_job: str) -> str:
    ini = texto.index(f"\n  {job}:\n")
    fim = texto.index(f"\n  {proximo_job}:\n")
    return texto[ini:fim]


def test_rotulo_informativa_sumiu_do_job_de_cobertura():
    texto = CI_YML.read_text(encoding="utf-8")
    # o campo `name:` do job (não o texto do comentário explicativo, que
    # cita o rótulo antigo de propósito, como registro do achado)
    assert "name: cobertura (informativa)" not in texto
    assert "name: cobertura (bloqueante)" in texto


def test_job_cobertura_continua_sem_continue_on_error():
    texto = CI_YML.read_text(encoding="utf-8")
    bloco = _bloco_do_job(texto, "cobertura", "tipos")
    assert "continue-on-error" not in bloco, (
        "job de cobertura ganhou continue-on-error — isso mudaria o "
        "comportamento real para não-bloqueante, o oposto da decisão P2-4")


def test_pisos_de_cobertura_nao_foram_reduzidos():
    texto = CI_YML.read_text(encoding="utf-8")
    bloco = _bloco_do_job(texto, "cobertura", "tipos")
    assert "--cov-fail-under=80" in bloco
    assert "--cov-fail-under=90" in bloco


def test_mypy_e_pip_audit_continuam_informativos_de_verdade():
    texto = CI_YML.read_text(encoding="utf-8")
    bloco_tipos = _bloco_do_job(texto, "tipos", "dependencias")
    bloco_dependencias = _bloco_do_job(texto, "dependencias", "smoke")
    assert "continue-on-error: true" in bloco_tipos
    assert "continue-on-error: true" in bloco_dependencias
    assert "name: mypy (informativo)" in bloco_tipos
    assert "name: pip-audit (informativo)" in bloco_dependencias


def test_ci_yml_continua_yaml_valido():
    """Rede de segurança extra: se PyYAML estiver disponível no ambiente
    (não é dependência declarada do projeto — só usamos se já presente),
    confirma que o arquivo inteiro continua parseável após a edição."""
    import pytest
    yaml = pytest.importorskip("yaml", reason="PyYAML não é dependência do projeto")
    doc = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    assert doc["jobs"]["cobertura"]["name"] == "cobertura (bloqueante)"
    assert "continue-on-error" not in doc["jobs"]["cobertura"]
    assert doc["jobs"]["tipos"]["continue-on-error"] is True
    assert doc["jobs"]["dependencias"]["continue-on-error"] is True
