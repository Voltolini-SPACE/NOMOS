"""Ciclo Fortaleza Local — o cadeado que mantém tudo na máquina do usuário."""
import pytest

from nomos.kernel import localidade
from nomos.kernel.policy import Category, Effect, PolicyEngine


# ---------- loopback vs externo ----------
@pytest.mark.parametrize("alvo,esperado", [
    ("127.0.0.1", True), ("127.0.0.1:11434", True), ("localhost", True),
    ("localhost:7860", True), ("::1", True), ("[::1]:8188", True),
    ("http://127.0.0.1:11434/api/tags", True),
    ("api.anthropic.com", False), ("https://api.anthropic.com/v1/messages", False),
    ("8.8.8.8", False), ("meuservidor.com:443", False), ("192.168.0.10", False),
])
def test_classifica_loopback(alvo, esperado):
    assert localidade.eh_loopback(alvo) is esperado


# ---------- estado padrão e persistência ----------
def test_padrao_ligado(nomos_home):
    from nomos.kernel import config
    home = config.nomos_home()
    assert localidade.esta_ligado(home) is True          # privacidade por padrão


def test_arquivo_corrompido_fica_ligado(nomos_home):
    from nomos.kernel import config
    home = config.ensure_home()
    (home / localidade.ARQUIVO).write_text("{quebrado")
    assert localidade.esta_ligado(home) is True          # fail-closed a favor da privacidade


def test_toggle_persiste(nomos_home):
    from nomos.kernel import config
    home = config.ensure_home()
    localidade.definir(home, False)
    assert localidade.esta_ligado(home) is False
    localidade.definir(home, True)
    assert localidade.esta_ligado(home) is True


# ---------- a política é o cadeado ----------
def test_politica_nega_egress_externo_em_so_local(tmp_path):
    pol = PolicyEngine(tmp_path / "policy.json")           # home = tmp_path, só-local padrão
    d = pol.decide(Category.NET_EGRESS, target="api.anthropic.com")
    assert d.effect is Effect.DENY
    assert "só-local" in d.reason


def test_politica_permite_loopback_em_so_local(tmp_path):
    pol = PolicyEngine(tmp_path / "policy.json")
    d = pol.decide(Category.NET_EGRESS, target="127.0.0.1:11434")
    assert d.effect is not Effect.DENY                    # motor local não é bloqueado


def test_politica_libera_externo_quando_desplugado(tmp_path):
    localidade.definir(tmp_path, False)                   # usuário plugou a nuvem
    pol = PolicyEngine(tmp_path / "policy.json")
    d = pol.decide(Category.NET_EGRESS, target="api.anthropic.com")
    assert d.effect is Effect.REQUIRE_APPROVAL            # volta a pedir permissão (não DENY)


def test_outras_categorias_intactas_em_so_local(tmp_path):
    pol = PolicyEngine(tmp_path / "policy.json")
    assert pol.decide(Category.READ_LOCAL).effect is Effect.ALLOW
    assert pol.decide(Category.WRITE_LOCAL).effect is Effect.REQUIRE_APPROVAL
    assert pol.decide(Category.DESTRUCTIVE).effect is Effect.DENY


# ---------- efeito ponta a ponta no roteador ----------
def test_router_cloud_bloqueado_por_so_local(tmp_path):
    from nomos.cognition.router import CLOUD_KEY_NAME, Router
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import gate
    from nomos.kernel.vault import Vault

    vault = Vault(tmp_path / "vault.json")
    vault.init("frase-de-teste-123")
    vault.set(CLOUD_KEY_NAME, "sk-teste-000111", "frase-de-teste-123")

    class OllamaOff:
        host = "http://127.0.0.1:11434"
        def available(self): return False
        def chat(self, m): raise RuntimeError

    r = Router(policy=PolicyEngine(tmp_path / "p.json"), gate=gate,
               approver=lambda d: True,   # mesmo aprovando TUDO...
               audit=AuditLog(tmp_path / "a.jsonl"), vault=vault,
               ollama=OllamaOff(), cloud_factory=lambda **k: None)
    out = r.chat([{"role": "user", "content": "oi"}], prefer_cloud=True,
                 passphrase="frase-de-teste-123")
    assert out.ok is False                                # ...a nuvem NÃO sai em só-local
    assert "egress" in out.reason or "negado" in out.reason
