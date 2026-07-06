"""NOMOS cognition.engine_catalog — catálogo de motores v0.11, por modalidade.

Camada de LEITURA sobre a detecção existente (cognition.motores) — não muda
como motores são detectados nem escolhidos; enriquece com os atributos que o
usuário e o roteador precisam: local/nuvem, custo, privacidade, velocidade,
qualidade, chave, aprovação e status.

Modalidades v0.11 (12): texto, codigo, raciocinio, resumo, memoria, voz_stt,
voz_tts, imagem, visao, embeddings, ferramentas, roteamento.

Tipos de motor: embutido · ollama · llamacpp · cloud (opt-in) · mock ·
skill (fornecido por skill) · conector (externo, só se plugado).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from nomos.cognition import motores as _mot
from nomos.kernel import config, localidade

MODALIDADES_V011 = ("texto", "codigo", "raciocinio", "resumo", "memoria",
                    "voz_stt", "voz_tts", "imagem", "visao", "embeddings",
                    "ferramentas", "roteamento")

TIPOS = ("embutido", "ollama", "llamacpp", "cloud", "mock", "skill", "conector")

# Servidor OpenAI-compatível LOCAL (MC30-C3) — loopback por lei
OPENAI_COMPAT_BASE = "http://127.0.0.1:1234/v1"


@dataclass(frozen=True)
class Motor:
    id: str
    rotulo: str
    modalidades: tuple[str, ...]
    tipo: str                      # um de TIPOS
    local: bool
    instalado: bool
    pronto: bool
    custo: str = "grátis"          # "grátis" | "pago por uso"
    privacidade: str = "total"     # "total (não sai da máquina)" | "dados saem da máquina"
    velocidade: str = "média"      # "alta" | "média" | "depende da internet"
    qualidade: str = "boa"         # "básica" | "boa" | "alta"
    requer_chave: bool = False
    requer_aprovacao: bool = False
    status: str = ""
    detalhe: str = ""

    def dict(self) -> dict:
        return asdict(self)


@dataclass
class Catalogo:
    motores: list[Motor] = field(default_factory=list)

    def por_modalidade(self, modalidade: str) -> list[Motor]:
        return [m for m in self.motores if modalidade in m.modalidades]

    def prontos(self, modalidade: str) -> list[Motor]:
        return [m for m in self.por_modalidade(modalidade) if m.pronto]

    def por_id(self, mid: str) -> Motor | None:
        return next((m for m in self.motores if m.id == mid), None)


def _status(pronto: bool, instalado: bool, bloqueado: str = "") -> str:
    if bloqueado:
        return bloqueado
    if pronto:
        return "pronto"
    return "instalado, não respondeu" if instalado else "não instalado"


def construir(home=None, mapa: dict | None = None) -> Catalogo:
    """Constrói o catálogo v0.11 a partir da detecção real (com cache de 10s)."""
    home = home or config.nomos_home()
    so_local = localidade.esta_ligado(home)
    mapa = mapa or _mot.detectar()
    de = {m["id"]: m for mod in mapa.values() for m in mod}

    def d(mid, campo="disponivel", padrao=False):
        return de.get(mid, {}).get(campo, padrao)

    itens: list[Motor] = []

    # --- texto / raciocínio / resumo (LLMs locais) ---
    itens.append(Motor(
        id="embutido", rotulo="Cérebro embutido do NOMOS (leve)",
        modalidades=("texto", "resumo", "raciocinio"), tipo="embutido",
        local=True, instalado=d("embutido"), pronto=d("embutido"),
        velocidade="média", qualidade="básica",
        status=_status(d("embutido"), d("embutido")) if d("embutido")
        else "baixe uma vez: nomos cerebro baixar",
        detalhe=d("embutido", "detalhe", "") or "nomos-mini"))
    ollama_modelo = d("ollama", "detalhe", None)
    itens.append(Motor(
        id="ollama", rotulo=f"Ollama local ({ollama_modelo or 'sem modelo'})",
        modalidades=("texto", "resumo", "raciocinio"), tipo="ollama",
        local=True, instalado=bool(ollama_modelo), pronto=d("ollama"),
        velocidade="alta", qualidade="alta",
        status=_status(d("ollama"), bool(ollama_modelo)),
        detalhe=ollama_modelo or ""))

    # OpenAI-compatível local (MC30-C3): LM Studio / llama.cpp server / LocalAI.
    # Loopback apenas — nada sai da máquina; probe leve em /v1/models.
    oc_pronto = _mot._http_ok(f"{OPENAI_COMPAT_BASE}/models")
    itens.append(Motor(
        id="openai-compat", rotulo="Servidor local OpenAI-compatível "
        "(LM Studio, llama.cpp, LocalAI)",
        modalidades=("texto", "resumo", "raciocinio", "codigo"),
        tipo="llamacpp", local=True, instalado=oc_pronto, pronto=oc_pronto,
        velocidade="alta", qualidade="alta",
        status=_status(oc_pronto, oc_pronto) if oc_pronto
        else "ligue seu servidor local na porta 1234 (ex.: LM Studio)",
        detalhe=OPENAI_COMPAT_BASE))

    # --- código ---
    coder = d("ollama-coder", "detalhe", None)
    itens.append(Motor(
        id="ollama-coder", rotulo=f"Ollama coder ({coder or 'sem modelo'})",
        modalidades=("codigo",), tipo="ollama", local=True,
        instalado=bool(coder), pronto=d("ollama-coder"),
        velocidade="alta", qualidade="alta",
        status=_status(d("ollama-coder"), bool(coder)), detalhe=coder or ""))
    itens.append(Motor(
        id="texto-como-codigo", rotulo="usar o motor de texto para código",
        modalidades=("codigo",), tipo="ollama", local=True,
        instalado=bool(ollama_modelo) or d("embutido"),
        pronto=d("texto") or d("ollama") or d("embutido"),
        qualidade="boa", status="reserva (fallback)", detalhe=ollama_modelo or ""))

    # --- nuvem (opt-in por lei) ---
    bloqueio = ("🔒 desplugada pelo modo só-local (nomos local off para plugar)"
                if so_local else "")
    itens.append(Motor(
        id="anthropic", rotulo="Claude na nuvem",
        modalidades=("texto", "codigo", "raciocinio", "resumo"), tipo="cloud",
        local=False, instalado=True, pronto=not so_local,
        custo="pago por uso", privacidade="dados saem da máquina",
        velocidade="depende da internet", qualidade="alta",
        requer_chave=True, requer_aprovacao=True,
        status=bloqueio or "opt-in: exige aprovação A2+A3 e chave no cofre",
        detalhe="api.anthropic.com"))

    # --- imagem / visão ---
    itens.append(Motor(
        id="sdwebui", rotulo="Stable Diffusion WebUI (gerar imagens)",
        modalidades=("imagem",), tipo="conector", local=True,
        instalado=d("sdwebui"), pronto=d("sdwebui"),
        requer_aprovacao=True,   # salvar arquivo => A1
        status=_status(d("sdwebui"), d("sdwebui")), detalhe=d("sdwebui", "detalhe", "")))
    itens.append(Motor(
        id="comfyui", rotulo="ComfyUI (gerar imagens)",
        modalidades=("imagem",), tipo="conector", local=True,
        instalado=d("comfyui"), pronto=d("comfyui"),
        requer_aprovacao=True,
        status=_status(d("comfyui"), d("comfyui")), detalhe=d("comfyui", "detalhe", "")))
    visao = d("visao-ollama", "detalhe", None)
    itens.append(Motor(
        id="visao-ollama", rotulo=f"Visão local ({visao or 'sem modelo'})",
        modalidades=("visao",), tipo="ollama", local=True,
        instalado=bool(visao), pronto=d("visao-ollama"),
        status=_status(d("visao-ollama"), bool(visao)), detalhe=visao or ""))

    # --- voz ---
    itens.append(Motor(
        id="piper", rotulo="Piper (falar em voz alta → WAV)",
        modalidades=("voz_tts",), tipo="conector", local=True,
        instalado=d("piper"), pronto=d("piper"), requer_aprovacao=True,
        status=_status(d("piper"), d("piper")), detalhe=str(d("piper", "detalhe", ""))))
    itens.append(Motor(
        id="whisper", rotulo="Whisper (transcrever áudio)",
        modalidades=("voz_stt",), tipo="conector", local=True,
        instalado=d("whisper"), pronto=d("whisper"),
        status=_status(d("whisper"), d("whisper")), detalhe=str(d("whisper", "detalhe", ""))))

    # --- memória / embeddings (sempre locais, parte do NOMOS) ---
    itens.append(Motor(
        id="memoria-local", rotulo="Memória local (SQLite, na sua máquina)",
        modalidades=("memoria",), tipo="embutido", local=True,
        instalado=True, pronto=True, velocidade="alta", status="pronto",
        detalhe="memory.db"))
    itens.append(Motor(
        id="busca-local", rotulo="Busca local nas memórias (FTS5)",
        modalidades=("embeddings",), tipo="embutido", local=True,
        instalado=True, pronto=True, velocidade="alta", qualidade="básica",
        status="pronto", detalhe="fts5"))

    # --- ferramentas (skills instaladas) ---
    n_skills = _contar_skills(home)
    itens.append(Motor(
        id="skills", rotulo=f"Skills instaladas ({n_skills})",
        modalidades=("ferramentas",), tipo="skill", local=True,
        instalado=n_skills > 0, pronto=n_skills > 0, requer_aprovacao=True,
        status="pronto" if n_skills else "instale com: nomos skills instalar",
        detalhe=f"{n_skills} skill(s)"))

    # --- roteamento (o próprio roteador local) ---
    itens.append(Motor(
        id="roteador", rotulo="Roteador automático do NOMOS (local)",
        modalidades=("roteamento",), tipo="embutido", local=True,
        instalado=True, pronto=True, velocidade="alta", status="pronto",
        detalhe="engine_router"))

    return Catalogo(itens)


def _contar_skills(home) -> int:
    try:
        from nomos.ext import skills as _sk
        base = home or config.nomos_home()
        return len(_sk.list_installed(base / "skills"))
    except Exception:
        return 0


def recomendar(modalidade: str, cat: Catalogo | None = None, home=None) -> Motor | None:
    """Melhor motor PRONTO para a modalidade — local primeiro, sempre."""
    cat = cat or construir(home)
    prontos = cat.prontos(modalidade)
    locais = [m for m in prontos if m.local]
    if locais:
        # qualidade alta > boa > básica, empate resolvido pela ordem do catálogo
        ordem = {"alta": 0, "boa": 1, "básica": 2}
        return sorted(locais, key=lambda m: ordem.get(m.qualidade, 3))[0]
    return prontos[0] if prontos else None


def tabela_v011(cat: Catalogo | None = None, home=None) -> str:
    """Tabela amigável: uma seção por modalidade, atributos que importam."""
    cat = cat or construir(home)
    linhas = ["Motores do NOMOS (v0.11)", "=" * 60]
    for mod in MODALIDADES_V011:
        ms = cat.por_modalidade(mod)
        if not ms:
            continue
        rec = recomendar(mod, cat)
        linhas.append(f"\n{mod}:")
        for m in ms:
            marca = "✓" if m.pronto else "–"
            estrela = "  ← recomendado" if rec and m.id == rec.id else ""
            linhas.append(f"  [{marca}] {m.id:<16} {m.rotulo}{estrela}")
            linhas.append(f"        {'local' if m.local else 'NUVEM'} · {m.custo} · "
                          f"privacidade: {m.privacidade} · {m.velocidade} · "
                          f"qualidade {m.qualidade}")
            extras = []
            if m.requer_chave:
                extras.append("requer chave no cofre")
            if m.requer_aprovacao:
                extras.append("pede sua aprovação")
            if extras or m.status:
                linhas.append(f"        {' · '.join(extras + ([m.status] if m.status else []))}")
    linhas.append("")
    linhas.append("recomendação por tarefa:  nomos motores recomendar <modalidade>")
    return "\n".join(linhas)
