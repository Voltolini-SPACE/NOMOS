# FASE 14 — CENSO INDEPENDENTE FINAL (autoritativo)

Fonte: `PARITY_MATRIX.json`. **Não sobrescrevi nada.**

```
TOTAL_CAPABILITIES = 53
FULL       = 9        (todas em SCRIPT_EXEC)
PARTIAL    = 29
MISSING    = 8
FORA_DO_NUCLEO = 7

GOVERNED   = 25
UNGOVERNED = 14
NA         = 14

FS_CRITICAL_GAPS        = 5
SCHEDULER_CRITICAL_GAPS = 8
SCRIPT_CRITICAL_GAPS    = 9
CRITICAL_GAPS_REMAINING = 22
```

| Categoria | FULL | PARTIAL | MISSING | FORA_DO_NUCLEO | críticas com gap |
|---|---|---|---|---|---|
| SCRIPT_EXEC | **9** | 6 | 5 | 4 | 9 |
| SCHEDULER/JOBS | 0 | 15 | 2 | 1 | 8 |
| FILESYSTEM | 0 | 8 | 1 | 2 | 5 |

**Primeiros FULL da linhagem** — 9 capacidades de execução de processo. O
criterio 2 (production caller), que zerava tudo na 04, foi fechado.

## Aviso de timing
O censo avaliou `HEAD=a120123`. O commit `44c2a3c` — que corrige as quatro
falhas que ele próprio encontrou, inclusive o bypass de PDP/PEP — veio DEPOIS.
Onde isso muda o veredito, digo abaixo; **não reclassifico por conta própria**.

## O que o censo confirmou como fechado
1. `registrar_scheduler()` tem **2 callers de produção** alcançáveis pelo CLI.
2. `Ticker` tem caller: `nomos scheduler rodar` **funciona de verdade** — o
   verificador rodou e o job escreveu o arquivo real.
3. A ocorrência executa pela cadeia governada, com a trilha em ordem:
   `pdp.decisao → pep.aplicacao → fs.escrever → scheduler.execucao.fim`.
   Job com alvo fora do escopo: `DENY recurso_fora_do_escopo`, nada criado.
4. `script-rodar` alcançável, allowlist canonicalizada, symlink trocado
   depois do registro não autoriza.

## O que ele encontrou de errado — e o que fiz
| # | Achado | Estado |
|---|---|---|
| 1 | **sched-* executavam sem PDP e sem PEP** (registro depois da construção do runtime) | **CORRIGIDO** `44c2a3c` |
| 2 | **CRON inalcançável por caller** — `_ponte_sched` ignorava a agenda, job virava ONE_SHOT em silêncio | **CORRIGIDO** `44c2a3c` |
| 3 | `--intervalo 0` virava 1.0 em silêncio | **CORRIGIDO** `44c2a3c` |
| 4 | `--executavel` sem `--adapters` não registrava e não avisava | **CORRIGIDO** `44c2a3c` |
| 5 | Scheduler e Ticker emitem alertas CONTRADITÓRIOS para a mesma ocorrência (UNKNOWN vs NO_EFFECT) | **REGISTRADO** |
| 6 | política de catch-up não exposta no CLI | **REGISTRADO** |
| 7 | 1 execução em 9 falhou 3 guards de registry race (suspeita de `__pycache__` obsoleto) | **REGISTRADO** — ver abaixo |

## Achado 7 — não classifiquei como defeito, e não classifiquei como ruído
O verificador rodou a suíte 9 vezes: 8 verdes, 1 com 3 falhas nos guards de
registry race (`Motivo.OK` em vez de `CAPACIDADE_MUDOU`). Ele não conseguiu
reproduzir e a causa mais provável é bytecode obsoleto em `__pycache__`
pré-existente. **Registro como pendência real**: uma execução em nove negou três
invariantes de segurança, e quem for congelar este HEAD deve repetir com
`__pycache__` limpo antes de confiar.

## SCHED-12 — por que continua PARTIAL, e por que isso está certo
O verificador foi preciso: os schedulers do Hermes e do OpenClaw rodam sob
launchd e sobrevivem a logout/reboot; no NOMOS o job só dispara enquanto alguém
segura o processo em foreground. **A proibição de daemon nesta missão EXPLICA o
gap, não o FECHA** — capacidade não vira FULL porque a lacuna foi autorizada.
