# FASE 13 — CENSO GLOBAL (independente e autoritativo)

Fonte: `PARITY_MATRIX.json` — 2 agentes de censo + verificação adversarial,
com o critério de FULL em 7 itens. **Este resultado é autoritativo para
promoção; não o sobrescrevi.**

## Contagem
```
TOTAL_CAPABILITIES = 29   (as 2 categorias remedidas)
FULL       = 0
PARTIAL    = 23
MISSING    = 3
FORA_DO_NUCLEO = 3

GOVERNED   = 12
UNGOVERNED = 9
NA         = 8

FS_CRITICAL_GAPS        = 5
SCHEDULER_CRITICAL_GAPS = 8
CRITICAL_GAPS_REMAINING = 13   (HTTP/CHANNELS/GIT/BROWSER não remedidos: +6 da 02)
```

| Categoria | FULL | PARTIAL | MISSING | FORA_DO_NUCLEO | críticas com gap |
|---|---|---|---|---|---|
| SCHEDULER/JOBS | 0 | 15 | 2 | 1 | **8** |
| FILESYSTEM | 0 | 8 | 1 | 2 | **5** |

## O motivo de ZERO FULL é um só, e é estrutural
**Critério 2 — production caller / runtime path.** O verificador provou:
- `registrar_scheduler()` **não tem nenhum caller em `src/`** — só os testes;
- `Ticker` só aparece no próprio módulo e no seu teste;
- `script-rodar` tem caller (`RuntimeGovernado.__init__`) mas só entra
  `if executaveis:`, e `cli.py` **nunca passa `executaveis`** — não existe flag
  `--executavel` em `nomos orquestrar`;
- em produção, `simple/rotinas.py` (intocado) segue sendo a única superfície
  real de agendamento.

Construí o motor. **Não liguei o fio.**

## O que o censo reconheceu como genuinamente bom
- o parser de cron é real e correto no núcleo POSIX, **incluindo o OR entre
  dom/dow** que quase toda implementação caseira erra;
- a timezone é de fato **aplicada** no cálculo, não armazenada;
- os dois casos de DST têm tratamento explícito e testado;
- a dedup por ocorrência com reserva ANTES do efeito sobrevive a restart, com
  prova real;
- `script.py` é "um dos executores de processo mais fechados que já vi" —
  argv[] sem shell, shells recusados como argv[0], env por allowlist, timeout
  com kill de grupo, allowlist de binário fixada no registro e não no plano;
- o caminho governado de `script-rodar` está provado ponta a ponta.

## Divergência de ambiente registrada
O verificador não reproduziu "2377 passed": no ambiente dele faltava
`argon2-cffi` e o pacote não estava instalado, dando 2330 passed / 49 failed.
**As 49 falhas são todas de módulos não relacionados** (vault2, mcp, sbom,
evidencia, mc29-32) — zero em adapters/scheduler. É a mesma LANDMINE da
ABSORPTION-01: sem venv com dependências, a suíte dá falso vermelho.

## Aviso de timing
O censo avaliou `HEAD=418bac5`. Os commits `cdc5f62` (script com caminho de
produção) e `d7badbc` (4 correções de fail-open) vieram DEPOIS. Onde isso muda
o veredito, digo — mas **não reclassifico nada por conta própria**: seria
exatamente a autoaprovação que a missão proíbe.
