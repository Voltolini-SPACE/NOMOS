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
from pathlib import Path

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


def capacidades_ollama(nome: str, host: str = OLLAMA) -> tuple[str, ...]:
    """Capacidades declaradas pelo próprio Ollama para um modelo.

    Ex.: `qwen3.5:4b-q8_0` -> ('completion','vision','tools','thinking');
    `embeddinggemma:300m` -> ('embedding',). Sem isto não há como distinguir
    um modelo de conversa de um modelo só de embedding pelo NOME.
    """
    def probe():
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{host}/api/show", data=json.dumps({"model": nome}).encode(),
                headers={"Content-Type": "application/json"})
            with _abrir_http(req, 3.0) as r:   # guard do módulo: valida esquema
                return tuple(json.loads(r.read().decode()).get("capabilities") or ())
        except Exception:
            return ()
    return _cacheado(f"caps:{host}:{nome}", 60.0, probe)


def modelos_ollama_geradores(host: str = OLLAMA) -> list[str]:
    """Só os modelos que SABEM gerar texto.

    Um modelo de embedding (`embeddinggemma`, `nomic-embed-text`) aparece em
    `/api/tags` como qualquer outro, mas o Ollama recusa `/api/generate` nele:
    `"embeddinggemma:300m" does not support generate`. Escolher um desses como
    cérebro produz um agente que não responde NADA — e um check-up verde
    mentindo "Cérebro pronto". Aconteceu em 22/08 com o cofre soberano, que só
    tinha dois modelos de embedding e um de conversa.

    Fail-safe: se o Ollama não declarar capacidades (versão antiga), cai na
    heurística do nome — melhor excluir demais que eleger um cérebro mudo.
    """
    nomes = modelos_ollama(host)
    geradores = []
    for n in nomes:
        caps = capacidades_ollama(n, host)
        if caps:
            if "completion" in caps:
                geradores.append(n)
        elif "embed" not in n.lower():
            geradores.append(n)
    return geradores


def _melhor(nomes: list[str], prefixos: tuple[str, ...]) -> str | None:
    for p in prefixos:
        for n in nomes:
            if p in n.lower():
                return n
    return None


def _melhor_por_capacidade(nomes: list[str], capacidade: str,
                           host: str = OLLAMA,
                           prefixos: tuple[str, ...] = ()) -> str | None:
    """O primeiro modelo que DECLARA a capacidade — não o que parece declarar.

    Casar o NOME do modelo ("llava", "vl", "vision") é um bug de classe: todo
    modelo novo entra como "sem motor" até alguém lembrar de acrescentar o
    prefixo. Medido em 23/08: `qwen3.5:4b-q8_0` responde
    `capabilities: ['completion','vision','tools','thinking']` no /api/show e
    descreveu uma imagem corretamente — enquanto o painel dizia "sem motor de
    visão", porque o nome não casava com nenhum prefixo.

    Fail-safe: Ollama antigo não devolve `capabilities`. Aí, e SÓ aí, cai na
    heurística do nome — melhor um palpite velho que nenhuma resposta.
    """
    declarados = [n for n in nomes if capacidade in capacidades_ollama(n, host)]
    if declarados:
        return declarados[0]
    # nenhum declarou: foi porque não sabem, ou porque o Ollama não conta?
    if any(capacidades_ollama(n, host) for n in nomes):
        return None                      # o Ollama conta, e a resposta é não
    return _melhor(nomes, prefixos) if prefixos else None


# Onde um modelo do whisper.cpp costuma estar. Lista FECHADA de propósito:
# varrer o disco inteiro levou mais de 10 minutos numa medição.
_DIRS_WHISPER = (
    "~/.nomos/models/whisper",
    "~/.cache/whisper",
    "/opt/homebrew/share/whisper-cpp",
    "/usr/local/share/whisper-cpp",
    "~/Desktop/Pantheon AI/pantheon-core/runtime/models/whisper",
)


