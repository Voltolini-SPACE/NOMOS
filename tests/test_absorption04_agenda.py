"""ABSORPTION-04 / FASES 1-2 — cron real e timezone aplicada.

O censo da 03 foi específico: "intervalo em segundos NÃO é cron" e "timezone
armazenada não é timezone aplicada". Estes testes provam os dois pelo
comportamento — próximo disparo correto no fuso certo, inclusive nas duas
transições de DST.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from nomos.adapters.agenda import (
    ErroCron, ScheduleSpec, TipoAgenda, compilar_cron, proximo_disparo_cron,
    resolver_tz,
)
from nomos.adapters.contrato import ErroInvalido

UTC = timezone.utc
BASE = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)          # segunda-feira


def _prox(expr: str, base=BASE, tz="UTC") -> datetime:
    return proximo_disparo_cron(compilar_cron(expr), base, resolver_tz(tz))


# ------------------------------------------------------- sintaxe exigida

def test_sintaxe_minima_exigida_pela_missao():
    assert _prox("* * * * *") == datetime(2026, 8, 10, 12, 31, tzinfo=UTC)
    assert _prox("*/5 * * * *") == datetime(2026, 8, 10, 12, 35, tzinfo=UTC)
    assert _prox("0 * * * *") == datetime(2026, 8, 10, 13, 0, tzinfo=UTC)
    assert _prox("0 9 * * 1-5") == datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    assert _prox("0 0 1 * *") == datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def test_listas_faixas_passos_e_nomes():
    assert _prox("30 8 1,15 * *") == datetime(2026, 8, 15, 8, 30, tzinfo=UTC)
    assert _prox("0 9 * * mon-fri") == datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    assert _prox("0 0 1 jan *") == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)
    assert _prox("0 0-6/2 * * *") == datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    assert _prox("@daily") == datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    assert _prox("@hourly") == datetime(2026, 8, 10, 13, 0, tzinfo=UTC)


def test_domingo_aceita_0_e_7():
    a = compilar_cron("0 0 * * 0")
    b = compilar_cron("0 0 * * 7")
    assert a.dias_semana == b.dias_semana == frozenset({0})


def test_semantica_or_entre_dom_e_dow():
    """Regra POSIX: com AMBOS restritos vale OR. É o detalhe que quase toda
    implementação caseira erra — e um AND aqui pularia disparos legítimos."""
    expr = compilar_cron("0 0 13 * fri")          # dia 13 OU sexta-feira
    assert expr.dom_restrito and expr.dow_restrito
    # 2026-08-13 é quinta: entra pelo DIA DO MÊS
    assert expr.casa(datetime(2026, 8, 13, 0, 0))
    # 2026-08-14 é sexta: entra pelo DIA DA SEMANA
    assert expr.casa(datetime(2026, 8, 14, 0, 0))
    # 2026-08-12 é quarta e não é dia 13: não entra
    assert not expr.casa(datetime(2026, 8, 12, 0, 0))


def test_and_quando_apenas_um_e_restrito():
    expr = compilar_cron("0 0 13 * *")
    assert expr.casa(datetime(2026, 8, 13, 0, 0))
    assert not expr.casa(datetime(2026, 8, 14, 0, 0))


# ------------------------------------------------------- inválidas

@pytest.mark.parametrize("ruim", [
    "", "   ", "* * * *", "* * * * * *", "60 * * * *", "* 24 * * *",
    "* * 0 * *", "* * 32 * *", "* * * 13 *", "* * * * 8",
    "abc * * * *", "*/0 * * * *", "5-1 * * * *", "*/x * * * *",
    "1,, * * * *", "* * * xyz *", "@nunca",
])
def test_expressao_invalida_falha_fechada(ruim):
    with pytest.raises(ErroCron):
        compilar_cron(ruim)


def test_expressao_invalida_nao_persiste_nem_arma(tmp_path):
    """Fail-closed de verdade: nada é gravado, nenhum job fica armado."""
    from nomos.adapters.scheduler import ArmazemJobs, Scheduler
    armazem = ArmazemJobs(tmp_path / "j.db")
    s = Scheduler(armazem, executor=lambda d, i: None, agora_fn=lambda: BASE)
    with pytest.raises(ErroCron):
        s.criar("j", "suj", "fs-ler",
                schedule=ScheduleSpec(kind=TipoAgenda.CRON, expression="60 * * * *"))
    assert s.listar() == []
    assert armazem.obter("j") is None


def test_expressao_que_nunca_dispara_e_recusada():
    """30 de fevereiro: termina com erro em vez de girar para sempre."""
    with pytest.raises(ErroCron, match="não dispara"):
        _prox("0 0 30 2 *")


def test_nunca_infere_cron_de_string_arbitraria():
    """`kind` é explícito — uma string de cron só é cron quando declarada."""
    with pytest.raises(ErroCron):
        ScheduleSpec(kind=TipoAgenda.CRON, expression="")
    umshot = ScheduleSpec(kind=TipoAgenda.ONE_SHOT, expression="0 9 * * *")
    assert umshot.proximo(BASE) is None          # a expressão é ignorada


# ------------------------------------------------------- timezone aplicada

def test_timezone_muda_o_instante_real():
    """09:00 local em fusos diferentes = instantes UTC diferentes."""
    assert _prox("0 9 * * *", tz="UTC") == datetime(2026, 8, 11, 9, 0, tzinfo=UTC)
    # São Paulo em agosto: UTC-3
    assert _prox("0 9 * * *", tz="America/Sao_Paulo") == datetime(
        2026, 8, 11, 12, 0, tzinfo=UTC)
    # Madri em agosto: UTC+2 (horário de verão)
    assert _prox("0 9 * * *", tz="Europe/Madrid") == datetime(
        2026, 8, 11, 7, 0, tzinfo=UTC)


def test_timezone_desconhecida_e_negada():
    for ruim in ("Marte/Olympus", "GMT-3", "", "   ", "america/sao paulo"):
        with pytest.raises(ErroInvalido):
            resolver_tz(ruim)


def test_timezone_invalida_no_schedulespec():
    with pytest.raises(ErroInvalido):
        ScheduleSpec(kind=TipoAgenda.CRON, expression="0 9 * * *",
                     timezone="Nao/Existe")


def test_dst_primavera_horario_inexistente():
    """Madri 2026-03-29: 02:00→03:00. Um job às 02:30 não existe nesse dia.

    O disparo tem de cair no primeiro instante REAL depois da lacuna, não
    sumir e não duplicar.
    """
    madri = "Europe/Madrid"
    antes = datetime(2026, 3, 29, 0, 0, tzinfo=ZoneInfo(madri)).astimezone(UTC)
    disparo = _prox("30 2 * * *", base=antes, tz=madri)
    local = disparo.astimezone(ZoneInfo(madri))
    # 02:30 não existe em 29/03; o próximo 02:30 real é no dia seguinte
    assert (local.hour, local.minute) == (2, 30)
    assert local.day == 30


def test_dst_outono_horario_ambiguo_dispara_uma_vez():
    """Madri 2026-10-25: 03:00→02:00. 02:30 acontece DUAS vezes.

    Usamos a primeira (`fold=0`) para o job rodar uma vez só.
    """
    madri = "Europe/Madrid"
    antes = datetime(2026, 10, 25, 0, 0, tzinfo=ZoneInfo(madri)).astimezone(UTC)
    d1 = _prox("30 2 * * *", base=antes, tz=madri)
    local = d1.astimezone(ZoneInfo(madri))
    assert (local.hour, local.minute) == (2, 30)
    assert local.day == 25
    # o próximo é no dia seguinte, não a segunda passagem do mesmo 02:30
    d2 = _prox("30 2 * * *", base=d1, tz=madri)
    assert d2.astimezone(ZoneInfo(madri)).day == 26


def test_sao_paulo_sem_dst_desde_2019():
    """Brasil não tem mais horário de verão — offset estável o ano todo."""
    sp = "America/Sao_Paulo"
    verao = _prox("0 9 * * *", base=datetime(2026, 1, 5, 0, 0, tzinfo=UTC), tz=sp)
    inverno = _prox("0 9 * * *", base=datetime(2026, 7, 5, 0, 0, tzinfo=UTC), tz=sp)
    assert verao.hour == inverno.hour == 12


# ------------------------------------------------------- viradas

def test_virada_de_dia_mes_e_ano():
    assert _prox("0 0 * * *", base=datetime(2026, 8, 10, 23, 59, tzinfo=UTC)) == \
        datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    assert _prox("0 0 1 * *", base=datetime(2026, 8, 31, 23, 59, tzinfo=UTC)) == \
        datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    assert _prox("0 0 1 1 *", base=datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == \
        datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


def test_ano_bissexto():
    assert _prox("0 0 29 2 *", base=datetime(2027, 3, 1, tzinfo=UTC)) == \
        datetime(2028, 2, 29, 0, 0, tzinfo=UTC)


def test_multiplas_execucoes_consecutivas():
    """Encadear 5 disparos de */15 não deriva nem repete."""
    atual = BASE
    vistos = []
    for _ in range(5):
        atual = _prox("*/15 * * * *", base=atual)
        vistos.append(atual)
    assert vistos == [
        datetime(2026, 8, 10, 12, 45, tzinfo=UTC),
        datetime(2026, 8, 10, 13, 0, tzinfo=UTC),
        datetime(2026, 8, 10, 13, 15, tzinfo=UTC),
        datetime(2026, 8, 10, 13, 30, tzinfo=UTC),
        datetime(2026, 8, 10, 13, 45, tzinfo=UTC)]


def test_disparo_e_estritamente_posterior():
    exato = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    assert _prox("0 12 * * *", base=exato) == datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


# ------------------------------------------------------- persistência

def test_schedulespec_roundtrip():
    original = ScheduleSpec(kind=TipoAgenda.CRON, expression="0 9 * * 1-5",
                            timezone="America/Sao_Paulo")
    assert ScheduleSpec.de_dict(original.dict()) == original


def test_cron_sobrevive_a_restart(tmp_path):
    """A agenda persiste e o próximo disparo continua correto no fuso."""
    from nomos.adapters.scheduler import ArmazemJobs, Scheduler
    db = tmp_path / "j.db"
    spec = ScheduleSpec(kind=TipoAgenda.CRON, expression="0 9 * * *",
                        timezone="America/Sao_Paulo")
    s1 = Scheduler(ArmazemJobs(db), executor=lambda d, i: None,
                   agora_fn=lambda: BASE)
    s1.criar("j", "suj", "fs-ler", schedule=spec)

    s2 = Scheduler(ArmazemJobs(db), executor=lambda d, i: None,
                   agora_fn=lambda: BASE)
    d = s2.status("j")
    assert d.schedule is not None
    assert d.schedule.kind is TipoAgenda.CRON
    assert d.schedule.expression == "0 9 * * *"
    assert d.schedule.timezone == "America/Sao_Paulo"
    assert d.recorrente()
    assert d.proximo_em == datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def test_intervalo_legado_continua_funcionando(tmp_path):
    """Compatibilidade: job gravado com `intervalo_s` segue válido."""
    from nomos.adapters.scheduler import ArmazemJobs, Scheduler
    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=lambda d, i: None,
                  agora_fn=lambda: BASE)
    d = s.criar("j", "suj", "fs-ler", intervalo_s=60)
    assert d.agenda().kind is TipoAgenda.INTERVAL
    assert d.recorrente()
    assert s.proximo_apos(d, BASE) == BASE + timedelta(seconds=60)
