"""NOMOS adapters.scheduler — scheduler nativo governado (ABSORPTION-03 / FASE 3).

Fecha as capacidades críticas de scheduler apontadas pelo censo da
ABSORPTION-02: one-shot, recorrente, list/status, enable, disable,
cancel/delete, execução, persistência/recovery, deduplicação, idempotência e
auditoria. Antes disto o NOMOS só sabia EXPORTAR um plist — nunca instalava
nem executava nada.

## Quatro conceitos separados de propósito

    JobDefinition  o que deve acontecer, e quando (persistente)
    JobState       em que ponto do ciclo a definição está
    JobInstance    UMA ocorrência agendada (job + instante) — a unidade de dedup
    JobExecution   o registro de UMA tentativa de executar uma instância

Confundir definição com execução é a origem clássica de efeito duplicado:
"o job rodou" não diz *qual ocorrência* rodou, então o restart reexecuta.

## Autoridade não é persistida

Um job guardado NÃO carrega token. `JobDefinition` guarda apenas o SUJEITO e as
capacidades pretendidas; a autoridade é obtida **no instante da execução**,
pelo mesmo caminho governado de qualquer outra coisa. Persistir um token curto
e reusá-lo seria criar autorização eterna — exatamente o que o modelo recusa.

## Dedup sobrevive a restart

A chave de ocorrência (`job_id` + instante planejado) é gravada no armazém
ANTES de executar, com `INSERT` que falha se já existir. Se o processo morrer
no meio, o restart encontra a marca e não repete — a alternativa (marcar depois
do efeito) perde a corrida com o crash.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from nomos.adapters.agenda import ScheduleSpec, TipoAgenda
from nomos.adapters.contrato import ErroConflito, ErroInvalido, ErroNaoEncontrado

_ID_MAX = 64


class JobState(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DISABLED = "DISABLED"
    CANCELLED = "CANCELLED"


# Transições permitidas. Tudo o que não está aqui é recusado — a máquina de
# estados é allowlist, como todo o resto do NOMOS.
TRANSICOES: dict[JobState, frozenset[JobState]] = {
    JobState.CREATED:   frozenset({JobState.SCHEDULED, JobState.DISABLED,
                                   JobState.CANCELLED}),
    JobState.SCHEDULED: frozenset({JobState.RUNNING, JobState.DISABLED,
                                   JobState.CANCELLED}),
    JobState.RUNNING:   frozenset({JobState.SUCCEEDED, JobState.FAILED,
                                   JobState.CANCELLED}),
    JobState.SUCCEEDED: frozenset({JobState.SCHEDULED, JobState.DISABLED,
                                   JobState.CANCELLED}),
    JobState.FAILED:    frozenset({JobState.SCHEDULED, JobState.DISABLED,
                                   JobState.CANCELLED}),
    JobState.DISABLED:  frozenset({JobState.SCHEDULED, JobState.CANCELLED}),
    JobState.CANCELLED: frozenset(),          # terminal: não ressuscita
}


def transicao_valida(de: JobState, para: JobState) -> bool:
    return para in TRANSICOES.get(de, frozenset())


@dataclass(frozen=True)
class JobDefinition:
    """O que deve acontecer. NÃO guarda autorização — só identidade e intenção."""
    job_id: str
    sujeito: str
    capacidade: str
    argumentos: dict = field(default_factory=dict)
    alvo: str = ""
    intervalo_s: int | None = None            # compat: INTERVAL legado
    proximo_em: datetime | None = None
    estado: JobState = JobState.CREATED
    criado_em: datetime | None = None
    tz: str = "UTC"
    # ABSORPTION-04: a agenda vira EXPLÍCITA (ONE_SHOT/INTERVAL/CRON). O
    # `intervalo_s` continua no dataclass só para não quebrar quem já grava
    # nesse formato — `agenda()` normaliza os dois.
    schedule: ScheduleSpec | None = None

    def agenda(self) -> ScheduleSpec:
        """A agenda efetiva. Nunca INFERE cron de string arbitrária."""
        if self.schedule is not None:
            return self.schedule
        if self.intervalo_s:
            return ScheduleSpec(kind=TipoAgenda.INTERVAL,
                                intervalo_s=self.intervalo_s, timezone=self.tz)
        return ScheduleSpec(kind=TipoAgenda.ONE_SHOT, timezone=self.tz)

    def recorrente(self) -> bool:
        return self.agenda().recorrente()


@dataclass(frozen=True)
class JobInstance:
    """UMA ocorrência. `chave` é a unidade de deduplicação."""
    job_id: str
    ocorrencia: str                            # instante planejado, ISO-8601 UTC

    @property
    def chave(self) -> str:
        return f"{self.job_id}@{self.ocorrencia}"


@dataclass(frozen=True)
class JobExecution:
    instancia: JobInstance
    estado_final: JobState
    detalhe: str = ""
    efeito_aplicado: bool = False


class ArmazemJobs:
    """Persistência em SQLite. Um arquivo, dois estados: definições e ocorrências.

    A tabela de ocorrências existe para o dedup sobreviver a crash e restart —
    é ela que responde "esta ocorrência já foi tentada?".
    """

    def __init__(self, caminho: Path | str):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._criar()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.caminho, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        return c

    def _criar(self) -> None:
        with self._lock, self._conn() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, sujeito TEXT NOT NULL,
                capacidade TEXT NOT NULL, argumentos TEXT NOT NULL,
                alvo TEXT NOT NULL, intervalo_s INTEGER,
                proximo_em TEXT, estado TEXT NOT NULL,
                criado_em TEXT NOT NULL, tz TEXT NOT NULL,
                schedule TEXT)""")
            # migração aditiva para bancos criados antes da ABSORPTION-04
            cols = [r[1] for r in c.execute("PRAGMA table_info(jobs)")]
            if "schedule" not in cols:
                c.execute("ALTER TABLE jobs ADD COLUMN schedule TEXT")
            # PRIMARY KEY na chave da ocorrência: o INSERT duplicado FALHA.
            # É o dedup — e ele acontece ANTES do efeito, não depois.
            c.execute("""CREATE TABLE IF NOT EXISTS ocorrencias (
                chave TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                ocorrencia TEXT NOT NULL, iniciada_em TEXT NOT NULL,
                estado TEXT NOT NULL, detalhe TEXT NOT NULL DEFAULT '',
                efeito INTEGER NOT NULL DEFAULT 0)""")
            try:
                os.chmod(self.caminho, 0o600)
            except OSError:
                pass

    # ------------------------------------------------------------ definições

    def salvar(self, d: JobDefinition) -> None:
        with self._lock, self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (d.job_id, d.sujeito, d.capacidade,
                       json.dumps(d.argumentos, ensure_ascii=False), d.alvo,
                       d.intervalo_s,
                       d.proximo_em.isoformat() if d.proximo_em else None,
                       d.estado.value,
                       (d.criado_em or datetime.now(timezone.utc)).isoformat(),
                       d.tz,
                       json.dumps(d.agenda().dict(), ensure_ascii=False)))

    def obter(self, job_id: str) -> JobDefinition | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _linha_para_def(r) if r else None

    def listar(self) -> list[JobDefinition]:
        with self._lock, self._conn() as c:
            rs = c.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()
        return [_linha_para_def(r) for r in rs]

    def apagar(self, job_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))

    # ------------------------------------------------------------ ocorrências

    def reservar(self, inst: JobInstance) -> bool:
        """True se ESTA execução ganhou a ocorrência; False se já foi reservada.

        Reserva ANTES do efeito, de propósito: se marcássemos depois, um crash
        entre o efeito e a marca faria o restart repetir.
        """
        with self._lock, self._conn() as c:
            try:
                c.execute(
                    "INSERT INTO ocorrencias (chave, job_id, ocorrencia, "
                    "iniciada_em, estado) VALUES (?,?,?,?,?)",
                    (inst.chave, inst.job_id, inst.ocorrencia,
                     datetime.now(timezone.utc).isoformat(),
                     JobState.RUNNING.value))
                return True
            except sqlite3.IntegrityError:
                return False

    def concluir(self, inst: JobInstance, estado: JobState, detalhe: str = "",
                 efeito: bool = False) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE ocorrencias SET estado=?, detalhe=?, efeito=? "
                      "WHERE chave=?",
                      (estado.value, detalhe[:500], 1 if efeito else 0, inst.chave))

    def ocorrencia_estado(self, inst: JobInstance) -> str | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT estado FROM ocorrencias WHERE chave=?",
                          (inst.chave,)).fetchone()
        return r[0] if r else None