def whisper_disponivel() -> tuple[str | None, str | None, str]:
    """(binário, modelo, motivo) — a verdade sobre transcrever nesta máquina.

    Três defeitos moravam aqui, e consertar um só piora o conjunto:

    1. procurava `whisper`/`whisper-cpp` e ignorava `whisper-cli`, que é o nome
       atual do whisper.cpp no Homebrew — o único presente neste Mac;
    2. `"whisper-cli"` não contém a substring `"whisper-cpp"`, então quem só
       acrescenta o nome faz o binário cair no ramo de flags do openai-whisper.
       Medido: ele imprime o HELP e sai com **EXIT=0**, sem transcrever nada —
       um rc mentiroso que vira "transcrição vazia" com a causa errada;
    3. o ramo whisper.cpp nunca passava `-m`, e o binário morre em
       `failed to open 'models/ggml-base.en.bin'`.

    Por isso esta função devolve o MODELO junto: binário sem modelo não é motor
    pronto, é promessa. Dizer "pronto" ali seria trocar uma mentira por outra.
    """
    bin_ = (shutil.which("whisper-cli") or shutil.which("whisper-cpp")
            or shutil.which("whisper"))
    if not bin_:
        return None, None, "nenhum binário de whisper no PATH do serviço"
    # o openai-whisper baixa o modelo sozinho na primeira execução
    if Path(bin_).name == "whisper":
        return bin_, None, "openai-whisper (baixa o modelo na 1ª execução)"
    env = os.environ.get("NOMOS_WHISPER_MODEL")
    candidatos = [Path(env).expanduser()] if env else []
    for d in _DIRS_WHISPER:
        base = Path(d).expanduser()
        if not base.is_dir():
            continue
        candidatos += sorted(base.glob("ggml-*.bin"))
    for c in candidatos:
        if c.is_file() and c.stat().st_size > 1_000_000:
            return bin_, str(c), "pronto"
    return bin_, None, ("binário presente, modelo ausente — baixe um ggml-*.bin "
                        "(ex.: ggml-base.bin) ou aponte NOMOS_WHISPER_MODEL")


def say_disponivel() -> str | None:
    """O `say` do macOS: TTS que já existe em toda máquina, sem instalar nada.

    O detector só conhecia o `piper`, que exige download. Enquanto isso
    `/usr/bin/say` estava no PATH do próprio serviço, com 9 vozes pt-BR, e o
    painel dizia "nenhum motor de falar".
    """
    return shutil.which("say")


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
    # visão POR CAPACIDADE declarada; o nome vira só fail-safe de Ollama antigo
    visao = _melhor_por_capacidade(nomes, "vision", h["ollama"], PREFER["visao"])
    ferramentas = _melhor_por_capacidade(nomes, "tools", h["ollama"])
    sd_ok = _cacheado(f"sd:{h['sd']}", 10.0,
                      lambda: _http_ok(f"{h['sd']}/sdapi/v1/sd-models"))
    comfy_ok = _cacheado(f"comfy:{h['comfy']}", 10.0,
                         lambda: _http_ok(f"{h['comfy']}/system_stats"))
    piper = shutil.which("piper")
    say = say_disponivel()
    whisper_bin, whisper_modelo, whisper_motivo = whisper_disponivel()
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
            loc({"id": "say", "rotulo": "Voz do macOS (falar em voz alta → WAV)",
                 "disponivel": bool(say), "detalhe": say}),
            loc({"id": "piper", "rotulo": "Piper (falar em voz alta → WAV)",
                 "disponivel": bool(piper), "detalhe": piper}),
            # binário SEM modelo não é motor pronto: `disponivel` só é True com
            # os dois, e `detalhe` diz qual das duas peças falta.
            loc({"id": "whisper", "rotulo": "Whisper (transcrever áudio)",
                 "disponivel": bool(whisper_bin and whisper_modelo),
                 "detalhe": whisper_modelo or whisper_motivo}),
        ],
        "ferramentas": [
            # o motor SABER chamar ferramenta e HAVER skill instalada são coisas
            # diferentes; estavam na mesma linha e o dono lia "não sei chamar".
            loc({"id": "function-calling",
                 "rotulo": f"Chamar ferramentas ({ferramentas or 'sem modelo'})",
                 "disponivel": bool(ferramentas), "detalhe": ferramentas}),
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
