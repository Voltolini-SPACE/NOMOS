"""C3 — providers contra servidores HTTP locais REAIS (stdlib), sem mocks de rede."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nomos.cognition.providers import (
    AnthropicProvider, OllamaProvider, ProviderUnavailable,
)


class _Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):  # silencioso
        pass

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": "fake"}]})
        else:
            self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
        if self.path == "/api/chat":
            self._json(200, {"model": body["model"],
                             "message": {"role": "assistant", "content": "olá do ollama fake"}})
        elif self.path == "/v1/messages":
            if self.headers.get("x-api-key") != "sk-teste-valida-000":
                self._json(401, {"error": "bad key"})
            else:
                self._json(200, {"model": body["model"],
                                 "content": [{"type": "text", "text": "olá da cloud fake"}]})
        else:
            self._json(404, {})

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def server():
    _Handler.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_ollama_available_e_chat(server):
    p = OllamaProvider(host=server, model="fake")
    assert p.available() is True
    r = p.chat([{"role": "user", "content": "oi"}])
    assert r.text == "olá do ollama fake" and r.provider == "ollama"
    req = _Handler.seen[-1]
    assert req["body"]["stream"] is False and req["body"]["model"] == "fake"


def test_ollama_indisponivel_probe_false():
    p = OllamaProvider(host="http://127.0.0.1:1", probe_timeout=0.3)
    assert p.available() is False


def test_anthropic_chat_shape_e_headers(server):
    p = AnthropicProvider(api_key="sk-teste-valida-000", model="claude-sonnet-4-5",
                          url=f"{server}/v1/messages")
    r = p.chat([{"role": "system", "content": "seja direto"},
                {"role": "user", "content": "oi"}])
    assert r.text == "olá da cloud fake"
    req = _Handler.seen[-1]
    hdr = {k.lower(): v for k, v in req["headers"].items()}   # urllib capitaliza
    assert hdr.get("x-api-key") == "sk-teste-valida-000"
    assert hdr.get("anthropic-version") == "2023-06-01"
    assert req["body"]["system"] == "seja direto"
    assert req["body"]["messages"] == [{"role": "user", "content": "oi"}]
    assert "max_tokens" in req["body"]


def test_anthropic_http_erro_sem_vazar_chave(server):
    p = AnthropicProvider(api_key="sk-chave-errada-999", url=f"{server}/v1/messages")
    with pytest.raises(ProviderUnavailable) as ei:
        p.chat([{"role": "user", "content": "oi"}])
    assert "sk-chave-errada-999" not in str(ei.value)
    assert "sk-chave-errada-999" not in repr(p)


def test_conexao_recusada_vira_provider_unavailable():
    p = AnthropicProvider(api_key="sk-x-0000000000", url="http://127.0.0.1:1/v1/messages",
                          timeout=0.3)
    with pytest.raises(ProviderUnavailable):
        p.chat([{"role": "user", "content": "oi"}])
