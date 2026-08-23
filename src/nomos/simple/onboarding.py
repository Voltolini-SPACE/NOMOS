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
    # SÓ modelos que sabem gerar: um modelo de embedding entra em /api/tags
    # como qualquer outro, mas o Ollama recusa /api/generate nele. Ver
    # `modelos_ollama_geradores`.
    from nomos.cognition.motores import modelos_ollama_geradores
    return modelos_ollama_geradores(host)


def escolher_modelo(nomes: list[str]) -> str | None:
    """Escolhe o cérebro entre modelos que JÁ foram filtrados por capacidade.

    A lista chega de `modelos_ollama_geradores`; aqui só se ordena preferência.
    Ordem: Hermes (o cérebro padrão do projeto), depois llama — essa é uma
    decisão de produto, não um detalhe; eu a havia invertido sem necessidade e
    o teste `prefere_hermes` pegou. As famílias seguintes são acréscimo: sem
    elas, um cofre só com qwen/gemma/mistral caía no `sorted()[0]` alfabético.

    O `sorted(nomes)[0]` final é alfabético e por isso era perigoso enquanto a
    lista vinha crua: com um cofre contendo `embeddinggemma`, `nomic-embed-text`
    e `qwen3.5`, o alfabeto elegia o primeiro — um modelo que não responde.
    """
    if not nomes:
        return None
    for prefixo in ("hermes", "llama", "qwen", "gemma", "mistral", "phi"):
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
    say("Vamos deixar tudo pronto em 5 passinhos. Você decide onde seus dados")
    say("ficam — e nada sai daqui sem a sua permissão.\n")

    # 1) nome
    say(c("negrito", "1/5 · Como seu agente vai se chamar?"))
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
    say(c("negrito", f"2/5 · Que jeito o(a) {nome} deve ter?"))
    for k, (_, desc) in PERSONALIDADES.items():
        say(f"   {k}) {desc}")
    escolha = ask("escolha [1]> ").strip() or "1"
    persona = PERSONALIDADES.get(escolha, PERSONALIDADES["1"])[0]

    # 3) cérebro
    say("")
    say(c("negrito", "3/5 · Procurando um cérebro local (Ollama)…"))
    modelos = listar_modelos(host_ollama)
    modelo = escolher_modelo(modelos)
    if modelo:
        extra = " (Hermes! ótima escolha de casa)" if modelo.lower().startswith("hermes") else ""
        say(c("verde", f"   achei o modelo '{modelo}'{extra} — será o padrão."))
        modo = "local"
    else:
        say(c("amarelo", "   não achei um cérebro local rodando — sem problema."))
        say("   O caminho mais fácil (sem GPU, sem Ollama, ~400 MB, uma vez):")
        say("     nomos cerebro baixar    — o cérebro leve embutido do NOMOS.")
        say("   Prefere o Ollama? instale (ollama.com) e rode: ollama pull hermes3")
        say("   — qualquer um dos dois eu detecto sozinho.")
        say("   Por enquanto fico em MODO DEMO: converso sobre o que sei fazer,")
        say("   guardo suas anotações, mas não invento respostas de IA.")
        modo, modelo = "demo", None

    # 4) localidade — DECISÃO da pessoa, não regra da casa
    #
    # Antes deste passo o cadeado simplesmente nascia LIGADO e o assunto nunca
    # era levantado: na prática, uma regra imposta em silêncio. Agora é uma
    # pergunta. Quem apertar Enter continua protegido (o default segue LIGADO,
    # fail-closed a favor da privacidade) — a diferença é que passou a ser uma
    # escolha declarada, e não uma imposição invisível.
    say("")
    say(c("negrito", "4/5 · Onde seus dados podem ir?"))
    say(c("fraco", "   1) só nesta máquina — nenhum dado sai daqui (recomendado)"))
    say(c("fraco", "   2) posso usar a nuvem — cada saída ainda pede sua aprovação"))
    escolha_local = ask("escolha [1]> ").strip() or "1"
    so_local = escolha_local != "2"
    from nomos.kernel import localidade as _loc
    _loc.definir(config.nomos_home(), ligado=so_local)
    if so_local:
        say(c("verde", "   trancado nesta máquina. Muda quando quiser: nomos local off"))
    else:
        say(c("amarelo", "   nuvem liberada — mas o gate continua: toda saída para a"))
        say(c("amarelo", "   internet pede aprovação explícita, uma a uma."))
        say(c("fraco", "   Volta atrás quando quiser: nomos local on"))

    # 5) senha-mestra (opcional)
    say("")
    say(c("negrito", "5/5 · Cofre de chaves (opcional)"))
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
        "cofre": cofre, "so_local": so_local, "onboarding_completo": True,
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
