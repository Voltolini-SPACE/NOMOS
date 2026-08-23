"""Senha errada no painel não pode aprovar gate nenhum.

Defeito que este teste prende: `montar_runner_omniroute` decide A2 (egresso) e
A3 (uso de credencial) e SÓ DEPOIS usa a passphrase. Como o painel passava um
approver que sempre dizia sim, uma senha errada ainda produzia dois eventos de
gate APROVADO na auditoria — consentimento afirmado antes de ser provado.
"""
from __future__ import annotations


import pytest

from nomos.interface import painel_web as pw


class _CofreFalso:
    """Só abre com a senha certa — como o de verdade."""

    def __init__(self, senha_certa="certa"):
        self.senha_certa = senha_certa
        self.tentativas: list[str] = []

    def exists(self):
        return True

    def names(self):
        return ["omniroute_api_key"]

    def get(self, nome, passphrase):
        self.tentativas.append(passphrase)
        if passphrase != self.senha_certa:
            raise ValueError("passphrase inválida")
        return "sk-chave-de-teste"


class _AuditEspiao:
    def __init__(self):
        self.eventos: list[str] = []

    def append(self, evento, **kw):
        self.eventos.append(evento)


@pytest.fixture
def ctx(tmp_path):
    return {"home": tmp_path, "audit": _AuditEspiao(), "policy": None}


def _instalar(monkeypatch, cofre):
    monkeypatch.setattr("nomos.kernel.vault.Vault", lambda *a, **k: cofre)
    # o cadeado precisa estar desligado para a cadeia sequer começar
    monkeypatch.setattr("nomos.kernel.localidade.esta_ligado", lambda *a: False)


def test_senha_errada_nao_aprova_gate_nenhum(monkeypatch, ctx):
    """O coração do teste: a senha errada tem de barrar ANTES dos gates."""
    cofre = _CofreFalso()
    _instalar(monkeypatch, cofre)
    chamou_gate = []
    import nomos.cognition.relay as relay
    real = relay.montar_runner_omniroute

    def espiao(*a, **k):
        chamou_gate.append(True)
        return real(*a, **k)

    monkeypatch.setattr(relay, "montar_runner_omniroute", espiao)

    txt, motivo = pw.responder_nuvem(ctx, [{"role": "user", "content": "oi"}],
                                     "ERRADA")
    assert txt is None
    assert "senha-mestra não confere" in motivo
    # nenhum gate foi sequer consultado — logo nada foi auditado como aprovado
    assert chamou_gate == [], "os gates rodaram com a senha errada"
    assert ctx["audit"].eventos == [], f"auditou {ctx['audit'].eventos}"


def test_sem_passphrase_recusa_antes_de_tudo(monkeypatch, ctx):
    cofre = _CofreFalso()
    _instalar(monkeypatch, cofre)
    txt, motivo = pw.responder_nuvem(ctx, [], "")
    assert txt is None and "senha-mestra" in motivo
    assert cofre.tentativas == [], "tentou abrir o cofre sem senha"


def test_senha_certa_prova_posse_antes_do_gate(monkeypatch, ctx):
    """Com a senha certa, o cofre é aberto ANTES de montar o runner."""
    cofre = _CofreFalso()
    _instalar(monkeypatch, cofre)
    ordem: list[str] = []
    cofre_get = cofre.get

    def get_marcado(nome, pp):
        ordem.append("cofre")
        return cofre_get(nome, pp)

    cofre.get = get_marcado
    import nomos.cognition.relay as relay
    monkeypatch.setattr(relay, "montar_runner_omniroute",
                        lambda *a, **k: (ordem.append("gate"), (None, "parado no teste"))[1])

    pw.responder_nuvem(ctx, [{"role": "user", "content": "oi"}], "certa")
    assert ordem[:2] == ["cofre", "gate"], f"ordem errada: {ordem}"
