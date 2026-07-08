"""NOMOS simple.rotinas — o agente proativo, sem virar um daemon misterioso.

Modelo de segurança:
- uma rotina só executa AÇÕES INTERNAS de um registro fixo e seguro
  ("briefing", "doutor", "consolidar-memoria") ou uma skill instalada
  ("skill:<nome>") — nunca comando arbitrário;
- CRIAR uma rotina passa pelo gate (A1) com aprovação humana em TTY;
- EXECUTAR rotinas roda sem aprovador (é o ponto de ser automático) — por
  isso qualquer ação que exigiria aprovação é NEGADA na hora (fail-closed):
  na prática, skills além de A0 não rodam em rotina;
- o NOMOS não instala cron/agendador sozinho: `nomos rotinas agendar` mostra
  a linha para VOCÊ colar no seu agendador, se quiser.

Estado em NOMOS_HOME/rotinas.json (0600).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado
from nomos.kernel.policy import Category, gate

ARQUIVO = "rotinas.json"
ACOES_INTERNAS = ("briefing", "doutor", "consolidar-memoria")
HORA_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class RotinaError(Exception):
    pass


def _caminho(home: Path) -> Path:
    return Path(home) / ARQUIVO


def _ler(home: Path) -> list[dict]:
    p = _caminho(home)
    if not p.exists():
        return []
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        return dados.get("rotinas", []) if isinstance(dados, dict) else []
    except Exception:
        return []   # corrompido: nada roda (fail-closed)


def _gravar(home: Path, rotinas: list[dict]) -> None:
    p = _caminho(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    # escrita atômica + utf-8: crash no meio não apaga todas as rotinas e
    # emojis/acentos não quebram fora de UTF-8
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"rotinas": rotinas}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    chmod_privado(tmp, 0o600)
    tmp.replace(p)
    chmod_privado(p, 0o600)


def validar_acao(acao: str, skills_dir: Path | None = None) -> str | None:
    """None se válida; senão o problema."""
    if acao in ACOES_INTERNAS:
        return None
    if acao.startswith("skill:"):
        nome = acao.split(":", 1)[1]
        if skills_dir is not None and not (Path(skills_dir) / nome).exists():
            return f"skill '{nome}' não está instalada"
        return None
    if acao.startswith("briefing-telegram:"):
        chat = acao.split(":", 1)[1].strip()
        if re.fullmatch(r"-?\d{1,20}", chat) or re.fullmatch(r"@\w{3,64}",
                                                             chat):
            return None
        return ("briefing-telegram precisa de um chat válido: número "
                "(ex.: briefing-telegram:424242) ou @canal")
    if acao.startswith("briefing-whatsapp:"):
        numero = acao.split(":", 1)[1].strip().lstrip("+")
        if re.fullmatch(r"\d{8,15}", numero):
            return None
        return ("briefing-whatsapp precisa de um número internacional só "
                "com dígitos (ex.: briefing-whatsapp:5511999998888)")
    if acao.startswith("briefing-email:"):
        email = acao.split(":", 1)[1].strip()
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return None
        return ("briefing-email precisa de um e-mail válido (ex.: "
                "briefing-email:voce@dominio.com)")
    return (f"ação desconhecida: {acao!r} — permitidas: "
            f"{', '.join(ACOES_INTERNAS)}, skill:<nome>, "
            "briefing-telegram:<chat_id>, briefing-whatsapp:<numero> ou "
            "briefing-email:<endereço>")


def criar(home: Path, nome: str, hora: str, acao: str, policy, approver,
          audit=None, skills_dir: Path | None = None) -> dict:
    """Cria rotina COM aprovação humana (gate A1). Fail-closed sem TTY."""
    if not HORA_RE.match(hora or ""):
        raise RotinaError(f"hora inválida: {hora!r} (use HH:MM, ex.: 08:30)")
    problema = validar_acao(acao, skills_dir)
    if problema:
        raise RotinaError(problema)
    decision = policy.decide(Category.WRITE_LOCAL,
                             target=f"rotina:{nome} às {hora} → {acao}")
    if not gate(decision, approver):
        raise RotinaError("criação de rotina não aprovada (uma rotina roda "
                          "sozinha depois — por isso nasce só com seu sim)")
    rotinas = _ler(home)
    rid = max((r.get("id", 0) for r in rotinas), default=0) + 1
    nova = {"id": rid, "nome": nome, "hora": hora, "acao": acao,
            "ativa": True, "criada_em": int(time.time()), "ultima_execucao": 0}
    rotinas.append(nova)
    _gravar(home, rotinas)
    if audit is not None:
        audit.append("rotina.criada", id=rid, nome=nome, hora=hora, acao=acao)
    return nova


def listar(home: Path) -> list[dict]:
    return _ler(home)


def remover(home: Path, rid: int, audit=None) -> bool:
    rotinas = _ler(home)
    restantes = [r for r in rotinas if r.get("id") != rid]
    if len(restantes) == len(rotinas):
        return False
    _gravar(home, restantes)
    if audit is not None:
        audit.append("rotina.removida", id=rid)
    return True


def pausar(home: Path, rid: int, ativa: bool) -> bool:
    rotinas = _ler(home)
    for r in rotinas:
        if r.get("id") == rid:
            r["ativa"] = bool(ativa)
            _gravar(home, rotinas)
            return True
    return False


def devidas(home: Path, agora: datetime | None = None) -> list[dict]:
    """Rotinas ativas cuja hora já passou HOJE e ainda não rodaram hoje."""
    agora = agora or datetime.now()
    hoje0 = datetime(agora.year, agora.month, agora.day).timestamp()
    saida = []
    for r in _ler(home):
        if not r.get("ativa", True):
            continue
        try:
            hh, mm = map(int, r["hora"].split(":"))
        except Exception:
            continue
        alvo = datetime(agora.year, agora.month, agora.day, hh, mm)
        if agora >= alvo and r.get("ultima_execucao", 0) < hoje0:
            saida.append(r)
    return saida


def _marcar_execucao(home: Path, rid: int) -> None:
    rotinas = _ler(home)
    for r in rotinas:
        if r.get("id") == rid:
            r["ultima_execucao"] = int(time.time())
    _gravar(home, rotinas)


def briefing(ctx) -> str:
    """Briefing do dia: tarefas anotadas, rotinas de hoje e o próximo passo."""
    from nomos.cognition.memory import Memory
    from nomos.simple import doutor as doutor_mod
    linhas = [f"Bom dia! Briefing local de {datetime.now().strftime('%d/%m/%Y')}",
              "=" * 44]
    mem = Memory(Path(ctx["home"]) / "memory.db")
    tarefas = [i for i in mem.recent(200)
               if i.role == "note" and i.text.lower().startswith(("tarefa:", "data:"))]
    if tarefas:
        linhas.append("Suas tarefas e datas anotadas:")
        linhas += [f"  · {t.text}" for t in tarefas[:8]]
    else:
        linhas.append("Nenhuma tarefa anotada. (anote com: /memoria anotar tarefa: ...)")
    hoje = [r for r in listar(ctx["home"]) if r.get("ativa", True)]
    if hoje:
        linhas.append("Rotinas configuradas:")
        linhas += [f"  · {r['hora']} — {r['nome']} ({r['acao']})" for r in hoje]
    itens = doutor_mod.diagnostico_v011(Path(ctx["home"]), ctx)
    linhas.append(f"Check-up: {doutor_mod.status_geral(itens)} · próximo passo: "
                  f"{doutor_mod.proximo_passo(itens)}")
    linhas.append("(gerado 100% na sua máquina — nada saiu dela)")
    return "\n".join(linhas)


# Canais de entrega do briefing (MC41/MC45): cada um mapeia para a tool do
# seu conector MCP e como montar os argumentos. Um só caminho governado.
_CANAIS = {
    "telegram": {
        "tool": "telegram_enviar",
        "args": lambda destino, texto: {"chat_id": str(destino),
                                        "texto": texto},
        "manifesto_env": "NOMOS_TELEGRAM_MANIFESTO",
        "manifesto_pad": "examples/mcp/telegram/manifesto.json",
        "dir": "telegram",
        "rotulo": "Telegram",
    },
    "whatsapp": {
        "tool": "whatsapp_enviar_texto",
        "args": lambda destino, texto: {"numero": str(destino).lstrip("+"),
                                        "texto": texto},
        "manifesto_env": "NOMOS_WHATSAPP_MANIFESTO",
        "manifesto_pad": "examples/mcp/whatsapp-cloud/manifesto.json",
        "dir": "whatsapp-cloud",
        "rotulo": "WhatsApp",
    },
    "email": {
        "tool": "email_enviar",
        "args": lambda destino, texto: {
            "destinatario": str(destino),
            "assunto": (f"Briefing NOMOS — "
                        f"{datetime.now().strftime('%d/%m/%Y')}"),
            "texto": texto},
        "manifesto_env": "NOMOS_EMAIL_MANIFESTO",
        "manifesto_pad": "examples/mcp/email-smtp/manifesto.json",
        "dir": "email-smtp",
        "rotulo": "e-mail",
    },
}


def _manifesto_pad(cfg) -> str:
    """Caminho do manifesto padrão do canal. Prefere a cópia EMPACOTADA (achada
    por ``_raiz_exemplos`` — funciona instalado por pip); cai no caminho do
    repositório se aquela não existir."""
    from nomos.interface.mcp_catalogo import _raiz_exemplos
    raiz = _raiz_exemplos()
    if raiz is not None:
        cand = raiz / cfg["dir"] / "manifesto.json"
        if cand.is_file():
            return str(cand)
    return cfg["manifesto_pad"]


def entregar_briefing(ctx, canal: str, destino: str, manifesto_path,
                      approver, say=print) -> tuple[bool, str]:
    """Briefing do dia ENTREGUE por um conector MCP confiado (MC41/MC45).

    ``canal`` é 'telegram' ou 'whatsapp' — a única diferença é qual tool do
    conector é chamada e como o destino é embalado. As leis da casa valem
    igual para os dois:
    - o manifesto tem de estar CONFIÁVEL no trust store (senão, fail-closed
      com a instrução de confiar primeiro);
    - o nível da tool (A3: credencial + rede) passa pela política e pelo SEU
      gate de aprovação — sem aprovação, nada sai;
    - tudo auditado; o conteúdo do briefing é gerado 100% localmente.

    Devolve (ok, mensagem_para_o_usuario).
    """
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface import mcp_client as mc
    from nomos.kernel.policy import gate as gate_fn

    cfg = _CANAIS.get(canal)
    if cfg is None:
        return False, f"canal desconhecido: {canal!r}"
    try:
        manifesto = mc.carregar_manifesto(Path(manifesto_path))
    except mc.ManifestoInvalido as exc:
        return False, f"manifesto recusado (fail-closed): {exc}"
    confianca = cat.status(ctx["home"], manifesto)
    if confianca != "confiavel":
        return False, (f"'{manifesto['nome']}' é {confianca} — entregar o "
                       "briefing exige server CONFIÁVEL. Registre antes: "
                       f"nomos mcp confiar {manifesto_path}")
    tool = cfg["tool"]
    nivel = mc.nivel_da_tool(manifesto, tool)
    decisao = ctx["policy"].decide(
        mc.NIVEIS[nivel], target=f"rotina:briefing→{manifesto['nome']}")
    if not gate_fn(decisao, approver):
        if ctx.get("audit"):
            ctx["audit"].append("rotina.briefing.entrega_negada",
                                server=manifesto["nome"], nivel=nivel,
                                canal=canal)
        return False, (f"entrega é nível {nivel} — sem a sua aprovação, o "
                       "briefing não sai da máquina (e não saiu)")
    texto = briefing(ctx)
    say(f"briefing gerado — enviando pelo {cfg['rotulo']} (aprovado)…")
    try:
        with mc.ClienteMCP(manifesto,
                           base=Path(manifesto_path).parent) as cli:
            resultado = cli.chamar(tool, cfg["args"](destino, texto))
    except mc.McpErro as exc:
        return False, f"o conector recusou: {exc}"
    if ctx.get("audit"):
        ctx["audit"].append("rotina.briefing.entregue",
                            server=manifesto["nome"], nivel=nivel,
                            canal=canal, destino=str(destino))
    trecho = ""
    for bloco in resultado.get("content", []):
        if bloco.get("type") == "text":
            trecho = bloco.get("text", "")[:120]
    return True, f"briefing entregue ✓ {trecho}"


# --------------------------------------------------------------------------
# ENTRADA (Fase 3): LER o que chegou por um conector, com a mesma governança
# do briefing (manifesto CONFIÁVEL + gate A3 + auditoria). Só leitura.
# --------------------------------------------------------------------------
_ENTRADA = {
    "telegram": {
        "tool": "telegram_atualizacoes",
        "args": {"limite": 20},
        "manifesto_env": "NOMOS_TELEGRAM_MANIFESTO",
        "manifesto_pad": "examples/mcp/telegram/manifesto.json",
        "dir": "telegram",
        "rotulo": "Telegram",
    },
    "email": {
        "tool": "email_imap_recentes",
        "args": {"limite": 15, "nao_lidas": True},
        "manifesto_env": "NOMOS_IMAP_MANIFESTO",
        "manifesto_pad": "examples/mcp/email-imap/manifesto.json",
        "dir": "email-imap",
        "rotulo": "e-mail (IMAP)",
    },
}


def _fmt_entrada(canal: str, dados: dict) -> str:
    """Resumo humano do que chegou, a partir do resultado da tool de leitura."""
    msgs = dados.get("mensagens") or []
    if not msgs:
        return "nada novo por aqui — a caixa está em dia."
    linhas = [f"chegaram {len(msgs)} (mais recentes primeiro):"]
    for m in msgs[:20]:
        if canal == "telegram":
            linhas.append(f"  • {m.get('de', '?')}: "
                          f"{(m.get('texto') or '(sem texto)')[:80]}")
        else:  # email
            linhas.append(f"  • {m.get('de', '?')} — "
                          f"{(m.get('assunto') or '(sem assunto)')[:80]}")
    return "\n".join(linhas)


def ler_entrada(ctx, canal: str, manifesto_path, approver,
                say=print) -> tuple[bool, str]:
    """Lê o que chegou por um conector MCP confiado (Fase 3). Mesma governança
    do briefing: manifesto CONFIÁVEL (senão fail-closed), o nível da tool (A3)
    passa pelo SEU gate — sem aprovação, nada é lido — e tudo é auditado (só
    metadados/contagem). Devolve (ok, resumo)."""
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface import mcp_client as mc
    from nomos.kernel.policy import gate as gate_fn

    cfg = _ENTRADA.get(canal)
    if cfg is None:
        return False, f"canal de entrada desconhecido: {canal!r}"
    try:
        manifesto = mc.carregar_manifesto(Path(manifesto_path))
    except mc.ManifestoInvalido as exc:
        return False, f"manifesto recusado (fail-closed): {exc}"
    if cat.status(ctx["home"], manifesto) != "confiavel":
        return False, (f"'{manifesto['nome']}' não é confiável — ler a entrada "
                       "exige server CONFIÁVEL. Registre antes: "
                       f"nomos mcp confiar {manifesto_path}")
    tool = cfg["tool"]
    nivel = mc.nivel_da_tool(manifesto, tool)
    decisao = ctx["policy"].decide(
        mc.NIVEIS[nivel], target=f"entrada:{manifesto['nome']}:{tool}")
    if not gate_fn(decisao, approver):
        if ctx.get("audit"):
            ctx["audit"].append("entrada.negada", server=manifesto["nome"],
                                nivel=nivel, canal=canal)
        return False, (f"ler a entrada é nível {nivel} — sem a sua aprovação, "
                       "nada foi lido")
    try:
        with mc.ClienteMCP(manifesto,
                           base=Path(manifesto_path).parent) as cli:
            resultado = cli.chamar(tool, dict(cfg["args"]))
    except mc.McpErro as exc:
        return False, f"o conector recusou: {exc}"
    dados: dict = {}
    for bloco in resultado.get("content", []):
        if bloco.get("type") == "text":
            try:
                dados = json.loads(bloco.get("text") or "{}")
            except Exception:
                dados = {}
    if ctx.get("audit"):
        ctx["audit"].append("entrada.lida", server=manifesto["nome"],
                            nivel=nivel, canal=canal,
                            quantos=len(dados.get("mensagens") or []))
    return True, _fmt_entrada(canal, dados)


def enviar_briefing(ctx, chat_id: str, manifesto_path, approver,
                    say=print) -> tuple[bool, str]:
    """Compat (MC41): entrega no Telegram — hoje um atalho de
    ``entregar_briefing(..., 'telegram', ...)``."""
    return entregar_briefing(ctx, "telegram", chat_id, manifesto_path,
                             approver, say=say)


def prever_acao(acao: str) -> str:
    """F5/ISSUE-023: descreve o que a ação FARIA, sem executar nada."""
    if acao == "briefing":
        return "geraria o briefing do dia (tarefas + rotinas + próximo passo), só leitura"
    if acao == "doutor":
        return "rodaria o check-up (doutor), só leitura"
    if acao == "consolidar-memoria":
        return "extrairia fatos/tarefas das conversas para notas (idempotente)"
    if acao.startswith("skill:"):
        nome = acao.split(":", 1)[1]
        return (f"tentaria rodar a skill '{nome}' — mas só se ela for A0 "
                "(skills que pedem aprovação nunca rodam em rotina)")
    if acao.startswith("briefing-telegram:"):
        chat = acao.split(":", 1)[1]
        return (f"geraria o briefing e o ENTREGARIA no Telegram (chat "
                f"{chat}) — nível A3: só sai com aprovação sua (interativa "
                "ou pela fila do painel)")
    if acao.startswith("briefing-whatsapp:"):
        numero = acao.split(":", 1)[1]
        return (f"geraria o briefing e o ENTREGARIA no WhatsApp (número "
                f"{numero}) — nível A3: só sai com aprovação sua (interativa "
                "ou pela fila do painel)")
    if acao.startswith("briefing-email:"):
        email = acao.split(":", 1)[1]
        return (f"geraria o briefing e o ENTREGARIA por e-mail (para "
                f"{email}) — nível A3: só sai com aprovação sua (interativa "
                "ou pela fila do painel)")
    return f"ação desconhecida: {acao}"


def executar_acao(ctx, acao: str, say=print, simular: bool = False,
                  approver=None) -> tuple[bool, str]:
    """Executa UMA ação de rotina. `simular=True` só descreve, não executa.
    Sem aprovador: sensível é negado na hora (o approver da fila do painel
    — `--panel` — é um aprovador válido: um humano decide, com TTL)."""
    if simular:
        prev = prever_acao(acao)
        say(f"[simulação] {prev}")
        return True, f"simulado: {prev}"
    for canal, cfg in _CANAIS.items():
        prefixo = f"briefing-{canal}:"
        if acao.startswith(prefixo):
            import os as _os
            destino = acao.split(":", 1)[1]
            manifesto = _os.environ.get(cfg["manifesto_env"]) or _manifesto_pad(cfg)
            return entregar_briefing(ctx, canal, destino, manifesto,
                                     approver, say=say)
    if acao == "briefing":
        texto = briefing(ctx)
        say(texto)
        return True, "briefing gerado"
    if acao == "doutor":
        from nomos.simple import doutor as doutor_mod
        say(doutor_mod.texto_relatorio_v011(Path(ctx["home"]), ctx))
        return True, "check-up gerado"
    if acao == "consolidar-memoria":
        from nomos.cognition.memory import Memory
        criadas = Memory(Path(ctx["home"]) / "memory.db").consolidar()
        say(f"consolidação: {len(criadas)} nota(s) nova(s).")
        return True, f"{len(criadas)} nota(s)"
    if acao.startswith("skill:"):
        from nomos.ext import skill_registry as reg
        nome = acao.split(":", 1)[1]
        # approver=None de propósito: rotina roda sozinha, então só passa o
        # que NÃO exige aprovação (A0). Fail-closed para todo o resto.
        rc, saida = reg.executar(nome, Path(ctx["home"]) / "skills",
                                 ctx["policy"], approver=None,
                                 audit=ctx.get("audit"))
        if rc == 0:
            say(saida.strip())
            return True, "skill executada"
        return False, (f"skill '{nome}' não rodou em rotina (rc={rc}): ações "
                       "que pedem aprovação humana não rodam sozinhas — por design")
    return False, f"ação desconhecida: {acao}"


def executar_devidas(ctx, agora: datetime | None = None, say=print,
                     simular: bool = False, approver=None) -> list[dict]:
    """Roda (ou simula) as rotinas devidas. Em simulação: nada executa, nada
    é marcado como executado, e a auditoria registra apenas o dry-run."""
    resultados = []
    for r in devidas(Path(ctx["home"]), agora):
        ok, detalhe = executar_acao(ctx, r["acao"], say=say, simular=simular,
                                    approver=approver)
        if not simular:
            _marcar_execucao(Path(ctx["home"]), r["id"])
        if ctx.get("audit") is not None:
            ctx["audit"].append(
                "rotina.simulada" if simular else "rotina.executada",
                id=r["id"], nome=r["nome"], acao=r["acao"], ok=ok)
        resultados.append({"id": r["id"], "nome": r["nome"], "ok": ok,
                           "detalhe": detalhe})
    return resultados


FORMATOS_EXPORT = ("launchd", "systemd", "windows")


def exportar(home: Path, formato: str | None = None) -> tuple[list[Path], str]:
    """Gera arquivos de agendador do SO (MC30-B7). O NOMOS NUNCA os instala.

    Devolve (arquivos_gerados, instruções_de_instalação_manual).
    """
    import sys
    if formato is None:
        formato = ("launchd" if sys.platform == "darwin"
                   else "windows" if sys.platform.startswith("win")
                   else "systemd")
    if formato not in FORMATOS_EXPORT:
        raise RotinaError(f"formato desconhecido: {formato!r} — "
                          f"use um de: {', '.join(FORMATOS_EXPORT)}")
    destino = home / "agendadores"
    destino.mkdir(parents=True, exist_ok=True)
    exe = sys.executable
    # exe entre aspas: caminho do Python com espaços (ex.: "Program Files") não
    # quebra a linha gerada no systemd/schtasks
    cmd = f'"{exe}" -m nomos.cli rotinas executar'
    arquivos: list[Path] = []

    if formato == "launchd":
        plist = destino / "br.com.se7enpay.nomos.rotinas.plist"
        # sem DOCTYPE: launchd aceita, e o código-fonte permanece sem NENHUMA
        # URL externa (prova estática de egress-zero cobre até strings geradas)
        plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>br.com.se7enpay.nomos.rotinas</string>
  <key>ProgramArguments</key>
  <array><string>{exe}</string><string>-m</string><string>nomos.cli</string>
         <string>rotinas</string><string>executar</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>NOMOS_HOME</key><string>{home}</string></dict>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><false/>
</dict></plist>
""", encoding="utf-8")
        arquivos.append(plist)
        instrucao = (f"instale VOCÊ MESMO (uma vez):\n"
                     f"  cp {plist} ~/Library/LaunchAgents/\n"
                     f"  launchctl load ~/Library/LaunchAgents/{plist.name}")
    elif formato == "systemd":
        service = destino / "nomos-rotinas.service"
        timer = destino / "nomos-rotinas.timer"
        service.write_text(f"""[Unit]
Description=NOMOS — executa rotinas devidas (local, sem rede)

[Service]
Type=oneshot
Environment="NOMOS_HOME={home}"
ExecStart={cmd}
""", encoding="utf-8")
        timer.write_text("""[Unit]
Description=NOMOS — dispara as rotinas a cada 15 min

[Timer]
OnCalendar=*:0/15
Persistent=false

[Install]
WantedBy=timers.target
""", encoding="utf-8")
        arquivos += [service, timer]
        instrucao = (f"instale VOCÊ MESMO (uma vez):\n"
                     f"  cp {service} {timer} ~/.config/systemd/user/\n"
                     f"  systemctl --user enable --now nomos-rotinas.timer")
    else:  # windows
        cmdfile = destino / "nomos-rotinas.cmd"
        # dentro do /tr "..." as aspas do exe precisam ser DUPLICADAS (\"\")
        # para caminho com espaços não quebrar o comando do schtasks
        cmd_win = f'\"\"{exe}\"\" -m nomos.cli rotinas executar'
        cmdfile.write_text(
            f"@echo off\r\nrem NOMOS — crie a tarefa VOCÊ MESMO executando "
            f"este arquivo uma vez:\r\n"
            f"schtasks /create /tn \"NOMOS Rotinas\" /sc minute /mo 15 "
            f"/tr \"cmd /c set NOMOS_HOME={home}&& {cmd_win}\"\r\n",
            encoding="utf-8")
        arquivos.append(cmdfile)
        instrucao = (f"instale VOCÊ MESMO (uma vez): dê dois cliques em "
                     f"{cmdfile} (ou rode no Prompt).")
    return arquivos, instrucao


