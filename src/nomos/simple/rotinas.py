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
        dados = json.loads(p.read_text())
        return dados.get("rotinas", []) if isinstance(dados, dict) else []
    except Exception:
        return []   # corrompido: nada roda (fail-closed)


def _gravar(home: Path, rotinas: list[dict]) -> None:
    p = _caminho(home)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"rotinas": rotinas}, ensure_ascii=False, indent=2))
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
    return (f"ação desconhecida: {acao!r} — permitidas: "
            f"{', '.join(ACOES_INTERNAS)} ou skill:<nome>")


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
    return f"ação desconhecida: {acao}"


def executar_acao(ctx, acao: str, say=print, simular: bool = False) -> tuple[bool, str]:
    """Executa UMA ação de rotina. `simular=True` só descreve, não executa.
    Sem aprovador: sensível é negado na hora."""
    if simular:
        prev = prever_acao(acao)
        say(f"[simulação] {prev}")
        return True, f"simulado: {prev}"
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
                     simular: bool = False) -> list[dict]:
    """Roda (ou simula) as rotinas devidas. Em simulação: nada executa, nada
    é marcado como executado, e a auditoria registra apenas o dry-run."""
    resultados = []
    for r in devidas(Path(ctx["home"]), agora):
        ok, detalhe = executar_acao(ctx, r["acao"], say=say, simular=simular)
        if not simular:
            _marcar_execucao(Path(ctx["home"]), r["id"])
        if ctx.get("audit") is not None:
            ctx["audit"].append(
                "rotina.simulada" if simular else "rotina.executada",
                id=r["id"], nome=r["nome"], acao=r["acao"], ok=ok)
        resultados.append({"id": r["id"], "nome": r["nome"], "ok": ok,
                           "detalhe": detalhe})
    return resultados


def linha_agendador(home: Path) -> str:
    """A linha que VOCÊ pode colar no seu agendador. O NOMOS não mexe nele."""
    import sys
    exe = Path(sys.executable).name
    return (f"# roda as rotinas devidas a cada 15 min (cole no `crontab -e`):\n"
            f"*/15 * * * * NOMOS_HOME={home} {exe} -m nomos.cli rotinas executar\n"
            f"# Windows (Agendador de Tarefas → nova tarefa):\n"
            f"#   programa: {exe} · argumentos: -m nomos.cli rotinas executar")
