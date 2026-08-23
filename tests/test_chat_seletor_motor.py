"""O chat do painel deixou de ficar mudo e ganhou seletor de motor/roteamento.

Bug corrigido: responder_local usava default 'llama3.2' (não instalado) e
ignorava o modelo do agent.json — o chat não respondia nada. Agora a origem
do modelo é o perfil, e o composer deixa escolher motor e modo de roteamento.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nomos.interface import painel_web as pw


def test_modelo_vem_do_perfil_nao_de_default_fixo(monkeypatch, tmp_path):
    from nomos.kernel import config
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    config.save_agent("ZEUS")
    from nomos.simple.onboarding import salvar_perfil
    salvar_perfil({"modelo": "qwen3.5:4b-q8_0", "onboarding_completo": True})
    assert pw._modelo_configurado() == "qwen3.5:4b-q8_0"


def test_modelo_demo_nao_conta(monkeypatch, tmp_path):
    from nomos.kernel import config
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    config.save_agent("ZEUS")
    from nomos.simple.onboarding import salvar_perfil
    salvar_perfil({"modelo": "demo", "onboarding_completo": True})
    assert pw._modelo_configurado() is None


def test_motores_chat_lista_locais(monkeypatch, tmp_path):
    """Com Ollama mockado, o configurado vem primeiro e marcado padrão."""
    import json as _json

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return _json.dumps({"models": [
                {"name": "gemma3:4b"}, {"name": "qwen3.5:4b-q8_0"}]}).encode()

    import nomos.cognition.motores as _mot; monkeypatch.setattr(_mot, "modelos_ollama_geradores", lambda *a, **k: ["gemma3:4b", "qwen3.5:4b-q8_0"])
    monkeypatch.setattr(pw, "_modelo_configurado", lambda: "qwen3.5:4b-q8_0")
    itens = pw.motores_chat({"home": tmp_path})
    ids = [m["id"] for m in itens]
    assert ids[0] == "ollama:qwen3.5:4b-q8_0"       # o configurado primeiro
    assert itens[0]["padrao"] is True
    assert "ollama:gemma3:4b" in ids


def test_seletores_no_composer():
    chat = {"habilitado": True, "token": "T", "base": "/d/x",
            "motores": [{"id": "ollama:qwen3.5:4b-q8_0",
                         "rotulo": "Ollama · qwen3.5:4b-q8_0", "padrao": True}]}
    html = pw._seletores_chat(chat)
    assert 'name="roteamento"' in html
    assert 'name="motor"' in html
    assert "automático (local-first)" in html
    assert "qwen3.5:4b-q8_0" in html
    assert "selected" in html                       # o padrão vem marcado
    assert "nuvem só pelo terminal" in html         # honestidade sobre a nuvem


def test_seletores_somem_sem_motor():
    """Sem motor pronto, nada a escolher — não mostra <select> vazio."""
    assert pw._seletores_chat({"motores": []}) == ""


def test_responder_local_motor_fixo_ollama(monkeypatch, tmp_path):
    """roteamento=motor com ollama:<x> constrói o provider com aquele modelo."""
    capturado = {}

    class _Ollama:
        def __init__(self, host, model): capturado["model"] = model
    monkeypatch.setattr(pw, "_modelo_configurado", lambda: "qwen3.5:4b-q8_0")
    import nomos.cognition.providers as prov
    monkeypatch.setattr(prov, "OllamaProvider", _Ollama)
    monkeypatch.setattr(prov, "OpenAICompatProvider",
                        lambda **k: (_ for _ in ()).throw(ValueError()))

    class _Router:
        def __init__(self, **k): pass
        def _try_local(self, m): return None
    import nomos.cognition.router as rt
    monkeypatch.setattr(rt, "Router", _Router)
    from nomos.cognition.embutido import EmbeddedProvider
    monkeypatch.setattr(EmbeddedProvider, "disponivel", lambda self: False)

    ctx = {"home": tmp_path, "audit": None, "policy": None}
    pw.responder_local(ctx, [{"role": "user", "content": "oi"}],
                       motor="ollama:gemma3:12b", roteamento="motor")
    assert capturado["model"] == "gemma3:12b"       # usou o motor escolhido
