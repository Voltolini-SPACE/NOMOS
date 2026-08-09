# Orquestração governada — `nomos.orquestracao`

> **Status das capacidades descritas aqui**
> `VALIDATED` — implementado, testado (107 testes próprios) e auditado adversarialmente,
> **ainda sem caller de produção no CLI**. O pacote é fundação: nenhum módulo existente do
> NOMOS o importa. Expor comando ao usuário é missão de produto (regra MC35), não desta camada.
> Nada aqui é `PRODUCTION` até ter caller real e uso comprovado.

## Por que este pacote existe

O NOMOS sempre teve um **kernel de governança forte** (política A0–A6 fail-closed, aprovação
de uso único, auditoria encadeada por hash, cofre, consentimento, trava de localidade) e uma
execução deliberadamente **pequena**: 8 ferramentas numa allowlist fechada, sem retentativa,
sem grafo de tarefas, sem registro dinâmico.

Isso o tornava excelente em **decidir** e limitado em **conduzir**. Uma missão com vários passos
dependentes exigia que o operador dissesse "prossiga" a cada etapa.

Este pacote fecha essa lacuna **sem** transformar o NOMOS num executor genérico. A regra que
organiza tudo é a mesma do pacote `agents`:

> **ORQUESTRAR NÃO É ATALHO PARA BURLAR POLÍTICA.**

## Os cinco módulos

| Módulo | Papel | Invariante central |
|---|---|---|
| `registro.py` | Registro dinâmico de capacidades | Capacidade desconhecida ⇒ risco A6; nativa não pode ser sombreada nem removida; registrar passa pelo gate como A5 |
| `grafo.py` | Grafo de tarefas + orquestrador | **Cada nó** passa por `policy.decide()` + `gate()` antes de executar; negação/falha bloqueia dependentes transitivos |
| `planejador.py` | Plano tipado | A categoria de cada passo vem **sempre** do registro — o plano nunca declara nem rebaixa o próprio risco |
| `recuperacao.py` | Retentativa governada | Retentativa só para capacidade declarada idempotente; disjuntor por ferramenta; orçamento por missão |
| `roteamento.py` | Adaptador para o roteador de motores | A rota é **dado**, não autorização; inspeção incompleta dos dados ⇒ tratada como sensível (nuvem barrada) |

## Fluxo

```
objetivo
   │
   ▼
planejador.planejar()  ──►  PlanoTipado   (passo inválido é rejeitado; dependentes caem junto)
   │                          │
   │                          ▼
   │                    para_grafo()
   ▼                          │
GrafoTarefas  ◄───────────────┘   (valida id duplicado, ciclo, dependência órfã, ferramenta fora do registro)
   │
   ▼
Orquestrador.executar()
   │
   ├─ para cada nó, em ordem topológica:
   │     categoria ← registro          (nunca do plano)
   │     decisão   ← policy.decide()
   │     gate()    ← MESMO gate do kernel; sem aprovador ⇒ nega
   │     rota      ← engine_router     (se motor="auto"; é dado, não permissão)
   │     execução  ← recuperacao       (retentativa só se idempotente)
   │
   └─ nó negado/falho ⇒ dependentes transitivos BLOQUEADOS; ramos independentes seguem
```

## O que este pacote deliberadamente **não** faz

Terminal, PTY, navegador, git, agendamento real. Essas capacidades pertencem a um **executor
especializado** (no ecossistema do autor, o Hermes) e devem ser alcançadas por delegação sob
contrato — com o NOMOS decidindo e o executor aplicando. Reimplementá-las aqui transformaria o
control plane em mais um agente genérico, que é exatamente o que a arquitetura evita.

## Auditoria adversarial

O pacote passou por duas rodadas de auditoria adversarial (132 agentes; cada achado julgado por
três céticos independentes com instrução de refutar). **12 defeitos reais** foram corrigidos —
entre eles um crítico: a marca de idempotência vinha do plano, de modo que um plano hostil que se
declarasse idempotente transformaria **uma aprovação humana em N execuções** de uma ação sensível.

Fato registrado por honestidade de engenharia: **seis dos doze defeitos foram introduzidos pelas
próprias correções anteriores**. A primeira correção de um defeito de segurança é código novo e
não auditado — daí a segunda rodada. O detalhe de cada um está no `CHANGELOG.md`, seção
*Security (NH hardening)*.

## Como usar (exemplo mínimo)

```python
from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.orquestracao.planejador import planejar
from nomos.orquestracao.grafo import Orquestrador

policy = PolicyEngine(home / "policy.json")
registro = RegistroCapacidades(policy=policy, approver=meu_aprovador, audit=meu_audit)
registro.registrar("coletar", Category.READ_LOCAL, coletar_fn, "minha-app",
                   idempotente=True)          # idempotência é da CAPACIDADE

plano = planejar("relatório diário", registro, passos=[
    {"id": "c", "ferramenta": "coletar"},
    {"id": "a", "ferramenta": "analisar", "depende_de": ["c"], "motor": "auto"},
])

orq = Orquestrador(registro, policy, approver=meu_aprovador, audit=meu_audit)
resultado = orq.executar(plano.para_grafo(registro))
```

## Trilha de auditoria

Todo evento relevante é registrado no mesmo audit encadeado do kernel:
`registro.capacidade.{registrada,removida,negada}` ·
`planejador.{plano.ok,plano.falhou,passo.rejeitado}` ·
`orquestracao.{missao.inicio,missao.fim,no.ok,no.negado,no.bloqueado,no.falhou,no.rota_motor}` ·
`recuperacao.{tentativa.falhou,recuperou,sem_retry,circuito.aberto,circuito.rejeitou,orcamento.esgotado}`.

A rota de motor é auditada sem o conteúdo da tarefa — só motor escolhido, alternativa e se a
localidade foi preservada.
