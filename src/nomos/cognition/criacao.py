"""NOMOS cognition.criacao — geração real de imagem (SD) e fala (piper).

Garantias:
- só age quando o motor EXISTE; ausência = CriacaoIndisponivel com dica;
- gravação em disco passa pelo gate A1 (aprovador do chamador);
- arquivos nascem em NOMOS_HOME/criacoes com nome datado, 0600;
- nenhuma mídia é inventada: sem motor, sem arquivo.
"""
from __future__ import annotations

from nomos.kernel.plataforma import chmod_privado

import base64
import datetime as _dt
import json
import re
import shutil
import subprocess  # nosec B404 - uso restrito: argv fixo, binário via shutil.which
import urllib.request

from nomos.kernel.policy import Category

def _abrir_http(url_ou_req, timeout: float):
    """urlopen restrito a http/https — nunca file:// ou esquemas custom."""
    from urllib.parse import urlparse
    alvo = url_ou_req if isinstance(url_ou_req, str) else url_ou_req.full_url
    if urlparse(alvo).scheme not in {"http", "https"}:
        raise ValueError(f"esquema de URL não permitido: {alvo!r}")
    return urllib.request.urlopen(url_ou_req, timeout=timeout)  # nosec B310 - esquema validado acima



PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
RIFF = b"RIFF"


class CriacaoIndisponivel(Exception):
    pass


class CriacaoNegada(Exception):
    pass


def _slug(texto: str, n: int = 24) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")
    return (s[:n] or "criacao").rstrip("-")


def _destino(home, tipo: str, prompt: str, ext: str):
    d = home / "criacoes"
    d.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    return d / f"{tipo}-{ts}-{_slug(prompt)}.{ext}"


def _gate_escrita(policy, gate, approver, alvo, motivo) -> None:
    d = policy.decide(Category.WRITE_LOCAL, target=str(alvo))
    d = type(d)(category=d.category, target=d.target, effect=d.effect, reason=motivo)
    if not gate(d, approver):
        raise CriacaoNegada("gravação não autorizada pelo usuário")


def gerar_imagem(prompt: str, home, policy, gate, approver,
                 host: str = "http://127.0.0.1:7860",
                 passos: int = 20, largura: int = 512, altura: int = 512,
                 timeout: float = 120.0):
    """txt2img via API do SD-WebUI; devolve caminho do PNG salvo."""
    corpo = json.dumps({"prompt": prompt, "steps": passos,
                        "width": largura, "height": altura}).encode()
    req = urllib.request.Request(f"{host}/sdapi/v1/txt2img", data=corpo,
                                 headers={"Content-Type": "application/json"})
    try:
        with _abrir_http(req, timeout) as r:
            data = json.loads(r.read().decode())
    except Exception as exc:
        raise CriacaoIndisponivel(
            f"não consegui falar com o gerador de imagens em {host} "
            f"({type(exc).__name__}). Dica: suba o Stable Diffusion WebUI "
            "com --api, ou escolha outro motor em /motores.") from None
    imagens = data.get("images") or []
    if not imagens:
        raise CriacaoIndisponivel("o gerador respondeu sem imagem — nada foi salvo")
    try:
        png = base64.b64decode(imagens[0])
    except Exception:
        raise CriacaoIndisponivel(
            "resposta do gerador não é base64 válido — nada foi salvo") from None
    if not png.startswith(PNG_MAGIC):
        raise CriacaoIndisponivel("resposta não é um PNG válido — nada foi salvo")
    destino = _destino(home, "imagem", prompt, "png")
    _gate_escrita(policy, gate, approver, destino, f"salvar imagem gerada de: {prompt[:60]}")
    destino.write_bytes(png)
    chmod_privado(destino, 0o600)
    return destino


def falar(texto: str, home, policy, gate, approver, voz: str | None = None,
          timeout: float = 60.0):
    """TTS via piper; devolve caminho do WAV salvo."""
    piper = shutil.which("piper")
    if not piper:
        raise CriacaoIndisponivel(
            "não achei o piper no PATH. Dica: github.com/rhasspy/piper "
            "(binário único) — depois é só tentar de novo.")
    destino = _destino(home, "fala", texto, "wav")
    _gate_escrita(policy, gate, approver, destino, f"salvar áudio da fala: {texto[:60]}")
    argv = [piper, "--output_file", str(destino)]
    if voz:
        argv += ["--model", voz]
    try:
        proc = subprocess.run(argv, input=texto.encode(), capture_output=True,  # nosec B603 - argv construído localmente, sem shell
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CriacaoIndisponivel("piper demorou demais — nada foi salvo") from None
    if proc.returncode != 0 or not destino.exists():
        raise CriacaoIndisponivel(
            f"piper falhou (rc={proc.returncode}): "
            f"{proc.stderr.decode(errors='replace')[:120]}")
    cab = destino.read_bytes()[:4]
    if cab != RIFF:
        destino.unlink(missing_ok=True)
        raise CriacaoIndisponivel("saída do piper não é WAV válido — descartada")
    chmod_privado(destino, 0o600)
    return destino
