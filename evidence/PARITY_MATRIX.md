# FASE 6 — PARIDADE RECALCULADA (FS e SCHEDULER)

Fonte: `PARITY_MATRIX.json` — recenso com 2 agentes de censo + verificação
adversarial instruída a REFUTAR. Percentuais NÃO foram editados à mão.

## Aviso metodológico honesto
O recenso é **estático** (não executou a suíte) e fotografou o worktree **em
voo**: rodou enquanto eu ainda commitava. Ele mesmo registra isso — às 08:14 as
capacidades usavam underscore (defeito real: `registro.NOME_RE` rejeita
underscore, então `adapters=True` seria inconstruível); às 08:23 já estavam com
hífen. E os commits `72b6489` (3 correções) e `a032ab9` (caller de produção)
vieram DEPOIS. Onde o veredito dele foi superado, digo abaixo.

## Contagem
| Categoria | GOVERNADO | PARCIAL | AUSENTE | FORA_DO_NUCLEO |
|---|---|---|---|---|
| FILESYSTEM (era 0/4/5/2) | 0 | **8** | 1 | 2 |
| SCHEDULER (era 0/7/10/1) | 0 | **10** | 7 | 1 |

```
FS_TOTAL=11   FS_FULL=0   FS_CRITICAL_GAPS=5
SCHEDULER_TOTAL=18  SCHEDULER_FULL=0  SCHEDULER_CRITICAL_GAPS=8
CRITICAL_GAPS_REMAINING (nestas 2 categorias) = 13
```

Cinco linhas subiram de AUSENTE para PARCIAL; **nenhuma regrediu**; nenhuma
chegou a GOVERNADO.

## Por que nada é GOVERNADO — os três motivos do verificador
| # | Motivo | Estado agora |
|---|---|---|
| A | sem caller de produção (`cli.py` não passava `adapters=True`) | **CORRIGIDO** em `a032ab9` — `nomos orquestrar --adapters --raiz` |
| B | o elo (`wiring.py`) estava untracked | **CORRIGIDO** — commitado em `6122814` |
| C | confinamento opt-in, default aberto | **CORRIGIDO** em `72b6489` — mutante exige raiz, fail-closed |

Ainda assim **não declaro GOVERNADO**: o veredito de GOVERNADO exige uma
recontagem que eu não reexecutei depois das correções. Declarar com base no
meu próprio julgamento derrotaria o propósito da verificação adversarial.

## Gaps críticos que continuam REAIS (não são artefato de timing)
### Filesystem — 1 lacuna funcional + herança
- `FS-READ-BINARY` AUSENTE: `fs-ler` recusa binário explicitamente (honesto),
  mas não há equivalente ao `/api/fs/read-data-url` do Hermes.
- `fs-editar` não tem patch unificado/multi-arquivo nem diff auditável.
- As nativas `arquivo_ler`/`arquivo_resumir` continuam sem resolver próprio —
  agora protegidas pelo escopo do PDP corrigido, mas só quando `--raiz` é usado.

### Scheduler — 4 ausências estruturais
- **`SCHED-02` cron real não existe.** Há `intervalo_s`, não expressão cron
  (`0 7 * * *`). Hermes usa cron. Intervalo ≠ cron.
- **`SCHED-17` timezone é armazenada, não aplicada.** O campo `tz` persiste; o
  cálculo do próximo disparo é UTC puro. Guardar a string sem usá-la não é
  suporte a timezone.
- **`SCHED-12` não há daemon-ticker.** Alguém precisa chamar
  `executar_devidos()`. Daemon está fora do escopo desta missão por decisão da
  própria missão.
- **`SCHED-11` exec-script-sem-LLM** e **`SCHED-15` delivery/alerta de falha**
  não existem.

## Outras categorias
HTTP, CHANNELS, GIT e BROWSER **não foram remedidas** — nenhum código dessas
áreas foi tocado. Os números da ABSORPTION-02 seguem valendo, e os 6 gaps
críticos de HTTP/channels permanecem para a ABSORPTION-04, como a própria
missão autorizou.
