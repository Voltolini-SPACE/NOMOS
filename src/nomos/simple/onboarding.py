"""NOMOS simple.onboarding — primeiro contato, em português de gente.

Fluxo (streams injetáveis => 100% testável sem terminal):
1. boas-vindas   2. nome do agente   3. personalidade   4. cérebro (Ollama,
preferindo Hermes; senão modo demo honesto)   5. senha-mestra opcional
6. perfil gravado em agent.json (0600) e pronto para o chat.
"""
from __future__ import annotations

import json
import os

from nomos.kernel import config
from nomos.kernel.vault import Vault, VaultError
from nomos.simple.traducao import cor

PERSONALIDADES = {
    "1": ("caloroso", "prestativo e caloroso — explica com paciência"),
    "2": ("direto", "direto ao ponto — respostas curtas, sem enrolação"),
    "3": ("leve", "descontraído — leve, mas sempre útil"),
}


def listar_modelos(host: str = "http://127.0.0.1:11434", timeout: float = 1.5) -> list[str]:
    """Modelos do Ollama. Delega ao registry (fonte única, com guard de esquema
    e cache); import tardio evita ciclo com cognition.motores."""
    from nomos.cognition.motores import modelos_ollama
    return modelos_ollama(host)


def escolher_modelo(nomes: list[str]) -> str | None:
    """Prefere Hermes (cérebro padrão do projeto), depois llama, depois o 1º."""
    if not nomes:
        return None
    for prefixo in ("hermes", "llama"):
        for n in nomes:
            if n.lower().startswith(prefixo):
                return n
    return sorted(nomes)[0]


def salvar_perfil(extras: dict) -> dict:
    config.ensure_home()
    dados = config.load_agent() or {}
    dados.update(extras)
    path = config.nomos_home() / config.AGENT_FILE
    path.write_text(json.dumps(dados, ensure_ascii=False, indent=2))
    os.chmod(path, 0o600)
    return dados


def run_onboarding(ask=input, say=print, host_ollama: str = "http://127.0.0.1:11434",
                   colorido: bool = True) -> dict:
    c = lambda n, t: cor(n, t, colorido)
    from nomos.simple.marca import banner
    say(banner())
    say(c("negrito", "  Bem-vindo(a) ao NOMOS — seu agente pessoal"))
    say("Vamos deixar tudo pronto em 4 passinhos. Nada sai do seu computador")
    say("sem a sua permissão — essa é a regra da casa.\n")

    # 1) nome
    say(c("negrito", "1/4 · Como seu agente vai se chamar?"))
    say(c("fraco", "   (2-32 letras/números, começando por letra — ex.: Atlas, Luna, Jarbas)"))
    while True:
        try:
            nome = config.validate_agent_name(ask("nome> "))
            break
        except config.ConfigError as exc:
            say(f"   hmm, {exc}. Tente outro:")
    config.save_agent(nome)

    # 2) personalidade
    say("")
    say(c("negrito", f"2/4 · Que jeito o(a) {nome} deve ter?"))
    for k, (_, desc) in PERSONALIDADES.items():
        say(f"   {k}) {desc}")
    escolha = ask("escolha [1]> ").strip() or "1"
    persona = PERSONALIDADES.get(escolha, PERSONALIDADES["1"])[0]

    # 3) cérebro
    say("")
    say(c("negrito", "3/4 · Procurando um cérebro local (Ollama)…"))
    modelos = listar_modelos(host_ollama)
    modelo = escolher_modelo(modelos)
    if modelo:
        extra = " (Hermes! ótima escolha de casa)" if modelo.lower().startswith("hermes") else ""
        say(c("verde", f"   achei o modelo '{modelo}'{extra} — será o padrão."))
        modo = "local"
    else:
        say(c("amarelo", "   não achei o Ollama rodando — sem problema."))
        say("   Para ter um cérebro local depois: instale o Ollama (ollama.com)")
        say("   e rode:  ollama pull hermes3   — eu detecto sozinho.")
        say("   Por enquanto fico em MODO DEMO: converso sobre o que sei fazer,")
        say("   guardo suas anotações, mas não invento respostas de IA.")
        modo, modelo = "demo", None

    # 4) senha-mestra (opcional)
    say("")
    say(c("negrito", "4/4 · Caixa-forte de chaves (opcional)"))
    say(c("fraco", "   Guarda suas chaves e senhas trancadas. Pode criar agora (senha de"))
    say(c("fraco", "   10+ caracteres) ou apertar Enter para deixar para depois."))
    vault = Vault(config.nomos_home() / "vault.json")
    while True:
        senha = ask("senha-mestra (Enter pula)> ")
        if not senha.strip():
            say("   ok, sem caixa-forte por enquanto — dá para criar quando quiser, é só")
            say("   pedir /chaves no chat.")
            cofre = False
            break
        try:
            if not vault.exists():
                vault.init(senha)
            cofre = True
            say(c("verde", "   caixa-forte criada e trancada."))
            break
        except VaultError as exc:
            say(f"   {exc} — tente de novo ou Enter para pular.")

    say("")
    say(c("fraco", "   Outros motores que sei usar (veja depois com /motores):"))
    try:
        from nomos.cognition import motores as _mot
        mapa = _mot.detectar()
        for modal in ("codigo", "imagem", "audio"):
            achou = [m["id"] for m in mapa[modal] if m["disponivel"]]
            say(f"   · {modal}: {', '.join(achou) if achou else 'nenhum ainda — ' + _mot.DICAS[modal]}")
    except Exception as exc:  # detecção é cortesia; falha não bloqueia onboarding
        say(c("fraco", f"   (não consegui listar outros motores agora: {type(exc).__name__})"))

    perfil = salvar_perfil({
        "personalidade": persona, "modelo": modelo, "modo_cerebro": modo,
        "cofre": cofre, "onboarding_completo": True,
    })

    say("")
    say(c("negrito", "Bônus · Cores (opcional)"))
    say(c("fraco", "   Deixe o NOMOS com a sua cara. Enter mantém o padrão; ou digite:"))
    from nomos.simple import tema as _tema
    say(c("fraco", "   " + " · ".join(_tema.PALETAS)))
    escolha_tema = ask("paleta (Enter pula)> ").strip().lower()
    if escolha_tema in _tema.PALETAS:
        perfil = _tema.aplicar(paleta=escolha_tema, perfil=perfil)
        say("   pronto! veja: ")
        say(_tema.amostra(perfil))
    say("")
    say(c("ciano", "═" * 46))
    say(c("negrito", f"  Pronto! {nome} está no ar. Experimente:"))
    say("   · escreva qualquer pergunta e Enter")
    say("   · /memoria anotar comprar café    (ele lembra!)")
    say("   · /ajuda para ver tudo · /sair para encerrar")
    say(c("ciano", "═" * 46))
    return perfil
