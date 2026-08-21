# ADR — Memória: um store autoritativo (NH-005, GO CONDICIONADO)

Data: 2026-08-21 · Missão: OPERACAO-01 · Status: fatia P0–P2 entregue

## Censo (verificado no código)

- **Store A (PROD)** — `cognition/memory.py` (`memory.db`, SQLite+FTS5):
  10 callers de produção (CLI, painel, MCP server, agents, rotinas, chat).
- **Store B (MC28)** — `memory/` (`memory.jsonl`, append-only, hash por
  entrada, política fail-closed): **zero** importadores fora do pacote.

## Decisão

Direção única: **`memory.db` é a fonte autoritativa**; o motor MC28 é
rebaixado a **gate de política + trilha**. O NO-GO foi rejeitado por um
fato: `Memory.remember*` gravava QUALQUER texto sem varredura de segredo,
e `memory/policy.evaluate` (fail-closed) já existia — não usar era dívida.

## Entregue nesta fatia (risco baixo)

- **P0** caracterização dos dois stores congelada em teste.
- **P1** gate de admissão: `remember`/`remember_typed`/`aprovar_candidata`
  passam por `policy.evaluate`; recusa = `MemoriaRecusada` VISÍVEL
  (o chat avisa e segue; demais callers propagam).
- **P2** `nomos memoria importar-mc28 [--dry-run|--desfazer]`: hash
  validado por entrada (adulterada = pulada + exit≠0 — tripwire NO-GO),
  política re-aplicada, dedup idempotente, origem byte-idêntica,
  rollback completo por `fonte='mc28'`.

## Fora desta fatia (atrás de flag, missão futura)

- **P3** leitura do `MemoryEngine` a partir do `memory.db` sob
  `NOMOS_MEMORIA_FONTE_UNICA=1`, com gate de paridade de leitura.
- **P4** `memory.jsonl` rebaixado a trilha derivada (write-through).

## Critérios de parada (NO-GO imediato)

1. Caracterização P0 quebrar; 2. paridade de leitura divergir; 3. surgir
consumidor externo do FORMATO `memory.jsonl`; 4. qualquer caminho deixar
conteúdo `allowed==False` chegar ao `memory.db`.

## Integridade

`memory.db` não tem hash-chain: a integridade por entrada do MC28 é
validada NO momento da importação e a trilha da importação vai ao audit
hash-chained — integridade deslocada, não perdida.
