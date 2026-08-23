"""NOMOS cognition.providers — backends de modelo (stdlib puro, sem SDKs).

Garantias:
- OllamaProvider fala APENAS com host local por padrão; timeouts curtos;
- AnthropicProvider recebe a chave por parâmetro (origem: cofre, atrás de
  gate A3) e a envia somente no header da requisição — nunca em logs/erros;
- falha de rede/serviço => ProviderUnavailable (nunca resposta inventada).
"""
from __future__ import annotations

import urllib.request as _urllib

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

def _abrir_http(url_ou_req, timeout: float):
    """urlopen restrito a http/https — nunca file:// ou esquemas custom."""
    from urllib.parse import urlparse
    alvo = url_ou_req if isinstance(url_ou_req, str) else url_ou_req.full_url
    if urlparse(alvo).scheme not in {"http", "https"}:
        raise ValueError(f"esquema de URL não permitido: {alvo!r}")
    return urllib.request.urlopen(url_ou_req, timeout=timeout)  # nosec B310 - esquema validado acima


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _exigir_loopback(url: str, quem: str) -> None:
    """Motor 'local' é LOCAL por lei (MC30-C3): host fora do loopback é
    recusado na construção. Sem isso, um NOMOS_OLLAMA_HOST remoto enviaria a
    conversa para fora da máquina com o cadeado ligado e auditoria dizendo
    egress="nenhum"."""
    import ipaddress
    from urllib.parse import urlparse

    # Loopback que ROTEIA para fora não é motor local. Sem isto, apontar
    # NOMOS_OPENAI_COMPAT_BASE para um relay em 127.0.0.1 produziria
    # exatamente o desfecho que esta função existe para impedir: conversa
    # saindo com o cadeado ligado e auditoria dizendo egress="nenhum".
    from nomos.kernel.localidade import eh_relay_declarado
    if eh_relay_declarado(url):
        raise ValueError(
            f"{quem} aponta para um ROTEADOR em loopback (porta de relay) — "
            "falar com ele é falar com a internet. Use um motor local de "
            "verdade, ou plugue o roteador pelo caminho governado.")

    host = urlparse(url).hostname or ""
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise ValueError(
        f"{quem} é LOCAL por lei — o host deve ser loopback "
        f"(ex.: 127.0.0.1), não {host or url!r}")


class ProviderUnavailable(Exception):
    """Backend indisponível/erro — o chamador decide rota alternativa."""


