"""Regressão — nuvem é opt-in: local off + chave + aprovação, sempre."""
import io

import pytest

from nomos import cli
from nomos.cognition import engine_catalog as cat_mod
from nomos.cognition import engine_policy as epol
from nomos.cognition import motores
from nomos.cognition.router import Router
from nomos.kernel import localidade
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine, gate
from nomos.kernel.vault import Vault


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


class _OllamaMorto:
    host = "http://127.0.0.1:11434"

    def available(self):
        return False

    def chat(self, messages):
        raise AssertionError("não deveria ser chamado")


def _router(nomos_home, approver):
    engine = PolicyEngine(nomos_home / "policy.json")
    return Router(policy=engine, gate=gate, approver=approver,
                  audit=AuditLog(nomos_home / "logs" / "audit.jsonl"),
                  vault=Vault(nomos_home / "vault.json"),
                  ollama=_OllamaMorto())


def test_cloud_negada_com_cadeado_mesmo_aprovando(nomos_home):
    """Cadeado ligado: nem um humano aprovando tudo consegue usar a nuvem."""
    r = _router(nomos_home, approver=lambda d: True)
    out = r.chat([{"role": "user", "content": "oi"}], prefer_cloud=True,
                 passphrase="qualquer")
    assert out.ok is False and out.route == "degradada"


def test_cloud_negada_sem_aprovacao_com_cadeado_aberto(nomos_home):
    localidade.definir(nomos_home, False)
    r = _router(nomos_home, approver=lambda d: False)   # humano diz não
    out = r.chat([{"role": "user", "content": "oi"}], prefer_cloud=True,
                 passphrase="x")
    assert out.ok is False
    assert "negado" in out.reason or "negad" in out.reason


def test_cloud_negada_sem_aprovador_fail_closed(nomos_home):
    localidade.definir(nomos_home, False)
    r = _router(nomos_home, approver=None)              # CI: sem humano
    out = r.chat([{"role": "user", "content": "oi"}], prefer_cloud=True,
                 passphrase="x")
    assert out.ok is False


def test_cli_chat_cloud_nao_interativo_nega(capsys):
    assert cli.main(["init"]) == 0
    rc = cli.main(["chat", "--cloud", "qual a previsão?"])
    assert rc == 3   # EXIT_DENIED: aprovação impossível fora de TTY
    assert "DEGRADADO" in capsys.readouterr().out


def test_elegibilidade_exige_chave_e_cadeado_aberto(nomos_home):
    nuvem = cat_mod.construir(nomos_home).por_id("anthropic")
    assert epol.elegivel(nuvem, nomos_home).ok is False           # cadeado
    localidade.definir(nomos_home, False)
    assert epol.elegivel(nuvem, nomos_home,
                         chave_configurada=False).ok is False     # sem chave
    e = epol.elegivel(nuvem, nomos_home, chave_configurada=True)
    assert e.ok is True and e.exige_aprovacao is True             # nunca "de graça"


def test_verificacao_de_chave_nao_le_valor(nomos_home):
    """chave_cloud_configurada só olha NOMES — cofre trancado não é aberto."""
    v = Vault(nomos_home / "vault.json")
    assert epol.chave_cloud_configurada(v) is False   # cofre nem existe
