"""Um roteador em loopback NÃO é motor local — o cadeado tem de vê-lo.

A isenção de loopback do modo só-local (kernel/localidade.py) assume que todo
serviço em 127.0.0.1 é TERMINAL: Ollama, Stable Diffusion, ComfyUI e piper
executam na máquina e param ali. Em 23/08/2026 foi instalado um roteador de
LLM (OmniRoute, porta 20128) cuja função é justamente SAIR para a internet —
a premissa deixou de valer.

Medido antes da correção, com o cadeado LIGADO:
    api.anthropic.com   bloqueia_egress=True   DENY
    127.0.0.1:20128     bloqueia_egress=False  REQUIRE_APPROVAL   <- passava
e o operador leria "127.0.0.1:20128" no prompt, que parece um motor local.
"""
from __future__ import annotations

import pytest

from nomos.kernel import localidade
from nomos.kernel.policy import Category, PolicyEngine, gate

RELAY = next(iter(localidade.PORTAS_DE_RELAY))
MOTORES_LOCAIS = ("127.0.0.1:11434", "http://127.0.0.1:11434/api/tags",
                  "localhost:7860", "[::1]:8188", "http://127.0.0.1:1234/v1")


@pytest.fixture
def home_trancado(tmp_path):
    """Cadeado LIGADO — é o default por ausência do arquivo (fail-closed)."""
    assert localidade.esta_ligado(tmp_path)
    return tmp_path


@pytest.mark.parametrize("alvo", [
    f"127.0.0.1:{RELAY}", f"localhost:{RELAY}",
    f"http://127.0.0.1:{RELAY}/v1/chat/completions", f"[::1]:{RELAY}",
])
def test_relay_em_loopback_e_bloqueado(home_trancado, alvo):
    assert localidade.eh_loopback(alvo), "o alvo É loopback — esse é o ponto"
    assert localidade.eh_relay_declarado(alvo)
    assert localidade.bloqueia_egress(home_trancado, alvo), \
        f"{alvo} roteia para a internet; o cadeado tem de negar"


@pytest.mark.parametrize("alvo", MOTORES_LOCAIS)
def test_motores_locais_de_verdade_continuam_livres(home_trancado, alvo):
    """Anti-regressão: a correção não pode fechar o Ollama nem o SD."""
    assert not localidade.eh_relay_declarado(alvo)
    assert not localidade.bloqueia_egress(home_trancado, alvo)


def test_alvo_remoto_continua_bloqueado(home_trancado):
    assert localidade.bloqueia_egress(home_trancado, "api.anthropic.com")


def test_com_cadeado_desligado_o_relay_passa(tmp_path):
    """Desligar é ato consciente e auditado — aí o relay é permitido."""
    localidade.definir(tmp_path, ligado=False)
    assert not localidade.bloqueia_egress(tmp_path, f"127.0.0.1:{RELAY}")


def test_adversarial_chamada_ao_relay_e_NEGADA_pela_politica(home_trancado):
    """O teste que importa: fim a fim, pela política real, sem atalho."""
    pol = PolicyEngine(home_trancado / "policy.json")
    # PolicyEngine deriva self.home de path.parent (policy.py:102), então o
    # engine criado em home_trancado consulta o cadeado DESSE home.
    assert pol.home == home_trancado
    d = pol.decide(Category.NET_EGRESS, target=f"127.0.0.1:{RELAY}")
    assert not gate(d, lambda _x: True), \
        "com o cadeado ligado, nem um aprovador que diz SIM pode liberar o relay"


def test_provider_recusa_apontar_para_relay():
    """A via da variável de ambiente: NOMOS_OPENAI_COMPAT_BASE -> relay."""
    from nomos.cognition.providers import OpenAICompatProvider
    with pytest.raises(ValueError, match="ROTEADOR"):
        OpenAICompatProvider(base=f"http://127.0.0.1:{RELAY}/v1")


def test_provider_aceita_motor_local_de_verdade():
    from nomos.cognition.providers import OpenAICompatProvider
    assert OpenAICompatProvider(base="http://127.0.0.1:1234/v1") is not None
