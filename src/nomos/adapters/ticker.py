"""NOMOS adapters.ticker — o loop que transforma job em ocorrência (FASE 3-4).

    CLOCK → STORE → DUE → RESERVATION → AUTHORIZATION → PDP → PEP
          → BOUNDARY → CAPABILITY → AUDIT → FINALIZE

Componente **foreground e testável**, não daemon. A ABSORPTION-04 proíbe
instalar serviço; o ticker é a peça que um daemon futuro embrulha, e que aqui
já roda sob teste com relógio injetável.

## Autorização é POR OCORRÊNCIA

Um job criado em T0 e executado em T2 não pode usar autoridade de T0. O ticker
não guarda token: para CADA ocorrência ele chama o `autorizador`, que devolve
`(decisor, autorizacao)` frescos. Se a política, o registro ou o escopo mudaram
entre T0 e T2, a decisão em T2 reflete T2 — e o `versoes` do descritor
(ABSORPTION-03) faz o PDP recusar metadata obsoleta.

## Catch-up é explícito

Máquina desligada por 5 horas com um job de 5 em 5 minutos: rodar 60 vezes?
uma? nenhuma? Não deixo isso implícito.

    SKIP             ignora o atrasado, reagenda para a próxima ocorrência
    RUN_ONCE         roda UMA vez (default) e reagenda
    RUN_ALL_BOUNDED  roda as perdidas até um teto explícito

## Sem busy-loop

`rodar_ate` dorme entre passadas com um `dormir` injetável. O teste usa um
relógio falso e não espera de verdade; a produção usa `time.sleep`. Em nenhum
dos dois o loop gira sem pausa.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from nomos.adapters.alertas import AuditAlertSink, EventoFalha
from nomos.adapters.scheduler import JobDefinition, JobInstance, JobState


class CatchUp(str, Enum):
    SKIP = "SKIP"
    RUN_ONCE = "RUN_ONCE"
    RUN_ALL_BOUNDED = "RUN_ALL_BOUNDED"


@dataclass(frozen=True)
class ResultadoTick:
    """O que uma passada fez. `executadas` conta EFEITOS, não tentativas."""
    examinados: int = 0
    executadas: int = 0
    puladas: int = 0
    falhas: int = 0
    negadas: int = 0


class Ticker:
    """Uma passada = `tick()`. Um loop com pausa = `rodar_ate()`."""

    def __init__(self, scheduler, autorizador=None, *, audit=None,
                 alert_sink=None, catchup: CatchUp = CatchUp.RUN_ONCE,
                 catchup_max: int = 10, intervalo_s: float = 1.0,
                 agora_fn=lambda: datetime.now(timezone.utc),
                 dormir=time.sleep):
        self.scheduler = scheduler
        self.autorizador = autorizador
        self.audit = audit
        self.alertas = alert_sink or (AuditAlertSink(audit) if audit else None)
        self.catchup = catchup
        self.catchup_max = max(1, int(catchup_max))
        self.intervalo_s = max(0.0, float(intervalo_s))
        self._agora = agora_fn
        self._dormir = dormir
        self._parar = False

    # ---------------------------------------------------------------- loop

    def parar(self) -> None:
        """Shutdown limpo: a passada corrente termina, e não começa outra."""
        self._parar = True

    def tick(self) -> ResultadoTick:
        agora = self._agora()
        devidos = self.scheduler.devidos(agora)
        r = ResultadoTick(examinados=len(devidos))
        for d in devidos:
            if self._parar:
                break
            r = self._processar(d, agora, r)
        return r

    def rodar_ate(self, condicao=None, max_ticks: int | None = None) -> list[ResultadoTick]:
        """Roda até `parar()`, até `condicao()` virar False, ou `max_ticks`.

        Sempre dorme entre passadas — inclusive quando não houve trabalho. É o
        que impede o busy-loop, e é observável: o teste conta as pausas.
        """
        self._parar = False
        resultados: list[ResultadoTick] = []
        n = 0
        while not self._parar:
            if max_ticks is not None and n >= max_ticks:
                break
            if condicao is not None and not condicao():
                break
            resultados.append(self.tick())
            n += 1
            if self._parar:
                break
            self._dormir(self.intervalo_s)
        return resultados

    # ------------------------------------------------------------ execução

    def _processar(self, d: JobDefinition, agora: datetime,
                   r: ResultadoTick) -> ResultadoTick:
        atrasadas = self._ocorrencias_pendentes(d, agora)
        if not atrasadas:
            return r
        if self.catchup is CatchUp.SKIP and len(atrasadas) > 1:
            # só a mais recente interessa; as antigas são explicitamente puladas
            puladas = len(atrasadas) - 1
            self._auditar("ticker.catchup.pulou", job=d.job_id,
                          politica=self.catchup.value, puladas=puladas)
            atrasadas = atrasadas[-1:]
            r = ResultadoTick(r.examinados, r.executadas, r.puladas + puladas,
                              r.falhas, r.negadas)
        for quando in atrasadas:
            ex = self._executar_ocorrencia(d, quando, agora)
            if ex is None:
                r = ResultadoTick(r.examinados, r.executadas, r.puladas + 1,
                                  r.falhas, r.negadas)
            elif ex.estado_final is JobState.SUCCEEDED:
                r = ResultadoTick(r.examinados, r.executadas + 1, r.puladas,
                                  r.falhas, r.negadas)
            else:
                r = ResultadoTick(r.examinados, r.executadas, r.puladas,
                                  r.falhas + 1, r.negadas)
        return r

    def _ocorrencias_pendentes(self, d: JobDefinition, agora: datetime) -> list[datetime]:
        """Instantes planejados ainda não executados, conforme a política."""
        base = d.proximo_em
        if base is None or base > agora:
            return []
        if self.catchup is CatchUp.RUN_ONCE or not d.recorrente():
            return [base]
        pendentes = [base]
        if self.catchup is CatchUp.RUN_ALL_BOUNDED:
            proximo = base
            while len(pendentes) < self.catchup_max:
                seguinte = self.scheduler.proximo_apos(d, proximo)
                if seguinte is None or seguinte > agora:
                    break
                pendentes.append(seguinte)
                proximo = seguinte
        elif self.catchup is CatchUp.SKIP:
            proximo = base
            while len(pendentes) < self.catchup_max:
                seguinte = self.scheduler.proximo_apos(d, proximo)
                if seguinte is None or seguinte > agora:
                    break
                pendentes.append(seguinte)
                proximo = seguinte
        return pendentes

    def _executar_ocorrencia(self, d: JobDefinition, quando: datetime,
                             agora: datetime):
        """Uma ocorrência: autoridade FRESCA, reserva, execução, finalização."""
        inst = JobInstance(job_id=d.job_id, ocorrencia=quando.isoformat())

        # AUTORIZAÇÃO POR OCORRÊNCIA — nada guardado do momento da criação.
        credencial = None
        if self.autorizador is not None:
            try:
                credencial = self.autorizador(d, inst)
            except Exception as exc:
                self._auditar("ticker.autorizacao.falhou", job=d.job_id,
                              ocorrencia=inst.ocorrencia,
                              erro=type(exc).__name__)
                self._alertar(d, inst, type(exc).__name__, "NO_EFFECT",
                              str(exc))
                return None
            if credencial is None:
                self._auditar("ticker.autorizacao.negada", job=d.job_id,
                              ocorrencia=inst.ocorrencia)
                self._alertar(d, inst, "AutorizacaoNegada", "NO_EFFECT",
                              "autorizador recusou a ocorrência")
                return None

        execucao = self.scheduler.executar_ocorrencia(d, inst, agora,
                                                      credencial=credencial)
        if execucao.estado_final is JobState.FAILED:
            self._alertar(d, inst, "ExecucaoFalhou",
                          "UNKNOWN" if execucao.efeito_aplicado else "NO_EFFECT",
                          execucao.detalhe)
        return execucao

    # ---------------------------------------------------------------- util

    def _auditar(self, evento: str, **campos) -> None:
        if self.audit is not None:
            self.audit.append(evento, **campos)

    def _alertar(self, d: JobDefinition, inst: JobInstance, classe: str,
                 efeito: str, detalhe: str) -> None:
        if self.alertas is None:
            return
        self.alertas.emitir(EventoFalha(
            job_id=d.job_id, occurrence_id=inst.chave, capability=d.capacidade,
            error_class=classe, effect_state=efeito, detalhe=detalhe or "",
            timestamp=self._agora()))
