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
  /ver <imagem>             descrevo uma imagem (modelo de visão local)
  /imagem <descrição>       gero uma imagem (se houver motor de imagem)
  /audio <texto>            falo em voz alta num arquivo .wav (via piper)
  /bem · /mal               avalio minha última resposta (aprendo localmente)
  /contexto                 mostro exatamente o que enviei ao motor (com redação)
  /skills usar <nome> [json] executo uma skill instalada (com seu aval)
  /conversas                listo o histórico das nossas conversas
  /continuar <id>           retomo uma conversa antiga com o contexto dela
  /fixar                    marco esta conversa como importante (não expira)
  /privado                  modo efêmero: esta conversa NÃO é gravada em disco
  /nuvem <pergunta>         respondo usando a nuvem (peço permissão antes)
  /conselho                 Motor Council (pré-release, ainda DESABILITADO)
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


def _rodar_skill_conversa(ctx, nome_skill: str, argumentos, aprovador,
                          origem: str) -> tuple[bool, str]:
    """Executa skill a partir da conversa: gate de sempre + auditoria da cadeia."""
    from nomos.ext import skill_intencao as intencao
    from nomos.ext import skill_registry as reg
    from nomos.ext import skill_status as st
    policy = ctx["policy"]
    skills_dir = ctx.get("skills") or (ctx["home"] / "skills")
    rc, resultado, bruto = reg.executar_json(nome_skill, skills_dir, policy,
                                             aprovador, argumentos=argumentos)
    audit = ctx.get("audit")
    if audit is not None:
        audit.append("skill.conversa", name=nome_skill, origem=origem,
                     rc=rc, ok=rc == 0)
    if rc == 0:
        st.marcar_uso(ctx["home"], nome_skill)
        return True, intencao.render_resultado_skill(nome_skill, resultado, bruto)
    if rc == 3:
        return False, (f"a skill '{nome_skill}' não rodou: alguma permissão "
                       "foi negada (nada além do aprovado aconteceu)")
    return False, f"a skill '{nome_skill}' falhou (rc={rc})"


