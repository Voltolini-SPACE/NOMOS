"""ABSORPTION-03 / FASE 3 — scheduler governado: estados, dedup e recovery.

O critério não é "existe uma classe Scheduler". É comportamental:

- mesma ocorrência ⇒ NO MÁXIMO um efeito, inclusive depois de crash/restart;
- job DISABLED ou CANCELLED não produz efeito nenhum;
- transição de estado inválida é recusada, não "corrigida";
- o job persistido NÃO carrega autorização eterna.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nomos.adapters.contrato import ErroInvalido, ErroNaoEncontrado
from nomos.adapters.scheduler import (
    TRANSICOES, ArmazemJobs, ErroScheduler, JobDefinition, JobInstance,
    JobState, Scheduler, transicao_valida,
)
from nomos.kernel.audit import AuditLog

T0 = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)


class _Efeito:
    """Executor de teste: conta efeitos reais por ocorrência."""

    def __init__(self, falhar=False):
        self.chamadas: list[str] = []
        self.falhar = falhar

    def __call__(self, definicao, instancia):
        self.chamadas.append(instancia.chave)
        if self.falhar:
            raise RuntimeError("efeito falhou")
        return type("R", (), {"efeito_aplicado": True})()


@pytest.fixture()
def sched(tmp_path):
    relogio = {"t": T0}
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    efeito = _Efeito()
    s = Scheduler(armazem, executor=efeito,
                  audit=AuditLog(tmp_path / "logs" / "audit.jsonl"),
                  agora_fn=lambda: relogio["t"])
    return s, efeito, relogio, armazem


# ------------------------------------------------------ criação e listagem

def test_cria_one_shot_e_recorrente(sched):
    s, _e, _r, _a = sched
    a = s.criar("um", "suj", "fs_ler", alvo="/x")
    b = s.criar("rec", "suj", "fs_ler", alvo="/x", intervalo_s=60)
    assert a.estado is JobState.SCHEDULED and not a.recorrente()
    assert b.recorrente() and b.intervalo_s == 60
    assert {d.job_id for d in s.listar()} == {"um", "rec"}


def test_id_duplicado_e_recusado(sched):
    s, *_ = sched
    s.criar("j", "suj", "fs_ler")
    with pytest.raises(ErroScheduler, match="já existe"):
        s.criar("j", "suj", "fs_ler")


def test_intervalo_invalido_e_recusado(sched):
    s, *_ = sched
    for ruim in (0, -1):
        with pytest.raises(ErroInvalido):
            s.criar(f"j{ruim}", "suj", "fs_ler", intervalo_s=ruim)


def test_status_de_job_inexistente(sched):
    s, *_ = sched
    with pytest.raises(ErroNaoEncontrado):
        s.status("fantasma")


# ------------------------------------------------------ máquina de estados

def test_transicoes_validas_sao_allowlist():
    assert transicao_valida(JobState.SCHEDULED, JobState.RUNNING)
    assert transicao_valida(JobState.RUNNING, JobState.SUCCEEDED)
    assert not transicao_valida(JobState.CANCELLED, JobState.SCHEDULED)
    assert not transicao_valida(JobState.CREATED, JobState.RUNNING)
    assert TRANSICOES[JobState.CANCELLED] == frozenset()


def test_cancelado_e_terminal(sched):
    s, *_ = sched
    s.criar("j", "suj", "fs_ler")
    s.cancelar("j")
    for tentativa in (s.habilitar, s.desabilitar):
        with pytest.raises(ErroScheduler, match="transição inválida"):
            tentativa("j")
    assert s.status("j").estado is JobState.CANCELLED


def test_disable_e_enable(sched):
    s, *_ = sched
    s.criar("j", "suj", "fs_ler")
    assert s.desabilitar("j").estado is JobState.DISABLED
    assert s.habilitar("j").estado is JobState.SCHEDULED


def test_transicao_invalida_e_auditada(sched, tmp_path):
    s, *_ = sched
    s.criar("j", "suj", "fs_ler")
    s.cancelar("j")
    with pytest.raises(ErroScheduler):
        s.habilitar("j")
    assert "scheduler.transicao.negada" in (tmp_path / "logs" / "audit.jsonl").read_text()


# ------------------------------------------------------ execução e dedup

def test_executa_job_devido(sched):
    s, efeito, _r, _a = sched
    s.criar("j", "suj", "fs_ler", primeiro_em=T0)
    execs = s.executar_devidos()
    assert len(execs) == 1
    assert execs[0].estado_final is JobState.SUCCEEDED
    assert execs[0].efeito_aplicado
    assert len(efeito.chamadas) == 1


def test_mesma_ocorrencia_no_maximo_um_efeito(sched):
    """O gate central: same job + same occurrence → max 1 effect."""
    s, efeito, _r, armazem = sched
    d = s.criar("j", "suj", "fs_ler", primeiro_em=T0)
    s.executar_job(d, T0)
    s.executar_job(d, T0)          # mesma ocorrência de novo
    s.executar_job(d, T0)
    assert len(efeito.chamadas) == 1, efeito.chamadas


def test_dedup_sobrevive_a_restart(tmp_path):
    """Processo morre e volta: a marca de ocorrência está no disco."""
    db = tmp_path / "jobs.db"
    e1 = _Efeito()
    s1 = Scheduler(ArmazemJobs(db), executor=e1, agora_fn=lambda: T0)
    d = s1.criar("j", "suj", "fs_ler", primeiro_em=T0)
    s1.executar_job(d, T0)
    assert len(e1.chamadas) == 1

    # "reinício": novo Scheduler, novo executor, MESMO banco
    e2 = _Efeito()
    s2 = Scheduler(ArmazemJobs(db), executor=e2, agora_fn=lambda: T0)
    d2 = JobDefinition(job_id="j", sujeito="suj", capacidade="fs_ler",
                       proximo_em=T0, estado=JobState.SCHEDULED)
    s2.executar_job(d2, T0)
    assert len(e2.chamadas) == 0, "restart repetiu a ocorrência"


def test_reserva_acontece_antes_do_efeito(tmp_path):
    """Se o efeito estourar, a ocorrência continua reservada — crash entre
    efeito e marca não pode virar repetição."""
    db = tmp_path / "jobs.db"
    armazem = ArmazemJobs(db)
    s = Scheduler(armazem, executor=_Efeito(falhar=True), agora_fn=lambda: T0)
    d = s.criar("j", "suj", "fs_ler", primeiro_em=T0)
    ex = s.executar_job(d, T0)
    assert ex.estado_final is JobState.FAILED
    inst = JobInstance("j", T0.isoformat())
    assert armazem.ocorrencia_estado(inst) == JobState.FAILED.value

    e2 = _Efeito()
    s2 = Scheduler(armazem, executor=e2, agora_fn=lambda: T0)
    s2.executar_job(s2.status("j"), T0)
    assert len(e2.chamadas) == 0, "ocorrência falhada foi repetida"


def test_job_desabilitado_nao_produz_efeito(sched):
    s, efeito, _r, _a = sched
    s.criar("j", "suj", "fs_ler", primeiro_em=T0)
    s.desabilitar("j")
    assert s.devidos() == []
    s.executar_job(s.status("j"), T0)
    assert len(efeito.chamadas) == 0


def test_job_cancelado_nao_produz_efeito(sched):
    s, efeito, _r, _a = sched
    s.criar("j", "suj", "fs_ler", primeiro_em=T0)
    s.cancelar("j")
    assert s.devidos() == []
    s.executar_job(s.status("j"), T0)
    assert len(efeito.chamadas) == 0


def test_job_futuro_nao_e_devido(sched):
    s, efeito, _r, _a = sched
    s.criar("j", "suj", "fs_ler", primeiro_em=T0 + timedelta(hours=1))
    assert s.devidos(T0) == []
    assert len(efeito.chamadas) == 0


# ------------------------------------------------------ recorrência

def test_recorrente_reagenda_para_o_futuro(sched):
    s, efeito, relogio, _a = sched
    d = s.criar("r", "suj", "fs_ler", primeiro_em=T0, intervalo_s=60)
    s.executar_job(d, T0)
    depois = s.status("r")
    assert depois.estado is JobState.SCHEDULED
    assert depois.proximo_em == T0 + timedelta(seconds=60)


def test_recorrente_nao_acumula_ocorrencias_vencidas(sched):
    """Máquina desligada por muito tempo não dispara N execuções de uma vez."""
    s, _e, _r, _a = sched
    d = s.criar("r", "suj", "fs_ler", primeiro_em=T0, intervalo_s=60)
    muito_depois = T0 + timedelta(hours=5)
    s.executar_job(d, muito_depois)
    prox = s.status("r").proximo_em
    assert prox > muito_depois
    assert prox <= muito_depois + timedelta(seconds=60)


def test_one_shot_nao_reagenda(sched):
    s, _e, _r, _a = sched
    d = s.criar("u", "suj", "fs_ler", primeiro_em=T0)
    s.executar_job(d, T0)
    assert s.status("u").estado is JobState.SUCCEEDED
    assert s.devidos(T0 + timedelta(days=1)) == []


def test_recorrente_ocorrencias_distintas_executam(sched):
    """Dedup é por OCORRÊNCIA, não por job — ocorrência nova roda."""
    s, efeito, _r, _a = sched
    d = s.criar("r", "suj", "fs_ler", primeiro_em=T0, intervalo_s=60)
    s.executar_job(d, T0)
    s.executar_job(s.status("r"), T0 + timedelta(seconds=60))
    assert len(efeito.chamadas) == 2
    assert len(set(efeito.chamadas)) == 2


# ------------------------------------------------------ autoridade

def test_job_persistido_nao_carrega_autorizacao(tmp_path):
    """Nem o dataclass nem a tabela guardam token/assinatura/nonce."""
    import dataclasses
    campos = {f.name for f in dataclasses.fields(JobDefinition)}
    for proibido in ("token", "autorizacao", "authorization", "assinatura",
                     "signature", "nonce", "chave", "key", "capacidades"):
        assert proibido not in campos, f"JobDefinition guarda '{proibido}'"

    armazem = ArmazemJobs(tmp_path / "j.db")
    s = Scheduler(armazem, executor=_Efeito(), agora_fn=lambda: T0)
    s.criar("j", "suj", "fs_ler", alvo="/x")
    import sqlite3
    with sqlite3.connect(armazem.caminho) as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(jobs)")]
    assert not ({"token", "autorizacao", "assinatura", "nonce"} & set(cols))


def test_sem_executor_governado_nao_ha_efeito(tmp_path):
    """Scheduler não executa por conta própria."""
    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=None,
                  agora_fn=lambda: T0)
    d = s.criar("j", "suj", "fs_ler", primeiro_em=T0)
    ex = s.executar_job(d, T0)
    assert ex.estado_final is JobState.FAILED
    assert "sem executor governado" in ex.detalhe


def test_persistencia_sobrevive_a_nova_instancia(tmp_path):
    db = tmp_path / "j.db"
    s1 = Scheduler(ArmazemJobs(db), executor=_Efeito(), agora_fn=lambda: T0)
    s1.criar("j", "suj", "fs_ler", alvo="/x", intervalo_s=30)
    s2 = Scheduler(ArmazemJobs(db), executor=_Efeito(), agora_fn=lambda: T0)
    d = s2.status("j")
    assert d.capacidade == "fs_ler" and d.intervalo_s == 30
    assert d.alvo == "/x"


def test_apagar_job(sched):
    s, *_ = sched
    s.criar("j", "suj", "fs_ler")
    s.apagar("j")
    with pytest.raises(ErroNaoEncontrado):
        s.status("j")
