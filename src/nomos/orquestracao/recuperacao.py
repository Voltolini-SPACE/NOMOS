"""NOMOS orquestracao.recuperacao — retry, backoff e circuit-breaker (NH-004).

O que o NOMOS não tinha: sobreviver a falha transiente sem operador. Regras
(todas fail-closed; hardening da ETAPA 12 da missão NH):

- retry SÓ quando o REGISTRO de capacidades diz que a ferramenta é idempotente
  (parâmetro `idempotente=`, autoritativo; ABSORPTION-01) — repetir efeito
  colateral às cegas é pior que falhar; não-idempotente falha na 1ª tentativa.
  O campo `no.idempotente` NÃO é consultado aqui: plano não decide risco;
- backoff exponencial com teto (relógio injetável: teste não dorme);
- circuit-breaker POR FERRAMENTA: N falhas consecutivas abrem o circuito;
  chamada com circuito aberto falha imediatamente (sem tempestade de retry);
  um sucesso fecha o circuito;
- orçamento global de tentativas por missão: esgotado ⇒ falha fechada
  (anti retry-storm; um gerenciador = uma missão);
- exceção do executor NUNCA escapa (vira falha com o tipo no motivo);
- timeout duro de execução é responsabilidade do sandbox (`runtime/sandbox`),
  que já mata processo por tempo — aqui não se duplica esse mecanismo.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PoliticaRecuperacao:
    max_tentativas: int = 2        # por nó (idempotente); não-idempotente = 1
    backoff_base: float = 0.5      # segundos; cresce 2^n até o teto
    backoff_teto: float = 8.0
    circuito_limite: int = 3       # falhas consecutivas p/ abrir o circuito
    orcamento_missao: int = 20     # total de tentativas da missão inteira


class GerenciadorRecuperacao:
    """Um gerenciador por missão (o orçamento é da missão, não do processo)."""

    def __init__(self, politica: PoliticaRecuperacao | None = None,
                 audit=None, dormir: Callable[[float], None] = time.sleep):
        self.politica = politica or PoliticaRecuperacao()
        self.audit = audit
        self.dormir = dormir
        self._falhas_consecutivas: dict[str, int] = {}
        self._tentativas_gastas = 0

    def _auditar(self, evento: str, **campos) -> None:
        if self.audit is not None:
            self.audit.append(evento, **campos)

    def _circuito_aberto(self, ferramenta: str) -> bool:
        return (self._falhas_consecutivas.get(ferramenta, 0)
                >= self.politica.circuito_limite)

    def executar(self, no, executor: Callable, params: dict,
                 *, idempotente: bool | None = None):
        """(ok, resultado|motivo, tentativas) — contrato do Orquestrador._rodar.

        `idempotente` é AUTORITATIVO e vem do registro de capacidades
        (ABSORPTION-01). Deliberadamente NÃO se lê `no.idempotente`: o nó é
        dado de plano, e plano não decide o próprio risco. Ausente ⇒ False
        (fail-closed): perder um retry é seguro, repetir efeito colateral
        não autorizado não é.
        """
        idempotente = bool(idempotente)
        ferramenta = no.ferramenta
        if self._circuito_aberto(ferramenta):
            self._auditar("recuperacao.circuito.rejeitou", no=no.id,
                          ferramenta=ferramenta)
            return False, (f"circuito aberto para '{ferramenta}' "
                           f"({self.politica.circuito_limite} falhas consecutivas)"), 0
        if self._tentativas_gastas >= self.politica.orcamento_missao:
            self._auditar("recuperacao.orcamento.esgotado", no=no.id,
                          ferramenta=ferramenta,
                          orcamento=self.politica.orcamento_missao)
            return False, ("orçamento de tentativas da missão esgotado "
                           f"({self.politica.orcamento_missao})"), 0
        maximo = self.politica.max_tentativas if idempotente else 1
        tentativas = 0
        ultimo_motivo = ""
        while tentativas < maximo:
            if self._tentativas_gastas >= self.politica.orcamento_missao:
                self._auditar("recuperacao.orcamento.esgotado", no=no.id,
                              ferramenta=ferramenta,
                              orcamento=self.politica.orcamento_missao)
                break
            tentativas += 1
            self._tentativas_gastas += 1
            try:
                resultado = executor(**params)
                self._falhas_consecutivas[ferramenta] = 0     # sucesso fecha circuito
                if tentativas > 1:
                    self._auditar("recuperacao.recuperou", no=no.id,
                                  ferramenta=ferramenta, tentativas=tentativas)
                return True, resultado, tentativas
            except Exception as exc:
                ultimo_motivo = f"{type(exc).__name__}: {exc}"
                falhas = self._falhas_consecutivas.get(ferramenta, 0) + 1
                self._falhas_consecutivas[ferramenta] = falhas
                self._auditar("recuperacao.tentativa.falhou", no=no.id,
                              ferramenta=ferramenta, tentativa=tentativas,
                              motivo=type(exc).__name__)
                if falhas == self.politica.circuito_limite:
                    self._auditar("recuperacao.circuito.aberto",
                                  ferramenta=ferramenta, falhas=falhas)
                if not idempotente:
                    self._auditar("recuperacao.sem_retry", no=no.id,
                                  ferramenta=ferramenta,
                                  motivo="nó não idempotente")
                    break
                if self._circuito_aberto(ferramenta):
                    break                                     # não insistir com circuito aberto
                if tentativas < maximo:
                    pausa = min(self.politica.backoff_base * (2 ** (tentativas - 1)),
                                self.politica.backoff_teto)
                    self.dormir(pausa)
        if tentativas >= maximo and idempotente:
            motivo = f"tentativas esgotadas ({tentativas}): {ultimo_motivo}"
        else:
            motivo = ultimo_motivo or "falha sem execução (orçamento/circuito)"
        return False, motivo, tentativas
