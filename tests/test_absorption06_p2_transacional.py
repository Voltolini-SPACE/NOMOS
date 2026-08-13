"""ABSORPTION-06 / P2 — o scheduler não produz efeito incompatível com o estado.

O censo do G1 achou três defeitos que eram uma só omissão: **a decisão não era
persistida**. O ticker recusava a ocorrência e devolvia `None`. Nada era
gravado. Consequências encadeadas:

- a ocorrência continuava devida, e o job era reexaminado a cada tick, para
  sempre, chamando o autorizador de novo toda vez;
- `negadas` nunca era incrementado — tudo virava `puladas` —, então a CLI
  imprimia "executadas: 0 · falhas: 0" e devolvia `EXIT_OK` com 100% das
  ocorrências recusadas;
- e a negação do PDP, quando chegava a ser classificada, saía como
  `FAILED/UNKNOWN/ERRO` com "verifique antes de repetir" — para algo que não
  tocou em nada.

Negação é DECISÃO DE SEGURANÇA e é TERMINAL. Um job negado que volta sozinho
para a fila não foi negado: foi adiado.

## Os três pontos de crash

    A) decisão do PDP   ↓CRASH   estado durável
    B) reivindicação    ↓CRASH   efeito
    C) efeito           ↓CRASH   estado terminal

Em A não pode haver efeito. Em B e C não pode haver efeito DUPLICADO — e
"retry" não é resposta: a reserva é a reivindicação durável, gravada ANTES do
efeito, e é ela que sobrevive ao `SIGKILL`.

Os testes de crash matam PROCESSO de verdade (`os.kill`), não levantam exceção
simulada: exceção roda os `finally`, e é justamente o que não acontece quando o
processo morre.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from nomos.adapters.scheduler import (ArmazemJobs, JobInstance, JobState,
                                      Scheduler, transicao_valida)
from nomos.adapters.ticker import CatchUp, Ticker

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class Relogio:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def avanca(self, **kw):
        self.t += timedelta(**kw)


def _monta(tmp_path, *, intervalo_s=None, efeitos=None):
    efeitos = [] if efeitos is None else efeitos

    def executor(d, inst, credencial=None):
        efeitos.append(inst.ocorrencia)
        return type("R", (), {"efeito_aplicado": True})()

    relogio = Relogio()
    s = Scheduler(ArmazemJobs(tmp_path / "jobs.db"), executor=executor,
                  agora_fn=relogio)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=intervalo_s)
    return s, efeitos, relogio


def _ticker(s, relogio, *, autoriza=False):
    return Ticker(s, (lambda d, i: object() if autoriza else None),
                  catchup=CatchUp.RUN_ONCE, agora_fn=relogio,
                  dormir=lambda _x: None)


# ============================================ DENY terminal

def test_p2_deny_leva_one_shot_ao_estado_terminal_DENIED(tmp_path):
    s, efeitos, relogio = _monta(tmp_path)
    _ticker(s, relogio).rodar_ate(max_ticks=1)
    assert s.armazem.obter("j").estado is JobState.DENIED
    assert not efeitos


def test_p2_DENIED_e_terminal_na_allowlist():
    """Nenhuma transição sai de DENIED — nem para RUNNING, nem para SCHEDULED."""
    from nomos.adapters.scheduler import TRANSICOES
    assert TRANSICOES[JobState.DENIED] == frozenset()
    for destino in JobState:
        assert not transicao_valida(JobState.DENIED, destino), destino


def test_p2_one_shot_negado_nao_faz_livelock(tmp_path):
    """ONE_SHOT_DENY_LIVELOCK=FALSE — dez ticks, uma negação."""
    s, efeitos, relogio = _monta(tmp_path)
    t = _ticker(s, relogio)
    resultados = []
    for _ in range(10):
        relogio.avanca(minutes=1)
        resultados.extend(t.rodar_ate(max_ticks=1))
    assert sum(r.negadas for r in resultados) == 1, (
        f"negadas por tick: {[r.negadas for r in resultados]}")
    assert sum(r.examinados for r in resultados) == 1, (
        "job negado continuou sendo examinado — livelock")
    assert not efeitos


def test_p2_contador_de_negadas_conta_exatamente_uma_vez(tmp_path):
    """DENY_COUNTER_EXACTLY_ONCE=TRUE, e `negadas` não vira `puladas`."""
    s, _efeitos, relogio = _monta(tmp_path)
    r = _ticker(s, relogio).rodar_ate(max_ticks=1)[0]
    assert (r.negadas, r.executadas, r.falhas) == (1, 0, 0), r
    assert r.puladas == 0, "negada foi contada como pulada"


def test_p2_job_negado_nao_reexecuta_sem_autoridade_nova(tmp_path):
    """DENIED_JOB_REEXECUTABLE_WITHOUT_NEW_AUTH=FALSE.

    O autorizador passa a ACEITAR depois da negação. Sem estado terminal, o
    job voltaria a rodar sozinho — a recusa teria sido só um atraso.
    """
    s, efeitos, relogio = _monta(tmp_path)
    _ticker(s, relogio).rodar_ate(max_ticks=1)
    assert s.armazem.obter("j").estado is JobState.DENIED
    for _ in range(5):
        relogio.avanca(minutes=1)
        _ticker(s, relogio, autoriza=True).rodar_ate(max_ticks=1)
    assert not efeitos, "job negado executou só porque o autorizador mudou"
    assert s.armazem.obter("j").estado is JobState.DENIED


def test_p2_restart_nao_ressuscita_job_negado(tmp_path):
    """RESTART_RESURRECTS_DENIED_JOB=FALSE — o estado é durável."""
    s, efeitos, relogio = _monta(tmp_path)
    _ticker(s, relogio).rodar_ate(max_ticks=1)
    # "restart": armazém novo sobre o MESMO arquivo, executor que aceitaria
    s2 = Scheduler(ArmazemJobs(tmp_path / "jobs.db"),
                   executor=lambda d, i, credencial=None: efeitos.append("X"),
                   agora_fn=relogio)
    relogio.avanca(hours=1)
    _ticker(s2, relogio, autoriza=True).rodar_ate(max_ticks=1)
    assert not efeitos
    assert s2.armazem.obter("j").estado is JobState.DENIED


def test_p2_negacao_e_DENIED_nao_FAILED(tmp_path):
    """PDP_DENY_CLASSIFICATION=DENIED.

    Misturar decisão de segurança com erro operacional faz o operador tratar
    política como incidente — e, pior, incidente parecer rotina.
    """
    from nomos.adapters.resultado import ResultadoOcorrencia, canonico
    s, _e, relogio = _monta(tmp_path)
    ex = _ticker(s, relogio).rodar_ate(max_ticks=1)
    assert ex
    estado = canonico(ResultadoOcorrencia.DENIED)
    assert estado.effect_state == "NO_EFFECT"
    assert estado.severidade.value == "AVISO"
    falha = canonico(ResultadoOcorrencia.FAILED)
    assert falha.effect_state == "UNKNOWN" and falha.severidade.value == "ERRO"


def test_p2_recorrente_negado_avanca_a_agenda_sem_reexaminar_a_mesma(tmp_path):
    """Negar UMA ocorrência não nega as futuras — mas não repete a negada."""
    s, efeitos, relogio = _monta(tmp_path, intervalo_s=60)
    t = _ticker(s, relogio)
    primeiro = t.rodar_ate(max_ticks=1)[0]
    assert primeiro.negadas == 1
    antes = s.armazem.obter("j").proximo_em
    relogio.avanca(seconds=120)
    segundo = _ticker(s, relogio).rodar_ate(max_ticks=1)[0]
    depois = s.armazem.obter("j").proximo_em
    assert depois > antes, "agenda de job recorrente não avançou"
    assert segundo.negadas <= 1
    assert not efeitos


# ============================================ crash REAL de processo

_PROGRAMA = '''
import os, sys, time
from datetime import datetime, timezone
from nomos.adapters.scheduler import ArmazemJobs, JobInstance, Scheduler
DB, MARCA, PONTO = sys.argv[1], sys.argv[2], sys.argv[3]
agora = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

def executor(d, inst, credencial=None):
    if PONTO == "B":
        os._exit(9)                      # morre ANTES do efeito
    with open(MARCA, "a") as f:
        f.write(inst.ocorrencia + "\\n")
        f.flush()
        os.fsync(f.fileno())
    if PONTO == "C":
        os._exit(9)                      # morre DEPOIS do efeito
    return type("R", (), {"efeito_aplicado": True})()

s = Scheduler(ArmazemJobs(DB), executor=executor, agora_fn=lambda: agora)
try:
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
except Exception:
    pass
if PONTO == "A":
    os._exit(9)                          # morre entre decisão e estado durável
for d in s.devidos():
    s.executar_ocorrencia(d, JobInstance(job_id=d.job_id,
                          ocorrencia=d.proximo_em.isoformat()), agora)
'''


def _rodar_filho(tmp_path, ponto):
    db = tmp_path / "jobs.db"
    marca = tmp_path / "efeitos.txt"
    p = subprocess.run([sys.executable, "-c", _PROGRAMA, str(db), str(marca), ponto],
                       capture_output=True, timeout=60)
    efeitos = (marca.read_text().splitlines() if marca.exists() else [])
    return p.returncode, efeitos, db, marca


@pytest.mark.parametrize("ponto", ["A", "B", "C"])
def test_p2_crash_real_nao_duplica_efeito_no_restart(tmp_path, ponto):
    """DUPLICATE_SIDE_EFFECT_AFTER_CRASH=FALSE, com `os._exit(9)` de verdade.

    Exceção simulada roda os `finally`; morte de processo não roda nada. É a
    diferença entre testar o tratamento de erro e testar a durabilidade.
    """
    rc, primeiro, db, marca = _rodar_filho(tmp_path, ponto)
    assert rc != 0, f"o filho deveria ter morrido no ponto {ponto}"
    # RESTART: mesmo armazém, processo novo, agora sem morrer
    rc2, depois, _db, _m = _rodar_filho(tmp_path, "OK")
    if ponto == "A":
        # nada foi reivindicado antes da morte: a ocorrência ainda é devida,
        # e executar UMA vez no restart é o comportamento correto
        assert len(depois) <= 1, depois
    else:
        assert depois == primeiro, (
            f"ponto {ponto}: efeito DUPLICADO no restart "
            f"({primeiro} → {depois})")


def test_p2_reivindicacao_e_gravada_antes_do_efeito(tmp_path):
    """EXECUTION_WITHOUT_DURABLE_CLAIM=FALSE.

    Se a marca viesse DEPOIS do efeito, um crash no meio perderia a
    reivindicação e o restart repetiria — a ordem é a defesa.
    """
    db = tmp_path / "jobs.db"
    vistos = []

    def executor(d, inst, credencial=None):
        con = sqlite3.connect(db)
        try:
            linhas = con.execute(
                "SELECT estado FROM ocorrencias WHERE chave=?",
                (inst.chave,)).fetchall()
        finally:
            con.close()
        vistos.append(linhas)
        return type("R", (), {"efeito_aplicado": True})()

    s = Scheduler(ArmazemJobs(db), executor=executor, agora_fn=lambda: T0)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    d = s.devidos()[0]
    s.executar_ocorrencia(d, JobInstance(job_id="j",
                                         ocorrencia=d.proximo_em.isoformat()), T0)
    assert vistos and vistos[0], (
        "o efeito rodou sem reivindicação durável visível no armazém")
    assert vistos[0][0][0] == JobState.RUNNING.value


def test_p2_perder_o_estado_terminal_nao_reexecuta(tmp_path):
    """LOST_TERMINAL_STATE_CAUSES_REEXECUTION=FALSE.

    Simula o crash do ponto C: a reserva existe, o terminal nunca foi gravado.
    A ocorrência não pode voltar a rodar.
    """
    s, efeitos, relogio = _monta(tmp_path, intervalo_s=60)
    d = s.armazem.obter("j")
    inst = JobInstance(job_id="j", ocorrencia=d.proximo_em.isoformat())
    assert s.armazem.reservar(inst)          # reivindicou e "morreu"
    n = len(efeitos)
    s.executar_ocorrencia(s.armazem.obter("j"), inst, relogio.t)
    assert len(efeitos) == n, "ocorrência com reserva órfã foi reexecutada"


# ============================================ contrato de idempotência

CATEGORIAS = {"IDEMPOTENT", "IDEMPOTENCY_KEY_PROTECTED",
              "EXACTLY_ONCE_VIA_DURABLE_PROTOCOL", "NON_RETRYABLE_MANUAL_RECOVERY"}


def test_p2_toda_capacidade_declara_categoria_de_retry():
    """Nenhuma capacidade com efeito pode ficar em "provavelmente não acontece".

    O registro já sabe o que é idempotente; o que faltava era NOMEAR o que
    acontece com o que não é. `retry` automático indeterminado sobre efeito não
    idempotente é duplicação esperando o momento.
    """
    from nomos.adapters.wiring import (CATEGORIAS_FS, CATEGORIAS_SCHED,
                                       IDEMPOTENTES_FS, IDEMPOTENTES_SCHED)
    from nomos.adapters.retry import CATEGORIA_DE_RETRY
    todas = set(CATEGORIAS_FS) | set(CATEGORIAS_SCHED)
    faltando = sorted(todas - set(CATEGORIA_DE_RETRY))
    assert not faltando, f"capacidades sem categoria de retry declarada: {faltando}"
    for nome, cat in CATEGORIA_DE_RETRY.items():
        assert cat in CATEGORIAS, f"{nome}: categoria desconhecida {cat}"
    # coerência com o registro: idempotente ⇒ IDEMPOTENT
    for nome in IDEMPOTENTES_FS | IDEMPOTENTES_SCHED:
        assert CATEGORIA_DE_RETRY[nome] == "IDEMPOTENT", nome


def test_p2_nao_idempotente_nao_ganha_retry_automatico():
    from nomos.adapters.retry import CATEGORIA_DE_RETRY, pode_repetir_sozinho
    for nome, cat in CATEGORIA_DE_RETRY.items():
        if cat == "IDEMPOTENT":
            assert pode_repetir_sozinho(nome)
        else:
            assert not pode_repetir_sozinho(nome), (
                f"{nome} ({cat}) ganharia retry automático indeterminado")


def test_p2_mesma_ocorrencia_negada_duas_vezes_conta_uma(tmp_path):
    """A reserva precede a negação — e é ela que impede contagem dupla.

    Mutação achou a lacuna: remover a reserva do caminho de negação não
    quebrava nenhum teste, porque nenhum deles negava a MESMA ocorrência duas
    vezes. Sem a reserva, um despacho repetido gravaria duas negações e
    emitiria dois eventos para um único fato — a mesma família do efeito
    duplicado, só que na trilha em vez de no mundo.
    """
    import json

    from nomos.kernel.audit import AuditLog
    trilha = AuditLog(tmp_path / "audit.jsonl")
    s = Scheduler(ArmazemJobs(tmp_path / "jobs.db"),
                  executor=lambda d, i, credencial=None: None,
                  audit=trilha, agora_fn=lambda: T0)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    d = s.armazem.obter("j")
    inst = JobInstance(job_id="j", ocorrencia=d.proximo_em.isoformat())

    primeira = s.negar_ocorrencia(d, inst, T0, "recusado")
    segunda = s.negar_ocorrencia(s.armazem.obter("j"), inst, T0, "recusado")
    assert primeira.estado_final is JobState.DENIED
    assert segunda.estado_final is JobState.DENIED
    assert "dedup" in segunda.detalhe, (
        "segunda negação da MESMA ocorrência não foi deduplicada")

    eventos = [json.loads(x).get("event") for x in
               (tmp_path / "audit.jsonl").read_text().splitlines() if x.strip()]
    assert eventos.count("scheduler.ocorrencia.negada") == 1, (
        f"a mesma ocorrência gerou {eventos.count('scheduler.ocorrencia.negada')} "
        "eventos de negação")


def test_p2_negacao_e_idempotente_ATRAVES_de_restart(tmp_path):
    """SAME_OCCURRENCE_DOUBLE_DENY=IDEMPOTENT, com processo NOVO no meio.

    O teste irmão nega duas vezes no mesmo processo. Este separa as duas
    tentativas por um restart real: `Scheduler` e `ArmazemJobs` novos sobre o
    mesmo arquivo, sem nenhum estado em memória sobrevivendo. É o cenário que
    importa — dois tickers subindo depois de uma queda, ou o operador
    reiniciando o daemon entre as tentativas.

    A chamada é DIRETA ao mecanismo persistente, não pelo ticker: a agenda
    impediria naturalmente a segunda visita e mascararia a propriedade.
    """
    import json

    from nomos.kernel.audit import AuditLog
    db = tmp_path / "jobs.db"
    trilha = tmp_path / "audit.jsonl"

    s1 = Scheduler(ArmazemJobs(db), executor=lambda d, i, credencial=None: None,
                   audit=AuditLog(trilha), agora_fn=lambda: T0)
    s1.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    d1 = s1.armazem.obter("j")
    inst = JobInstance(job_id="j", ocorrencia=d1.proximo_em.isoformat())
    primeira = s1.negar_ocorrencia(d1, inst, T0, "recusado")
    assert primeira.estado_final is JobState.DENIED
    del s1

    # RESTART: nada em memória atravessa; só o disco
    s2 = Scheduler(ArmazemJobs(db), executor=lambda d, i, credencial=None: None,
                   audit=AuditLog(trilha), agora_fn=lambda: T0)
    segunda = s2.negar_ocorrencia(s2.armazem.obter("j"), inst, T0, "recusado")
    assert segunda.estado_final is JobState.DENIED
    assert "dedup" in segunda.detalhe, (
        "após restart, a mesma ocorrência foi negada de novo como se fosse nova")

    eventos = [json.loads(x).get("event") for x in
               trilha.read_text().splitlines() if x.strip()]
    assert eventos.count("scheduler.ocorrencia.negada") == 1, (
        "DUPLICATE_DENIAL_AUDIT_EFFECT: a mesma ocorrência gerou "
        f"{eventos.count('scheduler.ocorrencia.negada')} eventos através do restart")

    con = sqlite3.connect(db)
    try:
        n = con.execute("SELECT COUNT(*) FROM ocorrencias WHERE chave=?",
                        (inst.chave,)).fetchone()[0]
    finally:
        con.close()
    assert n == 1, f"DENIAL_RECORDS_FOR_SAME_OCCURRENCE={n}, esperado 1"
