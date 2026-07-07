"""MC41 — briefing diário entregue no Telegram, com TODAS as leis da casa.

O teste-coroa é ponta a ponta SEM internet: uma Bot API FAKE local (HTTP
em 127.0.0.1) recebe o que o conector REAL (processo stdio) envia, depois
que o gate aprovou. Prova o encanamento inteiro: rotina → trust store →
política/gate → ClienteMCP → servidor MCP → "Telegram".
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
MANIFESTO = RAIZ / "examples" / "mcp" / "telegram" / "manifesto.json"


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


class _BotApiFake:
    """Bot API do Telegram em 127.0.0.1 — grava o que recebeu."""

    def __init__(self):
        self.recebidos: list[dict] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                tam = int(self.headers.get("Content-Length") or 0)
                corpo = json.loads(self.rfile.read(tam).decode() or "{}")
                fake.recebidos.append({"caminho": self.path, "corpo": corpo})
                resp = json.dumps({"ok": True, "result": {
                    "message_id": 77,
                    "chat": {"id": corpo.get("chat_id")}}}).encode()
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


def test_sem_confianca_falha_fechado(nomos_home):
    ctx = _ctx(nomos_home)
    ok, msg = rot.enviar_briefing(ctx, "123", MANIFESTO,
                                  approver=lambda d: True)
    assert not ok and "confiar" in msg          # instrui, não finge


def test_gate_negado_nada_sai(nomos_home, monkeypatch):
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    # aprovador nega ⇒ o conector NUNCA é chamado
    import nomos.interface.mcp_client as mc
    monkeypatch.setattr(mc.ClienteMCP, "__enter__", lambda s: (_ for _ in ())
                        .throw(AssertionError("não podia conectar!")))
    ok, msg = rot.enviar_briefing(ctx, "123", MANIFESTO,
                                  approver=lambda d: False)
    assert not ok and "aprovação" in msg
    trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "rotina.briefing.entrega_negada" in trilha


def test_e2e_sem_internet_briefing_chega_na_botapi_fake(nomos_home,
                                                        monkeypatch):
    """Ponta a ponta REAL: gate aprova → conector (processo de verdade)
    → Bot API fake local recebe o briefing. Zero internet."""
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    ctx = _ctx(nomos_home)
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    fake = _BotApiFake()
    monkeypatch.setenv("NOMOS_TELEGRAM_API", fake.url)
    monkeypatch.setenv("NOMOS_TELEGRAM_TOKEN", "999:TESTE")
    try:
        ok, msg = rot.enviar_briefing(ctx, "424242", MANIFESTO,
                                      approver=lambda d: True,
                                      say=lambda *a: None)
        assert ok, msg
        assert "entregue" in msg
        assert len(fake.recebidos) == 1
        req = fake.recebidos[0]
        assert req["caminho"].endswith("/sendMessage")
        assert "999:TESTE" in req["caminho"]        # foi para o bot certo
        assert req["corpo"]["chat_id"] == "424242"
        assert "Briefing local" in req["corpo"]["text"]      # conteúdo real
        trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
        assert "rotina.briefing.entregue" in trilha
    finally:
        fake.parar()


def test_cli_briefing_sem_telegram_continua_igual(nomos_home, capsys):
    """Sem --telegram, o subcomando imprime o briefing como sempre."""
    ctx = _ctx(nomos_home)
    print(rot.briefing(ctx))
    saida = capsys.readouterr().out
    assert "Briefing local" in saida and "nada saiu dela" in saida
