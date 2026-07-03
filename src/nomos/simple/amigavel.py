"""NOMOS simple.amigavel — o chat com personalidade, sem jargão.

Mesmo Router/Memory/gate dos ciclos anteriores; muda só a conversa.
Modo demo é HONESTO: acolhe, lembra, orienta — jamais finge ser IA.
"""
from __future__ import annotations

from nomos.cognition import criacao, motores
from nomos.kernel import localidade
from nomos.simple import doutor as doutor_mod
from nomos.simple import tema as tema_mod
from nomos.simple import chaves as chaves_mod
from nomos.cognition.memory import Memory
from nomos.cognition.providers import OllamaProvider, ProviderUnavailable
from nomos.kernel.policy import gate as _gate
from nomos.simple.traducao import aprovador_amigavel, cor

AJUDA = """comandos:
  /memoria anotar <texto>   guardo uma anotação para sempre
  /memoria buscar <termo>   procuro nas suas anotações
  /tema                     escolho as cores do NOMOS (do seu jeito)
  /doutor                   faço um check-up e digo o que falta
  /local                    mostro/ajusto o cadeado que mantém tudo local
  /chaves                   guardo suas chaves com segurança (sem digitar aqui)
  /cerebro                  mostro/baixo meu cérebro leve
  /motores                  mostro meus motores (texto·código·imagem·áudio)
  /motor <modal> <id>       troco de motor  ex.: /motor codigo ollama-coder
  /cod <pedido>             programo usando o motor de código
  /arquivo <caminho>        leio e resumo um arquivo seu (tudo local)
  /ouvir <audio>            transcrevo um áudio (whisper local) e resumo
  /imagem <descrição>       gero uma imagem (se houver motor de imagem)
  /audio <texto>            falo em voz alta num arquivo .wav (via piper)
  /nuvem <pergunta>         respondo usando a nuvem (peço permissão antes)
  /status                   como estou por dentro
  /ajuda                    esta lista
  /sair                     até logo"""


def system_prompt(perfil: dict) -> str:
    nome = perfil.get("agent_name", "Agente")
    persona = {
        "caloroso": "prestativo e caloroso; explica com paciência e simpatia",
        "direto": "direto ao ponto; respostas curtas e objetivas",
        "leve": "descontraído e bem-humorado, sempre útil",
    }.get(perfil.get("personalidade", "caloroso"))
    return (f"Você é {nome}, o agente pessoal do usuário no NOMOS. "
            f"Seu jeito: {persona}. Responda SEMPRE em português do Brasil. "
            "Seja honesto sobre o que não sabe. Nunca invente fatos.")


_GATILHOS_LEMBRETE = ("me lembra", "lembrar", "lembre", "anota", "anote",
                      "não esquec", "nao esquec", "guarda isso", "guardar isso",
                      "não deixa eu esquecer", "nao deixa eu esquecer")


def parece_lembrete(texto: str) -> bool:
    t = texto.strip().lower()
    return any(g in t for g in _GATILHOS_LEMBRETE)


def resposta_demo(texto: str, nome: str) -> str:
    return (f"[{nome} em modo demo — ainda sem cérebro de IA conectado]\n"
            "Eu registro e busco suas anotações (/memoria), explico minhas "
            "permissões e fico pronto para o dia em que você conectar um "
            "modelo (instale o Ollama e rode: ollama pull hermes3). "
            "O que eu NÃO faço é fingir uma resposta de IA — regra da casa.")


