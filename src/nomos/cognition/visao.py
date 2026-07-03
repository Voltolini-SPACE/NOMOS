"""NOMOS cognition.visao — entender imagens com modelo LOCAL (Ollama/llava).

- a imagem vai em base64 para o Ollama em 127.0.0.1 — loopback, não é egress;
- sem modelo de visão instalado => erro honesto com a instrução de 1 linha;
- formatos aceitos: png/jpg/jpeg/webp/gif; limite de 20 MB.
"""
from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

LIMITE_BYTES = 20 * 1024 * 1024
FORMATOS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DICA = "instale um modelo de visão local: ollama pull llava"


class VisaoError(Exception):
    pass


def _validar(caminho: Path) -> Path:
    p = Path(caminho)
    if not p.exists():
        raise VisaoError(f"imagem não encontrada: {p}")
    if p.suffix.lower() not in FORMATOS:
        raise VisaoError(f"formato {p.suffix!r} não suportado "
                         f"(uso: {', '.join(sorted(FORMATOS))})")
    if p.stat().st_size > LIMITE_BYTES:
        raise VisaoError("imagem grande demais (limite 20 MB)")
    return p


def descrever(caminho, modelo: str, pergunta: str = "Descreva esta imagem em português.",
              host: str = "http://127.0.0.1:11434", timeout: float = 120.0,
              transporte=None) -> str:
    """Pergunta sobre uma imagem ao modelo de visão LOCAL."""
    p = _validar(caminho)
    if urlparse(host).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise VisaoError("visão só roda em motor local (loopback) — por projeto")
    img_b64 = base64.b64encode(p.read_bytes()).decode()
    payload = json.dumps({
        "model": modelo, "stream": False,
        "messages": [{"role": "user", "content": pergunta, "images": [img_b64]}],
    }).encode()
    if transporte is None:
        def transporte(url, dados, t):
            req = urllib.request.Request(url, data=dados,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=t) as r:  # nosec B310 - loopback validado acima
                return json.loads(r.read().decode())
    try:
        resposta = transporte(f"{host}/api/chat", payload, timeout)
    except Exception as exc:
        raise VisaoError(f"o modelo de visão não respondeu ({type(exc).__name__}) "
                         f"— {DICA}") from None
    texto = (resposta.get("message") or {}).get("content", "").strip()
    if not texto:
        raise VisaoError("o modelo de visão devolveu resposta vazia")
    return texto
