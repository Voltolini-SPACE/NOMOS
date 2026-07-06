"""NOMOS cognition.motores — multi-motores por modalidade, com honestidade.

Modalidades: texto · codigo · imagem · audio.
Regras:
- detecção automática LOCAL (Ollama, SD-WebUI, ComfyUI, piper, whisper);
- preferência sensata por modalidade, mas o usuário manda: escolha explícita
  é persistida no perfil e sobrevive a reinícios;
- motor ausente NUNCA vira resposta inventada: status honesto + instrução
  de instalação em uma linha;
- sondas com cache curto (10 s) para o chat continuar ágil.
"""
from __future__ import annotations

import json
import os
import shutil
import time
import urllib.request

from nomos.kernel import config, localidade
from nomos.cognition import embutido as _emb
from nomos.simple.onboarding import salvar_perfil

def _abrir_http(url_ou_req, timeout: float):
    """urlopen restrito a http/https — nunca file:// ou esquemas custom."""
    from urllib.parse import urlparse
    alvo = url_ou_req if isinstance(url_ou_req, str) else url_ou_req.full_url
    if urlparse(alvo).scheme not in {"http", "https"}:
        raise ValueError(f"esquema de URL não permitido: {alvo!r}")
    return urllib.request.urlopen(url_ou_req, timeout=timeout)  # nosec B310 - esquema validado acima



MODALIDADES = ("texto", "codigo", "imagem", "audio")
_OLLAMA_PADRAO = "http://127.0.0.1:11434"
OLLAMA = os.environ.get("NOMOS_OLLAMA_HOST", _OLLAMA_PADRAO)
# motor "local" é local por lei: host não-loopback no env NUNCA é sondado
# (senão o catálogo marcaria como "privacidade total" algo que sai da máquina)
if not localidade.eh_loopback(OLLAMA):
    OLLAMA = _OLLAMA_PADRAO
SD_WEBUI = "http://127.0.0.1:7860"
COMFYUI = "http://127.0.0.1:8188"

PREFER = {
    "texto": ("hermes", "llama", "qwen", "mistral", "gemma"),
    "codigo": ("qwen2.5-coder", "qwen-coder", "deepseek-coder", "codellama",
               "starcoder", "codegemma"),
    "visao": ("llava", "vl", "vision", "moondream"),
}

DICAS = {
    "texto": "instale o Ollama (ollama.com) e rode: ollama pull hermes3",
    "codigo": "rode: ollama pull qwen2.5-coder  (usa o de texto enquanto isso)",
    "imagem": "instale o Stable Diffusion WebUI (porta 7860) ou o ComfyUI (8188)",
    "audio": "instale o piper (TTS) — github.com/rhasspy/piper — e deixe no PATH",
}

_cache: dict[str, tuple[float, object]] = {}


def _cacheado(chave: str, ttl: float, fn):
    agora = time.monotonic()
    hit = _cache.get(chave)
    if hit and agora - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[chave] = (agora, val)
    return val


def limpar_cache() -> None:
    _cache.clear()


def _http_ok(url: str, timeout: float = 1.2) -> bool:
    try:
        with _abrir_http(url, timeout) as r:
            return 200 <= r.status < 500
    except Exception:
        return False


