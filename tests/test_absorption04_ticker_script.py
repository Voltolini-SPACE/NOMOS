"""ABSORPTION-04 / FASES 3-6 — ticker, autorização por ocorrência, script, alertas.

O que se prova aqui:
- o ticker transforma job persistido em ocorrência executada, sem busy-loop e
  com shutdown limpo;
- a autoridade é obtida POR OCORRÊNCIA — job de T0 não executa com poder de T0;
- `script-rodar` executa `argv[]` sem shell, com env por allowlist e timeout;
- falha vira EVENTO estruturado, e o canal é desacoplado do scheduler.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import pytest

from nomos.adapters.agenda import ScheduleSpec, TipoAgenda
from nomos.adapters.alertas import (
    AlertSink, AuditAlertSink, EventoFalha, SinkComposto, SinkDeTeste,
)
from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, ErroEscopo, ErroInvalido, ErroTimeout,
)
from nomos.adapters.scheduler import ArmazemJobs, Scheduler
from nomos.adapters.script import ScriptAdapter
from nomos.adapters.ticker import SEM_AUTORIZACAO, CatchUp, Ticker
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category

UTC = timezone.utc
T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


class _Efeito:
    def __init__(self, falhar=False):
        self.chamadas = []
        self.credenciais = []
        self.falhar = falhar

    def __call__(self, definicao, instancia, credencial=None):
        self.chamadas.append(instancia.chave)
        self.credenciais.append(credencial)
        if self.falhar:
            raise RuntimeError("efeito falhou")
        return type("R", (), {"efeito_aplicado": True})()


def _sched(tmp_path, efeito=None, relogio=None):
    relogio = relogio or {"t": T0}
    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=efeito or _Efeito(),
                  agora_fn=lambda: relogio["t"])
    return s, relogio


# ============================================== FASE 3 — TICKER

def test_ticker_executa_job_devido(tmp_path):
    ef = _Efeito()
    s, rel = _sched(tmp_path, ef)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0)
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    r = t.tick()
    assert r.executadas == 1
    assert len(ef.chamadas) == 1


def test_ticker_nao_executa_job_futuro(tmp_path):
    ef = _Efeito()
    s, rel = _sched(tmp_path, ef)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0 + timedelta(hours=1))
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    assert t.tick().executadas == 0
    assert ef.chamadas == []


def test_ticker_nao_repete_ocorrencia(tmp_path):
    ef = _Efeito()
    s, rel = _sched(tmp_path, ef)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0)
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    t.tick()
    t.tick()
    t.tick()
    assert len(ef.chamadas) == 1


def test_ticker_nao_faz_busy_loop(tmp_path):
    """Dorme SEMPRE entre passadas, inclusive quando não houve trabalho."""
    pausas = []
    s, rel = _sched(tmp_path)
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"], dormir=pausas.append,
               intervalo_s=0.25)
    t.rodar_ate(max_ticks=4)
    assert len(pausas) == 4
    assert all(p == 0.25 for p in pausas)


def test_ticker_shutdown_limpo(tmp_path):
    s, rel = _sched(tmp_path)
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    ticks = {"n": 0}

    def _dormir(_s):
        ticks["n"] += 1
        if ticks["n"] >= 2:
            t.parar()

    t._dormir = _dormir
    resultados = t.rodar_ate(max_ticks=100)
    assert len(resultados) == 2          # parou de verdade, não estourou o teto


def test_ticker_com_cron_reagenda_no_fuso(tmp_path):
    """Cron + timezone atravessando o ticker."""
    ef = _Efeito()
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    spec = ScheduleSpec(kind=TipoAgenda.CRON, expression="0 9 * * *",
                        timezone="America/Sao_Paulo")
    s.criar("j", "suj", "fs-ler", schedule=spec, primeiro_em=T0)
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    t.tick()
    assert len(ef.chamadas) == 1
    # 09:00 em São Paulo (UTC-3) = 12:00 UTC do dia seguinte
    assert s.status("j").proximo_em == datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


# --------------------------------------- catch-up explícito

def _job_atrasado(tmp_path, catchup, catchup_max=10):
    ef = _Efeito()
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    s.criar("j", "suj", "fs-ler", intervalo_s=300, primeiro_em=T0)  # 5 min
    rel["t"] = T0 + timedelta(hours=5)                              # downtime
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"], dormir=lambda _s: None,
               catchup=catchup, catchup_max=catchup_max)
    t.tick()
    return ef


def test_catchup_run_once_e_o_default(tmp_path):
    ef = _job_atrasado(tmp_path, CatchUp.RUN_ONCE)
    assert len(ef.chamadas) == 1


def test_catchup_skip_pula_as_antigas(tmp_path):
    ef = _job_atrasado(tmp_path, CatchUp.SKIP)
    assert len(ef.chamadas) == 1


def test_catchup_run_all_bounded_respeita_o_teto(tmp_path):
    ef = _job_atrasado(tmp_path, CatchUp.RUN_ALL_BOUNDED, catchup_max=3)
    assert len(ef.chamadas) == 3          # 5 h daria 60; o teto vale
    assert len(set(ef.chamadas)) == 3     # ocorrências distintas


def test_catchup_e_explicito_nao_implicito():
    assert {c.value for c in CatchUp} == {"SKIP", "RUN_ONCE", "RUN_ALL_BOUNDED"}


# ============================================== FASE 4 — AUTH POR OCORRÊNCIA

def test_autorizador_e_chamado_por_ocorrencia(tmp_path):
    ef = _Efeito()
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    s.criar("j", "suj", "fs-ler", intervalo_s=60, primeiro_em=T0)
    pedidos = []

    def _autorizador(d, inst):
        pedidos.append(inst.chave)
        return {"token": f"fresco-{len(pedidos)}"}

    t = Ticker(s, autorizador=_autorizador, agora_fn=lambda: rel["t"],
               dormir=lambda _s: None)
    t.tick()
    rel["t"] = T0 + timedelta(seconds=60)
    t.tick()
    assert len(pedidos) == 2
    assert len(set(pedidos)) == 2                       # ocorrências distintas
    assert ef.credenciais == [{"token": "fresco-1"}, {"token": "fresco-2"}]


def test_autorizacao_negada_no_instante_da_execucao(tmp_path):
    """Job criado em T0; política muda; ocorrência em T2 é NEGADA."""
    ef = _Efeito()
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0)
    politica = {"permite": False}                       # mudou depois da criação
    t = Ticker(s, autorizador=lambda d, i: {"ok": 1} if politica["permite"] else None,
               agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    t.tick()
    assert ef.chamadas == []                            # nenhum efeito


def test_autorizador_que_explode_nao_produz_efeito(tmp_path):
    ef = _Efeito()
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0)

    def _quebrado(d, i):
        raise RuntimeError("registro fora do ar")

    sink = SinkDeTeste()
    t = Ticker(s, autorizador=_quebrado, alert_sink=sink,
               agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    t.tick()
    assert ef.chamadas == []
    assert sink.eventos and sink.eventos[0].effect_state == "NO_EFFECT"


def test_job_nao_persiste_credencial(tmp_path):
    """A credencial fresca não é gravada em lugar nenhum."""
    import sqlite3
    ef = _Efeito()
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0)
    t = Ticker(s, autorizador=lambda d, i: {"segredo": "TOKEN-SUPER-SECRETO"},
               agora_fn=lambda: rel["t"], dormir=lambda _s: None)
    t.tick()
    with sqlite3.connect(tmp_path / "j.db") as c:
        dump = "\n".join(str(r) for tabela in ("jobs", "ocorrencias")
                         for r in c.execute(f"SELECT * FROM {tabela}"))
    assert "TOKEN-SUPER-SECRETO" not in dump


# ============================================== FASE 5 — SCRIPT SEM SHELL

class _RegScript:
    conhecida = staticmethod(lambda n: n == "script-rodar")
    categoria_de = staticmethod(lambda n: Category.CODE_EXEC)
    risco_de = staticmethod(lambda n: "A5")
    idempotente_de = staticmethod(lambda n: False)
    executor_de = staticmethod(lambda n: None)


@pytest.fixture()
def ctx_script(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    audit = AuditLog(tmp_path / "logs" / "audit.jsonl")

    def _fazer(deadline=None):
        return CapabilityContext.de_registro(
            _RegScript(), "script-rodar", "suj", raizes=(str(ws),),
            home=str(ws), deadline_monotonic=deadline, audit=audit)
    return _fazer, ws


def _rodar(ctx, **args):
    return ScriptAdapter().executar(
        CapabilityRequest(capacidade="script-rodar", argumentos=args), ctx)


def test_script_roda_argv(ctx_script):
    fazer, ws = ctx_script
    r = _rodar(fazer(), argv=[sys.executable, "-c", "print('ola')"], cwd=str(ws))
    assert r.ok and r.valor.codigo == 0
    assert "ola" in r.valor.stdout


def test_script_recusa_string_em_vez_de_lista(ctx_script):
    fazer, ws = ctx_script
    with pytest.raises(ErroInvalido, match="lista"):
        _rodar(fazer(), argv="echo ola", cwd=str(ws))


@pytest.mark.parametrize("payload", [
    "; rm -rf /", "&& rm -rf /", "|| whoami", "$(whoami)", "`whoami`",
    "| cat /etc/passwd", "> /tmp/invadido", "\n rm -rf /",
])
def test_metacaracteres_sao_texto_inerte(ctx_script, payload):
    """Sem shell, metacaractere em ARGUMENTO é só texto para o programa."""
    fazer, ws = ctx_script
    r = _rodar(fazer(), argv=[sys.executable, "-c",
                             "import sys; print(sys.argv[1])", payload],
               cwd=str(ws))
    assert r.ok
    assert payload.strip() in r.valor.stdout          # chegou literal
    assert not (ws / "invadido").exists()


def test_shell_como_argv0_e_recusado(ctx_script):
    fazer, ws = ctx_script
    for shell in ("sh", "bash", "zsh", "/bin/sh", "/bin/bash", "cmd.exe"):
        with pytest.raises(ErroInvalido, match="interpretador de shell"):
            _rodar(fazer(), argv=[shell, "-c", "echo x"], cwd=str(ws))


def test_cwd_fora_do_escopo_e_recusado(ctx_script, tmp_path):
    fazer, _ws = ctx_script
    with pytest.raises(ErroEscopo):
        _rodar(fazer(), argv=[sys.executable, "-c", "pass"], cwd=str(tmp_path))


def test_allowlist_de_executaveis_e_a_defesa_em_profundidade(ctx_script, tmp_path):
    """Escopo de DADOS não confina BINÁRIO — quem faz isso é a allowlist.

    A primeira versão deste teste exigia que argv[0] estivesse dentro de
    `ctx.raizes`. Estava errado: obrigaria copiar o interpretador para dentro
    do workspace. Escopo de dados diz onde LER/ESCREVER; quem autoriza RODAR é
    o gate (script-rodar é A5_CODE_EXEC). A allowlist opcional é a camada extra.
    """
    fazer, ws = ctx_script
    # sem allowlist: roda (o gate A5 é quem autorizou chegar até aqui)
    assert _rodar(fazer(), argv=[sys.executable, "-c", "pass"], cwd=str(ws)).ok
    # com allowlist que não inclui o alvo: recusado
    with pytest.raises(ErroEscopo, match="fora da allowlist"):
        _rodar(fazer(), argv=[sys.executable, "-c", "pass"], cwd=str(ws),
               executaveis=["/bin/true"])
    # com allowlist que inclui: passa
    assert _rodar(fazer(), argv=[sys.executable, "-c", "pass"], cwd=str(ws),
                  executaveis=[sys.executable]).ok


def test_cwd_continua_confinado_pelo_escopo_de_dados(ctx_script, tmp_path):
    """A separação não afrouxou o dado: cwd fora da raiz segue recusado."""
    fazer, _ws = ctx_script
    with pytest.raises(ErroEscopo):
        _rodar(fazer(), argv=[sys.executable, "-c", "pass"], cwd=str(tmp_path))


def test_ambiente_e_confinado_por_allowlist(ctx_script, monkeypatch):
    fazer, ws = ctx_script
    monkeypatch.setenv("NOMOS_SEGREDO", "NAO-DEVE-VAZAR")
    r = _rodar(fazer(), argv=[sys.executable, "-c",
                             "import os; print(sorted(os.environ))"],
               cwd=str(ws))
    assert "NOMOS_SEGREDO" not in r.valor.stdout


def test_env_fora_da_allowlist_e_recusado(ctx_script):
    fazer, ws = ctx_script
    with pytest.raises(ErroEscopo, match="allowlist"):
        _rodar(fazer(), argv=[sys.executable, "-c", "pass"], cwd=str(ws),
               env={"LD_PRELOAD": "/tmp/mal.so"})


def test_env_permitido_passa(ctx_script):
    fazer, ws = ctx_script
    r = _rodar(fazer(), argv=[sys.executable, "-c",
                             "import os; print(os.environ.get('TZ',''))"],
               cwd=str(ws), env={"TZ": "UTC"})
    assert "UTC" in r.valor.stdout


def test_timeout_mata_o_processo(ctx_script):
    fazer, ws = ctx_script
    with pytest.raises(ErroTimeout, match="efeito desconhecido"):
        _rodar(fazer(), argv=[sys.executable, "-c",
                              "import time; time.sleep(30)"],
               cwd=str(ws), timeout_s=0.5)


def test_deadline_do_no_limita_o_script(ctx_script):
    import time as _t
    fazer, ws = ctx_script
    with pytest.raises(ErroTimeout):
        _rodar(fazer(deadline=_t.monotonic() - 1),
               argv=[sys.executable, "-c", "pass"], cwd=str(ws))


def test_saida_grande_e_truncada(ctx_script):
    fazer, ws = ctx_script
    r = _rodar(fazer(), argv=[sys.executable, "-c",
                             "print('x' * 500000)"], cwd=str(ws), timeout_s=20)
    assert r.valor.truncado
    assert "truncado pelo NOMOS" in r.valor.stdout


def test_stdin_fechado(ctx_script):
    fazer, ws = ctx_script
    r = _rodar(fazer(), argv=[sys.executable, "-c",
                             "import sys; print(repr(sys.stdin.read()))"],
               cwd=str(ws))
    assert "''" in r.valor.stdout


def test_codigo_de_saida_nao_zero_nao_e_sucesso(ctx_script):
    fazer, ws = ctx_script
    r = _rodar(fazer(), argv=[sys.executable, "-c",
                             "import sys; sys.exit(3)"], cwd=str(ws))
    assert not r.ok and r.valor.codigo == 3


def test_timeout_invalido_e_recusado(ctx_script):
    fazer, ws = ctx_script
    for ruim in (0, -1, 10_000, "abc"):
        with pytest.raises(ErroInvalido):
            _rodar(fazer(), argv=[sys.executable, "-c", "pass"],
                   cwd=str(ws), timeout_s=ruim)


# ============================================== FASE 6 — ALERTAS

def test_evento_de_falha_e_estruturado():
    ev = EventoFalha(job_id="j", occurrence_id="j@t", capability="fs-ler",
                     error_class="Boom", attempt=2, effect_state="UNKNOWN")
    d = ev.dict()
    assert set(d) == {"job_id", "occurrence_id", "capability", "error_class",
                      "attempt", "timestamp", "effect_state", "detalhe"}


def test_evento_nao_carrega_payload_integral():
    """Detalhe é truncado — alerta que vaza segredo é incidente, não alerta."""
    ev = EventoFalha(job_id="j", occurrence_id="o", capability="c",
                     error_class="E", detalhe="S" * 5000)
    assert len(ev.dict()["detalhe"]) <= 300


def test_sinks_satisfazem_o_protocolo(tmp_path):
    audit = AuditLog(tmp_path / "a.jsonl")
    for sink in (AuditAlertSink(audit), SinkDeTeste(),
                 SinkComposto(SinkDeTeste())):
        assert isinstance(sink, AlertSink)


def test_audit_sink_grava_na_trilha(tmp_path):
    import json
    audit = AuditLog(tmp_path / "logs" / "a.jsonl")
    AuditAlertSink(audit).emitir(EventoFalha(
        job_id="j", occurrence_id="o", capability="fs-ler", error_class="Boom"))
    eventos = [json.loads(x).get("event")
               for x in (tmp_path / "logs" / "a.jsonl").read_text().splitlines() if x.strip()]
    assert "scheduler.ocorrencia.falhou" in eventos


def test_falha_de_execucao_emite_evento(tmp_path):
    ef = _Efeito(falhar=True)
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0)
    sink = SinkDeTeste()
    t = Ticker(s, SEM_AUTORIZACAO, alert_sink=sink, agora_fn=lambda: rel["t"],
               dormir=lambda _s: None)
    t.tick()
    assert len(sink.eventos) == 1
    ev = sink.eventos[0]
    assert ev.job_id == "j" and ev.capability == "fs-ler"
    assert ev.occurrence_id.startswith("j@")


def test_sink_quebrado_nao_derruba_os_outros():
    class _Quebrado:
        nome = "quebrado"

        def emitir(self, evento):
            raise RuntimeError("canal fora")

    bom = SinkDeTeste()
    composto = SinkComposto(_Quebrado(), bom)
    composto.emitir(EventoFalha(job_id="j", occurrence_id="o",
                                capability="c", error_class="E"))
    assert len(bom.eventos) == 1
    assert composto.falhas == [("quebrado", "RuntimeError")]


def test_alertas_nao_dependem_de_canal_externo():
    """Nenhum sink desta camada fala rede."""
    import ast
    import inspect

    import nomos.adapters.alertas as mod
    arvore = ast.parse(inspect.getsource(mod))
    importados = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            importados.add(no.module or "")
        elif isinstance(no, ast.Import):
            importados.update(a.name for a in no.names)
    for rede in ("socket", "http", "urllib", "requests", "smtplib", "ssl"):
        assert not any(rede in m for m in importados), f"alertas importa {rede}"


# ============================================== caminho de produção do script

def test_script_registrado_exige_raizes_e_executaveis(tmp_path):
    from nomos.adapters.wiring import registrar_script
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades
    home = tmp_path / "h"
    home.mkdir()
    reg = RegistroCapacidades(policy=PolicyEngine(home / "policy.json"),
                              approver=lambda d: True)
    with pytest.raises(ValueError, match="raizes"):
        registrar_script(reg, raizes=(), executaveis=[sys.executable])
    with pytest.raises(ValueError, match="executaveis|allowlist"):
        registrar_script(reg, raizes=(str(home),), executaveis=())


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_script_alcancavel_pelo_runtime_governado(tmp_path):
    """Caminho de PRODUÇÃO: efeito real atravessando registry→PDP→PEP→adapter."""
    import json

    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    from nomos.runtime.governado import RuntimeGovernado
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, lambda d: True, adapters=True,
                          caminhos=(str(ws),), executaveis=(sys.executable,))
    assert "script-rodar" in rt.capacidades_adapter
    res = rt.rodar("rodar script", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": [sys.executable, "-c", "print('governado')"],
                   "cwd": str(ws)}}])
    assert res.ok, res.resumo()
    assert "governado" in res.missao.nos["s"].resultado["stdout"]
    ev = [json.loads(x).get("event")
          for x in (home / "logs" / "audit.jsonl").read_text().splitlines() if x.strip()]
    assert "pdp.decisao" in ev and "pep.aplicacao" in ev and "script.fim" in ev


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_allowlist_de_executaveis_nao_vem_do_plano(tmp_path):
    """Um passo hostil não amplia a allowlist fixada no registro."""
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    from nomos.runtime.governado import RuntimeGovernado
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, lambda d: True, adapters=True,
                          caminhos=(str(ws),), executaveis=(sys.executable,))
    res = rt.rodar("escalar", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": ["/bin/echo", "oi"], "cwd": str(ws),
                   "executaveis": ["/bin/echo"]}}])   # tenta ampliar
    assert not res.ok
    assert "allowlist" in res.missao.nos["s"].detalhe


# ====================== correções vindas do censo independente da FASE 8

def test_ticker_sem_autorizador_e_fail_closed(tmp_path):
    """D1 do censo: `autorizador=None` era default e executava com credencial
    None. Invariante que se desliga por omissão não é invariante."""
    ef = _Efeito()
    s, rel = _sched(tmp_path, ef)
    with pytest.raises(ValueError, match="autorizador"):
        Ticker(s, None, agora_fn=lambda: rel["t"])
    with pytest.raises(TypeError):
        Ticker(s)                       # nem posicionalmente é opcional


def test_rodar_sem_autoridade_exige_dizer_em_voz_alta(tmp_path):
    """A escolha de rodar sem autoridade precisa ser NOMEADA, não esquecida."""
    ef = _Efeito()
    s, rel = _sched(tmp_path, ef)
    s.criar("j", "suj", "fs-ler", primeiro_em=T0)
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"],
               dormir=lambda _s: None)
    assert t.tick().executadas == 1
    assert t.autorizador is None


def test_catchup_skip_roda_a_MAIS_RECENTE_nao_uma_velha(tmp_path):
    """D3 do censo: com downtime > catchup_max*intervalo, SKIP executava uma
    ocorrência VELHA. Meu teste antigo só conferia len(chamadas)==1 e não pegava.

    Agora assevera QUAL ocorrência rodou.
    """
    ef = _Efeito()
    rel = {"t": T0}
    s, _ = _sched(tmp_path, ef, rel)
    s.criar("j", "suj", "fs-ler", intervalo_s=300, primeiro_em=T0)
    rel["t"] = T0 + timedelta(hours=5)          # 60 ocorrências perdidas
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: rel["t"],
               dormir=lambda _s: None, catchup=CatchUp.SKIP, catchup_max=10)
    t.tick()
    assert len(ef.chamadas) == 1
    executada = datetime.fromisoformat(ef.chamadas[0].split("@", 1)[1])
    # a mais recente que venceu está a menos de um intervalo de agora
    assert rel["t"] - executada < timedelta(seconds=300), (
        f"SKIP executou ocorrência velha: {executada}")


def test_agenda_corrompida_falha_fechada(tmp_path):
    """D5 do censo: agenda ilegível virava None e o job CRON voltava como
    ONE_SHOT — parava de recorrer EM SILÊNCIO."""
    import sqlite3

    from nomos.adapters.contrato import ErroConflito
    db = tmp_path / "j.db"
    s = Scheduler(ArmazemJobs(db), executor=_Efeito(), agora_fn=lambda: T0)
    s.criar("j", "suj", "fs-ler",
            schedule=ScheduleSpec(kind=TipoAgenda.CRON, expression="0 9 * * *"))
    with sqlite3.connect(db) as c:
        c.execute("UPDATE jobs SET schedule='{corrompido' WHERE job_id='j'")
    s2 = Scheduler(ArmazemJobs(db), executor=_Efeito(), agora_fn=lambda: T0)
    with pytest.raises(ErroConflito, match="ilegível"):
        s2.status("j")


def test_scheduler_alerta_sem_depender_do_ticker(tmp_path):
    """D4 do censo: o alerta vivia só no ticker, então falha por
    `executar_job()` era 100% muda."""
    sink = SinkDeTeste()
    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=_Efeito(falhar=True),
                  agora_fn=lambda: T0, alert_sink=sink)
    d = s.criar("j", "suj", "fs-ler", primeiro_em=T0)
    s.executar_job(d, T0)                       # caminho SEM ticker
    assert len(sink.eventos) == 1
    assert sink.eventos[0].job_id == "j"
