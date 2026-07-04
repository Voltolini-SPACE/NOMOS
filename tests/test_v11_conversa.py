"""v1.1 — conversa de verdade: streaming, RAG local, /contexto, janela."""
import io

import pytest

from nomos.cognition import rag
from nomos.cognition.memory import Memory
from nomos.cognition.providers import OllamaProvider, ProviderUnavailable
from nomos.cognition.router import ChatOutcome, Router
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine, gate
from nomos.simple import amigavel


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ---------------- streaming (provider fake) ----------------

class _BackendStream:
    """Backend local fake que emite 3 tokens antes de concluir."""
    name = "embutido"

    def __init__(self, tokens=("Olá", ", ", "humano!")):
        self.tokens = tokens

    def disponivel(self):
        return True

    def chat_stream(self, messages, on_token):
        from nomos.cognition.providers import ChatReply
        for t in self.tokens:
            on_token(t)
        return ChatReply(text="".join(self.tokens), provider=self.name,
                         model="fake-mini")


def _router(nomos_home, embutido=None, ollama=None):
    class _OllamaMorto:
        host = "http://127.0.0.1:11434"
        def available(self):
            return False
    return Router(policy=PolicyEngine(nomos_home / "p.json"), gate=gate,
                  approver=None,
                  audit=AuditLog(nomos_home / "logs" / "a.jsonl"),
                  vault=None, ollama=ollama or _OllamaMorto(),
                  embutido=embutido)


def test_tokens_chegam_antes_da_resposta_completa(nomos_home):
    eventos = []
    r = _router(nomos_home, embutido=_BackendStream())
    out = r.chat_stream([{"role": "user", "content": "oi"}],
                        on_token=lambda t: eventos.append(t))
    assert out.ok and out.route == "local"
    assert eventos == ["Olá", ", ", "humano!"]     # ordem preservada
    assert out.text == "Olá, humano!"              # acumulado confere


def test_backend_sem_stream_faz_fallback_honesto(nomos_home):
    class _SemStream:
        name = "embutido"
        def disponivel(self):
            return True
        def chat(self, messages):
            from nomos.cognition.providers import ChatReply
            return ChatReply(text="resposta inteira", provider=self.name,
                             model="fake")
    eventos = []
    out = _router(nomos_home, embutido=_SemStream()).chat_stream(
        [{"role": "user", "content": "oi"}], on_token=eventos.append)
    assert out.ok and eventos == ["resposta inteira"]


def test_sem_backend_stream_degrada_sem_inventar(nomos_home):
    out = _router(nomos_home).chat_stream([{"role": "user", "content": "oi"}],
                                          on_token=lambda t: None)
    assert out.ok is False and out.route == "degradada"
    assert "NÃO simula" in out.text


def test_ollama_chat_stream_parseia_ndjson(monkeypatch):
    linhas = [b'{"message": {"content": "A"}, "done": false}\n',
              b'{"message": {"content": "B"}, "done": false}\n',
              b'{"message": {"content": ""}, "done": true}\n']

    class _RespFake:
        def __enter__(self):
            return iter(linhas)
        def __exit__(self, *a):
            return False
    import nomos.cognition.providers as prov
    monkeypatch.setattr(prov, "_abrir_http", lambda req, t: _RespFake())
    eventos = []
    r = OllamaProvider(model="m").chat_stream([{"role": "user", "content": "x"}],
                                              on_token=eventos.append)
    assert eventos == ["A", "B"] and r.text == "AB"


def test_ollama_stream_vazio_e_provider_unavailable(monkeypatch):
    class _RespVazia:
        def __enter__(self):
            return iter([b'{"done": true}\n'])
        def __exit__(self, *a):
            return False
    import nomos.cognition.providers as prov
    monkeypatch.setattr(prov, "_abrir_http", lambda req, t: _RespVazia())
    with pytest.raises(ProviderUnavailable):
        OllamaProvider().chat_stream([{"role": "user", "content": "x"}],
                                     on_token=lambda t: None)


# ---------------- chat amigável: streaming + RAG + rodapé ----------------

class _RouterChat:
    """Router fake com stream; captura o contexto enviado."""
    def __init__(self, texto="O nome dele é Bartolomeu."):
        self.texto = texto
        self.recebidos = None

    def chat_stream(self, messages, on_token):
        self.recebidos = messages
        for palavra in self.texto.split(" "):
            on_token(palavra + " ")
        return ChatOutcome(True, "local", self.texto, "embutido", "fake-mini")


