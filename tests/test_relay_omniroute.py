"""O OmniRoute como motor governado: cada barreira nega sozinha.

O roteador fala por 127.0.0.1:20128, mas SAI para a internet. A cadeia aqui é
a mesma de `arbitragem.montar_runner_nuvem` — cadeado, A2, A3, cofre — com uma
diferença deliberada: o alvo declarado ao PDP é `RELAY_TARGET`, não o socket.
Perguntar pelo socket faria o operador ler "127.0.0.1:20128" no prompt e
aprovar achando que é um motor local.
"""
from __future__ import annotations

import pytest

from nomos.cognition import relay
from nomos.kernel import localidade
from nomos.kernel.policy import Category, Effect, PolicyEngine


class _CofreFake:
    def __init__(self, chaves=None, erro=None):
        self._c = chaves or {}
        self._erro = erro

    def get(self, nome, _passphrase):
        if self._erro:
            raise RuntimeError(self._erro)
        return self._c[nome]


@pytest.fixture
def ambiente(tmp_path):
    localidade.definir(tmp_path, ligado=False)          # nuvem permitida
    policy = PolicyEngine(tmp_path / "policy.json")
    cofre = _CofreFake({relay.RELAY_KEY_NAME: "chave-de-teste"})
    return tmp_path, policy, cofre


def _montar(home, policy, cofre, **kw):
    kw.setdefault("approver", lambda _d: True)
    kw.setdefault("passphrase", "senha")
    return relay.montar_runner_omniroute(home, policy=policy, vault=cofre, **kw)


# ------------------------------------------------------------ caminho feliz
def test_com_tudo_aprovado_monta_o_provedor(ambiente):
    home, policy, cofre = ambiente
    prov, motivo = _montar(home, policy, cofre)
    assert prov is not None and motivo == ""
    assert prov.name == "omniroute"


def test_a_chave_vem_do_cofre_e_nao_do_env(ambiente):
    home, policy, cofre = ambiente
    capturado = {}
    prov, _ = _montar(home, policy, cofre,
                      factory=lambda api_key, modelo: capturado.update(
                          {"key": api_key, "modelo": modelo}) or object())
    assert capturado["key"] == "chave-de-teste"
    assert capturado["modelo"] == relay.MODELO_PADRAO


# ------------------------------------------------------- cada barreira nega
def test_cadeado_ligado_bloqueia_mesmo_com_aprovador_dizendo_sim(tmp_path):
    """A barreira que NÃO depende de parsear host."""
    localidade.definir(tmp_path, ligado=True)
    policy = PolicyEngine(tmp_path / "policy.json")
    prov, motivo = _montar(tmp_path, policy, _CofreFake({relay.RELAY_KEY_NAME: "x"}))
    assert prov is None
    assert "cadeado só-local LIGADO" in motivo


def test_gate_A2_negado_bloqueia(ambiente):
    home, policy, cofre = ambiente
    prov, motivo = _montar(home, policy, cofre, gate=lambda d, _a:
                           d.category != Category.NET_EGRESS.value)
    assert prov is None and "A2" in motivo


def test_gate_A3_negado_bloqueia(ambiente):
    home, policy, cofre = ambiente
    prov, motivo = _montar(home, policy, cofre, gate=lambda d, _a:
                           d.category != Category.CRED_USE.value)
    assert prov is None and "A3" in motivo


def test_sem_passphrase_bloqueia(ambiente):
    home, policy, cofre = ambiente
    prov, motivo = _montar(home, policy, cofre, passphrase=None)
    assert prov is None and "passphrase" in motivo


def test_chave_ausente_no_cofre_bloqueia(ambiente):
    home, policy, _ = ambiente
    prov, motivo = _montar(home, policy, _CofreFake(erro="não existe"))
    assert prov is None and relay.RELAY_KEY_NAME in motivo


# ---------------------------------------------- o alvo declarado é honesto
def test_alvo_do_gate_NAO_e_loopback(tmp_path):
    """Se fosse, o cadeado o isentaria e o operador leria um endereço local."""
    assert not localidade.eh_loopback(relay.RELAY_TARGET)
    localidade.definir(tmp_path, ligado=True)
    assert localidade.bloqueia_egress(tmp_path, relay.RELAY_TARGET)


def test_o_socket_real_tambem_e_tratado_como_egresso(tmp_path):
    """Cinto e suspensório: mesmo quem perguntasse pelo socket seria barrado,
    porque 20128 está em PORTAS_DE_RELAY."""
    localidade.definir(tmp_path, ligado=True)
    assert localidade.bloqueia_egress(tmp_path, "127.0.0.1:20128")


def test_provider_recusa_ser_construido_sem_chave():
    from nomos.cognition.providers import OmniRouteProvider
    with pytest.raises(ValueError, match="exige chave"):
        OmniRouteProvider(api_key="")


def test_chave_nao_vaza_no_repr():
    from nomos.cognition.providers import OmniRouteProvider
    p = OmniRouteProvider(api_key="segredo-que-nao-pode-aparecer")
    assert "segredo" not in repr(p)


# ------------------------------------------------------ descoberta automática
def test_descoberta_nao_autoriza_nada(ambiente, monkeypatch):
    """A fronteira: descobrir lista, não libera. Uma rota nova NÃO vira ativa.

    Se descoberta autorizasse, adicionar uma chave no painel do OmniRoute
    criaria um caminho de saída que ninguém aprovou — exatamente o oposto do
    modelo do NOMOS.
    """
    home, policy, cofre = ambiente
    monkeypatch.setattr(relay, "descobrir_rotas",
                        lambda *a, **k: ["auto/best-free", "oc/novo-provedor-free"])
    assert "oc/novo-provedor-free" in relay.rotas_gratuitas("k")
    # descobriu, mas usar continua exigindo a cadeia inteira:
    prov, motivo = _montar(home, policy, cofre, gate=lambda d, _a:
                           d.category != Category.NET_EGRESS.value)
    assert prov is None and "A2" in motivo


def test_descoberta_filtra_gratuitas(monkeypatch):
    monkeypatch.setattr(relay, "descobrir_rotas", lambda *a, **k: [
        "auto/best-free", "anthropic/claude-opus", "oc/hy3-free", "openai/gpt-5"])
    assert relay.rotas_gratuitas("k") == ["auto/best-free", "oc/hy3-free"]


def test_falha_de_descoberta_nao_derruba(monkeypatch):
    """Serviço fora do ar não pode quebrar quem só queria conversar."""
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    from nomos.cognition import motores
    motores._CACHE.clear() if hasattr(motores, "_CACHE") else None
    assert relay.descobrir_rotas("k", base="http://127.0.0.1:59999/v1") == []


def test_resumo_tem_o_que_o_operador_precisa(monkeypatch):
    monkeypatch.setattr(relay, "descobrir_rotas",
                        lambda *a, **k: ["auto/best-free", "openai/gpt-5"])
    r = relay.resumo_descoberta("k")
    assert r == {"total": 2, "gratuitas": 1,
                 "rotas_gratuitas": ["auto/best-free"], "disponivel": True}
