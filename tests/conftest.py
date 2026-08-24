import socket

import pytest

# Portas dos MOTORES REAIS da máquina (Ollama :11434, OpenAI-compat :1234).
# Teste unitário jamais deve alcançá-las: o daemon vivo do operador — e qual
# modelo ele tem instalado — não pode decidir se a suíte passa. Integração
# de verdade é opt-in explícito via @pytest.mark.motor_real.
PORTAS_DE_MOTOR_REAL = frozenset({11434, 1234})


@pytest.fixture(autouse=True)
def _sem_modelo_do_operador(monkeypatch):
    """O shell do operador pode exportar NOMOS_OLLAMA_MODEL (ex.: mitigação de
    produção em ~/.zshenv). Herdado pela suíte, ele dá um modelo REAL aos
    caminhos "sem motor" e o chat passa a conversar com o Ollama VIVO da
    máquina — 5 testes viraram reféns do ambiente em 23/08. A suíte nasce sem
    o override; teste que o quiser, seta explicitamente via monkeypatch."""
    monkeypatch.delenv("NOMOS_OLLAMA_MODEL", raising=False)


@pytest.fixture(autouse=True)
def _sem_motor_real(request, monkeypatch):
    """Hermético: para a suíte, as portas de motor real estão sempre RECUSADAS.

    O delenv acima não basta: o fallback ('llama3.2') ainda dava host+modelo
    ao OllamaProvider, e `available()`/`chat()` têm transporte urllib PRÓPRIO
    que os mocks da camada `motores` não cobrem. Medido no hardening (24/08):
    dois testes 'sem motor' fizeram 6 conexões reais (4× :11434, 2× :1234) e
    só passavam porque llama3.2 não estava instalado no daemon vivo.

    O guard fecha o SOCKET (nível mais baixo — qualquer transporte cai aqui)
    com `ConnectionRefusedError`: exatamente o que uma máquina SEM daemon
    responde, que é a máquina onde o CI roda. 83 testes da suíte sondam por
    design ("sondou → não está pronto"); para eles nada muda, só fica
    determinístico. Onde o código NÃO trata indisponibilidade, o erro sobe
    com a mensagem explícita. Servidores de teste em porta efêmera não são
    afetados; integração real é opt-in via @pytest.mark.motor_real. A lista
    devolvida registra as tentativas bloqueadas (os testes de
    test_suite_hermetica_motor_real.py a inspecionam).
    """
    if request.node.get_closest_marker("motor_real"):
        yield []
        return
    tentativas: list = []
    conectar = socket.socket.connect

    def _guard(self, address, *args, **kwargs):
        porta = address[1] if isinstance(address, tuple) and len(address) > 1 else None
        if porta in PORTAS_DE_MOTOR_REAL:
            tentativas.append(tuple(address))
            raise ConnectionRefusedError(
                f"[suíte hermética] teste tentou acessar motor real em "
                f"{address}; recusado pelo guard do conftest — mocke o "
                "provider (fixture motores_ausentes) ou marque o teste com "
                "@pytest.mark.motor_real (integração opt-in).")
        return conectar(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", _guard)
    yield tentativas


@pytest.fixture()
def motores_ausentes(monkeypatch):
    """Declara 'nenhum motor local pronto' SEM sondar nada: os providers
    respondem indisponível na própria camada deles. É o jeito certo de testar
    os caminhos degradados/fail-closed — independe do daemon do operador."""
    from nomos.cognition.providers import OllamaProvider, OpenAICompatProvider
    monkeypatch.setattr(OllamaProvider, "available", lambda self: False)
    monkeypatch.setattr(OpenAICompatProvider, "available", lambda self: False)


@pytest.fixture()
def nomos_home(tmp_path, monkeypatch):
    home = tmp_path / "nomos-home"
    monkeypatch.setenv("NOMOS_HOME", str(home))
    return home
