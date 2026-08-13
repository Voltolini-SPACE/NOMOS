"""ABSORPTION-06 / ETAPAS 4-5 — cron de produção e catch-up pela cadeia real.

A 04 construiu o motor de cron. A 05 ligou o ticker. Esta etapa perguntou uma
coisa diferente: **um operador consegue agendar, pela CLI, um job CRON com
timezone, e ele chega inteiro do outro lado?** A resposta era não, por quatro
motivos independentes que só aparecem quando se percorre o caminho todo:

1. `AgendadorGovernado.preparar()` registrava as sete capacidades num
   `RuntimeGovernado` que descartava na linha seguinte. Anunciava o scheduler
   como operacional e nenhuma capacidade era alcançável.
2. `ScheduleSpec` só validava a timezone no ramo CRON: ONE_SHOT e INTERVAL
   aceitavam `Mars/Olympus` e persistiam.
3. `cron` e `intervalo_s` juntos gravavam um registro com duas agendas — cada
   leitor consultava um campo diferente.
4. Um job podia apontar para capacidade inexistente: ficava SCHEDULED, o
   operador lia "criado", e a morte só aparecia ocorrência a ocorrência.

Os quatro têm a mesma forma: aceitar em silêncio o que não vai funcionar.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from nomos.adapters.agenda import ScheduleSpec, TipoAgenda
from nomos.adapters.contrato import ErroInvalido
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador


def _sim(_d):
    return True


@pytest.fixture()
def ag(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    a = AgendadorGovernado(ctx, _sim, ConfigAgendador(raizes=(str(ws),)))
    a.preparar()
    a._ws = ws
    a._ctx = ctx
    return a


def _eventos(ctx):
    p = pathlib.Path(ctx["home"]) / "logs" / "audit.jsonl"
    return [json.loads(x).get("event")
            for x in p.read_text().splitlines() if x.strip()]


# ================================================= 1. capacidade alcançável

def test_preparar_confirma_alcancabilidade_em_vez_de_registrar_no_vazio(ag):
    """O bug: registrar num runtime descartado e anunciar sucesso."""
    for nome in ag.capacidades:
        assert nome.startswith("sched-")
    rt = ag._runtime()
    for nome in ag.capacidades:
        assert nome in rt.executores, f"{nome} anunciada mas inalcançável"
        assert nome in rt.autorizacao.capacidades


def test_preparar_recusa_se_capacidade_ficar_inalcancavel(ag, monkeypatch):
    """Anti-regressão: se o wiring voltar a vazar, `preparar()` RECUSA.

    Sem isto, a próxima refatoração que soltar `sched-*` do mapa protegido
    volta a anunciar sete capacidades mortas — silenciosamente, como antes.
    """
    class RuntimeVazado:
        capacidades_adapter = ["sched-criar"]
        executores: dict = {}                 # fora do mapa protegido
        autorizacao = type("A", (), {"capacidades": ()})()

    monkeypatch.setattr(ag, "_runtime", lambda: RuntimeVazado())
    with pytest.raises(RuntimeError, match="INALCANÇÁVEIS"):
        ag.preparar()


def test_preparar_recusa_scheduler_sem_nenhuma_capacidade(ag, monkeypatch):
    class RuntimeVazio:
        capacidades_adapter: list = []
        executores: dict = {}
        autorizacao = type("A", (), {"capacidades": ()})()

    monkeypatch.setattr(ag, "_runtime", lambda: RuntimeVazio())
    with pytest.raises(RuntimeError, match="nenhuma capacidade"):
        ag.preparar()


# ================================================= 2. timezone em TODO kind

@pytest.mark.parametrize("kind,extra", [
    (TipoAgenda.ONE_SHOT, {}),
    (TipoAgenda.INTERVAL, {"intervalo_s": 60}),
    (TipoAgenda.CRON, {"expression": "0 3 * * *"}),
])
def test_timezone_inexistente_recusada_em_todo_tipo_de_agenda(kind, extra):
    """Antes só CRON validava. INTERVAL não usa a tz para calcular o próximo
    disparo — e era por isso que a mentira sobrevivia calada no registro."""
    with pytest.raises(ErroInvalido, match="timezone desconhecida"):
        ScheduleSpec(kind=kind, timezone="Mars/Olympus", **extra)


@pytest.mark.parametrize("kind,extra", [
    (TipoAgenda.ONE_SHOT, {}),
    (TipoAgenda.INTERVAL, {"intervalo_s": 60}),
])
def test_timezone_valida_aceita_em_todo_tipo(kind, extra):
    s = ScheduleSpec(kind=kind, timezone="America/Sao_Paulo", **extra)
    assert s.timezone == "America/Sao_Paulo"


def test_tz_invalida_pela_cadeia_governada_nao_persiste(ag):
    ok, _, motivo = ag.operar("sched-criar", job_id="mars",
                              capacidade="fs-listar",
                              alvo_job=str(ag._ws), tz="Mars/Olympus")
    assert not ok and "timezone desconhecida" in motivo
    assert ag.armazem.obter("mars") is None, "job com tz falsa PERSISTIU"


# ================================================= 3. agenda ambígua

def test_cron_e_intervalo_juntos_sao_recusados(ag):
    ok, _, motivo = ag.operar("sched-criar", job_id="amb",
                              capacidade="fs-listar", alvo_job=str(ag._ws),
                              cron="0 3 * * *", intervalo_s=60)
    assert not ok and "ambígua" in motivo
    assert ag.armazem.obter("amb") is None


def test_cron_aceito_nao_carrega_intervalo_no_registro(ag):
    """Um registro com `kind=CRON` e `intervalo_s=60` responde coisas
    diferentes conforme o campo que o leitor escolher."""
    ok, _, _ = ag.operar("sched-criar", job_id="so-cron",
                         capacidade="fs-listar", alvo_job=str(ag._ws),
                         cron="0 3 * * *")
    assert ok
    d = ag.armazem.obter("so-cron")
    assert d.agenda().kind is TipoAgenda.CRON
    assert d.intervalo_s is None, "CRON gravou intervalo junto"


def test_intervalo_zero_e_recusado_e_nao_vira_one_shot(ag):
    """Zero é falsy — e era por isso que sumia.

    Testar `elif intervalo:` em vez de `is not None` fazia `intervalo_s=0`
    desaparecer no caminho: o operador pedia INTERVAL, recebia ONE_SHOT e
    nenhuma mensagem. Mesma família do `--intervalo 0` → 1.0 que o censo já
    tinha achado no ticker.
    """
    ok, _, motivo = ag.operar("sched-criar", job_id="zero",
                              capacidade="fs-listar", alvo_job=str(ag._ws),
                              intervalo_s=0)
    assert not ok, "intervalo_s=0 foi ACEITO — virou ONE_SHOT em silêncio"
    assert ag.armazem.obter("zero") is None
    # O MOTIVO é asseverado, não só a recusa. Com truthiness o pedido vira
    # ONE_SHOT e quem recusa é a validação genérica de `Scheduler.criar`, com
    # outra mensagem. Recusar pelo motivo errado ensina o operador a procurar
    # no lugar errado — e deixa a regressão passar por "também deu erro".
    # "INTERVAL" E o nome do campo. Asseverar só `intervalo_s` foi um
    # enfraquecimento que eu mesmo introduzi ao fechar o GATE C: a mensagem
    # do caminho ERRADO também contém `intervalo_s`, então o teste ficou
    # verde e perdeu os dentes — a mutação pegou.
    assert "INTERVAL" in motivo and "intervalo_s" in motivo, (
        f"recusado, mas não COMO INTERVAL inválido: {motivo!r} — o pedido "
        "virou ONE_SHOT e a recusa veio por acidente de outra camada")


def test_cron_com_intervalo_zero_tambem_e_ambiguo(ag):
    """`cron` + `intervalo_s=0` é pedido contraditório mesmo com zero falsy."""
    ok, _, motivo = ag.operar("sched-criar", job_id="amb0",
                              capacidade="fs-listar", alvo_job=str(ag._ws),
                              cron="0 3 * * *", intervalo_s=0)
    assert not ok and "ambígua" in motivo
    assert ag.armazem.obter("amb0") is None


# ================================================= 4. sem rebaixamento

def test_cron_permanece_cron_e_a_tz_e_aplicada(ag):
    """03:00 em America/Sao_Paulo (UTC-3) é 06:00 UTC. Se a tz fosse ignorada,
    o próximo disparo cairia às 03:00 UTC — meia-noite em São Paulo."""
    ok, _, _ = ag.operar("sched-criar", job_id="noturno",
                         capacidade="fs-listar", alvo_job=str(ag._ws),
                         cron="0 3 * * *", tz="America/Sao_Paulo")
    assert ok
    d = ag.armazem.obter("noturno")
    assert d.agenda().kind is TipoAgenda.CRON
    assert d.agenda().expression == "0 3 * * *"
    assert d.proximo_em.hour == 6 and d.proximo_em.minute == 0


def test_sem_agenda_o_job_e_one_shot_explicito(ag):
    ok, _, _ = ag.operar("sched-criar", job_id="unico",
                         capacidade="fs-listar", alvo_job=str(ag._ws))
    assert ok
    assert ag.armazem.obter("unico").agenda().kind is TipoAgenda.ONE_SHOT


# ================================================= 5. job que nunca rodaria

def test_capacidade_desconhecida_e_recusada_na_criacao(ag):
    ok, _, motivo = ag.operar("sched-criar", job_id="ghost",
                              capacidade="nao-existe", alvo_job=str(ag._ws))
    assert not ok and "capacidade desconhecida" in motivo
    assert ag.armazem.obter("ghost") is None, (
        "job morto persistiu anunciando-se SCHEDULED")


def test_job_nao_pode_agendar_a_propria_gestao_de_jobs(ag):
    """Scheduler que se opera no relógio é laço de controle sem operador."""
    ok, _, motivo = ag.operar("sched-criar", job_id="meta",
                              capacidade="sched-criar", alvo_job=str(ag._ws))
    assert not ok and "capacidade de scheduler" in motivo
    assert ag.armazem.obter("meta") is None


# ================================================= 6. a cadeia é a mesma

def test_operar_passa_por_pdp_e_pep_antes_do_efeito(ag):
    ok, _, _ = ag.operar("sched-criar", job_id="auditado",
                         capacidade="fs-listar", alvo_job=str(ag._ws))
    assert ok
    ev = _eventos(ag._ctx)
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao") < \
        ev.index("scheduler.job.criado")


def test_listar_devolve_o_registro_descrito_nao_id_opaco(ag):
    ag.operar("sched-criar", job_id="j1", capacidade="fs-listar",
              alvo_job=str(ag._ws), cron="0 3 * * *", tz="Europe/Madrid")
    ok, jobs, _ = ag.operar("sched-listar")
    assert ok and len(jobs) == 1
    j = jobs[0]
    # id opaco obrigava o chamador a ler o armazém cru para exibir qualquer
    # coisa — e ler cru foi o que manteve a CLI fora da cadeia
    for campo in ("job_id", "capacidade", "estado", "kind", "expression",
                  "tz", "intervalo_s", "proximo_em"):
        assert campo in j, f"listar não descreve '{campo}'"
    assert j["kind"] == "CRON" and j["tz"] == "Europe/Madrid"


def test_cli_nao_le_o_armazem_cru_para_listar():
    """Estrutural: `cmd_scheduler` não pode chamar `scheduler.listar()`.

    Verificado na AST, não por substring: esta própria docstring cita o nome
    do método, e um teste de substring reprovaria a explicação em vez do
    código — armadilha que já pegou três testes nesta série de missões.
    """
    fonte = pathlib.Path(
        __import__("nomos.cli", fromlist=["x"]).__file__).read_text()
    arvore = ast.parse(fonte)
    alvo = next(n for n in ast.walk(arvore)
                if isinstance(n, ast.FunctionDef) and n.name == "cmd_scheduler")
    cruas = []
    for no in ast.walk(alvo):
        if (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                and isinstance(no.func.value, ast.Attribute)
                and no.func.value.attr == "scheduler"):
            cruas.append(no.func.attr)
    assert not cruas, f"cmd_scheduler chama o adapter cru: {cruas}"


# ================================================= 7. catch-up (ETAPA 5)

def test_catchup_mapeia_as_tres_politicas():
    from nomos.adapters.ticker import CatchUp
    from nomos.cli import _catchup_valido
    assert _catchup_valido("skip") is CatchUp.SKIP
    assert _catchup_valido("once") is CatchUp.RUN_ONCE
    assert _catchup_valido("all") is CatchUp.RUN_ALL_BOUNDED
    assert _catchup_valido(None) is CatchUp.RUN_ONCE


def test_catchup_desconhecido_e_recusado_nao_vira_padrao():
    """Quem escreveu `--catch-up todas` receberia SKIP e descobriria pelas
    ocorrências que não rodaram. Recusa explícita."""
    from nomos.cli import _catchup_valido
    with pytest.raises(ValueError, match="catch-up inválido"):
        _catchup_valido("todas")


def test_catchup_escolhido_chega_ao_ticker(tmp_path):
    from nomos.adapters.ticker import CatchUp
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    a = AgendadorGovernado(ctx, _sim, ConfigAgendador(
        raizes=(str(ws),), catchup=CatchUp.RUN_ALL_BOUNDED, catchup_max=3))
    a.preparar()
    t = a.ticker(dormir=lambda _s: None)
    assert t.catchup is CatchUp.RUN_ALL_BOUNDED
    assert t.catchup_max == 3


def test_cli_expoe_catchup_no_subcomando_rodar():
    """Sem flag exposta, a política existia só no dataclass — inalcançável."""
    from nomos.cli import build_parser
    args = build_parser().parse_args(
        ["scheduler", "rodar", "--raiz", "/tmp", "--catch-up", "all",
         "--catch-up-max", "5"])
    assert args.catch_up == "all" and args.catch_up_max == 5


def test_cli_criar_com_intervalo_zero_recusa_e_nao_agenda(tmp_path, monkeypatch):
    """Exercita o MAPEAMENTO da CLI, não só o adapter.

    Os testes anteriores chamavam `operar()` direto e por isso não viam nada do
    que acontece entre `--intervalo-job 0` e o parâmetro que chega ao adapter.
    Era exatamente ali que o zero sumia: `elif args.intervalo_job:` descartava
    o valor, o adapter recebia um pedido sem agenda e devolvia um ONE_SHOT
    feliz. O defeito vivia no trecho que nenhum teste atravessava.
    """
    import nomos.cli as climod
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    monkeypatch.setattr(climod, "_approver_for", lambda _c, _a: _sim)
    args = climod.build_parser().parse_args(
        ["scheduler", "criar", "--raiz", str(ws), "--job-id", "zero",
         "--capacidade", "fs-listar", "--intervalo-job", "0"])
    rc = climod.cmd_scheduler(ctx, args)
    assert rc == climod.EXIT_DENIED, (
        f"--intervalo-job 0 devolveu {rc}: agendou algo em vez de recusar")

    from nomos.runtime.agendador import ArmazemJobs, caminho_do_armazem
    assert ArmazemJobs(caminho_do_armazem(home)).obter("zero") is None, (
        "job persistiu — provavelmente como ONE_SHOT silencioso")


def test_cli_criar_intervalo_valido_agenda_como_interval(tmp_path, monkeypatch):
    """Contraparte positiva: sem ela, o teste acima passaria com uma CLI que
    recusa TUDO."""
    import nomos.cli as climod
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    monkeypatch.setattr(climod, "_approver_for", lambda _c, _a: _sim)
    args = climod.build_parser().parse_args(
        ["scheduler", "criar", "--raiz", str(ws), "--job-id", "bom",
         "--capacidade", "fs-listar", "--intervalo-job", "300"])
    assert climod.cmd_scheduler(ctx, args) == climod.EXIT_OK

    from nomos.runtime.agendador import ArmazemJobs, caminho_do_armazem
    d = ArmazemJobs(caminho_do_armazem(home)).obter("bom")
    assert d is not None and d.agenda().kind is TipoAgenda.INTERVAL
    assert d.agenda().intervalo_s == 300


def test_cli_recusa_agenda_ambigua_antes_de_construir_nada():
    """`--cron` e `--intervalo-job` são mutuamente exclusivos no argparse: o
    operador descobre o conflito no ato, não pelo DENY do adapter."""
    from nomos.cli import build_parser
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["scheduler", "criar", "--raiz", "/tmp", "--job-id", "x",
             "--capacidade", "fs-listar", "--cron", "0 3 * * *",
             "--intervalo-job", "60"])
