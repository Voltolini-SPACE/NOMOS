"""Ciclo Motores — registry, preferências, persistência, geração real fake-local."""
import base64
import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nomos.cognition import criacao, motores
from nomos.kernel.policy import PolicyEngine, gate

PNG_MINI = base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()


@pytest.fixture(autouse=True)
def _cache_limpo():
    motores.limpar_cache()
    yield
    motores.limpar_cache()


class _Srv(BaseHTTPRequestHandler):
    modelos = []
    def log_message(self, *a): pass
    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [{"name": n} for n in type(self).modelos]})
        elif self.path == "/sdapi/v1/sd-models":
            self._json(200, [{"title": "sd15"}])
        else:
            self._json(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n)) if n else {}
        if self.path == "/sdapi/v1/txt2img":
            type(self).ultimo_prompt = body.get("prompt")
            self._json(200, {"images": [PNG_MINI]})
        else:
            self._json(404, {})


@pytest.fixture()
def srv():
    s = HTTPServer(("127.0.0.1", 0), _Srv)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def aprova(d): return True


# ---------- preferências e detecção ----------
def test_prefere_hermes_para_texto_e_coder_para_codigo(srv, nomos_home):
    _Srv.modelos = ["llama3.2", "hermes3:8b", "qwen2.5-coder:7b", "llava:13b"]
    mapa = motores.detectar(hosts={"ollama": srv, "sd": srv, "comfy": "http://127.0.0.1:9"})
    assert mapa["texto"][0]["id"] == "embutido"        # cérebro leve é o padrão
    assert mapa["texto"][1]["detalhe"] == "hermes3:8b"  # Ollama vem depois
    assert mapa["codigo"][0]["detalhe"] == "qwen2.5-coder:7b"
    assert mapa["imagem"][2]["detalhe"] == "llava:13b"      # visão
    assert mapa["imagem"][0]["disponivel"] is True          # SD fake responde


def test_sem_nada_tudo_indisponivel_com_dicas(nomos_home, monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *_: None)
    mapa = motores.detectar()
    t = motores.tabela(mapa)
    assert t.count("[–]") >= 6 and "dica:" in t
    assert motores.ativo("imagem", mapa) is None
    assert motores.ativo("audio", mapa) is None


# ---------- escolha persistida ----------
def test_escolher_persiste_e_sobrevive_reinicio(srv, nomos_home, monkeypatch):
    _Srv.modelos = ["hermes3:8b", "qwen2.5-coder:7b"]
    monkeypatch.setattr(motores, "OLLAMA", srv)
    perfil = motores.escolher("codigo", "texto")
    assert perfil["motores"]["codigo"]["id"] == "texto"
    from nomos.kernel import config
    relido = config.load_agent()                       # "reinício"
    at = motores.ativo("codigo", perfil=relido)
    assert at and at["id"] == "texto"


def test_escolher_valida_modalidade_e_motor(nomos_home):
    with pytest.raises(ValueError, match="modalidade"):
        motores.escolher("video", "x")
    with pytest.raises(ValueError, match="motor desconhecido"):
        motores.escolher("audio", "caixa-de-som")


def test_escolha_indisponivel_cai_no_primeiro_disponivel(srv, nomos_home, monkeypatch):
    _Srv.modelos = ["hermes3:8b"]
    monkeypatch.setattr(motores, "OLLAMA", srv)
    perfil = motores.escolher("texto", "ollama")
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])  # sumiu!
    motores.limpar_cache()
    # modo só-local (padrão): SEM fallback para a nuvem — fica sem motor
    assert motores.ativo("texto", perfil=perfil) is None
    # usuário pluga a nuvem (sai do só-local): aí sim cai no anthropic
    from nomos.kernel import localidade, config
    localidade.definir(config.nomos_home(), False)
    motores.limpar_cache()
    at = motores.ativo("texto", perfil=perfil)
    assert at["id"] == "anthropic"


