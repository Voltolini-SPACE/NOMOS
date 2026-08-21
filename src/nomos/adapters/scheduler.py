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
from datetime import datetime, timedelta, timezone
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
    # P2: negação do PDP é DECISÃO DE SEGURANÇA, não erro operacional, e é
    # TERMINAL. Antes o ticker devolvia `None` sem persistir nada: a ocorrência
    # continuava devida, o job era reexaminado a cada tick para sempre, o
    # autorizador era chamado de novo toda vez, e nenhum contador registrava a
    # recusa. Um job negado que volta sozinho para a fila não foi negado — foi
    # adiado.
    DENIED = "DENIED"


# Transições permitidas. Tudo o que não está aqui é recusado — a máquina de
# estados é allowlist, como todo o resto do NOMOS.
TRANSICOES: dict[JobState, frozenset[JobState]] = {
    JobState.CREATED:   frozenset({JobState.SCHEDULED, JobState.DISABLED,
                                   JobState.CANCELLED}),
    JobState.SCHEDULED: frozenset({JobState.RUNNING, JobState.DISABLED,
                                   JobState.CANCELLED, JobState.DENIED}),
    JobState.RUNNING:   frozenset({JobState.SUCCEEDED, JobState.FAILED,
                                   JobState.CANCELLED}),
    JobState.SUCCEEDED: frozenset({JobState.SCHEDULED, JobState.DISABLED,
                                   JobState.CANCELLED}),
    JobState.FAILED:    frozenset({JobState.SCHEDULED, JobState.DISABLED,
                                   JobState.CANCELLED}),
    JobState.DISABLED:  frozenset({JobState.SCHEDULED, JobState.CANCELLED}),
    JobState.CANCELLED: frozenset(),          # terminal: não ressuscita
    # DENIED é TERMINAL: sair dele exige AUTORIDADE NOVA, não um tick a mais.
    # A única saída é o operador reabilitar explicitamente — e `habilitar()`
    # não está aqui de propósito: reabilitar um job negado é decidir de novo,
    # e essa decisão é do humano, pela capacidade governada `sched-habilitar`.
    JobState.DENIED: frozenset(),
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
    # NH-018 (ambos opt-in; default = comportamento clássico):
    # continuidade: a ocorrência N+1 recebe resumo compacto do fim da N;
    # monitorar_alvo: só dispara efeito quando o hash do alvo muda.
    continuidade: bool = False
    monitorar_alvo: str = ""

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
            # NH-018: colunas aditivas (mesmo padrão provado do `schedule`)
            if "continuidade" not in cols:
                c.execute("ALTER TABLE jobs ADD COLUMN "
                          "continuidade INTEGER DEFAULT 0")
            if "monitorar_alvo" not in cols:
                c.execute("ALTER TABLE jobs ADD COLUMN "
                          "monitorar_alvo TEXT DEFAULT ''")
            # NH-018: notepad durável por job — quota por chave, verificável
            # linha a linha; expurgo junto com o job (nota órfã = vazamento)
            c.execute("""CREATE TABLE IF NOT EXISTS job_notas (
                job_id TEXT NOT NULL, chave TEXT NOT NULL,
                valor TEXT NOT NULL, atualizado_em TEXT NOT NULL,
                PRIMARY KEY(job_id, chave))""")
            # PRIMARY KEY na chave da ocorrência: o INSERT duplicado FALHA.
            # É o dedup — e ele acontece ANTES do efeito, não depois.
            c.execute("""CREATE TABLE IF NOT EXISTS ocorrencias (
                chave TEXT PRIMARY KEY, job_id TEXT NOT NULL,
                ocorrencia TEXT NOT NULL, iniciada_em TEXT NOT NULL,
                estado TEXT NOT NULL, detalhe TEXT NOT NULL DEFAULT '',
                efeito INTEGER NOT NULL DEFAULT 0)""")
            # 0600 nos SIDECARS também, não só no .db. O `PRAGMA journal_mode
            # =WAL` roda antes daqui e já criou `-wal`/`-shm` com o padrão
            # 0644 — e o `-wal` carrega a coluna `argumentos` dos jobs em
            # texto claro. Proteger só o arquivo principal é proteger a porta
            # e deixar a janela aberta.
            for alvo in (self.caminho,
                         self.caminho.with_name(self.caminho.name + "-wal"),
                         self.caminho.with_name(self.caminho.name + "-shm")):
                try:
                    os.chmod(alvo, 0o600)
                except OSError:
                    pass

    # ------------------------------------------------------------ definições

    def salvar(self, d: JobDefinition) -> None:
        # Lista EXPLÍCITA de colunas (achado do juiz da OPERACAO-01): o
        # `INSERT ... VALUES (?,...)` posicional quebrava em runtime na
        # primeira coluna nova de migração aditiva — a tabela crescia e o
        # INSERT continuava contando 11.
        with self._lock, self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO jobs
                (job_id, sujeito, capacidade, argumentos, alvo, intervalo_s,
                 proximo_em, estado, criado_em, tz, schedule,
                 continuidade, monitorar_alvo)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (d.job_id, d.sujeito, d.capacidade,
                       json.dumps(d.argumentos, ensure_ascii=False), d.alvo,
                       d.intervalo_s,
                       d.proximo_em.isoformat() if d.proximo_em else None,
                       d.estado.value,
                       (d.criado_em or datetime.now(timezone.utc)).isoformat(),
                       d.tz,
                       json.dumps(d.agenda().dict(), ensure_ascii=False),
                       1 if d.continuidade else 0,
                       d.monitorar_alvo or ""))

    # ------------------------------------------------------- notepad (NH-018)

    NOTA_CHAVE_MAX = 64
    NOTA_VALOR_MAX = 4096          # bytes utf-8; nunca trunca — recusa
    NOTA_CHAVES_MAX = 32           # por job

    def nota_escrever(self, job_id: str, chave: str, valor: str) -> None:
        from nomos.kernel.audit import redact_text
        if not chave or len(chave.encode()) > self.NOTA_CHAVE_MAX:
            raise ErroInvalido(f"chave de nota inválida (1..{self.NOTA_CHAVE_MAX} bytes)")
        if len(str(valor).encode()) > self.NOTA_VALOR_MAX:
            raise ErroInvalido(
                f"valor de nota excede {self.NOTA_VALOR_MAX} bytes — "
                "recusado (nunca truncado em silêncio)")
        with self._lock, self._conn() as c:
            existentes = {r[0] for r in c.execute(
                "SELECT chave FROM job_notas WHERE job_id=?", (job_id,))}
            # Chaves de SISTEMA (`__*`) são ISENTAS da quota (achado da
            # revisão adversarial): com as 32 chaves do job ocupadas, o
            # `__monitor_hash` estourava a quota DEPOIS do efeito aplicado —
            # a ocorrência saía FAILED com efeito real feito, o hash nunca
            # persistia e TODO tick re-executava o efeito para sempre. A
            # quota existe para conter o JOB, não para calar o scheduler.
            de_usuario = {k for k in existentes if not k.startswith("__")}
            if (not chave.startswith("__") and chave not in de_usuario
                    and len(de_usuario) >= self.NOTA_CHAVES_MAX):
                raise ErroInvalido(
                    f"job '{job_id}' já tem {self.NOTA_CHAVES_MAX} notas — "
                    "apague antes de criar novas")
            c.execute("""INSERT OR REPLACE INTO job_notas
                         (job_id, chave, valor, atualizado_em)
                         VALUES (?,?,?,?)""",
                      (job_id, chave, redact_text(str(valor)),
                       datetime.now(timezone.utc).isoformat()))

    def nota_ler(self, job_id: str, chave: str) -> str | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT valor FROM job_notas WHERE job_id=? AND chave=?",
                          (job_id, chave)).fetchone()
        return r[0] if r else None

    def notas_de(self, job_id: str) -> dict[str, str]:
        with self._lock, self._conn() as c:
            return {r[0]: r[1] for r in c.execute(
                "SELECT chave, valor FROM job_notas WHERE job_id=? "
                "ORDER BY chave", (job_id,))}

    def notas_apagar(self, job_id: str) -> int:
        with self._lock, self._conn() as c:
            cur = c.execute("DELETE FROM job_notas WHERE job_id=?", (job_id,))
            return cur.rowcount

    def obter(self, job_id: str) -> JobDefinition | None:
        with self._lock, self._conn() as c:
            r = c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return _linha_para_def(r) if r else None

    def listar(self) -> list[JobDefinition]:
        """Jobs legíveis. Uma linha corrompida NÃO derruba a coleção.

        Antes isto era uma list-comprehension: uma única linha com estado
        inválido ou `schedule` ilegível levantava e levava junto `listar()`,
        `devidos()`, `tick()` e `rodar_ate()`. No daemon, o efeito era total —
        um registro ruim e NENHUM job voltava a rodar, calado.

        Fail-closed continua valendo, mas POR JOB: a linha ilegível não vira
        um default (isso seria o rebaixamento silencioso que a 04 fechou), não
        executa nunca, e fica registrada em `ilegiveis()` para ser mostrada ao
        operador. Sumir com ela seria pior que o defeito original: o operador
        deixaria de saber que o job existe.
        """
        with self._lock, self._conn() as c:
            rs = c.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()
        saida, ruins = [], {}
        for r in rs:
            try:
                saida.append(_linha_para_def(r))
            except Exception as exc:
                ruins[str(r[0])] = f"{type(exc).__name__}: {exc}"
        self._ilegiveis = ruins
        return saida

    def ilegiveis(self) -> dict[str, str]:
        """`{job_id: motivo}` das linhas em quarentena na última listagem."""
        with self._lock, self._conn() as c:
            rs = c.execute("SELECT * FROM jobs ORDER BY job_id").fetchall()
        ruins = {}
        for r in rs:
            try:
                _linha_para_def(r)
            except Exception as exc:
                ruins[str(r[0])] = f"{type(exc).__name__}: {exc}"
        return ruins

    def apagar(self, job_id: str) -> None:
        with self._lock, self._conn() as c:
            c.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
            # NH-018: nota órfã é vazamento de quota e de dado
            c.execute("DELETE FROM job_notas WHERE job_id=?", (job_id,))

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
        schedule=schedule,
        # NH-018: guarda posicional como a do `schedule` — banco antigo
        # (linha curta) lê com os defaults, sem quebrar
        continuidade=bool(r[11]) if len(r) > 11 and r[11] else False,
        monitorar_alvo=(r[12] or "") if len(r) > 12 else "")


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
              schedule: ScheduleSpec | None = None,
              continuidade: bool = False,
              monitorar_alvo: str = "") -> JobDefinition:
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
        if monitorar_alvo:
            # NH-018c: valida o alvo NA CRIAÇÃO (teto de arquivos, hash
            # computável) — recusa aqui, não degradação na milésima ocorrência
            from nomos.adapters.monitor import hash_alvo
            hash_alvo(monitorar_alvo)
        d = JobDefinition(
            job_id=job_id, sujeito=sujeito, capacidade=capacidade,
            argumentos=dict(argumentos or {}), alvo=alvo,
            intervalo_s=intervalo_s, proximo_em=primeiro_em or agora,
            estado=JobState.SCHEDULED, criado_em=agora, tz=tz,
            schedule=schedule, continuidade=bool(continuidade),
            monitorar_alvo=str(monitorar_alvo or ""))
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
        """Executa UMA ocorrência com encerramento GARANTIDO em toda saída.

        O censo adversarial achou dois defeitos que eram o mesmo defeito:

        - **D2** (livelock): quando o processo morria entre `reservar()` e
          `concluir()`, o restart via a ocorrência como duplicada e RETORNAVA
          antes de reagendar. `proximo_em` ficava cravado no instante original
          e o job era reexaminado para sempre — 10 ticks, 10 chamadas ao PDP,
          zero efeitos, zero alertas, e `executadas=1` reportado toda vez. Um
          travamento que se anuncia como sucesso é pior que um que grita.
        - **D3** (queda do daemon): `_mudar_estado` ficava FORA do `try`, então
          um `sched-cancelar` do operador caindo entre `devidos()` e a execução
          fazia `ErroScheduler: CANCELLED → RUNNING` subir até `rodar_ate` e
          matar o ticker, com a ocorrência RUNNING órfã — que é a entrada do D2.

        A causa era estrutural: o método tinha QUATRO saídas e só a feliz
        alcançava estado + reagendamento + auditoria. Uma função com saídas que
        fazem coisas diferentes do encerramento não tem invariante, tem sorte.

        Agora existe um só ponto de saída (`_encerrar`), alcançado por todos os
        caminhos, e as transições de estado do JOB — que são do operador e
        podem legitimamente falhar — não derrubam a EXECUÇÃO da ocorrência.
        """
        if d.estado in (JobState.DISABLED, JobState.CANCELLED):
            self._auditar("scheduler.execucao.recusada", job=d.job_id,
                          motivo=d.estado.value)
            return JobExecution(inst, d.estado, f"job {d.estado.value}")

        if not self.armazem.reservar(inst):
            return self._ocorrencia_ja_reservada(d, inst, agora)

        # A transição do JOB é do operador e pode falhar por corrida legítima
        # (ele cancelou agora mesmo). Isso NÃO pode derrubar a ocorrência já
        # reservada: quem reservou tem de chegar ao encerramento.
        self._transicao_tolerante(d.job_id, JobState.RUNNING)
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

        return self._encerrar(d, inst, agora, final, detalhe, efeito)

    def _encerrar(self, d: JobDefinition, inst: JobInstance, agora: datetime,
                  final: JobState, detalhe: str, efeito: bool) -> JobExecution:
        """O único fim. Estado, reagendamento e trilha acontecem AQUI."""
        if d.continuidade:
            # NH-018b: resumo compacto e determinístico da ocorrência que
            # terminou — cobre sucesso E falha (é o único fim, por desenho).
            # `redact_text` no detalhe: exceção pode ecoar segredo.
            from nomos.kernel.audit import redact_text
            resumo = json.dumps({
                "ocorrencia": inst.ocorrencia, "estado": final.value,
                "efeito": bool(efeito),
                "detalhe": redact_text(str(detalhe or ""))[:200],
                "concluida_em": agora.isoformat(),
            }, ensure_ascii=False, sort_keys=True)
            try:
                self.armazem.nota_escrever(d.job_id, "__resumo_anterior",
                                           resumo)
            except ErroInvalido:
                pass          # quota estourada não pode impedir o encerramento
        self._transicao_tolerante(d.job_id, final)
        self._reagendar(d, agora, final)
        self._auditar("scheduler.execucao.fim", job=d.job_id,
                      ocorrencia=inst.ocorrencia, estado=final.value,
                      efeito=efeito)
        return JobExecution(inst, final, detalhe, efeito_aplicado=efeito)

    def _transicao_tolerante(self, job_id: str, novo: JobState) -> None:
        """Muda o estado do job sem derrubar a ocorrência em curso.

        `_mudar_estado` continua levantando para o OPERADOR — a allowlist de
        transições é invariante e não foi afrouxada. O que muda é quem absorve
        a exceção: aqui dentro, onde o job pode ter sido cancelado ou apagado
        por baixo de uma execução que já está acontecendo. Recusar a transição
        é a resposta certa; matar o daemon não é.
        """
        try:
            self._mudar_estado(job_id, novo)
        except Exception as exc:
            self._auditar("scheduler.transicao.recusada", job=job_id,
                          para=novo.value, motivo=f"{type(exc).__name__}: {exc}")

    def negar_ocorrencia(self, d: JobDefinition, inst: JobInstance,
                         agora: datetime, motivo: str) -> JobExecution:
        """Persiste a NEGAÇÃO. Chamada pelo ticker quando a autoridade recusa.

        Reserva a ocorrência antes de marcar — a mesma chave de dedup que
        impede efeito duplicado impede também negação contada duas vezes. Sem
        isso, `negadas` incrementaria a cada tick para a mesma ocorrência.
        """
        if not self.armazem.reservar(inst):
            return JobExecution(inst, JobState.DENIED,
                                "ocorrência já resolvida (dedup)")
        self.armazem.concluir(inst, JobState.DENIED, motivo)
        self._auditar("scheduler.ocorrencia.negada", job=d.job_id,
                      ocorrencia=inst.ocorrencia, motivo=motivo[:200])
        # A OCORRÊNCIA é sempre marcada DENIED. O JOB só vai a terminal quando
        # não há próxima: negar uma ocorrência não é negar as futuras, e o
        # modelo inteiro se apoia em autorizar POR OCORRÊNCIA — matar um job
        # recorrente por causa de um estado transitório da política
        # contradiria isso. ONE_SHOT não tem próxima, então para ele a
        # negação é o fim.
        if d.recorrente():
            self._reagendar(d, agora, JobState.DENIED)
        else:
            self._transicao_tolerante(d.job_id, JobState.DENIED)
        return JobExecution(inst, JobState.DENIED, motivo)

    def _ocorrencia_ja_reservada(self, d: JobDefinition, inst: JobInstance,
                                 agora: datetime) -> JobExecution:
        """Reserva existente: ou já concluiu (dedup honesto), ou ficou ÓRFÃ.

        Distinguir os dois é o que separa "não repetir o efeito" de "travar o
        job para sempre". A reserva que ficou em RUNNING é de um processo que
        morreu no meio: o efeito dela é DESCONHECIDO — pode ter acontecido —
        então ela não pode ser reexecutada, mas TAMBÉM não pode continuar
        bloqueando a agenda.
        """
        estado_oc = self.armazem.ocorrencia_estado(inst)
        if estado_oc != JobState.RUNNING.value:
            self._auditar("scheduler.ocorrencia.duplicada", job=d.job_id,
                          ocorrencia=inst.ocorrencia)
            return JobExecution(inst, JobState.SUCCEEDED,
                                "ocorrência já executada (dedup)")

        # órfã: fecha como FAILED com efeito DESCONHECIDO e destrava a agenda
        detalhe = ("reserva órfã: processo morreu entre reservar e concluir — "
                   "o efeito é DESCONHECIDO, verifique antes de repetir")
        self.armazem.concluir(inst, JobState.FAILED, detalhe)
        self._alertar(d, inst, "ReservaOrfa", detalhe)
        self._auditar("scheduler.ocorrencia.orfa", job=d.job_id,
                      ocorrencia=inst.ocorrencia)
        return self._encerrar(d, inst, agora, JobState.FAILED, detalhe, False)

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
        # não acumular ocorrências vencidas: avança até o futuro.
        # INTERVAL é aritmética, não iteração: com passo de 1s e três dias de
        # parada, o laço precisaria de 259.200 voltas e batia no teto de
        # 100.000 — devolvendo um instante AINDA no passado. Um teto que
        # silenciosamente deixa o resultado errado é pior que não ter teto.
        esp = d.agenda()
        if (esp.kind is TipoAgenda.INTERVAL and proximo is not None
                and proximo <= agora and esp.intervalo_s):
            atraso = (agora - proximo).total_seconds()
            saltos = int(atraso // esp.intervalo_s) + 1
            proximo = proximo + timedelta(seconds=saltos * esp.intervalo_s)
        limite = 0
        while proximo is not None and proximo <= agora and limite < 100000:
            proximo = self.proximo_apos(d, proximo)
            limite += 1
        if proximo is None:
            return
        if atual.estado is JobState.SCHEDULED:
            # Já está SCHEDULED: reagendar é atualizar a AGENDA, não
            # transicionar. Exigir `transicao_valida(SCHEDULED, SCHEDULED)`
            # aqui — que é falsa, e corretamente falsa — travava o job órfão
            # para sempre: o encerramento chegava até aqui e não salvava nada.
            # Conflato de conceitos: a allowlist governa o CICLO DE VIDA do
            # job, não o instante do próximo disparo. Ela fica intocada.
            self.armazem.salvar(replace(atual, proximo_em=proximo))
        elif transicao_valida(atual.estado, JobState.SCHEDULED):
            self.armazem.salvar(replace(atual, estado=JobState.SCHEDULED,
                                        proximo_em=proximo))
