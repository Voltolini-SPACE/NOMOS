"""NOMOS runtime.agendador — o caller de produção do scheduler (ABSORPTION-05).

A ABSORPTION-04 construiu `Scheduler`, `Ticker` e `script-rodar` e não ligou o
fio: o censo independente encontrou **zero callers em `src/`** para
`registrar_scheduler()` e para `Ticker`. Módulo existir não é capacidade
existir — e a lição já tinha sido dada na 03.

Este módulo é o fio.

    CLI
      → AgendadorGovernado
      → Scheduler (store em NOMOS_HOME/scheduler/jobs.db)
      → registrar_scheduler()  → registro de capacidades (A5 + gate + audit)
      → Ticker (autorizador OBRIGATÓRIO)
      → ocorrência devida → reserva persistente
      → autorização POR OCORRÊNCIA (fresca)
      → PDP → PEP → boundary → adapter → efeito → audit

## Uma só autoridade

Não existe `scheduler_registry`, `scheduler_policy` nem `scheduler_executor`
paralelo. O scheduler usa o MESMO `RegistroCapacidades` que o planner e o PDP
consultam, e a execução de uma ocorrência é a MESMA
`RuntimeGovernado.executar()` de qualquer outra coisa. Um segundo caminho de
execução seria um segundo modelo de segurança — e o segundo sempre é o mais
fraco.

## Autoridade por ocorrência, de verdade

O `autorizador` que este módulo entrega ao ticker constrói um
`RuntimeGovernado` NOVO a cada ocorrência. Isso não é desperdício: é o que faz
a política, o registro e o escopo valerem no instante T2 da execução, e não no
T0 da criação do job. Um `RuntimeGovernado` reaproveitado carregaria a
autorização de sessão emitida lá atrás — autorização eterna com outro nome.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nomos.adapters.alertas import AuditAlertSink
from nomos.adapters.scheduler import ArmazemJobs, JobDefinition, Scheduler
from nomos.adapters.ticker import CatchUp, Ticker


def caminho_do_armazem(home) -> Path:
    """`NOMOS_HOME/scheduler/jobs.db` — um só lugar, previsível e auditável."""
    return Path(home) / "scheduler" / "jobs.db"


@dataclass(frozen=True)
class ConfigAgendador:
    """O que o operador escolheu. Tudo explícito, nada inferido."""
    raizes: tuple[str, ...] = ()
    executaveis: tuple[str, ...] = ()
    catchup: CatchUp = CatchUp.RUN_ONCE
    catchup_max: int = 10
    intervalo_s: float = 1.0


class AgendadorGovernado:
    """Scheduler + Ticker ligados ao runtime governado.

    Construção não executa nada e não regista nada: `preparar()` é o passo
    intencional. Ativação de capacidade nunca acontece por import.
    """

    def __init__(self, ctx, aprovador, config: ConfigAgendador | None = None,
                 *, agora_fn=lambda: datetime.now(timezone.utc)):
        if ctx is None or "policy" not in ctx:
            from nomos.runtime.governado import ErroRuntime
            raise ErroRuntime("contexto sem política carregada — fail-closed")
        if aprovador is None:
            from nomos.runtime.governado import ErroRuntime
            raise ErroRuntime(
                "agendador exige aprovador: registrar capacidade é ato "
                "sensível (A5) e não pode acontecer sem gate")
        self.ctx = ctx
        self.aprovador = aprovador
        self.config = config or ConfigAgendador()
        self._agora = agora_fn
        self.audit = ctx.get("audit")
        self.armazem = ArmazemJobs(caminho_do_armazem(ctx["home"]))
        self.scheduler = Scheduler(
            self.armazem, executor=self._executar_ocorrencia,
            audit=self.audit, agora_fn=agora_fn,
            alert_sink=AuditAlertSink(self.audit) if self.audit else None)
        self.capacidades: list[str] = []
        self._preparado = False

    # ------------------------------------------------------------- preparação

    def preparar(self) -> list[str]:
        """Registra as capacidades de scheduler no registro AUTORITATIVO.

        Usa um `RuntimeGovernado` para obter o registro — o mesmo que o planner
        e o PDP consultam. Registrar é `A5_SKILL_INSTALL`: passa pelo gate,
        exige aprovador e é auditado.
        """
        from nomos.adapters.wiring import registrar_scheduler

        rt = self._runtime()
        self.capacidades = registrar_scheduler(rt.registro, self.scheduler)
        self._registro_ativo = rt.registro
        self._preparado = True
        if self.audit is not None:
            self.audit.append("agendador.preparado",
                              capacidades=",".join(self.capacidades),
                              armazem=str(self.armazem.caminho))
        return list(self.capacidades)

    def _runtime(self):
        """Um `RuntimeGovernado` NOVO — autoridade fresca, sempre.

        Construir de novo a cada ocorrência é o que faz política, registro e
        escopo valerem no instante da EXECUÇÃO, não no da criação do job.
        """
        from nomos.runtime.governado import RuntimeGovernado
        return RuntimeGovernado(
            self.ctx, self.aprovador,
            caminhos=self.config.raizes,
            adapters=bool(self.config.raizes),
            executaveis=self.config.executaveis)

    # ------------------------------------------------------------- execução

    def autorizador(self, definicao: JobDefinition, instancia):
        """Autoridade POR OCORRÊNCIA. `None` ⇒ o ticker recusa a ocorrência.

        Constrói runtime novo (autorização fresca, registro revalidado) e
        confere que a capacidade do job ainda existe e ainda é executável. Se o
        registro mudou desde a criação do job, isto é onde se descobre.
        """
        try:
            rt = self._runtime()
        except Exception:
            return None                       # sem runtime não há autoridade
        if not rt.registro.conhecida(definicao.capacidade):
            if self.audit is not None:
                self.audit.append("agendador.capacidade.sumiu",
                                  job=definicao.job_id,
                                  capacidade=definicao.capacidade)
            return None
        if definicao.capacidade not in rt.executores:
            if self.audit is not None:
                self.audit.append("agendador.capacidade.sem_executor",
                                  job=definicao.job_id,
                                  capacidade=definicao.capacidade)
            return None
        return rt

    def _executar_ocorrencia(self, definicao: JobDefinition, instancia,
                             credencial=None):
        """Executa a capacidade do job pela cadeia governada COMPLETA.

        `credencial` é o `RuntimeGovernado` fresco vindo do autorizador. Sem
        ele, não executa — o scheduler não tem caminho próprio até o adapter.
        """
        from nomos.runtime.governado import ErroRuntime
        rt = credencial
        if rt is None:
            raise ErroRuntime(
                "ocorrência sem autoridade: o agendador não executa sem "
                "runtime governado (fail-closed)")
        passos = [{
            "id": "job",
            "ferramenta": definicao.capacidade,
            "params": dict(definicao.argumentos or {}),
        }]
        if definicao.alvo:
            passos[0]["params"].setdefault("alvo", definicao.alvo)
        resultado = rt.rodar(f"job:{definicao.job_id}", passos=passos)
        if not resultado.ok:
            no = (resultado.missao.nos.get("job")
                  if resultado.missao is not None else None)
            motivo = (no.detalhe if no is not None else resultado.motivo) or "sem detalhe"
            raise ErroRuntime(f"ocorrência falhou: {motivo}")
        return type("R", (), {"efeito_aplicado": True})()

    # ------------------------------------------------------------- ticker

    def ticker(self, *, dormir=None) -> Ticker:
        """Ticker com autorizador OBRIGATÓRIO — o nosso, nunca `None`."""
        if not self._preparado:
            raise RuntimeError("chame `preparar()` antes de montar o ticker")
        extra = {} if dormir is None else {"dormir": dormir}
        return Ticker(self.scheduler, self.autorizador, audit=self.audit,
                      alert_sink=AuditAlertSink(self.audit) if self.audit else None,
                      catchup=self.config.catchup,
                      catchup_max=self.config.catchup_max,
                      intervalo_s=self.config.intervalo_s,
                      agora_fn=self._agora, **extra)
