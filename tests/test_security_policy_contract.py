"""Contrato executável da Política Formal de Segurança (SEC-01…SEC-12).

Cada invariante declarada em ``docs/governance/SECURITY_POLICY.md`` é provada
aqui contra o código real. O último teste garante a sincronia bidirecional:
todo ID no documento tem teste, e todo teste daqui tem ID no documento.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from nomos.council import forbidden_flags, local_harness
from nomos.kernel import localidade
from nomos.kernel.policy import (
    Category,
    DEFAULT_RULES,
    Decision,
    Effect,
    PolicyEngine,
    gate,
)

RAIZ = Path(__file__).resolve().parent.parent
POLITICA = RAIZ / "docs" / "governance" / "SECURITY_POLICY.md"


# SEC-01 ---------------------------------------------------------------------
def test_sec01_execucao_real_do_council_desligada():
    assert local_harness.REAL_LOCAL_ENGINE_EXECUTION_ENABLED is False


# SEC-02 ---------------------------------------------------------------------
def test_sec02_contrato_unico_de_flags_proibidas():
    esperado = {
        "--real", "--enable", "--ativar", "--force", "--unsafe",
        "--cloud", "--audit-real", "--policy-real", "--vault-real",
        "--engine-real",
    }
    assert set(forbidden_flags.FORBIDDEN_FLAGS) == esperado
    assert forbidden_flags.is_forbidden_flag("--real") is True
    # igualdade estrita: parecidas-mas-legítimas NÃO são "proibidas"
    for legitima in ("--realmente", "--enabled", "--cloudy", "--forcado"):
        assert forbidden_flags.is_forbidden_flag(legitima) is False


# SEC-03 / SEC-04 ------------------------------------------------------------
def test_sec03_padrao_read_only_somente_a0_allow():
    allows = [c for c, e in DEFAULT_RULES.items() if e == Effect.ALLOW.value]
    assert allows == [Category.READ_LOCAL.value]


def test_sec04_destrutivo_e_deny_por_default():
    assert DEFAULT_RULES[Category.DESTRUCTIVE.value] == Effect.DENY.value


# SEC-05 / SEC-06 ------------------------------------------------------------
def test_sec05_categoria_desconhecida_nega(tmp_path):
    eng = PolicyEngine(tmp_path / "policy.json")
    dec = eng.decide("A9_INVENTADA", "x")
    assert dec.effect is Effect.DENY


def test_sec06_politica_corrompida_nega_tudo(tmp_path):
    caminho = tmp_path / "policy.json"
    eng = PolicyEngine(caminho)
    caminho.write_text("{ isso não é json válido !!!")
    dec = eng.decide(Category.READ_LOCAL, "arquivo.txt")
    assert dec.effect is Effect.DENY  # nem A0 sobrevive à política ilegível


# SEC-07 / SEC-08 ------------------------------------------------------------
def _decisao_aprovavel() -> Decision:
    return Decision(Effect.REQUIRE_APPROVAL, Category.WRITE_LOCAL.value, "f", "r")


def test_sec07_require_approval_sem_aprovador_nega():
    assert gate(_decisao_aprovavel(), None) is False


def test_sec08_aprovador_com_erro_nunca_autoriza():
    def aprovador_quebrado(_dec):
        raise RuntimeError("boom")

    assert gate(_decisao_aprovavel(), aprovador_quebrado) is False


# SEC-09 ---------------------------------------------------------------------
def test_sec09_localidade_default_ligada_e_bloqueia_egress(tmp_path):
    # ausência de estado = cadeado LIGADO (fail-closed)
    assert localidade.esta_ligado(tmp_path) is True
    eng = PolicyEngine(tmp_path / "policy.json")
    dec = eng.decide(Category.NET_EGRESS, "https://example.com")
    assert dec.effect is Effect.DENY
    # loopback não é egress bloqueado pelo cadeado (painel local funciona)
    assert localidade.bloqueia_egress(tmp_path, "http://127.0.0.1:8888") is False


# SEC-10 / SEC-11 / SEC-12 — invariantes cuja prova principal vive em suítes
# dedicadas; aqui garantimos que essas suítes existem e seguem no lugar.
def _conta_testes(path: Path) -> int:
    return len(re.findall(r"^def test_", path.read_text(encoding="utf-8"), re.M))


def test_sec10_suite_de_nao_vazamento_de_segredos_presente():
    suite = RAIZ / "tests" / "test_no_secret_leak_regression.py"
    assert suite.is_file() and _conta_testes(suite) >= 4


def test_sec11_contrato_anti_pip_install_nomos_presente():
    suite = RAIZ / "tests" / "test_missao_validacao_anti_regressao.py"
    texto = suite.read_text(encoding="utf-8")
    assert "test_docs_oficiais_nao_recomendam_pip_install_nomos_puro" in texto


def test_sec12_contrato_de_integridade_do_brandbook_presente():
    suite = RAIZ / "tests" / "test_missao_validacao_anti_regressao.py"
    assert "test_brandbook_congelado_integro" in suite.read_text(encoding="utf-8")


# Sincronia doc ↔ testes ------------------------------------------------------
def test_politica_e_testes_estao_sincronizados():
    assert POLITICA.is_file(), "SECURITY_POLICY.md ausente"
    doc_ids = set(re.findall(r"SEC-(\d{2})", POLITICA.read_text(encoding="utf-8")))
    fonte = Path(__file__).read_text(encoding="utf-8")
    test_ids = set(re.findall(r"def test_sec(\d{2})_", fonte))
    assert doc_ids == test_ids, (
        f"política e testes divergem — só no doc: {sorted(doc_ids - test_ids)}; "
        f"só nos testes: {sorted(test_ids - doc_ids)}"
    )
    assert len(doc_ids) == 12


if __name__ == "__main__":  # conveniência local
    raise SystemExit(pytest.main([__file__, "-q"]))