def linha_agendador(home: Path, telegram: str | None = None,
                    manifesto: str | None = None) -> str:
    """A linha que VOCÊ pode colar no seu agendador. O NOMOS não mexe nele."""
    import sys
    # caminho COMPLETO do Python, entre aspas (como em exportar()): o cron tem
    # PATH mínimo — só o basename cairia no Python do sistema, sem o nomos,
    # e a rotina falharia em silêncio (pior ainda em venv/pipx)
    exe = f'"{sys.executable}"'
    base = (f"# roda as rotinas devidas a cada 15 min (cole no `crontab -e`);\n"
            f"# --panel: rotinas sensíveis (ex.: briefing-telegram) pedem sua\n"
            f"# aprovação na fila do painel — sem aprovação, não rodam:\n"
            f"*/15 * * * * NOMOS_HOME={home} {exe} -m nomos.cli rotinas "
            f"executar --panel\n"
            f"# Windows (Agendador de Tarefas → nova tarefa):\n"
            f"#   programa: {exe} · argumentos: -m nomos.cli rotinas "
            f"executar --panel")
    if not telegram:
        return base
    # MC41.1: briefing entregue no Telegram, agendado — com a verdade na
    # frente: nível A3 nunca se auto-aprova. --panel enfileira o pedido na
    # fila de aprovações (TTL 5 min): você aprova no painel/Dash e ele sai;
    # ninguém aprovou ⇒ não sai (fail-closed), e fica auditado.
    mf = manifesto or "examples/mcp/telegram/manifesto.json"
    return (base + "\n\n"
            "# briefing das 08:00 entregue no seu Telegram "
            "(aprovação just-in-time):\n"
            "#   ATENÇÃO: troque SEU_TOKEN pelo token do @BotFather — o "
            "cron tem ambiente mínimo;\n"
            "#   a entrega é A3: aprove no painel em até 5 min, senão NÃO "
            "sai (fail-closed).\n"
            f"0 8 * * * NOMOS_HOME={home} NOMOS_TELEGRAM_TOKEN=SEU_TOKEN "
            f"{exe} -m nomos.cli rotinas briefing "
            f"--telegram {telegram} --manifesto {mf} --panel")
