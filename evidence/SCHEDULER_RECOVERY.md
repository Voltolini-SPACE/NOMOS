# FASE 3 — DEDUP E RECOVERY

## A chave de dedup é a OCORRÊNCIA
```
chave = f"{job_id}@{instante_planejado_iso}"
```
Instante **planejado** (`proximo_em`), não o relógio de agora — senão duas
execuções no mesmo tick virariam ocorrências distintas e o dedup não serviria.

## A reserva acontece ANTES do efeito
`ArmazemJobs.reservar()` faz `INSERT` numa tabela cuja `chave` é PRIMARY KEY.
Duplicado ⇒ `IntegrityError` ⇒ `False` ⇒ não executa.

Marcar DEPOIS do efeito perderia a corrida com o crash: o processo morre entre
o efeito e a marca, e o restart repete. Provado por
`test_reserva_acontece_antes_do_efeito`: mesmo quando o efeito ESTOURA, a
ocorrência fica reservada e um scheduler novo não a repete.

## Provas comportamentais
| Teste | O que prova |
|---|---|
| `test_mesma_ocorrencia_no_maximo_um_efeito` | 3 chamadas ⇒ 1 efeito |
| `test_dedup_sobrevive_a_restart` | novo processo, novo executor, MESMO banco ⇒ 0 efeitos |
| `test_reserva_acontece_antes_do_efeito` | efeito falho não libera a ocorrência |
| `test_recorrente_ocorrencias_distintas_executam` | dedup é por ocorrência, não por job |
| `test_recorrente_nao_acumula_ocorrencias_vencidas` | 5 h desligado ≠ 300 execuções |
| `test_job_desabilitado_nao_produz_efeito` | DISABLED ⇒ 0 |
| `test_job_cancelado_nao_produz_efeito` | CANCELLED ⇒ 0 |

## Persistência
SQLite com `journal_mode=WAL` e `synchronous=FULL`, arquivo `0600`.
`test_persistencia_sobrevive_a_nova_instancia` prova que a definição volta
íntegra num processo novo.
