"""A localidade é uma ESCOLHA declarada, não uma regra imposta em silêncio.

Antes, o cadeado nascia LIGADO e o onboarding nunca tocava no assunto: na
prática, regra da casa. Agora o passo 4/5 pergunta. O default para quem não
escolhe continua LIGADO — fail-closed a favor da privacidade —, mas a diferença
é que passou a ser decisão declarada.
"""
from __future__ import annotations

import json

from nomos.kernel import localidade
from nomos.simple import onboarding


def _rodar(monkeypatch, tmp_path, respostas):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    fila = list(respostas)
    ditas = []
    onboarding.run_onboarding(ask=lambda _p: fila.pop(0) if fila else "",
                              say=lambda t="": ditas.append(str(t)),
                              ask_secret=lambda _p: "", colorido=False)
    return "\n".join(ditas)


def test_onboarding_PERGUNTA_sobre_localidade(monkeypatch, tmp_path):
    saida = _rodar(monkeypatch, tmp_path, ["ZEUS", "1", "1", "", ""])
    assert "4/5 · Onde seus dados podem ir?" in saida
    assert "5 passinhos" in saida
    assert "regra da casa" not in saida, "deixou de ser regra imposta"


def test_escolher_nuvem_desliga_o_cadeado(monkeypatch, tmp_path):
    saida = _rodar(monkeypatch, tmp_path, ["ZEUS", "1", "2", "", ""])
    assert not localidade.esta_ligado(tmp_path)
    assert json.loads((tmp_path / "agent.json").read_text())["so_local"] is False
    # a escolha não relaxa o gate: cada saída ainda pede aprovação
    assert "pede aprovação explícita" in saida


def test_enter_mantem_protegido(monkeypatch, tmp_path):
    """Quem não escolhe continua fail-closed."""
    _rodar(monkeypatch, tmp_path, ["ZEUS", "1", "", "", ""])
    assert localidade.esta_ligado(tmp_path)
    assert json.loads((tmp_path / "agent.json").read_text())["so_local"] is True


def test_escolher_so_local_explicitamente(monkeypatch, tmp_path):
    _rodar(monkeypatch, tmp_path, ["ZEUS", "1", "1", "", ""])
    assert localidade.esta_ligado(tmp_path)


def test_cadeado_desligado_NAO_abre_egresso_sem_aprovacao(tmp_path):
    """A escolha muda de 'negado sempre' para 'pergunta sempre' — não para livre."""
    from nomos.kernel.policy import Category, Effect, PolicyEngine, gate
    localidade.definir(tmp_path, ligado=False)
    pol = PolicyEngine(tmp_path / "policy.json")
    d = pol.decide(Category.NET_EGRESS, target="api.anthropic.com")
    assert d.effect is Effect.REQUIRE_APPROVAL
    assert gate(d, None) is False, "sem aprovador, continua negado"
