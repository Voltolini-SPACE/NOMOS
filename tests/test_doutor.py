from nomos.cognition import motores
from nomos.kernel import config
from nomos.simple import doutor


def test_estrutura(nomos_home):
    config.ensure_home()
    assert all(set(i) == {"ok", "titulo", "detalhe"} for i in doutor.diagnostico())


def test_orienta_sem_agente(nomos_home, monkeypatch):
    config.ensure_home()
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    assert "nomos start" in doutor.texto_relatorio()
