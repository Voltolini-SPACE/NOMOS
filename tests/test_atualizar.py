"""v0.12 — `nomos atualizar`: opt-in, honesto e NUNCA automático."""
import io

import pytest

from nomos import __version__, cli
from nomos.kernel import localidade
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.simple import atualizar as at


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _ctx(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl")}


# ---------------- comparação de versões ----------------

def test_comparar_versoes():
    assert at.comparar_versoes("0.11.0", "0.12.0") == -1
    assert at.comparar_versoes("0.12.0", "0.12.0") == 0
    assert at.comparar_versoes("1.0.0", "0.12.0") == 1
    assert at.comparar_versoes("v0.12.0", "0.12.0") == 0
    assert at.comparar_versoes("1.0.0rc1", "1.0.0") == -1   # rc antes da final
    assert at.comparar_versoes("", "0.1.0") == -1           # malformada nunca "ganha"


# ---------------- gates ----------------

def test_cadeado_ligado_nega_mesmo_com_humano(nomos_home):
    ctx = _ctx(nomos_home)   # localidade padrão: LIGADA
    ditos = []
    rc = at.verificar(ctx, approver=lambda d: True,
                      fetcher=lambda: pytest.fail("não pode nem tentar rede"),
                      say=ditos.append)
    assert rc == 3
    tudo = "\n".join(ditos)
    assert "só-local" in tudo and "proteção" in tudo


def test_sem_aprovador_nega_fail_closed(nomos_home):
    ctx = _ctx(nomos_home)
    localidade.definir(nomos_home, False)
    rc = at.verificar(ctx, approver=None,
                      fetcher=lambda: pytest.fail("sem aprovação não há rede"),
                      say=lambda *_: None)
    assert rc == 3


# ---------------- fluxo aprovado (fetcher fake, sem rede real) ----------------

def test_versao_nova_orienta_e_nunca_instala(nomos_home):
    ctx = _ctx(nomos_home)
    localidade.definir(nomos_home, False)
    ditos = []
    rc = at.verificar(ctx, approver=lambda d: True,
                      fetcher=lambda: {"versao": "99.0.0", "nome": "v99",
                                       "url": "https://github.com/x/releases",
                                       "notas": "- coisas novas"},
                      say=ditos.append)
    assert rc == 0
    tudo = "\n".join(ditos)
    assert "99.0.0" in tudo and "NUNCA me atualizo sozinho" in tudo
    assert "instalando" not in tudo.lower()      # não executa nada
    assert "memórias, chaves" in tudo            # tranquiliza sobre os dados


def test_ja_na_mais_nova(nomos_home):
    ctx = _ctx(nomos_home)
    localidade.definir(nomos_home, False)
    ditos = []
    rc = at.verificar(ctx, approver=lambda d: True,
                      fetcher=lambda: {"versao": __version__},
                      say=ditos.append)
    assert rc == 0 and "mais nova" in "\n".join(ditos)


def test_fetcher_falha_e_resposta_honesta(nomos_home):
    ctx = _ctx(nomos_home)
    localidade.definir(nomos_home, False)
    ditos = []

    def quebrado():
        raise OSError("sem internet")
    rc = at.verificar(ctx, approver=lambda d: True, fetcher=quebrado,
                      say=ditos.append)
    assert rc == 1
    assert "Não consegui" in "\n".join(ditos)


def test_auditoria_sem_conteudo_de_notas(nomos_home):
    ctx = _ctx(nomos_home)
    localidade.definir(nomos_home, False)
    at.verificar(ctx, approver=lambda d: True,
                 fetcher=lambda: {"versao": "99.0.0",
                                  "notas": "SEGREDO-NAS-NOTAS-NUNCA-NO-LOG"},
                 say=lambda *_: None)
    bruto = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "SEGREDO-NAS-NOTAS" not in bruto      # log guarda versões, não corpo
    assert "atualizar.verificado" in bruto


# ---------------- CLI ----------------

def test_cli_atualizar_nao_interativo_nega(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["atualizar"]) == 3          # sem TTY: gate nega
    out = capsys.readouterr().out
    assert "proteção" in out
