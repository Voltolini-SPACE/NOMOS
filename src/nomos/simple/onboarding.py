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
    # escrita atômica + utf-8: crash no meio não corrompe o perfil e acentos
    # não quebram fora de UTF-8 (Windows/cp1252)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)
    return dados


def run_onboarding(ask=input, say=print, host_ollama: str = "http://127.0.0.1:11434",
                   colorido: bool = True, ask_secret=None) -> dict:
    c = lambda n, t: cor(n, t, colorido)
    # a senha-mestra do cofre NUNCA deve ecoar: getpass num terminal real;
    # fora de TTY (ou com ask_secret injetado nos testes), cai no ask normal
    if ask_secret is None:
        import getpass
        import sys as _sys
        if _sys.stdin.isatty():
            ask_secret = lambda p: getpass.getpass(p)
        else:
            ask_secret = ask
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
        say(c("amarelo", "   não achei um cérebro local rodando — sem problema."))
        say("   Caminho mais fácil: depois rode  nomos cerebro baixar  (uma vez,")
        say("   ~400 MB, sem GPU). Já usa Ollama com o modelo hermes3? eu detecto")
        say("   sozinho — veja outras opções em /motores quando quiser.")
        say("   Por enquanto fico em MODO DEMO: converso sobre o que sei fazer,")
        say("   guardo suas anotações, mas não invento respostas de IA.")
        modo, modelo = "demo", None

    # 4) senha-mestra (opcional)
    say("")
    say(c("negrito", "4/4 · Cofre de chaves (opcional)"))
    vault = Vault(config.nomos_home() / "vault.json")
    if vault.exists():
        # cofre pré-existente: NÃO pedir senha aqui — qualquer coisa digitada
        # seria ignorada e a pessoa sairia acreditando numa senha errada
        say(c("verde", "   você já tem um cofre — mantive a sua senha atual."))
        say(c("fraco", "   (para trocar a senha: nomos vault rotate)"))
        cofre = True
    else:
        say(c("fraco", "   Guarda suas chaves e senhas trancadas. Pode criar agora (senha de"))
        say(c("fraco", "   10+ caracteres) ou apertar Enter para deixar para depois."))
        while True:
            senha = ask_secret("senha-mestra (Enter pula)> ")
            if not senha.strip():
                say("   ok, sem cofre por enquanto — dá para criar quando quiser, é só")
                say("   pedir /chaves no chat.")
                cofre = False
                break
            try:
                vault.init(senha)
                cofre = True
                say(c("verde", "   cofre criado e trancado."))
                break
            except VaultError as exc:
                say(f"   {exc} — tente de novo ou Enter para pular.")

    perfil = salvar_perfil({
        "personalidade": persona, "modelo": modelo, "modo_cerebro": modo,
        "cofre": cofre, "onboarding_completo": True, "modo_iniciante": True,
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
