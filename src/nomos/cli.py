"""NOMOS CLI — superfície de comando da plataforma.

Fail-closed operacional: toda ação sensível (A1+) passa por gate de aprovação
interativo que exige digitar exatamente "APROVO" em um terminal real. Em
contexto não interativo (pipe/CI) a aprovação é NEGADA — não existe flag de
bypass por decisão de projeto.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from nomos import __version__
from nomos.kernel import config
from nomos.kernel.approvals import ApprovalQueue, panel_approver
from nomos.kernel import localidade
from nomos.kernel.audit import AuditLog
from nomos.ext import signing
from nomos.interface.panel import PanelServer
from nomos.cognition import motores as motores_mod
from nomos.simple import chaves as chaves_mod
from nomos.simple import doutor as doutor_mod
from nomos.simple import tema as tema_mod
from nomos.simple.amigavel import iniciar_chat
from nomos.simple.onboarding import run_onboarding
from nomos.simple.traducao import aprovador_amigavel
from nomos.kernel.consent import ConsentRegistry, DEVICES
from nomos.kernel.policy import Category, Decision, PolicyEngine, gate
from nomos.kernel.vault import Vault, VaultError, VaultLocked
from nomos.cognition.memory import Memory
from nomos.cognition.router import Router
from nomos.cognition.providers import OllamaProvider
from nomos.runtime import sandbox
from nomos.ext import skills as skills_mod

EXIT_OK, EXIT_ERROR, EXIT_DENIED = 0, 1, 3


def _paths():
    home = config.ensure_home()
    return {
        "home": home,
        "vault": Vault(home / "vault.json"),
        "policy": PolicyEngine(home / "policy.json"),
        "audit": AuditLog(home / "logs" / "audit.jsonl"),
        "consent": ConsentRegistry(home / "consent.json"),
        "skills": home / "skills",
    }


def interactive_approver(decision: Decision) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("NEGADO (fail-closed): aprovação exige terminal interativo.", file=sys.stderr)
        return False
    print("--- APROVAÇÃO NECESSÁRIA ---")
    print(f"categoria: {decision.category}")
    print(f"alvo:      {decision.target}")
    print(f"motivo:    {decision.reason}")
    resp = input('Digite exatamente "APROVO" para autorizar: ')
    return resp.strip() == "APROVO"


def _passphrase(confirm: bool = False) -> str:
    env = os.environ.get("NOMOS_PASSPHRASE")
    if env:
        print("aviso: passphrase lida de NOMOS_PASSPHRASE (uso restrito a automação).",
              file=sys.stderr)
        return env
    p1 = getpass.getpass("passphrase do cofre: ")
    if confirm:
        p2 = getpass.getpass("confirme a passphrase: ")
        if p1 != p2:
            raise VaultError("passphrases não conferem")
    return p1


# ------------------------- comandos -------------------------

def cmd_init(ctx, args) -> int:
    ctx["audit"].append("plataforma.init", nomos_version=__version__)
    print(f"NOMOS {__version__} inicializado em {ctx['home']}")
    print("próximo passo: nomos agent create --name <NomeDoSeuAgente>")
    return EXIT_OK


def cmd_agent_create(ctx, args) -> int:
    data = config.save_agent(args.name)
    ctx["audit"].append("agente.criado", agent=data["agent_name"], mode=data["mode"])
    print(f"agente '{data['agent_name']}' criado (modo: {data['mode']}, local-first).")
    return EXIT_OK


def cmd_vault(ctx, args) -> int:
    v: Vault = ctx["vault"]
    if args.vault_cmd == "init":
        v.init(_passphrase(confirm=sys.stdin.isatty()))
        ctx["audit"].append("vault.init")
        print("cofre criado (PBKDF2-SHA256, 600k iterações, arquivo 0600).")
        return EXIT_OK
    if args.vault_cmd == "set":
        pw = _passphrase()
        secret = getpass.getpass(f"valor de {args.name}: ") if sys.stdin.isatty() \
            else sys.stdin.readline().rstrip("\n")
        v.set(args.name, secret, pw)
        ctx["audit"].append("vault.set", entry=args.name)
        print(f"entrada '{args.name}' gravada cifrada.")
        return EXIT_OK
    if args.vault_cmd == "get":
        decision = ctx["policy"].decide(Category.CRED_USE, target=f"vault:{args.name}")
        if not gate(decision, interactive_approver):
            ctx["audit"].append("vault.get.negado", entry=args.name,
                                decision=decision.effect.value)
            return EXIT_DENIED
        value = v.get(args.name, _passphrase())
        ctx["audit"].append("vault.get.aprovado", entry=args.name)
        print(value if args.reveal else f"{value[:3]}***(oculto; use --reveal)")
        return EXIT_OK
    if args.vault_cmd == "list":
        for name in v.names():
            print(name)
        return EXIT_OK
    if args.vault_cmd == "rotate":
        n = v.rotate(_passphrase(), getpass.getpass("nova passphrase: ")
                     if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n"))
        ctx["audit"].append("vault.rotate", entradas=n)
        print(f"passphrase rotacionada; {n} entrada(s) re-encriptada(s).")
        return EXIT_OK
    return EXIT_ERROR


def cmd_consent(ctx, args) -> int:
    reg: ConsentRegistry = ctx["consent"]
    if args.consent_cmd == "status":
        for dev, ok in reg.status().items():
            print(f"{dev}: {'CONCEDIDO' if ok else 'desligado'}")
        return EXIT_OK
    if args.consent_cmd == "grant":
        cat = {"microfone": Category.DEVICE_MIC, "camera": Category.DEVICE_CAM,
               "tela": Category.DEVICE_SCREEN}[args.device]
        decision = ctx["policy"].decide(cat, target=f"consent:{args.device} ttl={args.ttl}min")
        if not gate(decision, interactive_approver):
            ctx["audit"].append("consent.negado", device=args.device)
            return EXIT_DENIED
        entry = reg.grant(args.device, args.ttl)
        ctx["audit"].append("consent.concedido", device=args.device,
                            expires_at=entry["expires_at"])
        print(f"{args.device}: concedido por {args.ttl} min.")
        return EXIT_OK
    if args.consent_cmd == "revoke":
        reg.revoke(args.device)
        ctx["audit"].append("consent.revogado", device=args.device)
        print(f"{args.device}: revogado.")
        return EXIT_OK
    return EXIT_ERROR


def cmd_panic(ctx, args) -> int:
    ctx["consent"].panic()
    ctx["audit"].append("panic.executado", efeito="todos os consentimentos revogados")
    print("PÂNICO: microfone, câmera e tela revogados imediatamente.")
    return EXIT_OK


def cmd_run(ctx, args) -> int:
    approver = _approver_for(ctx, args)
    decision = ctx["policy"].decide(Category.CODE_EXEC, target=args.cmd[:120])
    if not gate(decision, approver):
        ctx["audit"].append("sandbox.negado", alvo=args.cmd[:120],
                            decision=decision.effect.value)
        return EXIT_DENIED
    try:
        result = sandbox.run(args.cmd, timeout=args.timeout,
                             allow_network=args.allow_network)
    except sandbox.IsolationUnavailable as exc:
        ctx["audit"].append("sandbox.recusado_isolamento", motivo=str(exc))
        print(f"RECUSADO: {exc}", file=sys.stderr)
        return EXIT_DENIED
    ctx["audit"].append("sandbox.executado", rc=result.rc, timeout=result.timed_out,
                        rede_isolada=result.network_isolated)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.rc if not result.timed_out else EXIT_ERROR


def cmd_skill(ctx, args) -> int:
    if args.skill_cmd == "keygen":
        path, pub = signing.keygen(ctx["home"] / "keys")
        print(f"chave privada: {path} (0600 — NÃO compartilhe)")
        print(f"pubkey (b64): {pub}")
        return EXIT_OK
    if args.skill_cmd == "sign":
        import json as _json
        src = __import__("pathlib").Path(args.path)
        mf = _json.loads((src / "skill.json").read_text())
        signed = signing.sign_manifest(mf, args.key)
        (src / "skill.json").write_text(_json.dumps(signed, indent=2, ensure_ascii=False))
        print(f"assinada por {signed['signature']['publisher']}.")
        return EXIT_OK
    if args.skill_cmd == "trust":
        trust = signing.TrustStore(ctx["home"] / "trust.json")
        if args.trust_cmd == "add":
            decision = ctx["policy"].decide(Category.SKILL_INSTALL,
                                            target=f"trust:add:{args.label}")
            if not gate(decision, _approver_for(ctx, args)):
                ctx["audit"].append("skill.trust.negado", label=args.label)
                return EXIT_DENIED
            fp = trust.add(args.pubkey, args.label)
            ctx["audit"].append("skill.trust.adicionado", fingerprint=fp, label=args.label)
            print(f"publicador confiável: {fp} ({args.label})")
            return EXIT_OK
        if args.trust_cmd == "revoke":
            ok = trust.revoke(args.fingerprint)
            ctx["audit"].append("skill.trust.revogado", fingerprint=args.fingerprint, ok=ok)
            print("revogado." if ok else "fingerprint desconhecido.")
            return EXIT_OK if ok else EXIT_ERROR
        return EXIT_ERROR
    if args.skill_cmd == "install":
        try:
            mf = skills_mod.install(args.path, ctx["skills"], ctx["policy"],
                                    _approver_for(ctx, args),
                                    trust=signing.TrustStore(ctx["home"] / "trust.json"))
        except skills_mod.SkillError as exc:
            ctx["audit"].append("skill.install.falhou", motivo=str(exc))
            print(f"FALHA: {exc}", file=sys.stderr)
            return EXIT_DENIED
        ctx["audit"].append("skill.instalada", name=mf["name"], version=mf["version"],
                            permissions=mf["permissions"])
        print(f"skill {mf['name']}@{mf['version']} instalada.")
        return EXIT_OK
    if args.skill_cmd == "list":
        for item in skills_mod.list_installed(ctx["skills"]):
            print(f"{item['name']}@{item['version']}  perms={item['permissions']}")
        return EXIT_OK
    if args.skill_cmd == "remove":
        ok = skills_mod.remove(args.name, ctx["skills"])
        ctx["audit"].append("skill.removida", name=args.name, existia=ok)
        print("removida." if ok else "não instalada.")
        return EXIT_OK
    return EXIT_ERROR


def cmd_tema(ctx, args) -> int:
    sub = getattr(args, "tema_cmd", None)
    try:
        if sub == "paleta":
            tema_mod.aplicar(paleta=args.valor, cor_ligada=True)
            print(f"tema aplicado: {args.valor}")
        elif sub == "destaque":
            tema_mod.aplicar(destaque=args.valor)
            print(f"cor de destaque: {args.valor}")
        elif sub == "desligar":
            tema_mod.aplicar(cor_ligada=False)
            print("cores desligadas.")
        elif sub == "ligar":
            tema_mod.aplicar(cor_ligada=True)
            print("cores ligadas.")
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(tema_mod.amostra(config.load_agent() or {}))
    return EXIT_OK


def _barra(recebidos, total):
    if not total:
        return
    pct = int(recebidos * 100 / total)
    mb = recebidos // (1024 * 1024)
    tot = total // (1024 * 1024)
    sys.stdout.write(f"\r  baixando o cérebro... {pct}% ({mb}/{tot} MB)")
    sys.stdout.flush()


def cmd_cerebro(ctx, args) -> int:
    from nomos.cognition import embutido as emb
    home = ctx["home"]
    sub = getattr(args, "cerebro_cmd", None)
    rec = emb.recomendado()
    if sub in (None, "status"):
        print(f"Sua máquina tem ~{emb.ram_gb():.0f} GB de RAM.")
        print(f"Cérebro recomendado: {rec.rotulo}  (~{rec.mb} MB)")
        print(f"Motor instalado: {'sim' if emb.llama_disponivel() else 'não (rode: nomos cerebro instalar)'}")
        for m in emb.CATALOGO:
            marca = "✓ baixado" if emb.esta_baixado(home, m) else "–"
            print(f"  [{marca}] {m.id:<11} {m.rotulo}")
        print("\nBaixar o recomendado:  nomos cerebro baixar")
        return EXIT_OK
    if sub == "instalar":
        ok, msg = emb.instalar_motor()
        print(msg)
        return EXIT_OK if ok else EXIT_ERROR
    if sub == "baixar":
        modelo = emb.por_id(args.qual) if getattr(args, "qual", None) else rec
        d = ctx["policy"].decide(Category.NET_EGRESS, target="huggingface.co")
        d = type(d)(category=d.category, target=d.target, effect=d.effect,
                    reason=f"baixar o cérebro {modelo.id} (~{modelo.mb} MB), uma única vez")
        if not gate(d, interactive_approver):
            print("download não autorizado.", file=sys.stderr)
            print("(o cadeado só-local bloqueia a internet; baixar o cérebro é uma "
                  "escolha consciente — aprove no terminal para continuar)")
            return EXIT_DENIED
        print(f"Baixando {modelo.rotulo}...")
        try:
            emb.baixar(home, modelo, progresso=_barra)
        except emb.CerebroIndisponivel as exc:
            print(f"\n{exc}", file=sys.stderr)
            return EXIT_ERROR
        ctx["audit"].append("cerebro.baixado", modelo=modelo.id)
        print(f"\n✅ cérebro pronto! ({modelo.id})")
        if not emb.llama_disponivel():
            print("Falta o motor. Rode uma vez:  nomos cerebro instalar")
        return EXIT_OK
    return EXIT_ERROR


def cmd_doutor(ctx, args) -> int:
    print(doutor_mod.texto_relatorio_v011(ctx["home"], ctx))
    return EXIT_OK


def cmd_atualizar(ctx, args) -> int:
    from nomos.simple import atualizar as at
    return at.verificar(ctx, _approver_for(ctx, args))


def cmd_painel(ctx, args) -> int:
    from nomos.interface.painel_web import DashboardServer
    srv = DashboardServer(ctx, port=getattr(args, "port", 0) or 0)
    url = srv.start()
    print(f"painel local (somente leitura): {url}")
    print("só funciona neste computador (127.0.0.1). Ctrl+C encerra.")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        print("(não consegui abrir o navegador — copie a URL acima)")
    try:
        import signal as _sig
        _sig.pause()
    except (KeyboardInterrupt, AttributeError):
        pass
    finally:
        srv.stop()
    return EXIT_OK


def cmd_rotinas(ctx, args) -> int:
    from nomos.simple import rotinas as rot
    sub = getattr(args, "rotinas_cmd", None)
    if sub in (None, "listar"):
        itens = rot.listar(ctx["home"])
        if not itens:
            print("nenhuma rotina ainda. Crie com:")
            print('  nomos rotinas criar "Briefing da manhã" 08:00 briefing')
            return EXIT_OK
        for r in itens:
            marca = "✓" if r.get("ativa", True) else "·"
            ultima = ("nunca rodou" if not r.get("ultima_execucao")
                      else "já rodou hoje/antes")
            print(f"[{marca}] #{r['id']} {r['hora']} — {r['nome']} "
                  f"({r['acao']}) · {ultima}")
        print("\nexecutar as devidas agora:  nomos rotinas executar")
        return EXIT_OK
    if sub == "criar":
        try:
            nova = rot.criar(ctx["home"], args.nome, args.hora, args.acao,
                             ctx["policy"], _approver_for(ctx, args),
                             audit=ctx["audit"], skills_dir=ctx["skills"])
        except rot.RotinaError as exc:
            print(f"não criei: {exc}", file=sys.stderr)
            return EXIT_DENIED if "aprovada" in str(exc) else EXIT_ERROR
        print(f"rotina #{nova['id']} criada: {nova['hora']} — {nova['nome']}")
        print("ela roda quando você chamar `nomos rotinas executar` (ou agende "
              "no seu sistema: nomos rotinas agendar)")
        return EXIT_OK
    if sub == "remover":
        ok = rot.remover(ctx["home"], args.id, audit=ctx["audit"])
        print("removida." if ok else "id não encontrado.")
        return EXIT_OK if ok else EXIT_ERROR
    if sub in {"pausar", "retomar"}:
        ok = rot.pausar(ctx["home"], args.id, sub == "retomar")
        print(("retomada." if sub == "retomar" else "pausada.") if ok
              else "id não encontrado.")
        return EXIT_OK if ok else EXIT_ERROR
    if sub == "executar":
        resultados = rot.executar_devidas(ctx)
        if not resultados:
            print("nada devido agora — tudo em dia.")
            return EXIT_OK
        falhas = [r for r in resultados if not r["ok"]]
        for r in resultados:
            print(f"{'✓' if r['ok'] else '✗'} {r['nome']}: {r['detalhe']}")
        return EXIT_OK if not falhas else EXIT_ERROR
    if sub == "briefing":
        print(rot.briefing(ctx))
        return EXIT_OK
    if sub == "agendar":
        print(rot.linha_agendador(ctx["home"]))
        print("\n(o NOMOS nunca altera seu agendador sozinho — colar é com você)")
        return EXIT_OK
    return EXIT_ERROR


def cmd_arquivo(ctx, args) -> int:
    from nomos.cognition import arquivos as arq
    router = _router(ctx) if not args.sem_motor else None
    try:
        resultado, estado = arq.processar(args.caminho, ctx,
                                          _approver_for(ctx, args),
                                          router=router, salvar=args.salvar)
    except arq.ArquivoError as exc:
        print(f"não deu: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not resultado.ok:
        # etapa de leitura/salvamento negada ou falhou — mensagem honesta
        print(resultado.explicacao or resultado.motivo, file=sys.stderr)
        if estado.get("pontos") or estado.get("resumo"):
            print(arq.render_resultado(args.caminho, estado))
        return EXIT_DENIED if "negada" in resultado.motivo else EXIT_ERROR
    print(arq.render_resultado(args.caminho, estado))
    if estado.get("salvo_em"):
        print(f"\n(resumo salvo em {estado['salvo_em']} — com sua aprovação)")
    print(f"\n{resultado.explicacao}")
    return EXIT_OK


def cmd_local(ctx, args) -> int:
    home = ctx["home"]
    sub = getattr(args, "local_cmd", None)
    if sub in (None, "status"):
        ligado = localidade.esta_ligado(home)
        if ligado:
            print("Modo só-local: LIGADO 🔒")
            print("Tudo roda na sua máquina. Nenhuma informação sai para a "
                  "internet. Motores de nuvem estão desplugados.")
        else:
            print("Modo só-local: DESLIGADO 🔌")
            print("Você plugou motores externos. Saídas para a internet ainda "
                  "pedem sua permissão a cada uso. Para voltar a blindar: "
                  "nomos local on")
        return EXIT_OK
    if sub == "on":
        localidade.definir(home, True)
        ctx["audit"].append("localidade.ligada")
        print("pronto: modo só-local LIGADO 🔒 — nada sai da sua máquina.")
        return EXIT_OK
    if sub == "off":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("Desligar o modo só-local é uma decisão consciente — faça num "
                  "terminal interativo:\n  nomos local off", file=sys.stderr)
            return EXIT_DENIED
        print("Isto permite que MOTORES EXTERNOS (nuvem) sejam usados — cada uso")
        print("ainda pedirá sua permissão, mas informações poderão sair da sua")
        print("máquina. Tem certeza?")
        if input('digite "PLUGAR" para confirmar> ').strip() != "PLUGAR":
            print("ok, mantive tudo local.")
            return EXIT_OK
        localidade.definir(home, False)
        ctx["audit"].append("localidade.desligada")
        print("feito: motores externos podem ser plugados. Reative com: nomos local on")
        return EXIT_OK
    return EXIT_ERROR


def cmd_chaves(ctx, args) -> int:
    if getattr(args, "chaves_cmd", None) == "listar":
        nomes = chaves_mod.nomes_guardados()   # só nomes: seguro sem TTY
        if not nomes:
            print("nenhuma chave guardada ainda.")
        for n in nomes:
            print(f"  · {n}")
        return EXIT_OK
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Para guardar ou remover chaves com segurança, use um terminal "
              "interativo:\n  nomos chaves", file=sys.stderr)
        return EXIT_ERROR
    chaves_mod.menu_chaves(ctx["home"])   # menu guiado (getpass real)
    return EXIT_OK


def cmd_motores(ctx, args) -> int:
    from nomos.cognition import engine_catalog as cat_mod
    from nomos.cognition import engine_policy as epol
    from nomos.cognition import engine_router as erouter
    sub = args.motores_cmd
    if sub is None:
        print(motores_mod.tabela())   # compatível com v0.10
        return EXIT_OK
    if sub == "listar" or sub == "status":
        print(cat_mod.tabela_v011(home=ctx["home"]))
        auto = "LIGADO" if epol.auto_ligado() else "DESLIGADO"
        print(f"\nroteador automático: {auto} "
              f"(nomos motores auto {'off' if auto == 'LIGADO' else 'on'})")
        return EXIT_OK
    if sub == "menu":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print(cat_mod.tabela_v011(home=ctx["home"]))
            return EXIT_OK
        return _motores_menu(ctx)
    if sub == "recomendar":
        modalidade = getattr(args, "modalidade", None) or "texto"
        if modalidade not in cat_mod.MODALIDADES_V011:
            print(f"erro: modalidade desconhecida: {modalidade} "
                  f"(use: {', '.join(cat_mod.MODALIDADES_V011)})", file=sys.stderr)
            return EXIT_ERROR
        tarefa = erouter.Tarefa(tipo=modalidade, modalidade=modalidade)
        dec = erouter.rotear(tarefa, home=ctx["home"],
                             chave_configurada=epol.chave_cloud_configurada(ctx["vault"]))
        if dec.selected_engine:
            print(f"recomendado para {modalidade}: {dec.selected_engine}")
            print(f"  por quê: {dec.reason}")
            print(f"  privacidade: {dec.privacy_level} · custo: {dec.estimated_cost}"
                  + (" · pede sua aprovação" if dec.approval_required else ""))
            if dec.fallback_engine:
                print(f"  reserva: {dec.fallback_engine}")
        else:
            print(f"nenhum motor pronto para {modalidade}.")
            print(f"  {dec.reason}")
            return EXIT_ERROR
        return EXIT_OK
    if sub == "auto":
        estado = getattr(args, "estado", None)
        if estado not in {"on", "off"}:
            print("uso: nomos motores auto on|off", file=sys.stderr)
            return EXIT_ERROR
        epol.definir_auto(estado == "on")
        ctx["audit"].append("motores.auto", ligado=estado == "on")
        print("roteador automático " + ("LIGADO — escolho o melhor motor local "
              "para cada tarefa." if estado == "on" else
              "DESLIGADO — uso sempre o motor que você escolher."))
        return EXIT_OK
    if sub == "testar":
        cat = cat_mod.construir(ctx["home"])
        m = cat.por_id(args.motor)
        if m is None:
            print(f"erro: motor desconhecido: {args.motor}", file=sys.stderr)
            return EXIT_ERROR
        print(f"{m.id}: {'PRONTO ✓' if m.pronto else 'não está pronto'}"
              f" — {m.status or m.rotulo}")
        return EXIT_OK if m.pronto else EXIT_ERROR
    if sub == "diagnostico":
        cat = cat_mod.construir(ctx["home"])
        faltando = [mod for mod in cat_mod.MODALIDADES_V011 if not cat.prontos(mod)]
        prontas = [mod for mod in cat_mod.MODALIDADES_V011 if cat.prontos(mod)]
        print("Diagnóstico de motores")
        print(f"  modalidades prontas: {', '.join(prontas) or 'nenhuma'}")
        if faltando:
            print(f"  sem motor: {', '.join(faltando)}")
        print(f"  modo só-local: {'LIGADO 🔒' if localidade.esta_ligado(ctx['home']) else 'DESLIGADO 🔌'}")
        return EXIT_OK
    if sub == "usar":
        try:
            motores_mod.escolher(args.modalidade, args.motor)
        except ValueError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return EXIT_ERROR
        ctx["audit"].append("motor.escolhido", modalidade=args.modalidade, motor=args.motor)
        print(f"{args.modalidade} agora usa '{args.motor}'.")
        return EXIT_OK
    return EXIT_ERROR


def _motores_menu(ctx, ask=input, say=print) -> int:
    from nomos.cognition import engine_catalog as cat_mod
    from nomos.cognition import engine_policy as epol
    while True:
        say("\nNOMOS Motores\n"
            "1. Ver todos os motores\n"
            "2. Recomendação para uma tarefa\n"
            "3. Ligar/desligar modo automático\n"
            "4. Diagnóstico\n"
            "5. Voltar")
        op = ask("escolha> ").strip()
        if op in {"5", "", "voltar"}:
            return EXIT_OK
        if op == "1":
            say(cat_mod.tabela_v011(home=ctx["home"]))
        elif op == "2":
            mod = ask("modalidade (texto, codigo, resumo, imagem...)> ").strip() or "texto"
            ns = argparse.Namespace(motores_cmd="recomendar", modalidade=mod)
            cmd_motores(ctx, ns)
        elif op == "3":
            ligado = epol.auto_ligado()
            say(f"modo automático está {'LIGADO' if ligado else 'DESLIGADO'}.")
            r = ask("inverter? (sim/não)> ").strip().casefold()
            if r == "sim":
                epol.definir_auto(not ligado)
                say("feito.")
        elif op == "4":
            cmd_motores(ctx, argparse.Namespace(motores_cmd="diagnostico"))
        else:
            say("opção desconhecida — digite um número de 1 a 5.")


def cmd_skills(ctx, args) -> int:
    """Modo amigável de skills (o técnico `nomos skill` continua igual)."""
    from nomos.ext import skill_registry as reg
    from nomos.ext import skill_status as st
    from nomos.ext.signing import TrustStore
    from nomos.simple import skills_menu as smenu
    sub = getattr(args, "skills_cmd", None)
    trust = TrustStore(ctx["home"] / "trust.json")
    interativo = sys.stdin.isatty() and sys.stdout.isatty()

    def _confirmar_experimental(mf) -> bool:
        if not interativo:
            return False   # CI/non-interactive nega sempre (fail-closed)
        print(f"⚠️  '{mf['name']}' é experimental (risco {mf['risk_level']}"
              f"{', não assinada' if 'signature' not in mf else ''}).")
        return input('digite "ACEITO O RISCO" para continuar> ').strip() == "ACEITO O RISCO"

    if sub is None:
        sub = "menu" if interativo else "listar"
    if sub == "menu":
        if not interativo:
            sub = "listar"
        else:
            return smenu.menu(
                ctx, instalar_fn=lambda caminho: smenu.instalar_amigavel(
                    ctx, caminho, _approver_for(ctx, args), _confirmar_experimental))
    if sub == "listar":
        print(smenu.render_lista(st.status_todas(ctx["home"], ctx["skills"], trust),
                                 reg.disponiveis(ctx["home"], ctx["skills"])))
        return EXIT_OK
    if sub == "instalar":
        msg = smenu.instalar_amigavel(ctx, args.caminho, _approver_for(ctx, args),
                                      _confirmar_experimental)
        print(msg)
        return EXIT_OK if "instalada" in msg else EXIT_DENIED
    if sub == "remover":
        ok = skills_mod.remove(args.nome, ctx["skills"])
        ctx["audit"].append("skill.removida", name=args.nome, existia=ok)
        print("removida." if ok else "não estava instalada.")
        return EXIT_OK
    if sub == "info":
        alvo = ctx["skills"] / args.nome
        if not alvo.exists():
            print(f"'{args.nome}' não está instalada.", file=sys.stderr)
            return EXIT_ERROR
        print(smenu.render_info(st.status_skill(ctx["home"], alvo, trust)))
        return EXIT_OK
    if sub in {"ativar", "desativar"}:
        if not (ctx["skills"] / args.nome).exists():
            print(f"'{args.nome}' não está instalada.", file=sys.stderr)
            return EXIT_ERROR
        st.ativar(ctx["home"], args.nome, sub == "ativar")
        ctx["audit"].append(f"skill.{sub}", name=args.nome)
        print(f"'{args.nome}' {'ativada' if sub == 'ativar' else 'desativada'}.")
        return EXIT_OK
    if sub == "diagnostico":
        print(smenu.diagnostico_texto(ctx["home"], ctx["skills"], trust))
        return EXIT_OK
    if sub == "rodar":
        if not st.esta_ativa(ctx["home"], args.nome):
            print(f"'{args.nome}' está desativada — reative com: "
                  f"nomos skills ativar {args.nome}", file=sys.stderr)
            return EXIT_DENIED
        argumentos = None
        if getattr(args, "args_json", None):
            try:
                argumentos = json.loads(args.args_json)
            except ValueError as exc:
                print(f"--args precisa ser JSON válido: {exc}", file=sys.stderr)
                return EXIT_ERROR
        rc, saida = reg.executar(args.nome, ctx["skills"], ctx["policy"],
                                 _approver_for(ctx, args), audit=ctx["audit"],
                                 argumentos=argumentos)
        if rc == 0:
            st.marcar_uso(ctx["home"], args.nome)
        sys.stdout.write(saida if saida.endswith("\n") or not saida else saida + "\n")
        if rc == 3:
            print("(negado — nenhuma permissão além do declarado e aprovado)",
                  file=sys.stderr)
        return rc
    if sub == "criar":
        from nomos.ext import skill_sdk
        try:
            destino = skill_sdk.criar_skill(args.nome, Path(args.pasta))
        except skill_sdk.SdkError as exc:
            print(f"não criei: {exc}", file=sys.stderr)
            return EXIT_ERROR
        ctx["audit"].append("skill.esqueleto.criado", name=args.nome)
        print(f"skill '{args.nome}' criada em {destino}")
        print("próximos passos: edite main.py → atualize checksums (README) → "
              f"nomos skills instalar {destino}")
        return EXIT_OK
    if sub == "atualizar":
        skills_novas, assinado, publicador = reg.catalogo_info(ctx["home"], trust)
        origem = (f"catálogo assinado por {publicador} ✓" if assinado
                  else "catálogo local NÃO assinado" if skills_novas
                  else "nenhum catálogo local")
        print(f"fonte: {origem}")
        novidades = reg.atualizacoes_disponiveis(ctx["home"], ctx["skills"])
        if not novidades:
            print("suas skills estão em dia com o catálogo local.")
            return EXIT_OK
        for n in novidades:
            print(f"  ↑ {n['name']}: {n['instalada']} → {n['disponivel']} "
                  f"(risco {n['risco']})")
        print("atualizar é manual e passa pelo gate: "
              "nomos skills instalar <pasta-da-nova-versão>")
        return EXIT_OK
    return EXIT_ERROR


def cmd_start(ctx, args) -> int:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("O modo simples precisa de um terminal interativo.\n"
              "Abra um terminal de verdade e rode:  nomos start", file=sys.stderr)
        return EXIT_ERROR
    perfil = config.load_agent() or {}
    if not perfil.get("onboarding_completo"):
        perfil = run_onboarding()
    nome = perfil.get("agent_name", "Agente")
    router = _router(ctx)
    router.approver = aprovador_amigavel(nome)
    return iniciar_chat(ctx, perfil, router)


def _queue(ctx) -> ApprovalQueue:
    return ApprovalQueue(ctx["home"] / "approvals", audit=ctx["audit"])


def _approver_for(ctx, args):
    if getattr(args, "panel", False):
        return panel_approver(_queue(ctx))
    return interactive_approver


def cmd_approvals(ctx, args) -> int:
    q = _queue(ctx)
    if args.appr_cmd == "serve":
        srv = PanelServer(q, port=args.port)
        url = srv.start()
        print(f"painel local de aprovações: {url}")
        print("Ctrl+C encerra. Solicitações expiram sozinhas em 5 min.")
        try:
            import signal as _sig
            _sig.pause()
        except (KeyboardInterrupt, AttributeError):
            pass
        finally:
            srv.stop()
        return EXIT_OK
    if args.appr_cmd == "list":
        pend = q.pending()
        if not pend:
            print("nenhuma solicitação pendente.")
        for a in pend:
            print(f"[{a.id}] {a.category} alvo={a.target} motivo={a.reason}")
        return EXIT_OK
    return EXIT_ERROR


def _router(ctx) -> Router:
    host = os.environ.get("NOMOS_OLLAMA_HOST", "http://127.0.0.1:11434")
    model = os.environ.get("NOMOS_OLLAMA_MODEL", "llama3.2")
    from nomos.cognition.embutido import EmbeddedProvider
    return Router(policy=ctx["policy"], gate=gate, approver=interactive_approver,
                  audit=ctx["audit"], vault=ctx["vault"],
                  ollama=OllamaProvider(host=host, model=model),
                  embutido=EmbeddedProvider(ctx["home"]))


def cmd_chat(ctx, args) -> int:
    mem = Memory(ctx["home"] / "memory.db")
    router = _router(ctx)
    prompt = " ".join(args.prompt).strip() if args.prompt else ""
    if not prompt and not sys.stdin.isatty():
        print("erro: informe o prompt como argumento em modo não interativo.", file=sys.stderr)
        return EXIT_ERROR

    def one_turn(user_text: str) -> int:
        context = list(reversed(mem.recent(6)))
        messages = (
            [{"role": "system", "content": "Você é o agente pessoal do usuário no NOMOS. Responda em português, direto."}]
            + [{"role": ("assistant" if m.role == "assistant" else "user"), "content": m.text}
               for m in context if m.role in {"user", "assistant"}]
            + [{"role": "user", "content": user_text}]
        )
        pw = None
        if args.cloud and sys.stdin.isatty():
            pw = _passphrase()
        out = router.chat(messages, prefer_cloud=args.cloud, passphrase=pw)
        print(out.text)
        if out.ok:
            mem.remember("user", user_text)
            mem.remember("assistant", out.text)
            print(f"[rota={out.route} model={out.model}]", file=sys.stderr)
            return EXIT_OK
        return EXIT_DENIED if "negad" in out.reason else EXIT_ERROR

    if prompt:
        return one_turn(prompt)
    print("chat interativo — linha vazia encerra.")
    rc = EXIT_OK
    while True:
        try:
            line = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            break
        rc = one_turn(line)
    return rc


def _senha_backup() -> str | None:
    env = os.environ.get("NOMOS_BACKUP_SENHA")
    if env:
        print("aviso: senha do backup lida de NOMOS_BACKUP_SENHA "
              "(uso restrito a automação).", file=sys.stderr)
        return env
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    return getpass.getpass("senha do backup (mín. 8 caracteres): ")


def cmd_memory(ctx, args) -> int:
    mem = Memory(ctx["home"] / "memory.db")
    if args.mem_cmd == "search":
        for it in mem.recall_hibrido(" ".join(args.query), k=args.k):
            print(f"[{it.id}] ({it.role}) {it.text}")
        return EXIT_OK
    if args.mem_cmd == "exportar":
        from nomos.cognition import backup as bkp
        senha = _senha_backup()
        if senha is None:
            print("exportar exige terminal interativo (ou NOMOS_BACKUP_SENHA).",
                  file=sys.stderr)
            return EXIT_ERROR
        try:
            n = bkp.exportar(mem, args.arquivo, senha)
        except bkp.BackupError as exc:
            print(f"não exportei: {exc}", file=sys.stderr)
            return EXIT_ERROR
        ctx["audit"].append("memoria.exportada", quantidade=n)
        print(f"{n} memória(s) exportada(s) cifrada(s) para {args.arquivo}")
        print("guarde a senha: sem ela, o arquivo é ilegível (de propósito).")
        return EXIT_OK
    if args.mem_cmd == "importar":
        from nomos.cognition import backup as bkp
        senha = _senha_backup()
        if senha is None:
            print("importar exige terminal interativo (ou NOMOS_BACKUP_SENHA).",
                  file=sys.stderr)
            return EXIT_ERROR
        try:
            novas, ignoradas = bkp.importar(mem, args.arquivo, senha)
        except bkp.BackupError as exc:
            print(f"não importei: {exc}", file=sys.stderr)
            return EXIT_ERROR
        ctx["audit"].append("memoria.importada", novas=novas, ignoradas=ignoradas)
        print(f"{novas} memória(s) nova(s); {ignoradas} já existiam (nada apagado).")
        return EXIT_OK
    if args.mem_cmd == "consolidar":
        criadas = mem.consolidar()
        ctx["audit"].append("memoria.consolidada", notas=len(criadas))
        if not criadas:
            print("nada novo para consolidar — suas notas já estão em dia.")
        for n in criadas:
            print(f"  + {n}")
        return EXIT_OK
    if args.mem_cmd == "recent":
        for it in mem.recent(args.k):
            print(f"[{it.id}] ({it.role}) {it.text}")
        return EXIT_OK
    if args.mem_cmd == "note":
        mid = mem.remember("note", " ".join(args.text))
        print(f"anotado (id={mid}).")
        return EXIT_OK
    if args.mem_cmd == "forget":
        ok = mem.forget(args.id)
        print("removida." if ok else "id inexistente.")
        return EXIT_OK if ok else EXIT_ERROR
    if args.mem_cmd == "stats":
        print(f"memórias: {mem.count()} | fts5: {'sim' if mem.fts else 'não'}")
        return EXIT_OK
    return EXIT_ERROR


def cmd_status(ctx, args) -> int:
    agent = config.load_agent()
    intact, bad = ctx["audit"].verify()
    print(f"NOMOS {__version__} | home: {ctx['home']}")
    nome_agente = (agent or {}).get("agent_name")
    print(f"agente: {nome_agente or '— (crie com nomos agent create)'}")
    print(f"cofre: {'presente' if ctx['vault'].exists() else 'ausente'} "
          f"({len(ctx['vault'].names())} entrada(s))")
    print("política: read-only por padrão, fail-closed ativo")
    for dev, ok in ctx["consent"].status().items():
        print(f"consentimento {dev}: {'CONCEDIDO' if ok else 'desligado'}")
    print(f"skills instaladas: {len(skills_mod.list_installed(ctx['skills']))}")
    print(f"auditoria: {'ÍNTEGRA' if intact else f'VIOLADA na linha {bad}'}")
    return EXIT_OK


def cmd_logs(ctx, args) -> int:
    intact, bad = ctx["audit"].verify()
    if intact:
        print("cadeia de auditoria ÍNTEGRA.")
        return EXIT_OK
    print(f"cadeia de auditoria VIOLADA na linha {bad}.", file=sys.stderr)
    return EXIT_ERROR


# ------------------------- parser -------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nomos",
                                description="NOMOS Personal Agent Foundry")
    p.add_argument("--version", action="version", version=f"nomos {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False)

    st0 = sub.add_parser("start", help="modo simples: onboarding + chat")
    st0.set_defaults(fn=cmd_start)
    ce = sub.add_parser("cerebro", help="o cérebro leve do NOMOS (baixar/status)")
    cesub = ce.add_subparsers(dest="cerebro_cmd")
    cesub.add_parser("status").set_defaults(fn=cmd_cerebro)
    cesub.add_parser("instalar").set_defaults(fn=cmd_cerebro)
    cb = cesub.add_parser("baixar")
    cb.add_argument("qual", nargs="?")
    cb.set_defaults(fn=cmd_cerebro)
    ce.set_defaults(fn=cmd_cerebro, cerebro_cmd=None)
    sub.add_parser("doutor", help="check-up: o que está pronto e o próximo passo").set_defaults(fn=cmd_doutor)
    at = sub.add_parser("atualizar",
                        help="checa se há versão nova (opt-in; nunca atualiza sozinho)")
    at.add_argument("--panel", action="store_true")
    at.set_defaults(fn=cmd_atualizar)
    pn = sub.add_parser("painel", help="painel local no navegador (somente leitura)")
    pn.add_argument("--port", type=int, default=0)
    pn.set_defaults(fn=cmd_painel)
    ro = sub.add_parser("rotinas", help="rotinas locais: briefing, check-up e mais")
    rosub = ro.add_subparsers(dest="rotinas_cmd")
    rosub.add_parser("listar").set_defaults(fn=cmd_rotinas)
    rc_ = rosub.add_parser("criar")
    rc_.add_argument("nome")
    rc_.add_argument("hora")
    rc_.add_argument("acao")
    rc_.add_argument("--panel", action="store_true")
    rc_.set_defaults(fn=cmd_rotinas)
    for nome_r in ("remover", "pausar", "retomar"):
        rp = rosub.add_parser(nome_r)
        rp.add_argument("id", type=int)
        rp.set_defaults(fn=cmd_rotinas)
    rosub.add_parser("executar").set_defaults(fn=cmd_rotinas)
    rosub.add_parser("briefing").set_defaults(fn=cmd_rotinas)
    rosub.add_parser("agendar").set_defaults(fn=cmd_rotinas)
    ro.set_defaults(fn=cmd_rotinas, rotinas_cmd=None)
    aq = sub.add_parser("arquivo", help="ler e resumir um arquivo, tudo local")
    aq.add_argument("caminho")
    aq.add_argument("--salvar", action="store_true",
                    help="salva o resumo ao lado do arquivo (pede aprovação)")
    aq.add_argument("--sem-motor", dest="sem_motor", action="store_true",
                    help="só extração heurística, sem chamar o cérebro")
    aq.add_argument("--panel", action="store_true")
    aq.set_defaults(fn=cmd_arquivo)
    te = sub.add_parser("tema", help="personalizar as cores do NOMOS")
    tesub = te.add_subparsers(dest="tema_cmd")
    tp = tesub.add_parser("paleta")
    tp.add_argument("valor")
    tp.set_defaults(fn=cmd_tema)
    td = tesub.add_parser("destaque")
    td.add_argument("valor")
    td.set_defaults(fn=cmd_tema)
    tesub.add_parser("ligar").set_defaults(fn=cmd_tema)
    tesub.add_parser("desligar").set_defaults(fn=cmd_tema)
    tesub.add_parser("mostrar").set_defaults(fn=cmd_tema)
    te.set_defaults(fn=cmd_tema, tema_cmd=None)
    lo = sub.add_parser("local", help="cadeado de localidade: mantém tudo na sua máquina")
    losub = lo.add_subparsers(dest="local_cmd")
    losub.add_parser("status").set_defaults(fn=cmd_local)
    losub.add_parser("on").set_defaults(fn=cmd_local)
    losub.add_parser("off").set_defaults(fn=cmd_local)
    lo.set_defaults(fn=cmd_local, local_cmd=None)
    ck = sub.add_parser("chaves", help="guardar chaves com segurança (sem digitar no chat)")
    cksub = ck.add_subparsers(dest="chaves_cmd")
    cksub.add_parser("listar").set_defaults(fn=cmd_chaves)
    ck.set_defaults(fn=cmd_chaves, chaves_cmd=None)
    mo = sub.add_parser("motores", help="ver, escolher e rotear motores por modalidade")
    mosub = mo.add_subparsers(dest="motores_cmd")
    mosub.add_parser("listar").set_defaults(fn=cmd_motores)
    mosub.add_parser("menu").set_defaults(fn=cmd_motores)
    mosub.add_parser("status").set_defaults(fn=cmd_motores)
    mr = mosub.add_parser("recomendar")
    mr.add_argument("modalidade", nargs="?")
    mr.set_defaults(fn=cmd_motores)
    ma = mosub.add_parser("auto")
    ma.add_argument("estado", choices=["on", "off"])
    ma.set_defaults(fn=cmd_motores)
    mt = mosub.add_parser("testar")
    mt.add_argument("motor")
    mt.set_defaults(fn=cmd_motores)
    mosub.add_parser("diagnostico").set_defaults(fn=cmd_motores)
    mu = mosub.add_parser("usar")
    mu.add_argument("modalidade")
    mu.add_argument("motor")
    mu.set_defaults(fn=cmd_motores)
    mo.set_defaults(fn=cmd_motores, motores_cmd=None)

    sks = sub.add_parser("skills", help="suas habilidades, do jeito fácil")
    skssub = sks.add_subparsers(dest="skills_cmd")
    skssub.add_parser("menu").set_defaults(fn=cmd_skills)
    skssub.add_parser("listar").set_defaults(fn=cmd_skills)
    s_i = skssub.add_parser("instalar")
    s_i.add_argument("caminho")
    s_i.add_argument("--panel", action="store_true")
    s_i.set_defaults(fn=cmd_skills)
    for nome_cmd in ("remover", "info", "ativar", "desativar", "rodar"):
        sp = skssub.add_parser(nome_cmd)
        sp.add_argument("nome")
        if nome_cmd == "rodar":
            sp.add_argument("--args", dest="args_json",
                            help="argumentos JSON para a skill")
            sp.add_argument("--panel", action="store_true")
        sp.set_defaults(fn=cmd_skills)
    sc = skssub.add_parser("criar")
    sc.add_argument("nome")
    sc.add_argument("--pasta", default=".")
    sc.set_defaults(fn=cmd_skills)
    skssub.add_parser("atualizar").set_defaults(fn=cmd_skills)
    skssub.add_parser("diagnostico").set_defaults(fn=cmd_skills)
    sks.set_defaults(fn=cmd_skills, skills_cmd=None)
    sub.add_parser("init").set_defaults(fn=cmd_init)

    ag = sub.add_parser("agent").add_subparsers(dest="agent_cmd", required=True)
    c = ag.add_parser("create")
    c.add_argument("--name", required=True)
    c.set_defaults(fn=cmd_agent_create)

    va = sub.add_parser("vault").add_subparsers(dest="vault_cmd", required=True)
    va.add_parser("init").set_defaults(fn=cmd_vault)
    s = va.add_parser("set")
    s.add_argument("name")
    s.set_defaults(fn=cmd_vault)
    g = va.add_parser("get")
    g.add_argument("name")
    g.add_argument("--reveal", action="store_true")
    g.set_defaults(fn=cmd_vault)
    va.add_parser("list").set_defaults(fn=cmd_vault)
    va.add_parser("rotate").set_defaults(fn=cmd_vault)

    co = sub.add_parser("consent").add_subparsers(dest="consent_cmd", required=True)
    co.add_parser("status").set_defaults(fn=cmd_consent)
    gr = co.add_parser("grant")
    gr.add_argument("device", choices=DEVICES)
    gr.add_argument("--ttl", type=int, default=15)
    gr.set_defaults(fn=cmd_consent)
    rv = co.add_parser("revoke")
    rv.add_argument("device", choices=DEVICES)
    rv.set_defaults(fn=cmd_consent)

    sub.add_parser("panic").set_defaults(fn=cmd_panic)

    rn = sub.add_parser("run")
    rn.add_argument("cmd")
    rn.add_argument("--timeout", type=int, default=30)
    rn.add_argument("--allow-network", dest="allow_network", action="store_true")
    rn.add_argument("--panel", action="store_true",
                    help="aprovação via painel local (aguarda decisão humana)")
    rn.set_defaults(fn=cmd_run)

    sk = sub.add_parser("skill").add_subparsers(dest="skill_cmd", required=True)
    si = sk.add_parser("install")
    si.add_argument("path")
    si.add_argument("--panel", action="store_true")
    si.set_defaults(fn=cmd_skill)
    sk.add_parser("keygen").set_defaults(fn=cmd_skill)
    sg = sk.add_parser("sign")
    sg.add_argument("path")
    sg.add_argument("--key", required=True)
    sg.set_defaults(fn=cmd_skill)
    st = sk.add_parser("trust").add_subparsers(dest="trust_cmd", required=True)
    ta = st.add_parser("add")
    ta.add_argument("pubkey")
    ta.add_argument("--label", required=True)
    ta.add_argument("--panel", action="store_true")
    ta.set_defaults(fn=cmd_skill)
    tr = st.add_parser("revoke")
    tr.add_argument("fingerprint")
    tr.set_defaults(fn=cmd_skill)
    sk.add_parser("list").set_defaults(fn=cmd_skill)
    sr = sk.add_parser("remove")
    sr.add_argument("name")
    sr.set_defaults(fn=cmd_skill)

    ap = sub.add_parser("approvals").add_subparsers(dest="appr_cmd", required=True)
    aps = ap.add_parser("serve")
    aps.add_argument("--port", type=int, default=0)
    aps.set_defaults(fn=cmd_approvals)
    ap.add_parser("list").set_defaults(fn=cmd_approvals)

    ch = sub.add_parser("chat")
    ch.add_argument("prompt", nargs="*")
    ch.add_argument("--cloud", action="store_true",
                    help="opt-in cloud (exige aprovação A2+A3 em TTY)")
    ch.set_defaults(fn=cmd_chat)

    me = sub.add_parser("memory").add_subparsers(dest="mem_cmd", required=True)
    m1 = me.add_parser("search")
    m1.add_argument("query", nargs="+")
    m1.add_argument("-k", type=int, default=5)
    m2 = me.add_parser("recent")
    m2.add_argument("-k", type=int, default=10)
    m3 = me.add_parser("note")
    m3.add_argument("text", nargs="+")
    m4 = me.add_parser("forget")
    m4.add_argument("id", type=int)
    m5 = me.add_parser("stats")
    m6 = me.add_parser("exportar")
    m6.add_argument("arquivo")
    m7 = me.add_parser("importar")
    m7.add_argument("arquivo")
    m8 = me.add_parser("consolidar")
    for mp in (m1, m2, m3, m4, m5, m6, m7, m8):
        mp.set_defaults(fn=cmd_memory)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    lg = sub.add_parser("logs").add_subparsers(dest="logs_cmd", required=True)
    lg.add_parser("verify").set_defaults(fn=cmd_logs)
    return p


def cmd_menu(ctx, args) -> int:
    """Menu principal amigável (v0.11): 1ª vez => onboarding; depois => menu."""
    from nomos.simple.menu_principal import menu_principal
    perfil = config.load_agent() or {}
    if not perfil.get("onboarding_completo"):
        return cmd_start(ctx, args)   # onboarding + chat, como sempre foi
    ns = lambda **kw: argparse.Namespace(**kw)
    acoes = {
        "1": lambda: cmd_start(ctx, ns()),
        "2": lambda: cmd_status(ctx, ns()),
        "3": lambda: cmd_cerebro(ctx, ns(cerebro_cmd=None)),
        "4": lambda: cmd_motores(ctx, ns(motores_cmd="menu")),
        "5": lambda: cmd_skills(ctx, ns(skills_cmd="menu")),
        "6": lambda: cmd_chaves(ctx, ns(chaves_cmd=None)),
        "7": lambda: cmd_local(ctx, ns(local_cmd=None)),
        "8": lambda: cmd_doutor(ctx, ns()),
        "9": lambda: cmd_tema(ctx, ns(tema_cmd=None)),
    }
    return menu_principal(ctx, perfil, acoes)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = _paths()
    fn = getattr(args, "fn", None)
    if fn is None:
        # `nomos` sem comando: menu amigável (ou ajuda, se não houver TTY)
        if sys.stdin.isatty() and sys.stdout.isatty():
            return cmd_menu(ctx, args)
        build_parser().print_help()
        return EXIT_OK
    try:
        return fn(ctx, args)
    except (VaultError, VaultLocked, config.ConfigError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("\n(encerrado por você)", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # nunca despejar traceback na cara do iniciante
        print("Algo deu errado do meu lado, mas nada foi perdido. "
              "Você pode tentar de novo.", file=sys.stderr)
        print(f"(detalhe técnico para suporte: {type(exc).__name__}: {exc})",
              file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
