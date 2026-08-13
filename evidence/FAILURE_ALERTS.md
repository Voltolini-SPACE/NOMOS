# FASE 6 — FAILURE ALERT

`src/nomos/adapters/alertas.py`

## A separação que importa
```
EVENTO de falha        ≠        CANAL de entrega
```
O scheduler emite; um `AlertSink` entrega. Trocar o sink não mexe no scheduler,
e canais reais entram numa missão futura sem tocar nesta camada.

## O evento
`scheduler.ocorrencia.falhou` com exatamente:
```
job_id · occurrence_id · capability · error_class · attempt
timestamp · effect_state · detalhe
```
`detalhe` é truncado em 300 caracteres e o payload original nunca entra —
mensagem de exceção pode conter caminho, token ou conteúdo de arquivo. Alerta
que vaza o segredo que deveria proteger é incidente, não alerta.
(`test_evento_nao_carrega_payload_integral`)

## Sinks
| Sink | Papel |
|---|---|
| `AuditAlertSink` | grava na trilha hash-encadeada do NOMOS — o alerta herda integridade sem infraestrutura nova |
| `SinkDeTeste` | coleta em memória (teste e shadow futuro) |
| `SinkComposto` | vários sinks; um quebrado não impede os outros, e as falhas ficam em `falhas` |

`SinkComposto` tem a ÚNICA exceção engolida do módulo, e de propósito: o alerta
já está reportando uma falha; deixar o sink derrubar o caminho transformaria
"o job falhou" em "o processo caiu ao contar que o job falhou".

## Sem dependência de canal
`test_alertas_nao_dependem_de_canal_externo` verifica por **AST** que o módulo
não importa `socket`, `http`, `urllib`, `requests`, `smtplib` nem `ssl`.

## Gates
```
FAILURE_EVENT=PASS
ALERT_INTERFACE=PASS
NO_CHANNEL_DEPENDENCY=TRUE
```
