"""Qualidade — regressões dos aprimoramentos deste ciclo."""

import pytest

from nomos.cognition import criacao, motores
from nomos.cognition.providers import AnthropicProvider, ProviderUnavailable
from nomos.ext.signing import SigningError, TrustStore
from nomos.kernel.policy import PolicyEngine, gate


def test_trust_store_estrutura_errada_recusa_sem_assert(tmp_path):
    """Antes: asserts (somem com python -O). Agora: checagem explícita."""
    t = TrustStore(tmp_path / "t.json")
    for lixo in ('{"publishers": [], "revoked": [], "pins": {}}',
                 '{"publishers": {}, "revoked": {}, "pins": {}}',
                 '{"publishers": {}, "revoked": []}'):
        t.path.write_text(lixo)
        with pytest.raises(SigningError, match="corrompido"):
            t._load()


def test_urlopen_recusa_esquema_file(tmp_path):
    p = AnthropicProvider(api_key="sk-x-0000000000", url="file:///etc/passwd")
    with pytest.raises(ProviderUnavailable):
        p.chat([{"role": "user", "content": "oi"}])
    pol = PolicyEngine(tmp_path / "p.json")
    with pytest.raises(criacao.CriacaoIndisponivel):
        criacao.gerar_imagem("x", tmp_path, pol, gate, lambda d: True,
                             host="file:///tmp")


def test_motores_respeita_env_ollama_host(monkeypatch):
    import importlib
    monkeypatch.setenv("NOMOS_OLLAMA_HOST", "http://127.0.0.1:59999")
    importlib.reload(motores)
    try:
        assert motores.OLLAMA == "http://127.0.0.1:59999"
    finally:
        monkeypatch.delenv("NOMOS_OLLAMA_HOST")
        importlib.reload(motores)


def test_chat_imagem_com_apenas_comfy_orienta(nomos_home, tmp_path, monkeypatch):
    from nomos.simple import amigavel
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok",
                        lambda url, *a, **k: "8188" in url or "system_stats" in url)
    motores.limpar_cache()
    feed = iter(["/imagem um robô", "/sair"])
    tela = []
    ctx = {"home": tmp_path, "policy": PolicyEngine(tmp_path / "p.json")}
    amigavel.iniciar_chat(ctx, {"agent_name": "Nina", "modo_cerebro": "demo"},
                          router=None, ask=lambda _: next(feed),
                          say=tela.append, colorido=False, aprovador=lambda d: True)
    txt = "\n".join(str(x) for x in tela)
    assert "ComfyUI" in txt and "no plano" in txt          # honesto, sem gerar


def test_nuvem_em_so_local_recusa_sem_pedir_senha(nomos_home, tmp_path, monkeypatch):
    """Regressão: /nuvem em modo só-local recusa na hora, sem pedir senha-mestra."""
    from nomos.simple import amigavel

    def _boom(*a, **k):
        raise AssertionError("não deveria pedir senha em modo só-local")
    monkeypatch.setattr("getpass.getpass", _boom)

    class RouterNaoUsado:
        def chat(self, *a, **k):
            raise AssertionError("não deveria chamar a nuvem em modo só-local")

    feed = iter(["/nuvem qual a capital?", "/sair"])
    tela = []
    ctx = {"home": tmp_path, "policy": PolicyEngine(tmp_path / "p.json")}
    amigavel.iniciar_chat(ctx, {"agent_name": "Nina", "modo_cerebro": "local"},
                          router=RouterNaoUsado(), ask=lambda _: next(feed),
                          say=tela.append, colorido=False, aprovador=lambda d: True)
    txt = "\n".join(tela)
    assert "só-local" in txt and "desplugada" in txt
