"""MC31 — B1 provado e completado: streaming + memória no contexto.

Achado da missão: o B1 do ROADMAP_3 já estava implementado (v1.1) — streaming
no chat, RAG de memórias no contexto e /contexto transparente. Este arquivo
adiciona os CONTRATOS que faltavam e prova o gap fechado: o Router de chat
agora conhece o motor OpenAI-compatível local (LM Studio/llama.cpp), com
streaming SSE, mantendo a ordem local-first embutido → ollama → openai-compat.
"""
import pytest

from nomos.cognition import rag
from nomos.cognition.memory import Memory
from nomos.cognition.providers import (
    ChatReply,
    OpenAICompatProvider,
    ProviderUnavailable,
)
from nomos.cognition.router import Router
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine, gate


class _Backend:
    """Dublê de motor local com/sem streaming."""

    host = "http://127.0.0.1:0"          # _degraded() menciona o host do ollama

    def __init__(self, texto="olá mundo local", com_stream=True, pronto=True):
        self._texto, self._com_stream, self._pronto = texto, com_stream, pronto
        if com_stream:
            self.chat_stream = self._chat_stream   # só existe se suportar

    def available(self) -> bool:
        return self._pronto

    def chat(self, messages) -> ChatReply:
        if not self._pronto:
            raise ProviderUnavailable("desligado")
        return ChatReply(text=self._texto, provider="fake", model="m")

    def _chat_stream(self, messages, on_token) -> ChatReply:
        for palavra in self._texto.split(" "):
            on_token(palavra + " ")
        return ChatReply(text=self._texto, provider="fake", model="m")


def _router(tmp_path, **kw):
    return Router(policy=PolicyEngine(tmp_path / "policy.json"), gate=gate,
                  approver=None, audit=AuditLog(tmp_path / "logs" / "a.jsonl"),
                  vault=None, ollama=kw.pop("ollama", _Backend(pronto=False)),
                  embutido=None, **kw)


# 1. contrato de streaming: tokens chegam ANTES do resultado final
def test_primeiro_token_chega_antes_do_fim(tmp_path):
    eventos = []
    r = _router(tmp_path, ollama=_Backend("primeira palavra rápida"))
    out = r.chat_stream([{"role": "user", "content": "oi"}],
                        lambda t: eventos.append(t))
    eventos.append("FIM")
    assert out.ok and out.route == "local"
    assert eventos[0].startswith("primeira")     # 1º token veio na hora
    assert eventos[-1] == "FIM" and len(eventos) > 2


# 2. backend sem stream: fallback honesto emite o texto completo uma vez
def test_backend_sem_stream_emite_texto_completo(tmp_path):
    eventos = []
    r = _router(tmp_path, ollama=_Backend("resposta inteira", com_stream=False))
    out = r.chat_stream([{"role": "user", "content": "oi"}], eventos.append)
    assert out.ok and eventos == ["resposta inteira"]


# 3. gap fechado: openai-compat entra na cadeia local-first do chat
def test_openai_compat_assume_quando_ollama_cai(tmp_path):
    eventos = []
    r = _router(tmp_path, ollama=_Backend(pronto=False),
                openai_compat=_Backend("vim do lm studio"))
    out = r.chat_stream([{"role": "user", "content": "oi"}], eventos.append)
    assert out.ok and out.route == "local"
    assert "".join(eventos).strip() == "vim do lm studio"
    trilha = (tmp_path / "logs" / "a.jsonl").read_text(encoding="utf-8")
    assert "chat.local.openai" in trilha


def test_openai_compat_tambem_no_chat_sem_stream(tmp_path):
    r = _router(tmp_path, ollama=_Backend(pronto=False),
                openai_compat=_Backend("sem stream", com_stream=False))
    out = r.chat([{"role": "user", "content": "oi"}])
    assert out.ok and out.text == "sem stream"


def test_sem_nenhum_backend_degrada_honesto(tmp_path):
    out = _router(tmp_path).chat_stream([{"role": "user", "content": "oi"}],
                                        lambda t: None)
    assert out.ok is False and out.route == "degradada"


# 4. provider SSE real (parse), com dublê de transporte
def test_provider_openai_stream_parseia_sse(monkeypatch):
    linhas = [
        b'data: {"model":"qwen","choices":[{"delta":{"content":"ol\xc3\xa1 "}}]}',
        b"",
        b'data: {"choices":[{"delta":{"content":"local"}}]}',
        b"data: [DONE]",
    ]

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(linhas)

    import nomos.cognition.providers as prov
    monkeypatch.setattr(prov, "_abrir_http", lambda req, timeout: _Resp())
    tokens = []
    r = OpenAICompatProvider().chat_stream(
        [{"role": "user", "content": "oi"}], tokens.append)
    assert tokens == ["olá ", "local"]
    assert r.text == "olá local" and r.model == "qwen"


def test_provider_openai_stream_vazio_e_honesto(monkeypatch):
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter([b"data: [DONE]"])

    import nomos.cognition.providers as prov
    monkeypatch.setattr(prov, "_abrir_http", lambda req, timeout: _Resp())
    with pytest.raises(ProviderUnavailable):
        OpenAICompatProvider().chat_stream([{"role": "user", "content": "x"}],
                                           lambda t: None)


# 5. memória no contexto (contrato do que já existia, agora blindado)
def test_memorias_relevantes_entram_no_contexto(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    mem.remember_typed("meu aniversário é 12 de março", tipo="fato")
    bloco, n = rag.contexto_relevante(mem, "quando é meu aniversário?")
    assert n >= 1 and "12 de março" in bloco
    # e o bloco é material de SISTEMA (vai como contexto, não como fala)
    assert isinstance(bloco, str) and bloco


def test_sem_memoria_relevante_nao_polui_contexto(tmp_path):
    mem = Memory(tmp_path / "memory.db")
    bloco, n = rag.contexto_relevante(mem, "qualquer pergunta")
    assert n == 0 and not bloco
