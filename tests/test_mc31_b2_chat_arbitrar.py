"""MC31/B2 — /arbitrar no chat: espelho fail-closed da CLI, só motores locais."""
import io

import pytest

from nomos.cognition import arbitragem as arb
from nomos.kernel.policy import PolicyEngine
from nomos.simple import amigavel


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


class _RouterMudo:
    """Router que nunca é usado nestes testes (só /arbitrar e /sair)."""


def _conversa(nomos_home, entradas):
    feed = iter(entradas)
    tela = []
    ctx = {"home": nomos_home, "policy": PolicyEngine(nomos_home / "p.json")}
    rc = amigavel.iniciar_chat(ctx, {"agent_name": "Luna"}, router=_RouterMudo(),
                               ask=lambda _: next(feed), say=tela.append,
                               colorido=False, aprovador=lambda d: True)
    return rc, "\n".join(str(x) for x in tela)


class _Runner:
    local = True

    def __init__(self, engine_id, texto):
        self.engine_id, self._texto = engine_id, texto

    def available(self):
        return True

    def run(self, prompt, *, system=""):
        return self._texto


# 1. sandbox sem motor: honesto, nada inventado, conversa continua
def test_chat_arbitrar_sem_motor_e_honesto(nomos_home, monkeypatch):
    # força "sem Ollama" — o teste prova a honestidade (sem motor ⇒ não
    # inventa), sem depender de um Ollama aberto na máquina do dev.
    from nomos.cognition import providers
    monkeypatch.setattr(providers.OllamaProvider, "available", lambda self: False)
    rc, tela = _conversa(nomos_home, ["/arbitrar o que é local-first?", "/sair"])
    assert rc == 0
    assert "nenhum motor pronto" in tela and "nada foi" in tela
    assert "inventado" in tela


# 2. com motores locais (dublês): resposta REAL de um candidato, com confiança
def test_chat_arbitrar_com_motores_reais(nomos_home, monkeypatch):
    monkeypatch.setattr(arb, "montar_runners_producao", lambda home: [
        _Runner("m1", "Local-first significa: sua máquina primeiro."),
        _Runner("m2", "Local-first: os dados ficam com você."),
    ])
    rc, tela = _conversa(nomos_home, ["/arbitrar o que é local-first?", "/sair"])
    assert rc == 0
    assert "arbitrado por 2 motor(es)" in tela
    assert ("sua máquina primeiro" in tela) or ("ficam com você" in tela)
    # nuvem nunca entra pelo chat — só a dica da CLI gateada aparece
    assert "nomos motores arbitrar --nuvem" in tela


# 3. sem pergunta: orienta o uso
def test_chat_arbitrar_sem_pergunta_orienta(nomos_home):
    rc, tela = _conversa(nomos_home, ["/arbitrar", "/sair"])
    assert rc == 0 and "/arbitrar <pergunta>" in tela


# 4. ajuda anuncia o comando
def test_ajuda_lista_arbitrar():
    assert "/arbitrar" in amigavel.AJUDA
