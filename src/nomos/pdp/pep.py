"""NOMOS pdp.pep — o Policy Enforcement Point (ABSORPTION-01 / FASE 2).

O PDP decide; o PEP é o único lugar por onde a decisão vira (ou não vira)
efeito. A propriedade que este módulo entrega não é "existe uma checagem" — é
que **não há caminho até o adapter que não passe por aqui**.

Como isso é garantido em Python, que não tem `private` de verdade:

- o executor bruto é CAPTURADO NUMA CLOSURE dentro de `proteger()`. Ele não
  vira atributo do objeto devolvido, então não existe `obj.executor` para
  alguém alcançar — nem por engano, nem de propósito;
- o objeto devolvido é um `PontoDeAplicacao` com `__slots__`, sem `__dict__`:
  ninguém enxerta um caminho alternativo depois;
- chamar o PEP sem uma decisão ALLOW do PDP levanta `NegadoPeloPEP`. Não
  existe modo "seguir mesmo assim".

Isto NÃO substitui o gate A0–A6 do kernel: soma-se a ele. A ordem é
PDP (há autorização válida para isto?) → PEP (aplica) → boundary/gate
(esta política permite agora?) → adapter. Duas perguntas diferentes; nenhuma
delas opcional.
"""
from __future__ import annotations

from typing import Callable

from nomos.pdp.decisor import Decisao, Decisor, Efeito, Motivo, Pedido


class NegadoPeloPEP(PermissionError):
    """Efeito recusado no ponto de aplicação. Carrega a decisão para auditoria."""

    def __init__(self, decisao: Decisao):
        self.decisao = decisao
        super().__init__(f"negado ({decisao.motivo.value}): {decisao.detalhe}"
                         if decisao.detalhe else f"negado ({decisao.motivo.value})")


class PontoDeAplicacao:
    """Envoltório de UM efeito. Sem `__dict__`: nada é enxertado depois."""

    __slots__ = ("_chamar", "capacidade")

    def __init__(self, capacidade: str, chamar: Callable):
        object.__setattr__(self, "capacidade", capacidade)
        object.__setattr__(self, "_chamar", chamar)

    def __call__(self, pedido: Pedido, autorizacao, **params):
        return self._chamar(pedido, autorizacao, params)

    def __repr__(self) -> str:                      # nunca expõe o executor
        return f"<PontoDeAplicacao {self.capacidade!r}>"


def proteger(capacidade: str, executor: Callable, decisor: Decisor,
             *, audit=None) -> PontoDeAplicacao:
    """Devolve o efeito protegido. `executor` fica só na closure.

    Toda chamada exige (pedido, autorizacao). Sem ALLOW do PDP, o executor
    não é sequer referenciado.
    """
    if not callable(executor):
        raise TypeError("executor precisa ser chamável")

    def _aplicar(pedido: Pedido, autorizacao, params: dict):
        # coerência: o PEP não deixa pedir X e executar Y
        if not isinstance(pedido, Pedido) or pedido.capacidade != capacidade:
            decisao = Decisao(Efeito.DENY, Motivo.PEDIDO_MALFORMADO,
                              f"pedido não corresponde a '{capacidade}'")
            _registrar(audit, capacidade, decisao)
            raise NegadoPeloPEP(decisao)
        decisao = decisor.decidir(pedido, autorizacao)
        if not decisao.permitido:
            _registrar(audit, capacidade, decisao)
            raise NegadoPeloPEP(decisao)
        _registrar(audit, capacidade, decisao)
        return executor(**params)

    return PontoDeAplicacao(capacidade, _aplicar)


def _registrar(audit, capacidade: str, decisao: Decisao) -> None:
    if audit is None:
        return
    audit.append("pep.aplicacao", capacidade=capacidade,
                 efeito=decisao.efeito.value, motivo=decisao.motivo.value)
