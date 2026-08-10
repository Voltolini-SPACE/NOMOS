"""NOMOS adapters.contrato — o contrato comum de adapter (ABSORPTION-03 / FASE 1).

Um adapter é o ÚLTIMO elo antes do efeito externo. Por isso ele é o lugar mais
tentador para um atalho — e o único onde um atalho é fatal. Este módulo congela
o que um adapter pode e não pode fazer, com tipos que tornam o abuso difícil de
escrever por acidente.

    REQUEST → REGISTRY → PDP → PEP → BOUNDARY → **ADAPTER** → EFFECT → AUDIT

O adapter recebe `CapabilityContext` **já autorizado**. Ele não decide nada
sobre autoridade:

- não atribui risco (vem do registro, carimbado no contexto);
- não declara idempotência (idem);
- não emite nem assina autorização;
- não altera escopo;
- não pula o PDP — na verdade nem sabe que ele existe;
- não executa capacidade desconhecida;
- não expõe executor bruto fora do PEP.

`CapabilityContext` é `frozen` e seus campos de autoridade são derivados na
construção a partir do registro — um caller não consegue montar um contexto
"generoso" para si mesmo sem passar pelo registro (ver `de_registro`).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErroCapacidade(Exception):
    """Base tipada. Todo adapter falha com uma subclasse — nunca com `Exception`
    genérica, e nunca devolvendo string de erro como se fosse sucesso."""

    codigo = "E_CAPACIDADE"

    def __init__(self, mensagem: str, *, detalhe: str = ""):
        self.detalhe = detalhe
        super().__init__(mensagem)


class ErroEscopo(ErroCapacidade):
    """Alvo fora do escopo autorizado (root, traversal, symlink, rename-out)."""
    codigo = "E_ESCOPO"


class ErroNaoEncontrado(ErroCapacidade):
    codigo = "E_NAO_ENCONTRADO"


class ErroPermissao(ErroCapacidade):
    codigo = "E_PERMISSAO"


class ErroLimite(ErroCapacidade):
    """Tamanho, profundidade ou quantidade acima do teto."""
    codigo = "E_LIMITE"


class ErroInvalido(ErroCapacidade):
    """Argumento malformado — falha fechada, não "melhor esforço"."""
    codigo = "E_INVALIDO"


class ErroTimeout(ErroCapacidade):
    codigo = "E_TIMEOUT"


class ErroConflito(ErroCapacidade):
    """Estado incompatível (transição inválida, ocorrência já executada)."""
    codigo = "E_CONFLITO"


class EfeitoTimeout(str, Enum):
    """O que se sabe sobre o efeito quando o deadline estoura.

    Existe porque "deu timeout" não é uma resposta: o que importa é se o mundo
    mudou. `EFEITO_DESCONHECIDO` é o estado perigoso e NUNCA autoriza retry.
    """
    SEM_EFEITO = "TIMED_OUT_NO_EFFECT"
    EFEITO_DESCONHECIDO = "TIMED_OUT_EFFECT_UNKNOWN"
    EFEITO_CONFIRMADO = "TIMED_OUT_EFFECT_CONFIRMED"


@dataclass(frozen=True)
class CapabilityRequest:
    """O que se quer fazer. `argumentos` é DADO — nunca autoridade."""
    capacidade: str
    argumentos: dict = field(default_factory=dict)
    alvo: str = ""

    def arg(self, nome: str, padrao=None):
        return self.argumentos.get(nome, padrao)


@dataclass(frozen=True)
class CapabilityContext:
    """Contexto JÁ AUTORIZADO. Frozen: o adapter não reescreve a própria coleira.

    `risco` e `idempotente` são carimbos do REGISTRO. `raizes` é o escopo de
    caminho efetivo. `deadline_monotonic` é o prazo duro do nó (FASE 5).
    """
    capacidade: str
    sujeito: str
    risco: str
    idempotente: bool
    raizes: tuple[str, ...] = ()
    home: str = ""
    deadline_monotonic: float | None = None
    versao_capacidade: str = ""
    audit: Any = None

    # ---- os campos de autoridade não são construíveis à mão sem o registro ----

    @staticmethod
    def de_registro(registro, capacidade: str, sujeito: str, *,
                    raizes=(), home: str = "", deadline_monotonic=None,
                    audit=None) -> "CapabilityContext":
        """Única forma sancionada de montar um contexto.

        Risco e idempotência vêm do registro, não do chamador — é o mesmo
        princípio que já vale para planner e DAG, aplicado ao adapter.
        Capacidade desconhecida ⇒ `ErroInvalido` (fail-closed).
        """
        if not registro.conhecida(capacidade):
            raise ErroInvalido(f"capacidade desconhecida: {capacidade!r}")
        return CapabilityContext(
            capacidade=capacidade,
            sujeito=sujeito,
            risco=registro.risco_de(capacidade),
            idempotente=bool(registro.idempotente_de(capacidade)),
            raizes=tuple(raizes),
            home=home,
            deadline_monotonic=deadline_monotonic,
            versao_capacidade=versao_de_capacidade(registro, capacidade),
            audit=audit)

    # ---------------------------------------------------------------- deadline

    def restante(self) -> float | None:
        """Segundos até o deadline; None se não houver. Negativo ⇒ estourou."""
        if self.deadline_monotonic is None:
            return None
        return self.deadline_monotonic - time.monotonic()

    def exigir_prazo(self) -> None:
        """Fail-closed antes de começar algo caro."""
        r = self.restante()
        if r is not None and r <= 0:
            raise ErroTimeout(f"prazo do nó esgotado para '{self.capacidade}'")


@dataclass(frozen=True)
class CapabilityResult:
    """Resultado tipado. `efeito_aplicado` é o que a auditoria precisa saber."""
    ok: bool
    valor: Any = None
    efeito_aplicado: bool = False
    detalhe: str = ""
    metadados: dict = field(default_factory=dict)

    @staticmethod
    def sucesso(valor=None, *, efeito_aplicado: bool = False,
                **metadados) -> "CapabilityResult":
        return CapabilityResult(ok=True, valor=valor,
                                efeito_aplicado=efeito_aplicado,
                                metadados=metadados)


def versao_de_capacidade(registro, capacidade: str) -> str:
    """Impressão digital do descritor da capacidade (FASE 4 — registry race).

    Muda se a capacidade for removida, ou se risco/idempotência/executor
    mudarem. É o que a autorização carrega para detectar metadata obsoleta
    entre o planejamento e a execução.
    """
    import hashlib
    if not registro.conhecida(capacidade):
        return ""
    cat = registro.categoria_de(capacidade)
    executor = registro.executor_de(capacidade)
    partes = [
        capacidade,
        cat.value if cat is not None else "-",
        "1" if registro.idempotente_de(capacidade) else "0",
        # identidade do executor dinâmico: trocar o executor muda a versão
        getattr(executor, "__qualname__", "") or ("nativo" if executor is None else "?"),
    ]
    return hashlib.sha256("|".join(partes).encode("utf-8")).hexdigest()[:16]


class Adapter:
    """Base dos adapters. Deliberadamente magra.

    A única coisa que a base impõe é a checagem de coerência: o adapter não
    executa um pedido cuja capacidade não seja a do contexto autorizado. Sem
    isso, um caller poderia autorizar `arquivo_ler` e mandar `arquivo_apagar`.
    """

    capacidades: tuple[str, ...] = ()

    def executar(self, pedido: CapabilityRequest,
                 ctx: CapabilityContext) -> CapabilityResult:
        raise NotImplementedError

    # -------------------------------------------------------------- utilidades

    def _coerente(self, pedido: CapabilityRequest, ctx: CapabilityContext) -> None:
        if not isinstance(pedido, CapabilityRequest):
            raise ErroInvalido("pedido não é CapabilityRequest")
        if not isinstance(ctx, CapabilityContext):
            raise ErroInvalido("contexto não é CapabilityContext")
        if pedido.capacidade != ctx.capacidade:
            raise ErroEscopo(
                f"pedido '{pedido.capacidade}' não corresponde ao contexto "
                f"autorizado '{ctx.capacidade}'")
        if pedido.capacidade not in self.capacidades:
            raise ErroInvalido(
                f"'{pedido.capacidade}' não é servida por {type(self).__name__}")
        ctx.exigir_prazo()

    def _auditar(self, ctx: CapabilityContext, evento: str, **campos) -> None:
        if ctx.audit is not None:
            ctx.audit.append(evento, capacidade=ctx.capacidade,
                             sujeito=ctx.sujeito, risco=ctx.risco, **campos)
