"""NH-001 — registro dinâmico governado de capacidades (orquestracao.registro).

Invariantes cobertos:
- as 8 ferramentas nativas do manifesto são conhecidas com a categoria certa;
- capacidade desconhecida => categoria None e risco A6 (pior caso, fail-closed);
- registrar exige: nome válido, Category real, executor chamável, origem;
- registrar é ato sensível: passa pelo MESMO policy.gate (A5); sem aprovador
  => negado fail-closed; sem política => negado (nunca degrada para permitir);
- nativa não pode ser sombreada nem removida (anti-hijack);
- tudo auditado; remoção só de dinâmicas.
"""
from __future__ import annotations

import pytest

from nomos.agents.manifest import FERRAMENTAS
from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.registro import (
    Capacidade, ErroRegistro, RegistroCapacidades,
)


class AuditFake:
    def __init__(self):
        self.eventos: list[tuple[str, dict]] = []

    def append(self, evento: str, **campos) -> None:
        self.eventos.append((evento, campos))

    def nomes(self) -> list[str]:
        return [e for e, _ in self.eventos]


@pytest.fixture()
def policy(tmp_path):
    return PolicyEngine(tmp_path / "policy.json")


def _registro(policy, approver=None, audit=None):
    return RegistroCapacidades(policy=policy, approver=approver, audit=audit)


# ---------- nativas ----------

def test_nativas_todas_conhecidas(policy):
    reg = _registro(policy)
    for nome, categoria in FERRAMENTAS.items():
        assert reg.conhecida(nome)
        assert reg.categoria_de(nome) is categoria


def test_nativa_risco_correto(policy):
    reg = _registro(policy)
    assert reg.risco_de("arquivo_ler") == "A0"
    assert reg.risco_de("arquivo_escrever") == "A1"
    assert reg.risco_de("skill_rodar") == "A5"


# ---------- desconhecida => fail-closed ----------

def test_desconhecida_categoria_none_e_risco_a6(policy):
    reg = _registro(policy)
    assert not reg.conhecida("inexistente")
    assert reg.categoria_de("inexistente") is None
    assert reg.risco_de("inexistente") == "A6"
    assert reg.executor_de("inexistente") is None


# ---------- validação de entrada ----------

def test_registrar_nome_invalido(policy):
    reg = _registro(policy, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.registrar("Nome Inválido!", Category.READ_LOCAL, lambda: None, "teste")


def test_registrar_categoria_invalida(policy):
    reg = _registro(policy, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.registrar("minha-tool", "A9_FANTASIA", lambda: None, "teste")


def test_registrar_executor_nao_chamavel(policy):
    reg = _registro(policy, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.registrar("minha-tool", Category.READ_LOCAL, "nao-callable", "teste")


def test_registrar_origem_obrigatoria(policy):
    reg = _registro(policy, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.registrar("minha-tool", Category.READ_LOCAL, lambda: None, "")


# ---------- anti-hijack ----------

def test_nao_sombreia_nativa(policy):
    reg = _registro(policy, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.registrar("arquivo_ler", Category.READ_LOCAL, lambda: None, "malicioso")


def test_nao_remove_nativa(policy):
    reg = _registro(policy, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.desregistrar("arquivo_ler")


# ---------- gate obrigatório ----------

def test_registrar_sem_aprovador_negado(policy):
    """A5_SKILL_INSTALL exige aprovação; sem aprovador => fail-closed."""
    audit = AuditFake()
    reg = _registro(policy, approver=None, audit=audit)
    with pytest.raises(ErroRegistro):
        reg.registrar("minha-tool", Category.READ_LOCAL, lambda: None, "teste")
    assert "registro.capacidade.negada" in audit.nomes()
    assert not reg.conhecida("minha-tool")


def test_registrar_sem_politica_negado():
    reg = RegistroCapacidades(policy=None, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.registrar("minha-tool", Category.READ_LOCAL, lambda: None, "teste")


def test_registrar_com_aprovacao_ok(policy):
    audit = AuditFake()
    reg = _registro(policy, approver=lambda d: True, audit=audit)
    cap = reg.registrar("minha-tool", Category.READ_LOCAL, lambda: "ok", "teste")
    assert isinstance(cap, Capacidade)
    assert reg.conhecida("minha-tool")
    assert reg.categoria_de("minha-tool") is Category.READ_LOCAL
    assert reg.risco_de("minha-tool") == "A0"
    assert reg.executor_de("minha-tool")() == "ok"
    assert "registro.capacidade.registrada" in audit.nomes()


def test_aprovador_que_levanta_nega(policy):
    def aprovador_quebrado(d):
        raise RuntimeError("boom")
    reg = _registro(policy, approver=aprovador_quebrado)
    with pytest.raises(ErroRegistro):
        reg.registrar("minha-tool", Category.READ_LOCAL, lambda: None, "teste")


# ---------- remoção de dinâmica ----------

def test_desregistrar_dinamica_ok(policy):
    audit = AuditFake()
    reg = _registro(policy, approver=lambda d: True, audit=audit)
    reg.registrar("minha-tool", Category.READ_LOCAL, lambda: None, "teste")
    reg.desregistrar("minha-tool")
    assert not reg.conhecida("minha-tool")
    assert "registro.capacidade.removida" in audit.nomes()


def test_desregistrar_desconhecida_erro(policy):
    reg = _registro(policy, approver=lambda d: True)
    with pytest.raises(ErroRegistro):
        reg.desregistrar("nunca-existiu")


# ---------- nativas não têm executor implícito ----------

def test_nativa_sem_executor_implicito(policy):
    """Execução de nativas continua no wiring explícito (agents/execucao);
    o registro só responde identidade+categoria — nunca inventa executor."""
    reg = _registro(policy)
    assert reg.executor_de("arquivo_ler") is None