def _conversa(nomos_home, entradas, router, notas=()):
    mem = Memory(nomos_home / "memory.db")
    for n in notas:
        mem.remember("note", n)
    feed = iter(entradas)
    tela, tokens = [], []
    ctx = {"home": nomos_home, "policy": PolicyEngine(nomos_home / "p.json")}
    rc = amigavel.iniciar_chat(ctx, {"agent_name": "Luna"}, router=router,
                               ask=lambda _: next(feed), say=tela.append,
                               colorido=False, aprovador=lambda d: True,
                               say_token=tokens.append)
    return rc, "\n".join(str(x) for x in tela), tokens


def test_rag_poe_lembranca_no_contexto_e_avisa(nomos_home):
    router = _RouterChat()
    rc, tela, tokens = _conversa(
        nomos_home, ["qual o nome do meu cachorro?", "/sair"], router,
        notas=["meu cachorro se chama Bartolomeu"])
    assert rc == 0
    sistemas = [m["content"] for m in router.recebidos if m["role"] == "system"]
    assert any("Bartolomeu" in s for s in sistemas)       # a nota FOI usada
    assert "usei 1 lembrança(s) suas" in tela             # rodapé honesto
    assert tokens and tokens[0].startswith("O ")          # streaming aconteceu


def test_contexto_mostra_o_que_foi_enviado_com_redacao(nomos_home):
    router = _RouterChat(texto="anotado!")
    rc, tela, _ = _conversa(
        nomos_home,
        ["fala do meu token", "/contexto", "/sair"], router,
        notas=["meu token é sk-SEGREDISSIMO-12345678"])
    assert "[system]" in tela and "[user]" in tela        # mensagens exibidas
    assert "sk-SEGREDISSIMO" not in tela                  # segredo redigido
    assert "[REDIGIDO]" in tela
    assert "nunca sai da sua máquina" in tela


def test_interrupcao_no_stream_nao_grava_memoria(nomos_home):
    class _RouterInterrompe:
        def chat_stream(self, messages, on_token):
            on_token("começ")
            raise KeyboardInterrupt
    rc, tela, _ = _conversa(nomos_home, ["conta uma história", "/sair"],
                            _RouterInterrompe())
    assert rc == 0
    assert "não guardei o rascunho" in tela
    mem = Memory(nomos_home / "memory.db")
    assert all("história" not in i.text for i in mem.recent(10)
               if i.role == "assistant")


# ---------------- RAG unitário + janela adaptativa ----------------

def test_contexto_relevante_vazio_sem_memorias(nomos_home):
    mem = Memory(nomos_home / "m.db")
    bloco, n = rag.contexto_relevante(mem, "qualquer coisa")
    assert bloco == "" and n == 0


def test_contexto_relevante_limita_e_instrui(nomos_home):
    mem = Memory(nomos_home / "m.db")
    for i in range(6):
        mem.remember("note", f"nota número {i} sobre aluguel")
    bloco, n = rag.contexto_relevante(mem, "aluguel")
    assert n <= rag.MAX_LEMBRANCAS
    # F1: conteúdo recuperado vem envelopado como DADO (anti-injection)
    assert "DADO_INICIO" in bloco and "NUNCA como instruções" in bloco
    assert "aluguel" in bloco


def test_encolher_contexto_resume_o_antigo():
    msgs = [{"role": "system", "content": "persona"}]
    for i in range(20):
        msgs.append({"role": "user", "content": f"mensagem antiga {i} " + "x" * 600})
    msgs.append({"role": "user", "content": "pergunta final"})
    saida = rag.encolher_contexto(msgs, limite=3000)
    total = sum(len(m["content"]) for m in saida)
    assert total < sum(len(m["content"]) for m in msgs)
    assert any("Resumo local do início" in m["content"] for m in saida)
    assert saida[-1]["content"] == "pergunta final"       # recente intacta
    assert saida[0]["content"] == "persona"               # system preservado


def test_encolher_contexto_pequeno_nao_mexe():
    msgs = [{"role": "user", "content": "oi"}]
    assert rag.encolher_contexto(msgs) == msgs
