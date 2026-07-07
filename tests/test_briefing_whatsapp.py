"""MC45 — briefing entregue no WhatsApp como ação de rotina (paridade).

Simétrico ao Telegram (MC41/MC42): mesmo caminho governado (trust store →
gate A3 → ClienteMCP → conector), agora pela Cloud API oficial. O teste-
coroa é ponta a ponta SEM internet: uma Cloud API FAKE local (127.0.0.1)
recebe o que o conector REAL (processo stdio) envia após o gate aprovar.
"""
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from nomos.cognition import motores
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.simple import rotinas as rot

RAIZ = Path(__file__).resolve().parent.parent
MANIFESTO = RAIZ / "examples" / "mcp" / "whatsapp-cloud" / "manifesto.json"


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
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


class _CloudApiFake:
    """WhatsApp Cloud API em 127.0.0.1 — grava o que recebeu."""

    def __init__(self):
        self.recebidos: list[dict] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                tam = int(self.headers.get("Content-Length") or 0)
                corpo = json.loads(self.rfile.read(tam).decode() or "{}")
                fake.recebidos.append({"caminho": self.path,
                                       "auth": self.headers.get(
                                           "Authorization", ""),
                                       "corpo": corpo})
                resp = json.dumps({"messages": [{"id": "wamid.OK"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self._srv.server_port}"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def parar(self):
        self._srv.shutdown()
        self._srv.server_close()


# ---------------------------------------------------------------------------
# vocabulário de rotina: validação e preview honestos
# ---------------------------------------------------------------------------
def test_validar_acao_briefing_whatsapp():
    assert rot.validar_acao("briefing-whatsapp:5511999998888") is None
    assert rot.validar_acao("briefing-whatsapp:+5511999998888") is None
    assert rot.validar_acao("briefing-whatsapp:") is not None
    assert rot.validar_acao("briefing-whatsapp:abc") is not None
    assert rot.validar_acao("briefing-whatsapp:12") is not None       # curto


def test_prever_acao_briefing_whatsapp_e_honesta():
    prev = rot.prever_acao("briefing-whatsapp:5511999998888")
    assert "WhatsApp" in prev and "A3" in prev and "aprovação" in prev


def test_sem_confianca_falha_fechado(nomos_home):
    ctx = _ctx(nomos_home)
    ok, msg = rot.entregar_briefing(ctx, "whatsapp", "5511999998888",
                                    MANIFESTO, approver=lambda d: True)
    assert not ok and "confiar" in msg


def test_gate_negado_nada_sai_no_whatsapp(nomos_home):
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    ok, msg = rot.executar_acao(ctx, "briefing-whatsapp:5511999998888",
                                say=lambda *a: None, approver=lambda d: False)
    assert not ok and "aprovação" in msg
    trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "rotina.briefing.entrega_negada" in trilha


# ---------------------------------------------------------------------------
# teste-coroa: automação completa SEM internet
# ---------------------------------------------------------------------------
def test_e2e_rotina_devida_entrega_no_whatsapp(nomos_home, monkeypatch):
    from datetime import datetime

    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    rot.criar(nomos_home, "Briefing WA", "08:00",
              "briefing-whatsapp:5511999998888", ctx["policy"],
              approver=lambda d: True)
    fake = _CloudApiFake()
    monkeypatch.setenv("NOMOS_WHATSAPP_API", fake.url)
    monkeypatch.setenv("NOMOS_WHATSAPP_TOKEN", "EAAG-teste")
    monkeypatch.setenv("NOMOS_WHATSAPP_PHONE_ID", "111222333")
    monkeypatch.setenv("NOMOS_WHATSAPP_MANIFESTO", str(MANIFESTO))
    try:
        oito = datetime.now().replace(hour=8, minute=0)
        resultados = rot.executar_devidas(ctx, agora=oito,
                                          say=lambda *a: None,
                                          approver=lambda d: True)
        assert len(resultados) == 1 and resultados[0]["ok"], resultados
        assert len(fake.recebidos) == 1
        req = fake.recebidos[0]
        assert req["caminho"].endswith("/111222333/messages")
        assert req["auth"] == "Bearer EAAG-teste"
        assert req["corpo"]["to"] == "5511999998888"
        assert "Briefing local" in req["corpo"]["text"]["body"]
        trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
        assert "rotina.briefing.entregue" in trilha
    finally:
        fake.parar()


def test_telegram_continua_funcionando_apos_generalizacao(nomos_home,
                                                          monkeypatch):
    """Anti-regressão: o canal Telegram ainda entrega pela via nova."""
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    tg = RAIZ / "examples" / "mcp" / "telegram" / "manifesto.json"
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(tg))
    ok, msg = rot.entregar_briefing(ctx, "telegram", "424242", tg,
                                    approver=lambda d: False,
                                    say=lambda *a: None)
    assert not ok and "aprovação" in msg     # gate vale igual nos dois canais


def test_canal_desconhecido_recusado(nomos_home):
    ctx = _ctx(nomos_home)
    ok, msg = rot.entregar_briefing(ctx, "telegrama", "1", MANIFESTO,
                                    approver=lambda d: True)
    assert not ok and "canal desconhecido" in msg
