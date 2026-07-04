"""NOMOS cognition.providers — backends de modelo (stdlib puro, sem SDKs).

Garantias:
- OllamaProvider fala APENAS com host local por padrão; timeouts curtos;
- AnthropicProvider recebe a chave por parâmetro (origem: cofre, atrás de
  gate A3) e a envia somente no header da requisição — nunca em logs/erros;
- falha de rede/serviço => ProviderUnavailable (nunca resposta inventada).
"""
from __future__ import annotations

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


class ProviderUnavailable(Exception):
    """Backend indisponível/erro — o chamador decide rota alternativa."""


@dataclass(frozen=True)
class ChatReply:
    text: str
    provider: str
    model: str


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
        return ChatReply(text=msg, provider=self.name, model=data.get("model", self.model))

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
        return ChatReply(text=text, provider=self.name, model=data.get("model", self.model))
