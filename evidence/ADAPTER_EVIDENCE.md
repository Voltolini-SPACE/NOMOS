# FASE 3 — ADAPTERS NATIVOS · **NÃO EXECUTADA**

Status: `NOT_STARTED`. Nenhum adapter novo foi construído nesta missão.

Isto não é omissão de relatório: a FASE 3 depende do censo da FASE 2, que só
fechou perto do fim da janela (13 agentes, ~20 min, 2 M de tokens). Construir
6 famílias de adapter (fs-amplo, git, http, scheduler, browser, channels) com
o contrato exigido — `CapabilityRequest/Context/Result/Error`, timeout, erro
tipado, audit trail, sem executor bruto exportável — é trabalho de missão
inteira, não de sobra de janela.

## O que o censo determinou que precisa ser construído

Ordem sugerida (mais barato/reversível primeiro):

| Adapter | Capacidades críticas cobertas | Risco | Observação |
|---|---|---|---|
| **fs-amplo** | FS-EDIT-PATCH, FS-READ-TEXT (conteúdo real, offset/limit), confinamento transversal | A0–A1 | maior alavancagem: fecha 4 das 18 críticas |
| **scheduler** | SCHED-02/03/11/12/17, persistência, dedup, alerta | A2 | 8 das 18 críticas; hoje `rotinas` só EXPORTA plist |
| **http** | HTTP-05 probe loopback, HTTP-06 long-poll | A3 | exige allowlist de destino + validação de redirect |
| **git** | 19 capacidades, todas AUSENTE | A2–A4 | push/create-pr são as mais perigosas; tratar em faixa própria |
| **channels** | CH-04/05/06/07 | A3–A4 | **não ativar canal desabilitado**; antitamper é controle vivo |
| **browser** | 5 AUSENTE | A3 | menor prioridade: uso real em produção é baixo |

## Contrato obrigatório (a cumprir na próxima missão)
```
CapabilityRequest · CapabilityContext · CapabilityResult · CapabilityError
```
Cada adapter: recebe contexto JÁ autorizado; não decide risco; não aceita
`idempotent=True` do caller; produz audit trail; erro tipado; timeout;
testável sem produção; sem acesso a segredo desnecessário; e **nenhum executor
bruto exportável fora do PEP** (ou guard estrutural equivalente, como o
`__slots__`+closure já usado em `pdp/pep.py`).

## Lacuna de contrato já identificada
Não existe **timeout duro por nó** no runtime atual — `recuperacao.py` sempre
documentou que isso é do sandbox. O contrato de adapter acima precisa
implementá-lo de fato.
