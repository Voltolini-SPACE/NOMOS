"""O cérebro escolhido no onboarding tem de saber GERAR texto.

Defeito real (22/08): com o cofre soberano contendo apenas
`embeddinggemma:300m`, `nomic-embed-text:latest` e `qwen3.5:4b-q8_0`, o
onboarding elegeu `embeddinggemma` — `sorted(nomes)[0]`, ordem alfabética, sem
nenhum filtro de capacidade. O agente ficou MUDO (`"embeddinggemma:300m" does
not support generate`) e o `nomos doutor` exibia "Cérebro pronto (texto)".
"""
from __future__ import annotations

from nomos.cognition import motores
from nomos.simple.onboarding import escolher_modelo

COFRE_SOBERANO = ["embeddinggemma:300m", "nomic-embed-text:latest", "qwen3.5:4b-q8_0"]
CAPS = {
    "embeddinggemma:300m": ("embedding",),
    "nomic-embed-text:latest": ("embedding",),
    "qwen3.5:4b-q8_0": ("completion", "vision", "tools", "thinking"),
}


def _sem_cache(monkeypatch, tags, caps):
    monkeypatch.setattr(motores, "modelos_ollama", lambda host=None: list(tags))
    monkeypatch.setattr(motores, "capacidades_ollama",
                        lambda nome, host=None: tuple(caps.get(nome, ())))


def test_modelo_de_embedding_nunca_vira_cerebro(monkeypatch):
    _sem_cache(monkeypatch, COFRE_SOBERANO, CAPS)
    geradores = motores.modelos_ollama_geradores()
    assert geradores == ["qwen3.5:4b-q8_0"]
    assert escolher_modelo(geradores) == "qwen3.5:4b-q8_0"


def test_o_alfabeto_sozinho_elegia_o_modelo_mudo():
    """Controle: sem filtro, a escolha cai no primeiro alfabético — o defeito."""
    assert sorted(COFRE_SOBERANO)[0] == "embeddinggemma:300m"


def test_sem_capacidades_declaradas_cai_na_heuristica(monkeypatch):
    """Ollama antigo não devolve `capabilities`: excluir pelo nome é o fail-safe."""
    _sem_cache(monkeypatch, COFRE_SOBERANO, {})
    assert motores.modelos_ollama_geradores() == ["qwen3.5:4b-q8_0"]


def test_so_embedding_disponivel_nao_inventa_cerebro(monkeypatch):
    _sem_cache(monkeypatch, ["embeddinggemma:300m"], CAPS)
    assert motores.modelos_ollama_geradores() == []
    assert escolher_modelo([]) is None
