# FASE 3 — SCHEDULER NATIVO GOVERNADO

Commits: `34645e8` (scheduler) · `68308ff` (wiring)

## Capacidades registradas, e o risco pela DIREÇÃO da autoridade
| Capacidade | Categoria | Por quê |
|---|---|---|
| `sched-listar`, `sched-status` | A0_READ_LOCAL | consulta |
| `sched-criar`, `sched-habilitar` | **A5_CODE_EXEC** | ARMAM execução futura, que roda depois — possivelmente sem ninguém olhando |
| `sched-desabilitar`, `sched-cancelar`, `sched-apagar` | A1_WRITE_LOCAL | DESARMAM: reduzem autoridade |

Exigir aprovação forte para DESLIGAR algo perigoso seria pôr fechadura na saída
de emergência. A direção segura da falha é conseguir desligar.

Cada operação é capacidade SEPARADA — listar não carrega a autoridade de
cancelar.

(Nota: a primeira versão usou `Category.WRITE_SHARED`, que **não existe** no
kernel. Categoria inventada é risco inventado; corrigido para as reais.)

## Autoridade não é persistida
`JobDefinition` guarda `job_id`, `sujeito`, `capacidade`, `argumentos`, `alvo`,
`intervalo_s`, `proximo_em`, `estado`, `criado_em`, `tz`. **Nenhum** campo de
token, assinatura, nonce ou chave — verificado por teste que inspeciona os
campos do dataclass E as colunas da tabela SQLite
(`test_job_persistido_nao_carrega_autorizacao`).

A autoridade é obtida no instante da execução. Persistir um token curto e
reusá-lo seria criar autorização eterna.

`test_sem_executor_governado_nao_ha_efeito`: sem executor ligado, o job falha —
o scheduler não executa por conta própria.

## Gates
```
SCHEDULER_CRITICAL_GAPS=  ver PARITY (dedup, persistência, one-shot, intervalo,
                          enable/disable/cancel fechados; cron/timezone/ticker
                          NÃO — ver lacunas abaixo)
DUPLICATE_EXECUTION=0
INVALID_STATE_TRANSITION=DENY
DISABLED_JOB_EFFECTS=0
CANCELLED_JOB_EFFECTS=0
```

## Lacunas honestas desta fase
1. **Cron real não existe.** Há `intervalo_s` (segundos), não expressão cron
   (`0 7 * * *`). Hermes usa cron. Intervalo ≠ cron.
2. **Timezone é armazenada, não aplicada.** O campo `tz` existe e persiste, mas
   o cálculo do próximo disparo é UTC puro. Guardar a string sem usá-la **não é
   suporte a timezone** — registrado como gap, não como fechado.
3. **Não há daemon-ticker.** Alguém precisa chamar `executar_devidos()`; nada
   dispara sozinho. Por decisão da própria missão, daemon não é escopo aqui.
4. **Não há exec-script-sem-LLM nem delivery/alerta-de-falha.**
