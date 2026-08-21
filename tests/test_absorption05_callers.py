"""ABSORPTION-05 — os componentes órfãos ganharam caller de produção.

A ABSORPTION-04 construiu `Scheduler`, `Ticker` e `script-rodar` e o censo
independente encontrou **zero callers em `src/`**. Estes testes provam o fio:
não que a classe existe, mas que existe caminho de produção, que ele atravessa
registry→PDP→PEP→boundary→adapter, e que a trilha registra cada elo.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from nomos.adapters.agenda import ScheduleSpec, TipoAgenda
from nomos.adapters.scheduler import JobState
from nomos.adapters.ticker import SEM_AUTORIZACAO, CatchUp, Ticker
from nomos.adapters.wiring import validar_executaveis
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.agendador import (
    AgendadorGovernado, ConfigAgendador, caminho_do_armazem,
)

UTC = timezone.utc
T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


def _sim(_d):
    return True


def _nao(_d):
    return False


@pytest.fixture()
def amb(tmp_path):
    """(ctx, ws, relogio) — home e workspace separados, como em produção."""
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home,
           "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    return ctx, ws, {"t": T0}


def _agendador(amb, executaveis=(), catchup=CatchUp.RUN_ONCE):
    ctx, ws, rel = amb
    return AgendadorGovernado(
        ctx, _sim,
        ConfigAgendador(raizes=(str(ws),), executaveis=tuple(executaveis),
                        catchup=catchup),
        agora_fn=lambda: rel["t"])


def _eventos(ctx):
    p = ctx["home"] / "logs" / "audit.jsonl"
    return [json.loads(x).get("event")
            for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


# ==================================================== FASE 2 — caller scheduler

def test_registrar_scheduler_tem_caller_de_producao(amb):
    """O censo da 04 achou ZERO callers em src/. Agora há um."""
    import inspect

    import nomos.runtime.agendador as ag_mod
    fonte = inspect.getsource(ag_mod)
    assert "registrar_scheduler(" in fonte
    ag = _agendador(amb)
    nomes = ag.preparar()
    assert set(nomes) == {"sched-criar", "sched-listar", "sched-status",
                          "sched-habilitar", "sched-desabilitar",
                          "sched-cancelar", "sched-apagar"}


def test_registro_e_o_MESMO_que_o_planner_consulta(amb):
    """Sem registry paralelo: o planner enxerga as capacidades do scheduler."""
    ctx, ws, rel = amb
    ag = _agendador(amb)
    ag.preparar()
    rt = ag._runtime()
    from nomos.adapters.wiring import registrar_scheduler
    registrar_scheduler(rt.registro, ag.scheduler)
    plano = rt.planejar("agendar", passos=[
        {"id": "l", "ferramenta": "sched-listar", "params": {}}])
    assert plano.ok, plano.motivo
    assert plano.passos[0].categoria is not None


def test_registrar_e_ato_A5_auditado(amb):
    ctx, _ws, _rel = amb
    _agendador(amb).preparar()
    ev = _eventos(ctx)
    assert "registro.capacidade.registrada" in ev
    assert "agendador.preparado" in ev


def test_sem_aprovador_o_agendador_recusa(amb):
    from nomos.runtime.governado import ErroRuntime
    ctx, ws, _rel = amb
    with pytest.raises(ErroRuntime, match="aprovador"):
        AgendadorGovernado(ctx, None, ConfigAgendador(raizes=(str(ws),)))


def test_gate_nega_registro_sem_aprovacao(amb):
    """Aprovador que nega ⇒ nada é registrado (A5 fail-closed)."""
    from nomos.orquestracao.registro import ErroRegistro
    ctx, ws, rel = amb
    ag = AgendadorGovernado(ctx, _nao, ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: rel["t"])
    with pytest.raises(ErroRegistro):
        ag.preparar()


def test_armazem_fica_em_lugar_previsivel(amb):
    ctx, _ws, _rel = amb
    ag = _agendador(amb)
    assert ag.armazem.caminho == caminho_do_armazem(ctx["home"])
    assert ag.armazem.caminho.parent.name == "scheduler"


def test_nao_existe_registry_policy_ou_executor_paralelo():
    """Proíbe scheduler_registry / scheduler_policy / scheduler_executor."""
    import pathlib
    import re
    raiz = pathlib.Path(__file__).resolve().parents[1] / "src" / "nomos"
    proibidos = ("scheduler_registry", "scheduler_policy", "scheduler_executor")
    padrao = re.compile(
        r"^\s*(?:def|class)\s+(%s)\b|^\s*(%s)\s*=" % ("|".join(proibidos),
                                                      "|".join(proibidos)),
        re.MULTILINE)
    achados = [str(a.relative_to(raiz)) for a in raiz.rglob("*.py")
               if padrao.search(a.read_text(encoding="utf-8"))]
    assert not achados, f"mecanismo paralelo de scheduler: {achados}"


# ==================================================== FASE 3 — caller ticker

def test_ticker_tem_caller_de_producao():
    """`Ticker` saiu de 'classe testável sem chamador'."""
    import inspect

    from nomos import cli
    assert "Ticker" in inspect.getsource(
        __import__("nomos.runtime.agendador", fromlist=["x"]))
    assert "cmd_scheduler" in inspect.getsource(cli)
    assert "ag.ticker()" in inspect.getsource(cli.cmd_scheduler)


def test_ticker_do_agendador_nunca_tem_autorizador_none(amb):
    ag = _agendador(amb)
    ag.preparar()
    t = ag.ticker()
    assert t.autorizador is not None
    assert t.autorizador == ag.autorizador


def test_ticker_exige_preparar_antes(amb):
    ag = _agendador(amb)
    with pytest.raises(RuntimeError, match="preparar"):
        ag.ticker()


def test_ocorrencia_executada_pelo_ticker_com_traco_governado(amb):
    """A prova central: job → ticker → PDP → PEP → adapter → efeito → audit."""
    ctx, ws, rel = amb
    ag = _agendador(amb)
    ag.preparar()
    alvo = ws / "criado-pelo-job.txt"
    ag.scheduler.criar("j", "runtime-governado", "fs-escrever",
                       argumentos={"alvo": str(alvo), "conteudo": "efeito de job"},
                       primeiro_em=T0)
    r = ag.ticker(dormir=lambda _s: None).tick()
    assert r.executadas == 1, r
    assert alvo.read_text() == "efeito de job"          # EFEITO REAL
    ev = _eventos(ctx)
    # A cadeia REAL de uma capacidade DINÂMICA. `agente.ferramenta.usada` NÃO
    # aparece aqui de propósito: aquele evento é do `AgentToolBoundary`, que
    # governa as 8 ferramentas NATIVAS. Para capacidade dinâmica o papel de
    # fronteira é dividido entre o PDP (a capacidade está na autorização?),
    # o PEP (há ALLOW?) e `Adapter._coerente` (o pedido corresponde ao contexto
    # autorizado?). Asseverar o evento errado esconderia essa diferença.
    for elo in ("pdp.decisao", "pep.aplicacao", "fs.escrever",
                "scheduler.execucao.fim"):
        assert elo in ev, f"elo ausente na trilha: {elo}"
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao")
    assert ev.index("pep.aplicacao") < ev.index("fs.escrever")


def test_ciclo_completo_de_job_pelo_agendador(amb):
    """criar → listar → desabilitar → habilitar → cancelar."""
    ctx, ws, rel = amb
    ag = _agendador(amb)
    ag.preparar()
    s = ag.scheduler
    s.criar("j", "suj", "fs-listar", argumentos={"alvo": str(ws)},
            primeiro_em=T0)
    assert [d.job_id for d in s.listar()] == ["j"]
    assert s.desabilitar("j").estado is JobState.DISABLED
    assert s.devidos(T0) == []                        # desabilitado não é devido
    assert s.habilitar("j").estado is JobState.SCHEDULED
    assert s.cancelar("j").estado is JobState.CANCELLED
    assert s.devidos(T0) == []


def test_job_desabilitado_nao_produz_efeito_pelo_ticker(amb):
    ctx, ws, rel = amb
    ag = _agendador(amb)
    ag.preparar()
    alvo = ws / "nao-deve-existir.txt"
    ag.scheduler.criar("j", "suj", "fs-escrever",
                       argumentos={"alvo": str(alvo), "conteudo": "x"},
                       primeiro_em=T0)
    ag.scheduler.desabilitar("j")
    assert ag.ticker(dormir=lambda _s: None).tick().executadas == 0
    assert not alvo.exists()


def test_cron_pelo_agendador_reagenda_no_fuso(amb):
    ctx, ws, rel = amb
    ag = _agendador(amb)
    ag.preparar()
    ag.scheduler.criar(
        "c", "suj", "fs-listar", argumentos={"alvo": str(ws)},
        schedule=ScheduleSpec(kind=TipoAgenda.CRON, expression="0 9 * * *",
                              timezone="America/Sao_Paulo"),
        primeiro_em=T0)
    ag.ticker(dormir=lambda _s: None).tick()
    assert ag.scheduler.status("c").proximo_em == datetime(
        2026, 8, 11, 12, 0, tzinfo=UTC)               # 09:00 em SP = 12:00 UTC


# ==================================================== FASE 4 — script

def test_validar_executaveis_canonicaliza_e_deduplica(tmp_path):
    reais = validar_executaveis([sys.executable, sys.executable])
    assert len(reais) == 1
    import os
    assert reais[0] == os.path.realpath(sys.executable)


@pytest.mark.parametrize("ruim", ["", "   ", "/nao/existe/bin", "/tmp"])
def test_validar_executaveis_recusa_invalidos(ruim):
    with pytest.raises(ValueError):
        validar_executaveis([ruim])


def test_validar_executaveis_recusa_nao_executavel(tmp_path):
    arq = tmp_path / "texto.txt"
    arq.write_text("nao sou binario")
    with pytest.raises(ValueError, match="execução"):
        validar_executaveis([str(arq)])


def test_validar_executaveis_recusa_shell(tmp_path):
    import shutil
    sh = shutil.which("sh")
    if sh:
        with pytest.raises(ValueError, match="shell"):
            validar_executaveis([sh])


def test_validar_executaveis_resolve_symlink(tmp_path):
    """Guarda o caminho REAL — troca de symlink depois não muda o autorizado."""
    import os
    link = tmp_path / "python-link"
    link.symlink_to(sys.executable)
    (real,) = validar_executaveis([str(link)])
    assert real == os.path.realpath(sys.executable)
    assert real != str(link)


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_script_registrado_pelo_runtime_com_executavel(amb):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),),
                          executaveis=(sys.executable,))
    assert "script-rodar" in rt.capacidades_adapter


def test_script_nao_registra_sem_executavel(amb):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),))
    assert "script-rodar" not in rt.capacidades_adapter


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_script_efeito_real_pela_cadeia(amb):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),),
                          executaveis=(sys.executable,))
    res = rt.rodar("script", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": [sys.executable, "-c", "print('via caller')"],
                   "cwd": str(ws)}}])
    assert res.ok, res.resumo()
    assert "via caller" in res.missao.nos["s"].resultado["stdout"]
    ev = _eventos(ctx)
    assert "pdp.decisao" in ev and "pep.aplicacao" in ev and "script.fim" in ev


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_script_executavel_nao_permitido_e_negado(amb):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    import shutil
    outro = shutil.which("echo") or "/bin/echo"
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),),
                          executaveis=(sys.executable,))
    res = rt.rodar("proibido", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": [outro, "oi"], "cwd": str(ws)}}])
    assert not res.ok
    assert "allowlist" in res.missao.nos["s"].detalhe


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_script_cwd_fora_do_escopo_e_negado(amb, tmp_path):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),),
                          executaveis=(sys.executable,))
    res = rt.rodar("escapar", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": [sys.executable, "-c", "pass"], "cwd": str(tmp_path)}}])
    assert not res.ok


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_script_timeout_pela_cadeia(amb):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),),
                          executaveis=(sys.executable,))
    res = rt.rodar("demora", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": [sys.executable, "-c", "import time;time.sleep(20)"],
                   "cwd": str(ws), "timeout_s": 0.5}}])
    assert not res.ok
    assert "desconhecido" in res.missao.nos["s"].detalhe


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_script_saida_limitada_pela_cadeia(amb):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),),
                          executaveis=(sys.executable,))
    res = rt.rodar("grande", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": [sys.executable, "-c", "print('x'*500000)"],
                   "cwd": str(ws), "timeout_s": 20}}])
    assert res.ok
    assert res.missao.nos["s"].resultado["truncado"]


# ==================================================== FASE 10 — fail-closed

def test_ticker_sem_autorizador_continua_impossivel(amb):
    ag = _agendador(amb)
    ag.preparar()
    with pytest.raises(ValueError, match="autorizador"):
        Ticker(ag.scheduler, None)


def test_agendador_nao_executa_sem_credencial(amb):
    """O scheduler não tem caminho próprio até o adapter."""
    from nomos.runtime.governado import ErroRuntime
    ag = _agendador(amb)
    ag.preparar()
    d = ag.scheduler.criar("j", "suj", "fs-listar", primeiro_em=T0)
    with pytest.raises(ErroRuntime, match="sem autoridade"):
        ag._executar_ocorrencia(d, None, credencial=None)


def test_capacidade_removida_apos_criar_job_nega_a_ocorrencia(amb):
    """Job persistido referencia capability que sumiu ⇒ autorizador recusa."""
    ctx, ws, rel = amb
    ag = _agendador(amb)
    ag.preparar()
    d = ag.scheduler.criar("j", "suj", "capacidade-fantasma", primeiro_em=T0)
    assert ag.autorizador(d, None) is None
    assert "agendador.capacidade.sumiu" in _eventos(ctx)


def test_agenda_corrompida_continua_fail_closed(amb):
    import sqlite3

    from nomos.adapters.contrato import ErroConflito
    ag = _agendador(amb)
    ag.preparar()
    ag.scheduler.criar("j", "suj", "fs-listar",
                       schedule=ScheduleSpec(kind=TipoAgenda.CRON,
                                             expression="0 9 * * *"))
    with sqlite3.connect(ag.armazem.caminho) as c:
        c.execute("UPDATE jobs SET schedule='{corrompido' WHERE job_id='j'")
    with pytest.raises(ErroConflito, match="ilegível"):
        ag.scheduler.status("j")


def test_catchup_skip_do_agendador_roda_a_mais_recente(amb):
    ctx, ws, rel = amb
    ag = _agendador(amb, catchup=CatchUp.SKIP)
    ag.preparar()
    ag.scheduler.criar("j", "suj", "fs-listar", argumentos={"alvo": str(ws)},
                       intervalo_s=300, primeiro_em=T0)
    rel["t"] = T0 + timedelta(hours=5)
    ag.ticker(dormir=lambda _s: None).tick()
    executada = ag.scheduler.status("j")
    assert executada.proximo_em > rel["t"]


# ==================================================== FASE 11 — adversarial

@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_caller_nao_alcanca_adapter_bruto(amb):
    """Todo executor do agendador é PEP; nenhum callable cru exposto."""
    from nomos.pdp.pep import PontoDeAplicacao
    ctx, ws, _rel = amb
    ag = _agendador(amb, executaveis=(sys.executable,))
    ag.preparar()
    rt = ag._runtime()
    for nome, pep in rt.executores_protegidos.items():
        assert isinstance(pep, PontoDeAplicacao), nome


def test_capacidade_dinamica_nao_sobrescreve_nativa(amb):
    """Anti-hijack. Mas o guard que atua depende do NOME.

    Achado desta missão: das 8 nativas, só `doutor` não tem underscore, e
    `NOME_RE` (^[a-z][a-z0-9-]{1,31}$) rejeita underscore ANTES da checagem de
    sombreamento. Ou seja, para 7 das 8 quem protege é a validação de nome; a
    checagem "sombrear nativa é proibido" só é alcançável por `doutor`.
    A proteção existe nos dois casos — mas o motivo da recusa é diferente, e
    dizer isso é mais útil do que fingir um caminho só.
    """
    from nomos.agents.manifest import FERRAMENTAS, NOME_RE
    from nomos.orquestracao.registro import ErroRegistro
    from nomos.kernel.policy import Category
    ag = _agendador(amb)
    ag.preparar()
    rt = ag._runtime()

    # caminho A: nome com underscore ⇒ barrado por NOME_RE
    with pytest.raises(ErroRegistro, match="nome inválido"):
        rt.registro.registrar("arquivo_ler", Category.READ_LOCAL,
                              lambda **k: "x", origem="mal")

    # caminho B: `doutor` passa NOME_RE ⇒ chega à checagem de sombreamento
    assert NOME_RE.match("doutor")
    with pytest.raises(ErroRegistro, match="sombrear"):
        rt.registro.registrar("doutor", Category.READ_LOCAL,
                              lambda **k: "x", origem="mal")

    # e nenhuma das 8 pode ser registrada, por um motivo ou pelo outro
    for nativa in FERRAMENTAS:
        with pytest.raises(ErroRegistro):
            rt.registro.registrar(nativa, Category.READ_LOCAL,
                                  lambda **k: "x", origem="mal")


def test_id_de_capacidade_colidido_e_recusado(amb):
    from nomos.kernel.policy import Category
    from nomos.orquestracao.registro import ErroRegistro
    ag = _agendador(amb)
    ag.preparar()
    rt = ag._runtime()
    from nomos.adapters.wiring import registrar_scheduler
    registrar_scheduler(rt.registro, ag.scheduler)
    with pytest.raises(ErroRegistro, match="já registrada"):
        rt.registro.registrar("sched-listar", Category.READ_LOCAL,
                              lambda **k: "x", origem="colisao")


@pytest.mark.skip(reason=
    "`script-rodar` genérico foi RETIRADO do runtime de produção "
    "(G1: argv[1:] escapava do escopo e permitia sobrescrever "
    "policy.json). O adapter e estes testes ficam preservados para o "
    "executor tipado por capacidade que vier depois; a integração com "
    "o runtime não existe mais.")
def test_executavel_trocado_depois_do_registro_nao_e_aceito(amb, tmp_path):
    """A allowlist guarda o realpath; trocar o symlink depois não autoriza."""
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    link = tmp_path / "prog"
    link.symlink_to(sys.executable)
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(ws),),
                          executaveis=(str(link),))
    import shutil
    outro = shutil.which("echo") or "/bin/echo"
    link.unlink()
    link.symlink_to(outro)                      # troca depois do registro
    res = rt.rodar("troca", passos=[{
        "id": "s", "ferramenta": "script-rodar",
        "params": {"argv": [str(link), "oi"], "cwd": str(ws)}}])
    assert not res.ok                           # o real de agora não é o autorizado


def test_registro_parcial_apos_erro_nao_deixa_meia_capacidade(amb):
    """Se um registro falha, o que já entrou continua íntegro e identificável."""
    ctx, ws, rel = amb
    ag = AgendadorGovernado(ctx, _nao, ConfigAgendador(raizes=(str(ws),)),
                            agora_fn=lambda: rel["t"])
    from nomos.orquestracao.registro import ErroRegistro
    with pytest.raises(ErroRegistro):
        ag.preparar()
    assert ag.capacidades == []
    assert not ag._preparado


def test_cli_scheduler_exige_raiz(tmp_path, monkeypatch, capsys):
    from nomos import cli
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path / "h"))
    assert cli.main(["scheduler", "rodar"]) == cli.EXIT_ERROR
    assert "--raiz" in capsys.readouterr().err


def test_cli_orquestrar_scheduler_exige_raiz(tmp_path, monkeypatch, capsys):
    from nomos import cli
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path / "h"))
    assert cli.main(["orquestrar", "x", "--scheduler"]) == cli.EXIT_ERROR
    assert "--raiz" in capsys.readouterr().err


def test_ticker_sem_autorizacao_nao_e_usado_em_producao():
    """`SEM_AUTORIZACAO` existe só para teste — não pode aparecer no CLI."""
    import inspect

    from nomos import cli
    from nomos.runtime import agendador
    assert "SEM_AUTORIZACAO" not in inspect.getsource(cli)
    assert "SEM_AUTORIZACAO" not in inspect.getsource(agendador)
    assert SEM_AUTORIZACAO is not None          # existe, mas confinado a teste


# ============ correções vindas do censo independente final (FASE 14)

def test_sched_capacidades_estao_no_mapa_PEP(amb):
    """ACHADO CENTRAL do censo: registrar o scheduler DEPOIS de montar o
    runtime deixava sched-* fora do mapa protegido e fora da autorização, e a
    capacidade caía no fallback do Orquestrador direto para a ponte CRUA —
    sem PDP, sem PEP, sem escopo."""
    from nomos.pdp.pep import PontoDeAplicacao
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    ag = _agendador(amb)
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          scheduler=ag.scheduler)
    for nome in ("sched-criar", "sched-listar", "sched-cancelar"):
        assert nome in rt.executores, f"{nome} fora do mapa PEP"
        assert isinstance(rt.executores_protegidos[nome], PontoDeAplicacao)
        assert nome in rt.autorizacao.capacidades, f"{nome} fora da autorização"


def test_sched_criar_atravessa_pdp_e_pep(amb):
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    ag = _agendador(amb)
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          scheduler=ag.scheduler)
    res = rt.rodar("criar", passos=[{
        "id": "c", "ferramenta": "sched-criar",
        "params": {"job_id": "x", "capacidade": "fs-listar",
                   "alvo_job": str(ws)}}])
    assert res.ok, res.resumo()
    ev = _eventos(ctx)
    assert "pdp.decisao" in ev and "pep.aplicacao" in ev
    assert "scheduler.job.criado" in ev
    assert ev.index("pep.aplicacao") < ev.index("scheduler.job.criado")


def test_cron_e_alcancavel_pelo_caller_governado(amb):
    """ACHADO: a ponte de sched-criar ignorava a agenda, então um job criado
    pela capacidade governada virava ONE_SHOT em silêncio — o motor de cron
    ficava inalcançável por caller de produção."""
    from nomos.adapters.agenda import TipoAgenda
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws, _rel = amb
    ag = _agendador(amb)
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          scheduler=ag.scheduler)
    res = rt.rodar("cron", passos=[{
        "id": "c", "ferramenta": "sched-criar",
        "params": {"job_id": "jc", "capacidade": "fs-listar",
                   "alvo_job": str(ws), "cron": "0 9 * * 1-5",
                   "tz": "America/Sao_Paulo"}}])
    assert res.ok, res.resumo()
    d = ag.scheduler.status("jc")
    assert d.agenda().kind is TipoAgenda.CRON
    assert d.agenda().expression == "0 9 * * 1-5"
    assert d.agenda().timezone == "America/Sao_Paulo"
    assert d.recorrente()


def test_intervalo_zero_e_recusado_nao_corrigido(tmp_path, monkeypatch, capsys):
    """`--intervalo 0` virava 1.0 em silêncio (0.0 é falsy)."""
    from nomos import cli
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path / "h"))
    rc = cli.main(["scheduler", "rodar", "--raiz", str(tmp_path), "--intervalo", "0"])
    assert rc == cli.EXIT_ERROR
    assert "intervalo" in capsys.readouterr().err


def test_executavel_sem_adapters_e_recusado(tmp_path, monkeypatch, capsys):
    """`--executavel` é negado NA PORTA com a verdade do selamento (FIX-03).

    Contrato antigo: exigia `--adapters` e, satisfeito isso, deixava o
    usuário atravessar o CLI para receber um `ErroRuntime` tardio. Contrato
    novo: EXIT_DENIED imediato, mensagem diz que script-rodar está SELADO.
    """
    from nomos import cli
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path / "h"))
    rc = cli.main(["orquestrar", "x", "--raiz", str(tmp_path),
                   "--executavel", sys.executable])
    assert rc == cli.EXIT_DENIED
    assert "SELADO" in capsys.readouterr().err