def modelos_ollama(host: str = OLLAMA) -> list[str]:
    def probe():
        try:
            with _abrir_http(f"{host}/api/tags", 1.5) as r:
                data = json.loads(r.read().decode())
            return [m["name"] for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []
    return _cacheado(f"ollama:{host}", 10.0, probe)


def _melhor(nomes: list[str], prefixos: tuple[str, ...]) -> str | None:
    for p in prefixos:
        for n in nomes:
            if p in n.lower():
                return n
    return None


def _cerebro_baixado() -> bool:
    try:
        home = config.nomos_home()
        return any(_emb.esta_baixado(home, m) for m in _emb.CATALOGO)
    except Exception:
        return False


def detectar(hosts: dict | None = None) -> dict:
    """Mapa modalidade -> lista de motores {id, rotulo, disponivel, detalhe}."""
    h = {"ollama": OLLAMA, "sd": SD_WEBUI, "comfy": COMFYUI, **(hosts or {})}
    nomes = modelos_ollama(h["ollama"])
    texto_local = _melhor(nomes, PREFER["texto"])
    cod_local = _melhor(nomes, PREFER["codigo"])
    visao = _melhor(nomes, PREFER["visao"])
    sd_ok = _cacheado(f"sd:{h['sd']}", 10.0,
                      lambda: _http_ok(f"{h['sd']}/sdapi/v1/sd-models"))
    comfy_ok = _cacheado(f"comfy:{h['comfy']}", 10.0,
                         lambda: _http_ok(f"{h['comfy']}/system_stats"))
    piper = shutil.which("piper")
    whisper = shutil.which("whisper") or shutil.which("whisper-cpp")
    so_local = localidade.esta_ligado(config.nomos_home())

    def externo(base):
        # motor que sai da máquina: indisponível enquanto o cadeado só-local estiver ligado
        base = dict(base)
        base["local"] = False
        if so_local:
            base["disponivel"] = False
            base["rotulo"] = "🔌 " + base["rotulo"] + " — para plugar, use 'nomos local off'"
        return base

    def loc(base):
        base = dict(base)
        base["local"] = True
        return base

    return {
        "texto": [
            loc({"id": "embutido",
                 "rotulo": "Cérebro embutido do NOMOS (leve, sem instalar nada extra)",
                 "disponivel": _emb.llama_disponivel() and _cerebro_baixado(),
                 "detalhe": "nomos-mini"}),
            loc({"id": "ollama", "rotulo": f"Ollama local ({texto_local or 'sem modelo'})",
                 "disponivel": bool(texto_local), "detalhe": texto_local}),
            externo({"id": "anthropic", "rotulo": "Claude na nuvem (peça permissão)",
                     "disponivel": True, "detalhe": "opt-in A2+A3"}),
        ],
        "codigo": [
            loc({"id": "ollama-coder", "rotulo": f"Ollama coder ({cod_local or 'sem modelo'})",
                 "disponivel": bool(cod_local), "detalhe": cod_local}),
            loc({"id": "texto", "rotulo": "usar o motor de texto",
                 "disponivel": bool(texto_local), "detalhe": texto_local}),
        ],
        "imagem": [
            loc({"id": "sdwebui", "rotulo": "Stable Diffusion WebUI (gerar imagens)",
                 "disponivel": sd_ok, "detalhe": h["sd"]}),
            loc({"id": "comfyui", "rotulo": "ComfyUI (gerar imagens)",
                 "disponivel": comfy_ok, "detalhe": h["comfy"]}),
            loc({"id": "visao-ollama", "rotulo": f"Visão local ({visao or 'sem modelo'}) — entender imagens",
                 "disponivel": bool(visao), "detalhe": visao}),
        ],
        "audio": [
            loc({"id": "piper", "rotulo": "Piper (falar em voz alta → WAV)",
                 "disponivel": bool(piper), "detalhe": piper}),
            loc({"id": "whisper", "rotulo": "Whisper (transcrever áudio)",
                 "disponivel": bool(whisper), "detalhe": whisper}),
        ],
    }


def escolhas(perfil: dict | None = None) -> dict:
    perfil = perfil if perfil is not None else (config.load_agent() or {})
    return dict(perfil.get("motores") or {})


def escolher(modalidade: str, motor_id: str, detalhe: str | None = None) -> dict:
    if modalidade not in MODALIDADES:
        raise ValueError(f"modalidade desconhecida: {modalidade!r} "
                         f"(use: {', '.join(MODALIDADES)})")
    mapa = detectar()
    ids = {m["id"] for m in mapa[modalidade]}
    if motor_id not in ids:
        raise ValueError(f"motor desconhecido para {modalidade}: {motor_id!r} "
                         f"(opções: {', '.join(sorted(ids))})")
    atual = escolhas()
    atual[modalidade] = {"id": motor_id, "detalhe": detalhe}
    return salvar_perfil({"motores": atual})


def ativo(modalidade: str, mapa: dict | None = None, perfil: dict | None = None) -> dict | None:
    """Motor efetivo: escolha do usuário se válida/disponível; senão o 1º disponível."""
    mapa = mapa or detectar()
    opcoes = mapa.get(modalidade, [])
    desejo = escolhas(perfil).get(modalidade, {}).get("id")
    if desejo:
        for m in opcoes:
            if m["id"] == desejo and m["disponivel"]:
                return m
    for m in opcoes:
        if m["disponivel"]:
            return m
    return None


def tabela(mapa: dict | None = None, perfil: dict | None = None) -> str:
    mapa = mapa or detectar()
    linhas = []
    for mod in MODALIDADES:
        at = ativo(mod, mapa, perfil)
        linhas.append(f"{mod}:")
        for m in mapa[mod]:
            marca = "✓" if m["disponivel"] else "–"
            estrela = "  ← ativo" if at and m["id"] == at["id"] else ""
            linhas.append(f"  [{marca}] {m['id']:<13} {m['rotulo']}{estrela}")
        if not at:
            linhas.append(f"      nenhum agora · dica: {DICAS[mod]}")
    linhas.append("")
    linhas.append("trocar: /motor <modalidade> <id>   ex.: /motor codigo ollama-coder")
    return "\n".join(linhas)
