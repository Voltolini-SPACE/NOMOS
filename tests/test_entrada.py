"""MC52 / Fase 3 — `nomos entrada`: LER o que chegou, governado (A3), só leitura.

Contratos: manifesto CONFIÁVEL (senão fail-closed antes de conectar); o gate A3
tem de aprovar (sem aprovação, nada é lido — e o conector NEM é aberto); com o
`ClienteMCP` mockado, o resultado da tool de leitura vira um resumo humano.
"""
import json
from pathlib import Path

from nomos.interface import mcp_catalogo as cat
from nomos.interface.mcp_client import carregar_manifesto
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.simple import rotinas as rot

RAIZ = Path(__file__).resolve().parent.parent
TELE = RAIZ / "examples" / "mcp" / "telegram" / "manifesto.json"
IMAP = RAIZ / "examples" / "mcp" / "email-imap" / "manifesto.json"

_SIM = (lambda d: True)      # aprovador que confirma
_NAO = (lambda d: False)     # aprovador que nega


def _ctx(home):
    home.mkdir(parents=True, exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


class _FakeCli:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def chamar(self, tool, args):
        self.tool, self.args = tool, args
        return {"content": [{"type": "text",
                             "text": json.dumps(self.payload)}]}


def _mock_cliente(monkeypatch, payload):
    from nomos.interface import mcp_client as mc
    monkeypatch.setattr(mc, "ClienteMCP",
                        lambda m, timeout=30.0, base=None: _FakeCli(payload))


def test_entrada_telegram_resume(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(TELE))
    _mock_cliente(monkeypatch, {"mensagens": [
        {"de": "Ana", "texto": "reunião amanhã?"},
        {"de": "Bob", "texto": "orçamento aprovado"}], "next_offset": 11})
    ok, msg = rot.ler_entrada(ctx, "telegram", str(TELE), _SIM)
    assert ok
    assert "chegaram 2" in msg and "Ana" in msg and "reunião" in msg


def test_entrada_email_resume(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(IMAP))
    _mock_cliente(monkeypatch, {"mensagens": [
        {"de": "chefe@ex.com", "assunto": "prazo do relatório"}]})
    ok, msg = rot.ler_entrada(ctx, "email", str(IMAP), _SIM)
    assert ok and "chefe@ex.com" in msg and "prazo" in msg


def test_entrada_caixa_vazia(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(TELE))
    _mock_cliente(monkeypatch, {"mensagens": []})
    ok, msg = rot.ler_entrada(ctx, "telegram", str(TELE), _SIM)
    assert ok and "nada novo" in msg


def test_entrada_fail_closed_sem_confianca(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)     # NÃO confio → recusa antes de conectar
    from nomos.interface import mcp_client as mc

    def boom(*a, **k):
        raise AssertionError("não devia conectar sem confiança")

    monkeypatch.setattr(mc, "ClienteMCP", boom)
    ok, msg = rot.ler_entrada(ctx, "telegram", str(TELE), _SIM)
    assert not ok and "confiável" in msg


def test_entrada_gate_nega_nada_lido(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(TELE))
    from nomos.interface import mcp_client as mc

    def boom(*a, **k):
        raise AssertionError("gate negado não pode abrir o conector")

    monkeypatch.setattr(mc, "ClienteMCP", boom)
    ok, msg = rot.ler_entrada(ctx, "telegram", str(TELE), _NAO)
    assert not ok and "sem a sua aprovação" in msg


def test_entrada_canal_desconhecido(nomos_home):
    ok, msg = rot.ler_entrada(_ctx(nomos_home), "fax", str(TELE), _SIM)
    assert not ok and "desconhecido" in msg


# --------------------------------------------------------------------------
# MC53 / Fase 4 — briefing 2.0: o que chegou + o seu dia
# --------------------------------------------------------------------------

def test_resumo_com_entrada_junta_o_dia(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(TELE))
    _mock_cliente(monkeypatch, {"mensagens": [{"de": "Ana", "texto": "oi"}]})
    texto = rot.resumo_com_entrada(ctx, "telegram", _SIM)
    assert "O que chegou" in texto and "Ana" in texto      # entrada
    assert "O seu dia" in texto and "Briefing local" in texto   # dia local


def test_resumo_mostra_o_dia_mesmo_sem_entrada(nomos_home, monkeypatch):
    ctx = _ctx(nomos_home)                    # NÃO confio → entrada falha
    from nomos.interface import mcp_client as mc
    monkeypatch.setattr(mc, "ClienteMCP", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("não devia conectar sem confiança")))
    texto = rot.resumo_com_entrada(ctx, "telegram", _SIM)
    assert "não li" in texto                  # honesto sobre a entrada
    assert "O seu dia" in texto and "Briefing local" in texto   # dia sempre sai