def iniciar_chat(ctx, perfil: dict, router, ask=input, say=print, colorido: bool = True,
                 aprovador=None) -> int:
    c = lambda n, t: cor(n, t, colorido)
    nome = perfil.get("agent_name", "Agente")
    mem = Memory(ctx["home"] / "memory.db")
    aprovador = aprovador or aprovador_amigavel(perfil.get("agent_name", "Agente"),
                                                ask=ask, say=say)
    tobj = tema_mod.carregar(perfil)
    demo = perfil.get("modo_cerebro") == "demo"
    say(c("fraco", f"({nome} pronto — /ajuda mostra os comandos)"))
    while True:
        try:
            prompt = tobj.c("destaque", "você> ") if colorido else "você> "
            linha = ask(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            say("")
            linha = "/sair"
        if not linha:
            continue
        if linha == "/sair":
            say(f"{nome}: até logo! Suas memórias ficam guardadas aqui.")
            return 0
        if linha == "/ajuda":
            say(AJUDA)
            continue
        if linha == "/status":
            cerebro = perfil.get("modelo") or "nenhum (modo demo)"
            cadeado = "só-local 🔒" if localidade.esta_ligado(ctx["home"]) else "nuvem plugada 🔌"
            cofre_txt = "sim" if perfil.get("cofre") else "ainda não"
            say(f"cérebro: {cerebro} · memórias: {mem.count()} · "
                f"caixa-forte: {cofre_txt} · {cadeado} · tudo no seu computador")
            continue
        if linha.startswith("/nuvem"):
            pergunta = linha[6:].strip()
            if not pergunta:
                say("uso: /nuvem <sua pergunta> — eu peço sua permissão antes de sair.")
                continue
            if localidade.esta_ligado(ctx["home"]):
                say(f"{nome}: estou em modo só-local 🔒 — a nuvem está desplugada "
                    "e nada sai da sua máquina. Para plugar (no terminal): "
                    "nomos local off")
                continue
            if demo and router is None:
                say(f"{nome}: para usar a nuvem eu preciso do roteador ligado "
                    "(rode pelo 'nomos start').")
                continue
            import getpass as _gp
            senha = _gp.getpass("sua senha-mestra (para ler a chave): ") \
                if (hasattr(__import__("sys").stdin, "isatty") and __import__("sys").stdin.isatty()) else None
            msgs = [{"role": "system", "content": system_prompt(perfil)},
                    {"role": "user", "content": pergunta}]
            out = router.chat(msgs, prefer_cloud=True, passphrase=senha)
            if out.ok:
                say(f"{nome} (nuvem): {out.text}")
                mem.remember("user", pergunta)
                mem.remember("assistant", out.text)
            else:
                say(f"{nome}: não consegui usar a nuvem — {out.reason}")
            continue
        if linha == "/tema":
            perfil.update(tema_mod.menu_tema(ask=ask, say=say, perfil=perfil))
            continue
        if linha == "/doutor":
            say(doutor_mod.texto_relatorio(ctx["home"]))
            continue
        if linha == "/local":
            if localidade.esta_ligado(ctx["home"]):
                say(f"{nome}: modo só-local LIGADO 🔒 — tudo acontece no seu "
                    "computador, nada sai para a internet. Os motores de nuvem "
                    "ficam desplugados. Para plugar (no terminal): nomos local off")
            else:
                say(f"{nome}: modo só-local DESLIGADO 🔌 — você permitiu motores "
                    "externos; cada uso ainda pede sua permissão. Reative com: "
                    "nomos local on")
            continue
        if linha == "/chaves":
            chaves_mod.menu_chaves(ctx["home"], ask=ask, say=say)
            continue
        if linha == "/cerebro":
            from nomos.cognition import embutido as _emb
            rec = _emb.recomendado()
            baixado = any(_emb.esta_baixado(ctx["home"], m) for m in _emb.CATALOGO)
            if baixado and _emb.llama_disponivel():
                say(f"{nome}: meu cérebro leve já está pronto e rodando na sua máquina.")
            else:
                say(f"{nome}: meu cérebro leve ({rec.rotulo}, ~{rec.mb} MB) roda em qualquer PC.")
                say("       No terminal:  nomos cerebro baixar  (baixo sozinho, uma vez).")
            continue
        if linha == "/motores":
            say(motores.tabela(perfil=perfil))
            continue
        if linha.startswith("/motor "):
            partes = linha.split()
            if len(partes) < 3:
                say("uso: /motor <modalidade> <id> — veja /motores")
                continue
            try:
                perfil.update(motores.escolher(partes[1], partes[2]))
                say(f"{nome}: feito! {partes[1]} agora usa '{partes[2]}'.")
            except ValueError as exc:
                say(f"{nome}: {exc}")
            continue
        if linha.startswith("/cod"):
            pedido = linha[4:].strip()
            if not pedido:
                say("uso: /cod <o que você quer programar>")
                continue
            mapa = motores.detectar()
            m = motores.ativo("codigo", mapa, perfil)
            if not m:
                say(f"{nome}: ainda estou sem motor de código. "
                    f"Dica: {motores.DICAS['codigo']}")
                continue
            modelo = m.get("detalhe")
            sistema = (f"Você é {nome}, programador(a) sênior. Responda em português "
                       "com código claro e comentado. Nunca invente APIs.")
            try:
                r = OllamaProvider(model=modelo).chat(
                    [{"role": "system", "content": sistema},
                     {"role": "user", "content": pedido}])
                say(f"{nome} [{modelo}]:\n{r.text}")
                mem.remember("user", f"/cod {pedido}")
                mem.remember("assistant", r.text)
            except ProviderUnavailable as exc:
                say(f"{nome}: o motor de código não respondeu ({exc}).")
            continue
        if linha.startswith("/arquivo"):
            caminho = linha[8:].strip()
            if not caminho:
                say("uso: /arquivo <caminho do arquivo>")
                continue
            from nomos.cognition import arquivos as _arq
            try:
                resultado, estado = _arq.processar(caminho, ctx, aprovador,
                                                   router=router)
            except _arq.ArquivoError as exc:
                say(f"{nome}: {exc}")
                continue
            if estado.get("resumo") or estado.get("pontos"):
                say(_arq.render_resultado(caminho, estado))
                say(c("fraco", f"({resultado.explicacao})"))
                mem.remember("note", f"resumi o arquivo {caminho}")
            else:
                say(f"{nome}: não consegui extrair nada útil — {resultado.motivo}")
            continue
        if linha.startswith("/ouvir"):
            caminho = linha[6:].strip()
            if not caminho:
                say("uso: /ouvir <caminho do áudio> — transcrevo com o whisper local")
                continue
            from nomos.cognition import arquivos as _arq
            try:
                transcricao = _arq.transcrever(caminho)
            except _arq.ArquivoError as exc:
                say(f"{nome}: {exc}")
                continue
            say(f"{nome}: transcrevi ({len(transcricao)} caracteres, tudo local).")
            resumo = _arq.resumir_com_motor(transcricao, router)
            if resumo:
                say(f"resumo: {resumo}")
                mem.remember("note", f"áudio {caminho}: {resumo}")
            else:
                for p in _arq.extrair_pontos(transcricao, 5):
                    say(f"  · {p}")
                say(c("fraco", "(sem cérebro para resumo completo — guardei os pontos)"))
                mem.remember("note", f"áudio {caminho}: " +
                             "; ".join(_arq.extrair_pontos(transcricao, 3)))
            continue
        if linha.startswith("/imagem"):
            prompt = linha[7:].strip()
            if not prompt:
                say("uso: /imagem <descrição do que desenhar>")
                continue
            mapa_img = motores.detectar()
            m = next((x for x in mapa_img["imagem"]
                      if x["id"] == "sdwebui" and x["disponivel"]), None)
            comfy = next((x for x in mapa_img["imagem"]
                          if x["id"] == "comfyui" and x["disponivel"]), None)
            if not m and comfy:
                say(f"{nome}: vejo o ComfyUI rodando, mas por enquanto só gero "
                    "imagens pelo Stable Diffusion WebUI (--api na porta 7860). "
                    "Suporte ao ComfyUI está no plano.")
                continue
            if not m:
                say(f"{nome}: ainda não tenho um gerador de imagens. "
                    f"Dica: {motores.DICAS['imagem']}")
                continue
            try:
                cam = criacao.gerar_imagem(prompt, ctx["home"], ctx["policy"],
                                           _gate, aprovador,
                                           host=m["detalhe"])
                say(f"{nome}: imagem pronta! salvei em {cam}")
            except criacao.CriacaoNegada:
                say(f"{nome}: tudo bem, não salvei nada.")
            except criacao.CriacaoIndisponivel as exc:
                say(f"{nome}: {exc}")
            continue
        if linha.startswith("/audio"):
            texto = linha[6:].strip()
            if not texto:
                say("uso: /audio <o que devo falar>")
                continue
            try:
                cam = criacao.falar(texto, ctx["home"], ctx["policy"],
                                    _gate, aprovador)
                say(f"{nome}: gravei minha voz em {cam}")
            except criacao.CriacaoNegada:
                say(f"{nome}: sem problema, não gravei.")
            except criacao.CriacaoIndisponivel as exc:
                say(f"{nome}: {exc}")
            continue
        if linha.startswith("/memoria"):
            partes = linha.split(maxsplit=2)
            sub = partes[1] if len(partes) > 1 else "recentes"
            if sub == "anotar" and len(partes) > 2:
                mem.remember("note", partes[2])
                say(f"{nome}: anotado! ({mem.count()} lembranças no total)")
            elif sub == "buscar" and len(partes) > 2:
                achados = mem.recall_hibrido(partes[2])
                if not achados:
                    say(f"{nome}: não achei nada sobre isso ainda.")
                for it in achados:
                    say(f"  · {it.text}")
            else:
                for it in mem.recent(5):
                    say(f"  · ({it.role}) {it.text}")
            continue
        # conversa de verdade
        if demo:
            if parece_lembrete(linha):
                mem.remember("note", linha)
                say(f"{nome}: anotado! vou lembrar disso pra você. "
                    f"(veja tudo com /memoria)")
            else:
                say(resposta_demo(linha, nome))
                mem.remember("user", linha)
            continue
        contexto = [{"role": "system", "content": system_prompt(perfil)}] + [
            {"role": ("assistant" if m.role == "assistant" else "user"), "content": m.text}
            for m in reversed(mem.recent(6)) if m.role in {"user", "assistant"}
        ] + [{"role": "user", "content": linha}]
        out = router.chat(contexto)
        if out.ok:
            say(f"{nome}: {out.text}")
            mem.remember("user", linha)
            mem.remember("assistant", out.text)
        else:
            say(resposta_demo(linha, nome))
            say(c("fraco", f"(detalhe técnico: {out.reason})"))
    return 0