def iniciar_chat(ctx, perfil: dict, router, ask=input, say=print, colorido: bool = True,
                 aprovador=None, say_token=None) -> int:
    c = lambda n, t: cor(n, t, colorido)
    nome = perfil.get("agent_name", "Agente")
    mem = Memory(ctx["home"] / "memory.db")
    aprovador = aprovador or aprovador_amigavel(perfil.get("agent_name", "Agente"),
                                                ask=ask, say=say)
    tobj = tema_mod.carregar(perfil)
    demo = perfil.get("modo_cerebro") == "demo"
    ultima_rota = {"motor": None}   # para /bem e /mal (feedback local)
    ultima_troca = {"mensagens": None}   # para /contexto (transparência total)
    # F2: histórico. Modo privado (perfil) => store em memória, não toca o disco.
    from nomos.conversations.store import ConversationStore
    privado0 = bool(perfil.get("conversa_privada"))
    conv_store = ConversationStore(ctx["home"] / "conversas.db", privado=privado0)
    conversa_id = conv_store.nova_conversa()
    estado_privado = {"on": privado0}
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
            conv_store.close()
            extra = (" (modo privado: esta conversa não foi gravada)"
                     if estado_privado["on"] else "")
            say(f"{nome}: até logo! Suas memórias ficam guardadas aqui.{extra}")
            return 0
        if linha == "/ajuda":
            say(AJUDA)
            continue
        if linha == "/conselho" or linha.startswith("/conselho "):
            # MC16-UX: chat command do Motor Council — registrado, porém
            # DESABILITADO/fail-closed. Delega ao handler puro, que nunca
            # processa/ecoa o texto do usuário nem chama o orquestrador.
            from nomos.council.chat_disabled import handle_disabled_chat_command
            say(handle_disabled_chat_command(linha))
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
        if linha.startswith("/skills usar"):
            resto = linha[len("/skills usar"):].strip()
            if not resto:
                say("uso: /skills usar <nome> [argumentos JSON]")
                continue
            partes = resto.split(maxsplit=1)
            nome_skill = partes[0]
            argumentos = None
            if len(partes) > 1:
                import json as _json
                try:
                    argumentos = _json.loads(partes[1])
                except ValueError as exc:
                    say(f"{nome}: os argumentos precisam ser JSON válido ({exc})")
                    continue
            ok, msg = _rodar_skill_conversa(ctx, nome_skill, argumentos,
                                            aprovador, origem="explicito")
            say(f"{nome}: {msg}")
            continue
        if linha == "/privado":
            estado_privado["on"] = not estado_privado["on"]
            conv_store.close()
            conv_store = ConversationStore(ctx["home"] / "conversas.db",
                                           privado=estado_privado["on"])
            conversa_id = conv_store.nova_conversa()
            if estado_privado["on"]:
                say(f"{nome}: modo privado LIGADO 🕶️ — esta conversa NÃO será "
                    "gravada em disco. Nada fica quando você sair.")
            else:
                say(f"{nome}: modo privado desligado — volto a guardar o histórico "
                    "(local, só seu).")
            continue
        if linha == "/conversas":
            convs = conv_store.listar(20)
            if not convs:
                say(f"{nome}: ainda não há conversas guardadas.")
            for c in convs:
                fix = "📌 " if c.fixada else ""
                say(f"  {fix}#{c.id} {c.titulo or '(sem título)'} ({c.n_turnos} turnos)")
            continue
        if linha == "/fixar":
            conv_store.fixar(conversa_id, True)
            say(f"{nome}: conversa fixada 📌 — não expira na retenção.")
            continue
        if linha.startswith("/continuar"):
            arg = linha[len("/continuar"):].strip()
            if not arg.isdigit():
                say("uso: /continuar <id> — veja os ids em /conversas")
                continue
            conv, _ = conv_store.abrir(int(arg))
            if not conv:
                say(f"{nome}: não achei a conversa #{arg}.")
                continue
            if not conv.usar_como_memoria:
                say(f"{nome}: a conversa #{arg} está marcada como 'não usar' — "
                    "não vou trazer o contexto dela.")
                continue
            retomado = conv_store.turnos_para_contexto(int(arg), n=6)
            say(f"{nome}: retomando a conversa #{arg} ({conv.titulo}). "
                f"Trouxe {len(retomado)} mensagem(ns) de contexto.")
            estado_privado["retomado"] = retomado
            continue
        if linha == "/contexto":
            if not ultima_troca["mensagens"]:
                say(f"{nome}: ainda não enviei nada ao motor nesta conversa.")
                continue
            from nomos.kernel.audit import redact_text
            say("O que foi para o motor na última resposta (segredos redigidos):")
            for m in ultima_troca["mensagens"]:
                say(f"  [{m.get('role')}] {redact_text(str(m.get('content', '')))}")
            say(c("fraco", "(isto nunca sai da sua máquina — é só transparência)"))
            continue
        if linha in {"/bem", "/mal"}:
            from nomos.cognition import feedback as _fb
            motor = ultima_rota.get("motor")
            if not motor:
                say(f"{nome}: ainda não respondi nada nesta conversa para você avaliar.")
                continue
            _fb.registrar(ctx["home"], motor, linha == "/bem")
            say(f"{nome}: obrigado! Anotei ({'👍' if linha == '/bem' else '👎'} "
                f"para o motor '{motor}') — isso fica só na sua máquina e me "
                "ajuda a escolher melhor da próxima vez.")
            continue
        if linha.startswith("/ver"):
            caminho = linha[4:].strip()
            if not caminho:
                say("uso: /ver <caminho da imagem>")
                continue
            from nomos.cognition import visao as _vis
            mapa_v = motores.detectar()
            m = next((x for x in mapa_v["imagem"]
                      if x["id"] == "visao-ollama" and x["disponivel"]), None)
            if not m:
                say(f"{nome}: ainda não tenho um modelo de visão. Dica: {_vis.DICA}")
                continue
            try:
                descricao = _vis.descrever(caminho, m["detalhe"])
                say(f"{nome} (visão local): {descricao}")
                mem.remember("note", f"imagem {caminho}: {descricao[:120]}")
            except _vis.VisaoError as exc:
                say(f"{nome}: {exc}")
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
        from nomos.cognition.prompt_guard import texto_confiavel
        from nomos.ext import skill_intencao as intencao
        # F1/ISSUE-001: a oferta de skill considera SÓ o texto digitado pelo
        # usuário — nunca conteúdo recuperado de arquivo/memória.
        sugestao = intencao.sugerir_skill(texto_confiavel(linha), ctx["home"],
                                          ctx.get("skills") or (ctx["home"] / "skills"))
        if sugestao:
            say(f"{nome}: posso usar a skill '{sugestao['name']}' para isso"
                + (f" — {sugestao['description']}" if sugestao["description"] else "")
                + ". Quer? (sim/não)")
            resp = ask("> ").strip().casefold()
            if resp == "sim":
                ok, msg = _rodar_skill_conversa(ctx, sugestao["name"], None,
                                                aprovador, origem="oferta")
                say(f"{nome}: {msg}")
                mem.remember("note", f"skill {sugestao['name']} usada na conversa")
                continue
            say(c("fraco", "(ok, sigo eu mesmo)"))
        from nomos.cognition import rag
        bloco_rag, n_lembrancas = rag.contexto_relevante(mem, linha)
        contexto = [{"role": "system", "content": system_prompt(perfil)}]
        if bloco_rag:
            contexto.append({"role": "system", "content": bloco_rag})
        contexto += [
            {"role": ("assistant" if m.role == "assistant" else "user"), "content": m.text}
            for m in reversed(mem.recent(6)) if m.role in {"user", "assistant"}
        ] + [{"role": "user", "content": linha}]
        contexto = rag.encolher_contexto(contexto)
        ultima_troca["mensagens"] = contexto

        if hasattr(router, "chat_stream"):
            # streaming: a resposta aparece enquanto o motor gera (v1.1)
            emitir = say_token or (lambda t: (sys.stdout.write(t),
                                              sys.stdout.flush()))
            import sys
            try:
                if say_token is None:
                    sys.stdout.write(f"{nome}: ")
                    sys.stdout.flush()
                out = router.chat_stream(contexto, emitir)
                if say_token is None:
                    sys.stdout.write("\n")
            except KeyboardInterrupt:
                say("")
                say(c("fraco", f"({nome} parou a resposta a seu pedido — "
                               "não guardei o rascunho)"))
                continue
        else:
            out = router.chat(contexto)
            if out.ok:
                say(f"{nome}: {out.text}")
        if out.ok:
            ultima_rota["motor"] = out.provider or out.route
            mem.remember("user", linha)
            mem.remember("assistant", out.text)
            conv_store.add_turno(conversa_id, "user", linha)
            conv_store.add_turno(conversa_id, "assistant", out.text)
            if n_lembrancas:
                say(c("fraco", f"(usei {n_lembrancas} lembrança(s) suas para "
                               "contextualizar)"))
        else:
            say(resposta_demo(linha, nome))
            say(c("fraco", f"(detalhe técnico: {out.reason})"))
    return 0
