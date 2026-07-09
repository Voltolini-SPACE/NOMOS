"""Fase 4 (MC62) — briefing ENTREGUE no Slack como ação de rotina.

Mesmo caminho governado dos outros canais (trust store → gate A3 → ClienteMCP →
conector), agora pelo Incoming Webhook. Como o conector Slack recusa qualquer
destino fora de ``hooks.slack.com`` (e seu envio real já é testado à parte, com
``urlopen`` mockado), aqui o ``ClienteMCP`` é mockado para provar a LIGAÇÃO
(``_CANAIS`` → args só-texto → gate → auditoria), sem rede.
"""
import io
import json
from pathlib import Path

import pytest

from nomos.cognition import motores
from nomos.interface import mcp_catalogo as cat
from nomos.interface.mcp_client import carregar_manifesto
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.simple import rotinas as rot

RAIZ = Path(__file__).resolve().parent.parent
MANIFESTO = RAIZ / "examples" / "mcp" / "slack" / "manifesto.json"


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _ctx(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "skills").mkdir(exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
            "skills": nomos_home / "skills"}


class _FakeCli:
    """ClienteMCP falso: registra a tool e os args que o briefing mandaria."""
    ultimo = None

    def __init__(self, *a, **k):
        _FakeCli.ultimo = self
        self.tool = self.args = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def chamar(self, tool, args):
        self.tool, self.args = tool, args
        return {"content": [{"type": "text",
                             "text": json.dumps({"enviada": True})}]}


def _mock_cliente(monkeypatch):
    from nomos.interface import mcp_client as mc
    monkeypatch.setattr(mc, "ClienteMCP", _FakeCli)


# --- vocabulário de rotina -------------------------------------------------
def test_validar_acao_briefing_slack():
    # o webhook já é o canal → o que vem depois de ":" é ignorado (sempre válido)
    assert rot.validar_acao("briefing-slack:") is None
    assert rot.validar_acao("briefing-slack:geral") is None


def test_prever_acao_briefing_slack_e_honesta():
    prev = rot.prever_acao("briefing-slack:")
    assert "Slack" in prev and "A3" in prev and "aprovação" in prev


# --- entrega governada -----------------------------------------------------
def test_sem_confianca_falha_fechado(nomos_home):
    ok, msg = rot.entregar_briefing(_ctx(nomos_home), "slack", "",
                                    MANIFESTO, approver=lambda d: True,
                                    say=lambda *a: None)
    assert not ok and "confiar" in msg


def test_gate_negado_nada_sai_no_slack(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    from nomos.interface import mcp_client as mc

    def boom(*a, **k):
        raise AssertionError("gate negado não pode abrir o conector")

    monkeypatch.setattr(mc, "ClienteMCP", boom)
    ok, msg = rot.executar_acao(ctx, "briefing-slack:", say=lambda *a: None,
                                approver=lambda d: False)
    assert not ok and "aprovação" in msg
    trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "rotina.briefing.entrega_negada" in trilha


def test_entrega_no_slack_manda_so_texto(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    _mock_cliente(monkeypatch)
    ok, msg = rot.executar_acao(ctx, "briefing-slack:", say=lambda *a: None,
                                approver=lambda d: True)
    assert ok
    # o webhook é o canal: os args levam SÓ o texto (sem destino/número)
    assert _FakeCli.ultimo.tool == "slack_enviar"
    assert set(_FakeCli.ultimo.args) == {"texto"}
    assert "Briefing local" in _FakeCli.ultimo.args["texto"]
    trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "rotina.briefing.entregue" in trilha


def test_outros_canais_intactos(nomos_home, monkeypatch):
    """Anti-regressão: adicionar Slack não mexeu nos canais com destino."""
    tg = RAIZ / "examples" / "mcp" / "telegram" / "manifesto.json"
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(tg))
    _mock_cliente(monkeypatch)
    ok, _ = rot.executar_acao(ctx, "briefing-telegram:424242",
                              say=lambda *a: None, approver=lambda d: True)
    assert ok
    assert _FakeCli.ultimo.tool == "telegram_enviar"
    assert _FakeCli.ultimo.args["chat_id"] == "424242"     # destino preservado