@dataclass(frozen=True)
class ChatReply:
    text: str
    provider: str
    model: str
    # NH-019: contagem que o backend DEVOLVEU (None = não informou; nunca
    # inventar zero). Aditivos com default — nenhum construtor existente quebra.
    tokens_prompt: int | None = None
    tokens_resposta: int | None = None


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", **headers}
    )
    try:
        with _abrir_http(req, timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # corpo de erro pode conter detalhes, mas NUNCA anexamos headers/chave
        raise ProviderUnavailable(f"HTTP {exc.code} em {url}") from None
    except Exception as exc:
        raise ProviderUnavailable(f"falha de conexão em {url}: {type(exc).__name__}") from None


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str = DEFAULT_OLLAMA_HOST, model: str = DEFAULT_OLLAMA_MODEL,
                 timeout: float = 120.0, probe_timeout: float = 1.5):
        _exigir_loopback(host, "o Ollama do NOMOS")
        self.host = host.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.probe_timeout = probe_timeout

    def available(self) -> bool:
        try:
            with _abrir_http(f"{self.host}/api/tags", self.probe_timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def chat(self, messages: list[dict]) -> ChatReply:
        data = _post_json(
            f"{self.host}/api/chat",
            {"model": self.model, "messages": messages, "stream": False},
            headers={}, timeout=self.timeout,
        )
        msg = (data.get("message") or {}).get("content")
        if not isinstance(msg, str):
            raise ProviderUnavailable("resposta do ollama sem message.content")
        return ChatReply(text=msg, provider=self.name,
                         model=data.get("model", self.model),
                         tokens_prompt=data.get("prompt_eval_count"),
                         tokens_resposta=data.get("eval_count"))

    def chat_stream(self, messages: list[dict], on_token) -> ChatReply:
        """Streaming NDJSON do Ollama (v1.1): cada token vai ao callback na
        hora; devolve a resposta completa acumulada. Loopback apenas."""
        body = json.dumps({"model": self.model, "messages": messages,
                           "stream": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=body,
            headers={"Content-Type": "application/json"})
        pedacos: list[str] = []
        try:
            with _abrir_http(req, self.timeout) as resp:
                for linha in resp:
                    linha = linha.strip()
                    if not linha:
                        continue
                    evento = json.loads(linha)
                    tok = (evento.get("message") or {}).get("content", "")
                    if tok:
                        pedacos.append(tok)
                        on_token(tok)
                    if evento.get("done"):
                        break
        except KeyboardInterrupt:
            raise                                   # interrupção é do usuário
        except Exception as exc:
            raise ProviderUnavailable(
                f"stream do ollama falhou: {type(exc).__name__}") from None
        if not pedacos:
            raise ProviderUnavailable("stream do ollama sem conteúdo")
        return ChatReply(text="".join(pedacos), provider=self.name, model=self.model)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_ANTHROPIC_MODEL,
                 url: str = ANTHROPIC_URL, timeout: float = 120.0, max_tokens: int = 1024):
        self._api_key = api_key
        self.model = model
        self.url = url
        self.timeout = timeout
        self.max_tokens = max_tokens

    def __repr__(self) -> str:  # chave jamais aparece em repr/log
        return f"AnthropicProvider(model={self.model!r}, url={self.url!r})"

    def chat(self, messages: list[dict]) -> ChatReply:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system") or None
        turns = [m for m in messages if m["role"] in {"user", "assistant"}]
        payload = {"model": self.model, "max_tokens": self.max_tokens, "messages": turns}
        if system:
            payload["system"] = system
        data = _post_json(
            self.url, payload,
            headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01"},
            timeout=self.timeout,
        )
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if not text:
            raise ProviderUnavailable("resposta da API sem blocos de texto")
        uso = data.get("usage") or {}
        return ChatReply(text=text, provider=self.name,
                         model=data.get("model", self.model),
                         tokens_prompt=uso.get("input_tokens"),
                         tokens_resposta=uso.get("output_tokens"))


class OmniRouteProvider:
    """Roteador OmniRoute em loopback — que SAI para a internet.

    Fala o dialeto OpenAI (`/v1/chat/completions`), como o `OpenAICompatProvider`,
    mas com uma diferença que muda tudo: aquele é LOCAL por lei e este é uma
    FRONTEIRA DE SAÍDA. Por isso NÃO passa por `_exigir_loopback` — o alvo dele
    é justamente uma porta de relay, que aquela função recusa de propósito.

    Quem autoriza é a cadeia de gates do chamador (ver `montar_runner_omniroute`
    em cognition/relay.py): cadeado de localidade → A2 (egresso) → A3
    (credencial) → chave do COFRE. Este objeto só transporta; ele não decide.

    A chave nunca vem do `.env` do OmniRoute: vem do cofre do NOMOS, passada
    pelo construtor. Um provedor que lesse credencial de arquivo global estaria
    fora da governança mesmo rodando dentro dela.
    """

    name = "omniroute"

    def __init__(self, api_key: str, base: str = "http://127.0.0.1:20128/v1",
                 model: str = "auto/best-free", timeout: float = 120.0):
        if not api_key:
            raise ValueError("OmniRoute exige chave — sem credencial não há chamada")
        self._api_key = api_key
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def __repr__(self) -> str:   # a chave jamais aparece em repr/log
        return f"OmniRouteProvider(base={self.base!r}, model={self.model!r})"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}"}

    def chat(self, messages: list[dict]) -> ChatReply:
        payload = {"model": self.model, "messages": messages}
        data = _post_json(f"{self.base}/chat/completions", payload,
                          headers=self._headers(), timeout=self.timeout)
        choices = data.get("choices") or []
        text = (choices[0].get("message", {}) or {}).get("content", "") \
            if choices else ""
        if not text:
            raise ProviderUnavailable("OmniRoute respondeu sem conteúdo "
                                      "(sem provedor disponível para a rota?)")
        uso = data.get("usage") or {}
        return ChatReply(text=text, provider=self.name,
                         model=data.get("model", self.model),
                         tokens_prompt=uso.get("prompt_tokens"),
                         tokens_resposta=uso.get("completion_tokens"))

    def available(self) -> bool:
        """Probe no /models. 401 conta como VIVO-porém-sem-credencial: o serviço
        está de pé e a chave é que não serve — distinguir os dois evita anunciar
        motor pronto quando ele recusaria a chamada."""
        try:
            req = _urllib.request.Request(f"{self.base}/models",
                                          headers=self._headers())
            with _abrir_http(req, 2.0) as r:   # guard do módulo: valida esquema
                return r.status == 200
        except Exception:
            return False


