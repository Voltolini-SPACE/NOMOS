"""NOMOS adapters.resultado — taxonomia canônica de resultado (ABSORPTION-06 / ETAPA 3).

O censo independente da ABSORPTION-05 achou o problema: uma MESMA ocorrência
produzia dois alertas discordando entre si — `Scheduler._alertar` dizia
`effect_state=UNKNOWN` e `Ticker._alertar` dizia `NO_EFFECT`. O operador via
dois avisos contraditórios sobre se o mundo mudou.

A causa não era um dos dois estar errado: era **os dois interpretarem o mesmo
fato independentemente**. Dois intérpretes de um fato só produzem uma verdade
por acidente.

Este módulo é a fonte ÚNICA. Scheduler e Ticker não decidem mais nada sobre
resultado — eles relatam o que aconteceu e recebem de volta o estado canônico,
a severidade e a mensagem de operador.

## A taxonomia

    EXECUTED_EFFECT      rodou e o mundo mudou
    EXECUTED_NO_EFFECT   rodou, sem efeito externo (leitura, no-op, dedup)
    DENIED               política/autorização recusou — nada rodou
    FAILED               tentou, falhou; o efeito é DESCONHECIDO
    UNKNOWN              não dá para afirmar sequer se tentou
    MISSED               ocorrência vencida que a política de catch-up pulou
    RECOVERED            ocorrência atrasada executada com sucesso

## Por que `DENIED` não é `FAILED`

Recusa é o sistema funcionando; falha é o sistema quebrando. Misturar os dois
faz o operador tratar negação de política como incidente — e, pior, faz
incidente parecer rotina. A severidade separa os dois.

## Por que `FAILED` implica efeito DESCONHECIDO

Um executor que levantou no meio pode ter mudado o mundo antes de levantar.
Afirmar `NO_EFFECT` aí seria uma promessa que ninguém checou. Só é
`EXECUTED_NO_EFFECT` quando se SABE que nada mudou.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ResultadoOcorrencia(str, Enum):
    EXECUTED_EFFECT = "EXECUTED_EFFECT"
    EXECUTED_NO_EFFECT = "EXECUTED_NO_EFFECT"
    DENIED = "DENIED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    MISSED = "MISSED"
    RECOVERED = "RECOVERED"


class Severidade(str, Enum):
    INFO = "INFO"
    AVISO = "AVISO"
    ERRO = "ERRO"


# Estado do EFEITO derivado do resultado. É derivação, não escolha — por isso
# vive numa tabela e não em `if`s espalhados por dois módulos.
_EFEITO = {
    ResultadoOcorrencia.EXECUTED_EFFECT: "EFFECT_APPLIED",
    ResultadoOcorrencia.EXECUTED_NO_EFFECT: "NO_EFFECT",
    ResultadoOcorrencia.DENIED: "NO_EFFECT",       # negado antes de tocar nada
    ResultadoOcorrencia.FAILED: "UNKNOWN",         # pode ter mudado antes de cair
    ResultadoOcorrencia.UNKNOWN: "UNKNOWN",
    ResultadoOcorrencia.MISSED: "NO_EFFECT",       # nunca chegou a rodar
    ResultadoOcorrencia.RECOVERED: "EFFECT_APPLIED",
}

_SEVERIDADE = {
    ResultadoOcorrencia.EXECUTED_EFFECT: Severidade.INFO,
    ResultadoOcorrencia.EXECUTED_NO_EFFECT: Severidade.INFO,
    ResultadoOcorrencia.RECOVERED: Severidade.INFO,
    ResultadoOcorrencia.MISSED: Severidade.AVISO,
    ResultadoOcorrencia.DENIED: Severidade.AVISO,   # é o sistema funcionando
    ResultadoOcorrencia.FAILED: Severidade.ERRO,
    ResultadoOcorrencia.UNKNOWN: Severidade.ERRO,
}

_MENSAGEM = {
    ResultadoOcorrencia.EXECUTED_EFFECT: "executou e aplicou efeito",
    ResultadoOcorrencia.EXECUTED_NO_EFFECT: "executou sem efeito externo",
    ResultadoOcorrencia.DENIED: "recusado pela política — nada foi executado",
    ResultadoOcorrencia.FAILED: "falhou; o efeito é DESCONHECIDO — verifique antes de repetir",
    ResultadoOcorrencia.UNKNOWN: "estado indeterminado — verifique manualmente",
    ResultadoOcorrencia.MISSED: "ocorrência vencida pulada pela política de catch-up",
    ResultadoOcorrencia.RECOVERED: "ocorrência atrasada recuperada com sucesso",
}

# Só estes ALERTAM. Sucesso não vira alerta — alerta que dispara sempre é
# ruído, e ruído treina o operador a ignorar.
_ALERTA = frozenset({
    ResultadoOcorrencia.DENIED, ResultadoOcorrencia.FAILED,
    ResultadoOcorrencia.UNKNOWN, ResultadoOcorrencia.MISSED,
})


@dataclass(frozen=True)
class EstadoCanonico:
    """O que Scheduler e Ticker consultam em vez de decidir."""
    resultado: ResultadoOcorrencia
    effect_state: str
    severidade: Severidade
    mensagem: str
    error_class: str = ""

    @property
    def alerta(self) -> bool:
        return self.resultado in _ALERTA

    @property
    def autoriza_retry(self) -> bool:
        """Repetir só é seguro quando se SABE que nada aconteceu.

        `FAILED`/`UNKNOWN` têm efeito desconhecido: repetir às cegas pode
        duplicar. A decisão final ainda passa pela idempotência do registro —
        isto é o piso, não o teto.
        """
        return self.effect_state == "NO_EFFECT" and self.resultado is not ResultadoOcorrencia.DENIED

    def dict(self) -> dict:
        return {"resultado": self.resultado.value,
                "effect_state": self.effect_state,
                "severidade": self.severidade.value,
                "mensagem": self.mensagem,
                "error_class": self.error_class}


def canonico(resultado: ResultadoOcorrencia, *, error_class: str = "",
             detalhe: str = "") -> EstadoCanonico:
    """Fonte única. Todo `effect_state`, severidade e mensagem sai daqui."""
    if not isinstance(resultado, ResultadoOcorrencia):
        raise ValueError(f"resultado não canônico: {resultado!r}")
    mensagem = _MENSAGEM[resultado]
    if detalhe:
        mensagem = f"{mensagem}: {detalhe[:200]}"
    return EstadoCanonico(resultado=resultado, effect_state=_EFEITO[resultado],
                          severidade=_SEVERIDADE[resultado], mensagem=mensagem,
                          error_class=error_class)


def de_execucao(*, houve_excecao: bool, efeito_aplicado: bool,
                negado: bool = False, error_class: str = "",
                detalhe: str = "", recuperada: bool = False) -> EstadoCanonico:
    """Classifica UM fato observado. É o único ponto onde isso é decidido.

    Ordem importa: negação vem antes de falha (recusa não é quebra), e falha
    vem antes de sucesso (quem levantou não "executou sem efeito").
    """
    if negado:
        return canonico(ResultadoOcorrencia.DENIED, error_class=error_class,
                        detalhe=detalhe)
    if houve_excecao:
        return canonico(ResultadoOcorrencia.FAILED, error_class=error_class,
                        detalhe=detalhe)
    if efeito_aplicado:
        return canonico(
            ResultadoOcorrencia.RECOVERED if recuperada
            else ResultadoOcorrencia.EXECUTED_EFFECT, detalhe=detalhe)
    return canonico(ResultadoOcorrencia.EXECUTED_NO_EFFECT, detalhe=detalhe)
