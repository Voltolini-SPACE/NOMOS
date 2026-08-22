"""NOMOS orquestracao.checkpoint — estado durável + retomada de missão (NH-009).

Uma missão longa morre no meio — crash, panic, kill -9 — e sem isto a única
opção é executar TUDO de novo: desperdício nos nós idempotentes, efeito
duplicado nos que não são. O checkpoint grava a transição de cada nó em disco
(escrita atômica, 0600) e a retomada decide nó a nó, fail-closed:

- OK ................ não reexecuta (o ponto do checkpoint);
- EXECUTANDO ........ o crash pegou o nó NO MEIO. "O efeito aplicou?" não tem
                      resposta. Idempotente ⇒ reexecutar é seguro por
                      definição; não idempotente ⇒ FALHOU com o motivo — na
                      dúvida, não se aposta em efeito duplicado;
- FALHOU/NEGADO/
  BLOQUEADO ......... volta a PENDENTE e é reavaliado (a retomada existe
                      para consertar o ambiente e continuar; o gate decide
                      de novo, como sempre).

## Amarração ao grafo

O arquivo carrega o SHA-256 da serialização canônica dos nós. Retomar com um
plano DIFERENTE herdaria os status — e implicitamente as aprovações já
consumidas — de outro plano: um plano hostil "continuaria" a missão de um
benigno. Digest divergente ⇒ `ErroCheckpoint`, nada executa. Pela mesma
razão, checkpoint corrompido é RECUSA, nunca recomeço silencioso: recomeçar
do zero reexecutaria o que não pode ser reexecutado.

Params fora de JSON não têm serialização canônica ⇒ o grafo não pode usar
checkpoint (recusa explícita). O plano real passa por `entrada.py`, que só
produz JSON — a restrição atinge apenas grafo montado à mão.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from nomos.kernel.plataforma import chmod_privado

FORMATO = 1
ESTADOS_VALIDOS = ("OK", "EXECUTANDO", "FALHOU", "NEGADO", "BLOQUEADO")


class ErroCheckpoint(ValueError):
    """Checkpoint ilegível, de outro grafo, ou grafo não canonizável."""


def digest_do_grafo(grafo) -> str:
    """SHA-256 da forma canônica dos nós — a identidade que amarra o arquivo."""
    nos = []
    for no_id in sorted(grafo.nos):
        no = grafo.nos[no_id]
        nos.append({"id": no.id, "ferramenta": no.ferramenta,
                    "params": no.params, "depende_de": list(no.depende_de),
                    "motor": no.motor, "idempotente": no.idempotente,
                    "alvo": no.alvo})
    try:
        canonico = json.dumps(nos, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ErroCheckpoint(
            f"grafo não canonizável para checkpoint ({type(exc).__name__}): "
            "params precisam ser JSON — recusa explícita, não digest "
            "aproximado") from None
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


class CheckpointMissao:
    """Um arquivo = uma missão. `iniciar()` amarra ao grafo e devolve o
    estado anterior; `marcar()`/`sincronizar()` gravam transições."""

    def __init__(self, caminho):
        self.caminho = Path(caminho)
        self._digest: str | None = None
        self._status: dict[str, str] = {}

    # ------------------------------------------------------------- leitura

    def iniciar(self, grafo) -> dict[str, str]:
        """Amarra ao grafo (digest) e devolve os status da corrida anterior.

        Arquivo ausente ⇒ missão nova ({}). Arquivo de OUTRO grafo ou
        ilegível ⇒ ErroCheckpoint — ver docstring do módulo.
        """
        digest = digest_do_grafo(grafo)
        if self.caminho.exists():
            try:
                dados = json.loads(self.caminho.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                raise ErroCheckpoint(
                    f"checkpoint ilegível em {self.caminho} "
                    f"({type(exc).__name__}) — recusa, não recomeço "
                    "silencioso: recomeçar reexecutaria o que não pode ser "
                    "reexecutado") from None
            if (not isinstance(dados, dict) or dados.get("formato") != FORMATO
                    or not isinstance(dados.get("nos"), dict)):
                raise ErroCheckpoint(
                    f"checkpoint com estrutura desconhecida em {self.caminho}")
            if dados.get("digest") != digest:
                raise ErroCheckpoint(
                    "checkpoint pertence a OUTRO grafo — plano modificado não "
                    "herda estado (nem aprovações) do plano antigo")
            for no_id, estado in dados["nos"].items():
                if estado not in ESTADOS_VALIDOS:
                    raise ErroCheckpoint(
                        f"estado desconhecido no checkpoint: {estado!r}")
                self._status[str(no_id)] = estado
        self._digest = digest
        self._gravar()
        return dict(self._status)

    # ------------------------------------------------------------- escrita

    def marcar(self, no_id: str, estado: str) -> None:
        self.sincronizar({no_id: estado})

    def sincronizar(self, transicoes: dict[str, str]) -> None:
        """Aplica um lote de transições numa escrita só (uma por onda)."""
        if self._digest is None:
            raise ErroCheckpoint("checkpoint não iniciado — chame iniciar()")
        for no_id, estado in transicoes.items():
            if estado not in ESTADOS_VALIDOS:
                raise ErroCheckpoint(f"estado inválido: {estado!r}")
            self._status[str(no_id)] = estado
        self._gravar()

    def _gravar(self) -> None:
        """Atômico e 0600 ANTES de existir no nome final — o molde de
        `kernel/pausa.py`: crash no meio da gravação deixa o arquivo antigo
        intacto, nunca um meio-escrito."""
        conteudo = json.dumps({"formato": FORMATO, "digest": self._digest,
                               "nos": self._status},
                              ensure_ascii=False, sort_keys=True)
        tmp = self.caminho.with_name(self.caminho.name + ".tmp")
        tmp.write_text(conteudo, encoding="utf-8")
        chmod_privado(tmp)
        os.replace(tmp, self.caminho)
