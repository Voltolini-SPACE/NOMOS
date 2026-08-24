"""O chat do CLI tem de usar o modelo do PERFIL, não um default fixo.

Defeito real (23/08): `_router()` montava o OllamaProvider com
`NOMOS_OLLAMA_MODEL` e default 'llama3.2', IGNORANDO o modelo escolhido no
onboarding (agent.json, campo "modelo"). Com 'llama3.2' não instalado, o
/api/chat devolvia 404 → ProviderUnavailable → `nomos chat` entrava em MODO
DEGRADADO mesmo com o Ollama saudável. O painel já tinha sido curado do mesmo
mal (_modelo_configurado); aqui o CLI ganha a MESMA fonte da verdade.
"""
from __future__ import annotations

from nomos import cli
from nomos.kernel import config
from nomos.simple.onboarding import salvar_perfil


def _home_com_perfil(tmp_path, monkeypatch, modelo: str | None = None):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    monkeypatch.delenv("NOMOS_OLLAMA_MODEL", raising=False)
    if modelo is not None:
        config.save_agent("ZEUS")
        salvar_perfil({"modelo": modelo, "onboarding_completo": True})


def test_perfil_e_a_fonte_da_verdade(monkeypatch, tmp_path):
    _home_com_perfil(tmp_path, monkeypatch, modelo="qwen3.5:9b")
    assert cli._modelo_ollama() == "qwen3.5:9b"


def test_env_nao_atropela_o_perfil(monkeypatch, tmp_path):
    """Mesma precedência do painel: com perfil, o env não muda o cérebro."""
    _home_com_perfil(tmp_path, monkeypatch, modelo="qwen3.5:9b")
    monkeypatch.setenv("NOMOS_OLLAMA_MODEL", "llama3.2")
    assert cli._modelo_ollama() == "qwen3.5:9b"


def test_sem_perfil_o_env_decide(monkeypatch, tmp_path):
    _home_com_perfil(tmp_path, monkeypatch)          # sem agent.json
    monkeypatch.setenv("NOMOS_OLLAMA_MODEL", "qwen3.5:4b-q8_0")
    assert cli._modelo_ollama() == "qwen3.5:4b-q8_0"


def test_default_so_como_ultimo_recurso(monkeypatch, tmp_path):
    _home_com_perfil(tmp_path, monkeypatch)
    assert cli._modelo_ollama() == "llama3.2"


def test_modelo_demo_nao_conta(monkeypatch, tmp_path):
    """'demo' não é um modelo do Ollama — a cadeia segue adiante."""
    _home_com_perfil(tmp_path, monkeypatch, modelo="demo")
    assert cli._modelo_ollama() == "llama3.2"


def test_router_entrega_o_modelo_do_perfil_ao_ollama(monkeypatch, tmp_path):
    """Ponta a ponta do defeito: o OllamaProvider do `_router()` nasce com o
    modelo do agent.json — era exatamente aqui que o 404 começava."""
    _home_com_perfil(tmp_path, monkeypatch, modelo="qwen3.5:9b")
    ctx = cli._paths()
    router = cli._router(ctx)
    assert router.ollama.model == "qwen3.5:9b"