def _linha_para_def(r) -> JobDefinition:
    schedule = None
    if len(r) > 10 and r[10]:
        try:
            schedule = ScheduleSpec.de_dict(json.loads(r[10]))
        except Exception as exc:
            # FAIL-CLOSED (achado do censo): antes isto virava `None` e o job
            # voltava como ONE_SHOT — um job CRON PARAVA DE RECORRER em
            # silêncio. Agenda ilegível é corrupção de estado, não um default.
            raise ErroConflito(
                f"agenda do job '{r[0]}' está ilegível ({type(exc).__name__}) "
                "— recusando em vez de rebaixar para ONE_SHOT em silêncio"
            ) from None
    return JobDefinition(
        job_id=r[0], sujeito=r[1], capacidade=r[2],
        argumentos=json.loads(r[3]), alvo=r[4], intervalo_s=r[5],
        proximo_em=datetime.fromisoformat(r[6]) if r[6] else None,
        estado=JobState(r[7]),
        criado_em=datetime.fromisoformat(r[8]) if r[8] else None, tz=r[9],
        schedule=schedule)


class ErroScheduler(ErroConflito):
    """Conflito de agendamento — sempre fail-closed."""


class Scheduler:
    """As operações de scheduler. Cada uma é capacidade governada no registro.

    O `executor` recebido é a ponte para o caminho governado (PDP→PEP→adapter):
    o scheduler NUNCA executa efeito por conta própria, e não guarda autoridade.
    """

    def __init__(self, armazem: ArmazemJobs, executor=None, audit=None,
                 agora_fn=lambda: datetime.now(timezone.utc), alert_sink=None):
        self.armazem = armazem
        self._executor = executor
        self.audit = audit
        self._agora = agora_fn
        # Achado do censo: o alerta vivia só no ticker, então falha pelo
        # caminho `executar_devidos()`/`executar_job()` era 100% muda. Quem
        # conhece a falha é quem a registra.
        self.alertas = alert_sink
        if alert_sink is None and audit is not None:
            from nomos.adapters.alertas import AuditAlertSink
            self.alertas = AuditAlertSink(audit)

    def _auditar(self, evento: str, **campos) -> None:
        if self.audit is not None:
            self.audit.append(evento, **campos)

    # ------------------------------------------------------------- definição

    def criar(self, job_id: str, sujeito: str, capacidade: str, *,
              argumentos=None, alvo: str = "", intervalo_s: int | None = None,
              primeiro_em: datetime | None = None, tz: str = "UTC",
              schedule: ScheduleSpec | None = None) -> JobDefinition:
        if not job_id or not isinstance(job_id, str) or len(job_id) > _ID_MAX:
            raise ErroInvalido(f"job_id inválido: {job_id!r}")
        if self.armazem.obter(job_id) is not None:
            raise ErroScheduler(f"job '{job_id}' já existe")
        if intervalo_s is not None and intervalo_s <= 0:
            raise ErroInvalido("intervalo_s precisa ser positivo")
        agora = self._agora()
        if schedule is None and intervalo_s:
            schedule = ScheduleSpec(kind=TipoAgenda.INTERVAL,
                                    intervalo_s=intervalo_s, timezone=tz)
        elif schedule is None:
            schedule = ScheduleSpec(kind=TipoAgenda.ONE_SHOT, timezone=tz)
        # Fail-closed: uma agenda CRON inválida levanta na CONSTRUÇÃO do
        # ScheduleSpec, antes de qualquer persistência — job não fica armado
        # pela metade.
        if schedule.kind is TipoAgenda.CRON:
            primeiro_em = primeiro_em or schedule.proximo(agora)
        d = JobDefinition(
            job_id=job_id, sujeito=sujeito, capacidade=capacidade,
            argumentos=dict(argumentos or {}), alvo=alvo,
            intervalo_s=intervalo_s, proximo_em=primeiro_em or agora,
            estado=JobState.SCHEDULED, criado_em=agora, tz=tz,
            schedule=schedule)
        self.armazem.salvar(d)
        self._auditar("scheduler.job.criado", job=job_id, capacidade=capacidade,
                      recorrente=d.recorrente(), tz=tz)
        return d

    def _mudar_estado(self, job_id: str, novo: JobState) -> JobDefinition:
        d = self.armazem.obter(job_id)
        if d is None:
            raise ErroNaoEncontrado(f"job '{job_id}' não existe")
        if d.estado is novo:
            return d
        if not transicao_valida(d.estado, novo):
            self._auditar("scheduler.transicao.negada", job=job_id,
                          de=d.estado.value, para=novo.value)
            raise ErroScheduler(
                f"transição inválida para '{job_id}': "
                f"{d.estado.value} → {novo.value}")
        d2 = replace(d, estado=novo)
        self.armazem.salvar(d2)
        self._auditar("scheduler.job.estado", job=job_id, de=d.estado.value,
                      para=novo.value)
        return d2

    def desabilitar(self, job_id: str) -> JobDefinition:
        return self._mudar_estado(job_id, JobState.DISABLED)

    def habilitar(self, job_id: str) -> JobDefinition:
        return self._mudar_estado(job_id, JobState.SCHEDULED)

    def cancelar(self, job_id: str) -> JobDefinition:
        return self._mudar_estado(job_id, JobState.CANCELLED)

    def listar(self) -> list[JobDefinition]:
        return self.armazem.listar()

    def status(self, job_id: str) -> JobDefinition:
        d = self.armazem.obter(job_id)
        if d is None:
            raise ErroNaoEncontrado(f"job '{job_id}' não existe")
        return d

    def apagar(self, job_id: str) -> None:
        if self.armazem.obter(job_id) is None:
            raise ErroNaoEncontrado(f"job '{job_id}' não existe")
        self.armazem.apagar(job_id)
        self._auditar("scheduler.job.apagado", job=job_id)

    # ------------------------------------------------------------- execução

    def devidos(self, agora: datetime | None = None) -> list[JobDefinition]:
        """Jobs SCHEDULED cujo instante chegou. DISABLED/CANCELLED nunca entram."""
        agora = agora or self._agora()
        return [d for d in self.armazem.listar()
                if d.estado is JobState.SCHEDULED
                and d.proximo_em is not None and d.proximo_em <= agora]

    def executar_devidos(self, agora: datetime | None = None) -> list[JobExecution]:
        agora = agora or self._agora()
        return [self.executar_job(d, agora) for d in self.devidos(agora)]

    def executar_ocorrencia(self, d: JobDefinition, inst: JobInstance,
                            agora: datetime, credencial=None) -> JobExecution:
        """Executa UMA ocorrência já identificada, com autoridade FRESCA.

        É a entrada usada pelo ticker: ele resolve a autorização por ocorrência
        e a entrega aqui. O scheduler não guarda nem reaproveita credencial.
        """
        return self._executar(d, inst, agora, credencial)

    def executar_job(self, d: JobDefinition, agora: datetime) -> JobExecution:
        """Executa UMA ocorrência, com dedup e reagendamento.

        A ocorrência é identificada pelo instante PLANEJADO (`proximo_em`), não
        pelo relógio de agora — senão duas execuções no mesmo tick viravam
        ocorrências distintas e o dedup não serviria para nada.
        """
        inst = JobInstance(job_id=d.job_id,
                           ocorrencia=(d.proximo_em or agora).isoformat())
        return self._executar(d, inst, agora, None)

    def _executar(self, d: JobDefinition, inst: JobInstance, agora: datetime,
                  credencial) -> JobExecution:
        if d.estado in (JobState.DISABLED, JobState.CANCELLED):
            self._auditar("scheduler.execucao.recusada", job=d.job_id,
                          motivo=d.estado.value)
            return JobExecution(inst, d.estado, f"job {d.estado.value}")

        if not self.armazem.reservar(inst):
            self._auditar("scheduler.ocorrencia.duplicada", job=d.job_id,
                          ocorrencia=inst.ocorrencia)
            return JobExecution(inst, JobState.SUCCEEDED,
                                "ocorrência já executada (dedup)")

        self._mudar_estado(d.job_id, JobState.RUNNING)
        efeito = False
        try:
            if self._executor is None:
                raise ErroScheduler("scheduler sem executor governado ligado")
            # a AUTORIDADE é obtida agora, no instante da execução — nunca
            # persistida junto com o job
            resultado = (self._executor(d, inst, credencial)
                         if credencial is not None else self._executor(d, inst))
            efeito = bool(getattr(resultado, "efeito_aplicado", False))
            self.armazem.concluir(inst, JobState.SUCCEEDED, efeito=efeito)
            final = JobState.SUCCEEDED
            detalhe = ""
        except Exception as exc:
            detalhe = f"{type(exc).__name__}: {exc}"
            self.armazem.concluir(inst, JobState.FAILED, detalhe)
            final = JobState.FAILED
            self._alertar(d, inst, type(exc).__name__, detalhe)

        self._mudar_estado(d.job_id, final)
        self._reagendar(d, agora, final)
        self._auditar("scheduler.execucao.fim", job=d.job_id,
                      ocorrencia=inst.ocorrencia, estado=final.value,
                      efeito=efeito)
        return JobExecution(inst, final, detalhe, efeito_aplicado=efeito)

    def mais_recente_ate(self, d: JobDefinition, agora: datetime) -> datetime | None:
        """Última ocorrência planejada que já venceu — sem teto de catch-up.

        `SKIP` precisa da MAIS RECENTE, não da última dentro do limite de
        catch-up: são perguntas diferentes, e confundi-las fazia SKIP executar
        uma ocorrência velha depois de downtime longo.
        """
        atual = d.proximo_em
        if atual is None or atual > agora:
            return None
        limite = 0
        while limite < 500000:
            seguinte = self.proximo_apos(d, atual)
            if seguinte is None or seguinte > agora:
                return atual
            atual = seguinte
            limite += 1
        return atual

    def proximo_apos(self, d: JobDefinition, base: datetime) -> datetime | None:
        """Próximo disparo depois de `base`, pela agenda do job (cron ou intervalo)."""
        return d.agenda().proximo(base)

    def _alertar(self, d: JobDefinition, inst: JobInstance, classe: str,
                 detalhe: str, estado=None) -> None:
        """ABSORPTION-06: o estado vem da FONTE ÚNICA, não de um literal aqui.

        Antes este método cravava `effect_state="UNKNOWN"` enquanto o Ticker
        cravava `"NO_EFFECT"` para a MESMA ocorrência — dois intérpretes do
        mesmo fato, dois alertas contraditórios.
        """
        if self.alertas is None:
            return
        from nomos.adapters.alertas import EventoFalha
        from nomos.adapters.resultado import de_execucao
        if estado is None:
            estado = de_execucao(houve_excecao=True, efeito_aplicado=False,
                                 error_class=classe, detalhe=detalhe or "")
        if not estado.alerta:
            return
        self.alertas.emitir(EventoFalha(
            job_id=d.job_id, occurrence_id=inst.chave, capability=d.capacidade,
            error_class=estado.error_class or classe,
            effect_state=estado.effect_state, detalhe=estado.mensagem))

    def _reagendar(self, d: JobDefinition, agora: datetime, final: JobState) -> None:
        atual = self.armazem.obter(d.job_id)
        if atual is None or atual.estado is JobState.CANCELLED:
            return
        if not d.recorrente():
            return                    # one-shot fica no estado final
        base = d.proximo_em or agora
        proximo = self.proximo_apos(d, base)
        # não acumular ocorrências vencidas: avança até o futuro
        limite = 0
        while proximo is not None and proximo <= agora and limite < 100000:
            proximo = self.proximo_apos(d, proximo)
            limite += 1
        if proximo is None:
            return
        if transicao_valida(atual.estado, JobState.SCHEDULED):
            self.armazem.salvar(replace(atual, estado=JobState.SCHEDULED,
                                        proximo_em=proximo))
