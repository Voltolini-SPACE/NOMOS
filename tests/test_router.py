"""C3 — roteador local-first, cloud atrás de A2+A3, degradação transparente."""
import pytest

from nomos.cognition.providers import ChatReply, ProviderUnavailable
from nomos.cognition.router import CLOUD_KEY_NAME, Router
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine, gate
from nomos.kernel.vault import Vault

PASS = "frase-de-teste-123"
MSGS = [{"role": "user", "content": "oi"}]


class FakeOllama:
    host = "http://127.0.0.1:11434"
    def __init__(self, up=True):
        self.up = up
    def available(self):
        return self.up
    def chat(self, messages):
        if not self.up:
            raise ProviderUnavailable("down")
        return ChatReply(text="resposta local", provider="ollama", model="fake-local")


class FakeCloud:
    def __init__(self, api_key, **kw):
        self.key = api_key
    def chat(self, messages):
        assert self.key == "sk-teste-cloud-000111"
        return ChatReply(text="resposta cloud", provider="anthropic", model="fake-cloud")


def approver_sim(decision):
    return True


def approver_nao(decision):
    return False


@pytest.fixture()
def ctx(tmp_path):
    vault = Vault(tmp_path / "vault.json")
    vault.init(PASS)
    vault.set(CLOUD_KEY_NAME, "sk-teste-cloud-000111", PASS)
    return {
        "policy": PolicyEngine(tmp_path / "policy.json"),
        "audit": AuditLog(tmp_path / "audit.jsonl"),
        "vault": vault,
    }


def mk_router(ctx, up=True, approver=approver_nao):
    return Router(policy=ctx["policy"], gate=gate, approver=approver,
                  audit=ctx["audit"], vault=ctx["vault"],
                  ollama=FakeOllama(up=up), cloud_factory=FakeCloud)


def test_local_first_sem_gate(ctx):
    out = mk_router(ctx).chat(MSGS)
    assert out.ok and out.route == "local" and out.text == "resposta local"
    tail = ctx["audit"].path.read_text()
    assert '"event":"chat.local"' in tail and '"egress":"nenhum"' in tail


def test_sem_local_sem_optin_degrada_transparente(ctx):
    out = mk_router(ctx, up=False).chat(MSGS)
    assert out.ok is False and out.route == "degradada"
    assert "NÃO simula" in out.text and out.reason
    assert "chat.degradado" in ctx["audit"].path.read_text()


def test_cloud_optin_negado_no_gate_cai_para_local(ctx):
    out = mk_router(ctx, up=True, approver=approver_nao).chat(MSGS, prefer_cloud=True)
    assert out.ok and out.route == "local"          # fallback explícito
    assert "cloud indisponível" in out.reason
    assert "chat.cloud.negado" in ctx["audit"].path.read_text()


def test_cloud_optin_negado_sem_local_degrada(ctx):
    out = mk_router(ctx, up=False, approver=approver_nao).chat(MSGS, prefer_cloud=True)
    assert not out.ok and out.route == "degradada"
    assert "negado" in out.reason


def test_cloud_aprovado_a2_a3_com_chave_do_cofre(ctx, tmp_path):
    from nomos.kernel import localidade
    localidade.definir(tmp_path, False)   # usuário plugou a nuvem (saiu do só-local)
    out = mk_router(ctx, up=False, approver=approver_sim).chat(
        MSGS, prefer_cloud=True, passphrase=PASS)
    assert out.ok and out.route == "cloud" and out.text == "resposta cloud"
    log = ctx["audit"].path.read_text()
    assert "chat.cloud.aprovado" in log and "api.anthropic.com" in log
    assert "sk-teste-cloud-000111" not in log       # chave jamais no log


def test_cloud_sem_passphrase_degrada_sem_tocar_cofre(ctx, tmp_path):
    from nomos.kernel import localidade
    localidade.definir(tmp_path, False)
    out = mk_router(ctx, up=False, approver=approver_sim).chat(
        MSGS, prefer_cloud=True, passphrase=None)
    assert not out.ok and "passphrase" in out.reason


def test_cloud_sem_chave_no_cofre_degrada(tmp_path):
    from nomos.kernel import localidade
    localidade.definir(tmp_path, False)
    vault = Vault(tmp_path / "v.json")
    vault.init(PASS)   # cofre SEM a chave
    ctx = {"policy": PolicyEngine(tmp_path / "p.json"),
           "audit": AuditLog(tmp_path / "a.jsonl"), "vault": vault}
    out = mk_router(ctx, up=False, approver=approver_sim).chat(
        MSGS, prefer_cloud=True, passphrase=PASS)
    assert not out.ok and CLOUD_KEY_NAME in out.reason