# ---------- geração de imagem real (fake SD local) ----------
def test_imagem_gera_png_de_verdade_com_gate(srv, tmp_path, nomos_home):
    pol = PolicyEngine(tmp_path / "p.json")
    cam = criacao.gerar_imagem("um gato astronauta", tmp_path, pol, gate, aprova,
                               host=srv)
    assert cam.exists() and cam.suffix == ".png"
    assert cam.read_bytes().startswith(b"\x89PNG")
    assert "gato-astronauta" in cam.name
    assert oct(cam.stat().st_mode & 0o777) == "0o600"
    assert _Srv.ultimo_prompt == "um gato astronauta"


def test_imagem_gate_negado_nao_salva(srv, tmp_path, nomos_home):
    pol = PolicyEngine(tmp_path / "p.json")
    with pytest.raises(criacao.CriacaoNegada):
        criacao.gerar_imagem("x", tmp_path, pol, gate, lambda d: False, host=srv)
    assert not list((tmp_path / "criacoes").glob("*.png"))


def test_imagem_sem_servidor_mensagem_honesta(tmp_path, nomos_home):
    pol = PolicyEngine(tmp_path / "p.json")
    with pytest.raises(criacao.CriacaoIndisponivel, match="Stable Diffusion"):
        criacao.gerar_imagem("x", tmp_path, pol, gate, aprova,
                             host="http://127.0.0.1:9", timeout=0.4)


# ---------- fala real (fake piper no PATH) ----------
@pytest.fixture()
def piper_fake(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    exe = d / "piper"
    exe.write_text("""#!/bin/sh
out=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--output_file" ]; then out="$2"; shift; fi
  shift
done
cat > /dev/null
printf 'RIFF....WAVEfmt ' > "$out"
""")
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{d}:{os.environ['PATH']}")
    return exe


def test_audio_fala_gera_wav(piper_fake, tmp_path, nomos_home):
    pol = PolicyEngine(tmp_path / "p.json")
    cam = criacao.falar("olá, eu sou a Luna", tmp_path, pol, gate, aprova)
    assert cam.exists() and cam.suffix == ".wav"
    assert cam.read_bytes().startswith(b"RIFF")


def test_audio_sem_piper_dica_honesta(tmp_path, nomos_home, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *_: None)
    pol = PolicyEngine(tmp_path / "p.json")
    with pytest.raises(criacao.CriacaoIndisponivel, match="piper"):
        criacao.falar("oi", tmp_path, pol, gate, aprova)


# ---------- chat: comandos intuitivos ----------
def _chat(perfil, entradas, tmp_path, monkeypatch=None):
    from nomos.simple import amigavel
    feed = iter(entradas)
    tela = []
    ctx = {"home": tmp_path, "policy": PolicyEngine(tmp_path / "p.json")}
    rc = amigavel.iniciar_chat(ctx, perfil, router=None,
                               ask=lambda _: next(feed), say=tela.append,
                               colorido=False, aprovador=aprova)
    return rc, "\n".join(str(x) for x in tela)


def test_chat_motores_e_troca(nomos_home, tmp_path, monkeypatch, srv):
    _Srv.modelos = ["hermes3:8b", "qwen2.5-coder:7b"]
    monkeypatch.setattr(motores, "OLLAMA", srv)
    from nomos.kernel import config
    config.save_agent("Luna")
    perfil = {"agent_name": "Luna", "modo_cerebro": "demo"}
    rc, tela = _chat(perfil, ["/motores", "/motor codigo texto",
                              "/motor video x", "/sair"], tmp_path)
    assert "texto:" in tela and "← ativo" in tela
    assert "codigo agora usa 'texto'" in tela
    assert "modalidade desconhecida" in tela


def test_chat_imagem_sem_motor_orienta(nomos_home, tmp_path, monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    perfil = {"agent_name": "Nina", "modo_cerebro": "demo"}
    rc, tela = _chat(perfil, ["/imagem um dragão", "/sair"], tmp_path)
    assert "não tenho um gerador de imagens" in tela and "Stable Diffusion" in tela