class OpenAICompatProvider:
    """Servidor LOCAL OpenAI-compatível (LM Studio, llama.cpp server, LocalAI).

    Loopback por lei: qualquer host fora de 127.0.0.1/localhost/::1 é recusado
    na construção (MC30-C3). Nada sai da máquina.
    """

    name = "openai-compat"

    def __init__(self, base: str = "http://127.0.0.1:1234/v1",
                 model: str = "local", timeout: float = 120.0):
        _exigir_loopback(base, "o servidor OpenAI-compatível")
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"OpenAICompatProvider(base={self.base!r}, model={self.model!r})"

    def chat(self, messages: list[dict]) -> ChatReply:
        payload = {"model": self.model, "messages": messages}
        data = _post_json(f"{self.base}/chat/completions", payload,
                          headers={}, timeout=self.timeout)
        choices = data.get("choices") or []
        text = (choices[0].get("message", {}) or {}).get("content", "") \
            if choices else ""
        if not text:
            raise ProviderUnavailable("resposta do servidor local sem conteúdo")
        uso = data.get("usage") or {}
        return ChatReply(text=text, provider=self.name,
                         model=data.get("model", self.model),
                         tokens_prompt=uso.get("prompt_tokens"),
                         tokens_resposta=uso.get("completion_tokens"))

    def available(self) -> bool:
        """Probe leve no /models (loopback). Sem servidor => False, sem exceção."""
        try:
            with _abrir_http(f"{self.base}/models", 1.5) as r:
                return r.status == 200
        except Exception:
            return False

    def chat_stream(self, messages: list[dict], on_token) -> ChatReply:
        """Streaming SSE OpenAI (MC31): cada delta vai ao callback na hora.

        Formato: linhas ``data: {json}`` com ``choices[0].delta.content`` e
        terminador ``data: [DONE]``. Loopback apenas (garantido no __init__).
        """
        body = json.dumps({"model": self.model, "messages": messages,
                           "stream": True}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/chat/completions", data=body,
            headers={"Content-Type": "application/json"})
        pedacos: list[str] = []
        modelo = self.model
        try:
            with _abrir_http(req, self.timeout) as resp:
                for linha in resp:
                    linha = linha.strip()
                    if not linha or not linha.startswith(b"data:"):
                        continue
                    payload = linha[5:].strip()
                    if payload == b"[DONE]":
                        break
                    evento = json.loads(payload)
                    modelo = evento.get("model", modelo)
                    escolhas = evento.get("choices") or [{}]
                    tok = (escolhas[0].get("delta") or {}).get("content", "")
                    if tok:
                        pedacos.append(tok)
                        on_token(tok)
        except KeyboardInterrupt:
            raise                                   # interrupção é do usuário
        except Exception as exc:
            raise ProviderUnavailable(
                f"stream openai-compat falhou: {type(exc).__name__}") from None
        if not pedacos:
            raise ProviderUnavailable("stream openai-compat sem conteúdo")
        return ChatReply(text="".join(pedacos), provider=self.name, model=modelo)
