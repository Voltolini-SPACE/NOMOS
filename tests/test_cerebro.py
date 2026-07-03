"""Cérebro embutido leve — seleção por RAM, download (fake), provider (fake llama)."""
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nomos.cognition import embutido as emb


# ---------- RAM e recomendação ----------
def test_ram_positiva():
    assert emb.ram_gb() > 0


@pytest.mark.parametrize("ram,esperado", [
    (1.5, "nomos-mini"), (2.0, "nomos-mini"), (3.9, "nomos-mini"),
    (4.0, "nomos-base"), (7.0, "nomos-base"), (8.0, "nomos-plus"), (32.0, "nomos-max"),    # v0.18: catálogo estendido — 32 GB usa o maior
    (12.0, "nomos-plus"),
])
def test_recomendado_por_ram(ram, esperado):
    assert emb.recomendado(ram).id == esperado


def test_por_id_desconhecido():
    with pytest.raises(emb.CerebroIndisponivel):
        emb.por_id("nomos-super")


# ---------- download real contra servidor fake local ----------
class _H(BaseHTTPRequestHandler):
    conteudo = b"GGUF" + b"\x00" * (700 * 1024)   # ~700KB fingindo ser o modelo
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.conteudo)))
        self.end_headers()
        self.wfile.write(self.conteudo)


@pytest.fixture()
def servidor():
    s = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}/modelo.gguf"
    s.shutdown()


def _modelo_fake(url, mb=0.7):
    return emb.ModeloGGUF("teste", "modelo de teste", mb, 0.0, url, "teste.gguf")


def test_baixar_grava_e_marca_baixado(servidor, tmp_path):
    m = _modelo_fake(servidor)
    assert emb.esta_baixado(tmp_path, m) is False
    prog = []
    cam = emb.baixar(tmp_path, m, progresso=lambda r, t: prog.append((r, t)))
    assert cam.exists() and cam.read_bytes().startswith(b"GGUF")
    assert emb.esta_baixado(tmp_path, m) is True
    assert prog and prog[-1][0] == prog[-1][1]        # progresso chegou a 100%


def test_baixar_recusa_esquema_nao_http(tmp_path):
    m = _modelo_fake("file:///etc/passwd")
    with pytest.raises(emb.CerebroIndisponivel):
        emb.baixar(tmp_path, m, timeout=0.5)


def test_baixar_servidor_morto_falha_limpo(tmp_path):
    m = _modelo_fake("http://127.0.0.1:1/x.gguf")
    with pytest.raises(emb.CerebroIndisponivel):
        emb.baixar(tmp_path, m, timeout=0.5)
    assert not (tmp_path / "cerebros" / "teste.gguf").exists()   # nada pela metade


# ---------- provider com llama_cpp FALSO injetado ----------
def _instala_llama_fake(monkeypatch, resposta="olá do cérebro leve"):
    mod = types.ModuleType("llama_cpp")
    class Llama:
        def __init__(self, **kw): self.kw = kw
        def create_chat_completion(self, messages, **kw):
            return {"choices": [{"message": {"content": resposta}}]}
    mod.Llama = Llama
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)


def test_provider_indisponivel_sem_motor(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_cpp", None)   # simula ausência
    p = emb.EmbeddedProvider(tmp_path)
    assert p.disponivel() is False


def test_provider_chat_com_llama_fake(servidor, tmp_path, monkeypatch):
    _instala_llama_fake(monkeypatch)
    m = _modelo_fake(servidor)
    monkeypatch.setattr(emb, "CATALOGO", [m])
    monkeypatch.setattr(emb, "PADRAO", "teste")
    emb.baixar(tmp_path, m)                       # baixa o "modelo"
    p = emb.EmbeddedProvider(tmp_path, modelo_id="teste")
    assert p.disponivel() is True
    r = p.chat([{"role": "user", "content": "oi"}])
    assert r.text == "olá do cérebro leve" and r.provider == "embutido"


def test_provider_sem_download_erro_claro(tmp_path, monkeypatch):
    _instala_llama_fake(monkeypatch)
    p = emb.EmbeddedProvider(tmp_path, modelo_id="nomos-mini")
    with pytest.raises(emb.CerebroIndisponivel, match="baixad"):
        p.chat([{"role": "user", "content": "oi"}])
