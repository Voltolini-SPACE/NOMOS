# NOMOS v1.2.0rc1 — Delivery Ready

## Status
STATUS_FINAL=PASS_100_DELIVERY_READY (código local)
PROMOÇÃO_REMOTA=FAIL_CLOSED_BLOCKED_BY_REAL_CONSTRAINT (sem credencial de push no ambiente)

O código das fases F1–F6 está pronto, testado e commitado localmente. A
publicação no GitHub e a verificação de CI dependem do `git push` do operador
(credencial não disponível nesta sessão) — descrito no fim.

## Resumo
Esta entrega fecha as fases F1–F6 do plano de validação crítica: endurecimento
anti-injection, histórico de conversas local, agentes governados, UX/memória
tipada, rotinas dry-run e smoke pós-install. Parte de v1.2.0rc1 (remoto) e leva
o estado local a v1.3.0rc4.

## Commits a promover
| Commit | Fase | Entrega | Versão |
|---|---|---|---|
| 8d4bb44 | F1 | anti prompt-injection (P0), .coverage fora do git, docs 27→25, mypy CI, XSS | 1.2.0rc2 |
| 455b41b | F2 | histórico de conversas (local, cifrável, modo privado, retenção) | 1.3.0rc1 |
| 0b29e57 | F3 | agentes locais governados (agente não é bypass do gate) | 1.3.0rc2 |
| 19f1bf7 | F4 | UX: memória tipada, candidatas, erro humano, modo iniciante | 1.3.0rc3 |
| 240362a | F5+F6 | rotina dry-run + smoke CI + fix empacotamento dos agentes | 1.3.0rc4 |
| 129d309 | promo | `__main__.py` para `python -m nomos` (shim; sem mudar comportamento) | 1.3.0rc4 |

> Nota honesta: a missão previa 5 commits; há **6**. O 6º é um shim de 4 linhas
> adicionado na pré-promoção porque o próprio checklist da missão usa
> `python -m nomos doutor`, que exigia esse ponto de entrada. Não altera
> comportamento nem arquitetura.

## Garantias preservadas (todas provadas por teste)
- **Local-first**: cadeado ligado por padrão; egress externo negado na política.
- **Fail-closed**: sem TTY/aprovação, ação sensível é negada (rc=3).
- **Zero telemetria**: `test_egress_zero` (allowlist estática justificada).
- **Sem cloud silenciosa**: nuvem só com cadeado aberto + chave + A2+A3.
- **Sem bypass de aprovação**: nenhum caminho novo; agentes usam o mesmo gate.
- **Sem rotina sensível automática**: skills que pedem aprovação não rodam sós.
- **Sem persistência em modo privado**: store `:memory:`, FS inspecionado no teste.
- **Agente não é bypass do gate**: ferramenta fora do manifesto negada; A1 sem
  aprovação negado; sem herança entre agentes.
- **Anti-injection**: conteúdo recuperado envelopado como DADO; oferta de skill
  só do texto digitado.

## Testes
- Total: **494** (todos passam).
- Smoke wheel em venv limpo: PASS (`nomos --version`, `nomos doutor` rc=0,
  `nomos agentes listar` mostra os 3 oficiais).
- `git fsck --full`: PASS (após recuperar 1 objeto corrompido pelo sandbox).
- Cobertura: kernel policy/localidade 100%, vault 97%; geral 84%.
- CI remoto: **NÃO VERIFICADO AINDA** (aguarda push).

## Correções críticas
- **Agentes oficiais fora do wheel** (defeito real pego pelo smoke da F6): os
  manifestos viviam em `examples/` (não empacotado) e `nomos agentes listar`
  vinha vazio na instalação por wheel. Corrigido: movidos para
  `src/nomos/agents/oficiais/`, declarados em `package-data`, registry aponta
  para dentro do pacote. Reconfirmado em venv limpo (3 agentes listados).
- **Objeto git corrompido** durante um commit (efeito do sandbox bloqueando
  `unlink` de `tmp_obj`): detectado por `fsck`, objeto órfão removido, commit
  refeito, árvore reconferida — não mascarado.

## Riscos remanescentes (honesto)
1. **CI verde no GitHub não verificado** — depende do push; o job `smoke`
   (build wheel + install + doutor nos 3 SOs) só roda lá.
2. **Auditoria de segurança independente do kernel** — ainda não feita.
3. **Publicação (release/PyPI)** — pendente.
4. **mypy** é informativo (não bloqueante) e cobre só o kernel por ora.

## Próximo ciclo recomendado (apenas 1)
Após o push e o CI verde: **auditoria de segurança independente do kernel**
(vault, policy, audit, sandbox), pré-requisito do 1.0.0 final — todo o resto do
backlog é incremental e já tem testes.
