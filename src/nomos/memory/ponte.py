"""NOMOS memory.ponte — importação one-shot MC28 → memory.db (NH-005 P2).

Direção única da consolidação: `cognition/memory.py` (memory.db) é a fonte
autoritativa; o MC28 (`memory.jsonl`) vira gate de política + trilha. Esta
ponte importa o histórico MC28 SEM tocar a origem (o contrato append-only
é respeitado por NÃO-escrita) e com rollback provado (`--desfazer` remove
exatamente o que entrou: tudo tem `fonte='mc28'`).

Tripwire NO-GO objetivo: entrada com hash inválido é reportada e PULADA;
qualquer pulo por adulteração termina o comando com exit≠0 — importar dado
adulterado seria lavá-lo.
"""
from __future__ import annotations

from dataclasses import dataclass

_TIPOS = {
    # scope MC28 → tipo do memory.db (mapa conservador; desconhecido = fato)
    "project": "projeto",
    "user": "preferencia",
    "session": "conversa",
}


@dataclass(frozen=True)
class ResultadoImportacao:
    importadas: int
    duplicadas: int
    puladas_hash: int
    rejeitadas_politica: int

    @property
    def ok(self) -> bool:
        """Adulteração detectada ⇒ NÃO-ok (decisão humana antes de seguir)."""
        return self.puladas_hash == 0


def _texto_formatado(entry: dict) -> str:
    scope = str(entry.get("scope", ""))
    prio = str(entry.get("priority", ""))
    tags = ",".join(entry.get("tags") or [])
    cabeca = f"mc28[scope={scope};prio={prio}"
    if tags:
        cabeca += f";tags={tags}"
    return f"{cabeca}]: {entry.get('content', '')}"


def _mapear_tipo(entry: dict) -> str:
    return _TIPOS.get(str(entry.get("scope", "")), "fato")


def importar(store, mem, *, dry_run: bool = False) -> ResultadoImportacao:
    """Importa `store` (MC28 `MemoryStore`) para `mem` (`cognition.Memory`).

    - valida `recompute_hash` por entrada (adulterada ⇒ pulada e contada);
    - re-aplica `policy.evaluate` (defesa em profundidade — o gate P1 já
      recusaria, mas a ponte não depende disso);
    - dedup por texto formatado exato com fonte='mc28' (idempotente);
    - `dry_run` não escreve NADA.
    """
    from nomos.cognition.memory import MemoriaRecusada
    from nomos.memory.store import recompute_hash

    importadas = duplicadas = puladas = rejeitadas = 0
    existentes = {
        r[0] for r in mem.conn.execute(
            "SELECT text FROM memories WHERE fonte='mc28'")
    }
    for entry in store.read_raw():
        declarado = entry.get("hash", "")
        if not declarado or recompute_hash(entry) != declarado:
            puladas += 1
            continue
        texto = _texto_formatado(entry)
        if texto in existentes:
            duplicadas += 1
            continue
        if dry_run:
            importadas += 1
            continue
        try:
            mem.remember_typed(texto, tipo=_mapear_tipo(entry),
                               fonte="mc28", confianca=1.0)
        except MemoriaRecusada:
            rejeitadas += 1
            continue
        existentes.add(texto)
        importadas += 1
    return ResultadoImportacao(importadas=importadas, duplicadas=duplicadas,
                               puladas_hash=puladas,
                               rejeitadas_politica=rejeitadas)


def desfazer(mem) -> int:
    """Rollback COMPLETO da importação: a origem está intacta, então apagar
    `fonte='mc28'` do memory.db devolve o estado anterior por inteiro."""
    cur = mem.conn.execute("DELETE FROM memories WHERE fonte='mc28'")
    mem.conn.commit()
    return cur.rowcount
