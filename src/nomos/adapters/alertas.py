"""NOMOS adapters.alertas — evento de falha e sink desacoplado (ABSORPTION-04 / FASE 6).

Fecha `SCHED-15-DELIVERY-E-ALERTA-DE-FALHA` **sem** criar dependência de canal
externo. Duas coisas que costumam nascer grudadas e não deveriam:

    o EVENTO de falha        ≠        o CANAL que o entrega

O scheduler emite o evento. Quem entrega é um `AlertSink`, e trocar o sink não
mexe no scheduler. Telegram, e-mail e afins entram numa missão futura sem
tocar nesta camada — e enquanto não entram, nada fica pendurado esperando um
canal que não existe.

## O evento não carrega segredo

`EventoFalha` guarda identificadores e a CLASSE do erro, não o payload. Uma
mensagem de exceção pode conter caminho, token ou conteúdo de arquivo; por isso
`detalhe` é truncado e o payload original nunca entra. Alerta que vaza o
segredo que deveria proteger é um incidente, não um alerta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

_LIMITE_DETALHE = 300


@dataclass(frozen=True)
class EventoFalha:
    """Falha estruturada de uma ocorrência de scheduler."""
    job_id: str
    occurrence_id: str
    capability: str
    error_class: str
    attempt: int = 1
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc))
    effect_state: str = "UNKNOWN"
    detalhe: str = ""

    def dict(self) -> dict:
        """Forma serializável — já truncada, sem payload."""
        return {
            "job_id": self.job_id,
            "occurrence_id": self.occurrence_id,
            "capability": self.capability,
            "error_class": self.error_class,
            "attempt": self.attempt,
            "timestamp": self.timestamp.astimezone(timezone.utc).isoformat(),
            "effect_state": self.effect_state,
            "detalhe": (self.detalhe or "")[:_LIMITE_DETALHE],
        }


@runtime_checkable
class AlertSink(Protocol):
    """Contrato mínimo. Note o que NÃO está aqui: nada de rede, canal ou fila."""

    nome: str

    def emitir(self, evento: EventoFalha) -> None: ...


class AuditAlertSink:
    """Sink padrão: a trilha de auditoria do próprio NOMOS.

    Escolha deliberada — a trilha já é hash-encadeada e verificável, então o
    alerta herda integridade sem infraestrutura nova. Falha de auditoria
    PROPAGA, como em todo o resto do kernel: alerta que some em silêncio é
    pior que alerta que não existe.
    """

    nome = "audit"

    def __init__(self, audit):
        self.audit = audit

    def emitir(self, evento: EventoFalha) -> None:
        if self.audit is None:
            return
        self.audit.append("scheduler.ocorrencia.falhou", **evento.dict())


class SinkDeTeste:
    """Coleta em memória. Para teste e para o shadow de missões futuras."""

    nome = "teste"

    def __init__(self):
        self.eventos: list[EventoFalha] = []

    def emitir(self, evento: EventoFalha) -> None:
        self.eventos.append(evento)

    def limpar(self) -> None:
        self.eventos.clear()


class SinkComposto:
    """Vários sinks. Um sink quebrado não impede os outros de receberem.

    Aqui a exceção é engolida de propósito — e é a ÚNICA no módulo. O motivo:
    o alerta já está reportando uma falha; deixar o sink derrubar o caminho
    transformaria "o job falhou" em "o processo caiu ao contar que o job
    falhou". Quais sinks falharam fica registrado em `falhas`.
    """

    nome = "composto"

    def __init__(self, *sinks: AlertSink):
        self.sinks = list(sinks)
        self.falhas: list[tuple[str, str]] = []

    def emitir(self, evento: EventoFalha) -> None:
        for sink in self.sinks:
            try:
                sink.emitir(evento)
            except Exception as exc:
                self.falhas.append((getattr(sink, "nome", "?"),
                                    type(exc).__name__))
