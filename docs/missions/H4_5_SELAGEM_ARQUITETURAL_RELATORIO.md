# H4.5 — Selagem arquitetural, fail-closed executável e preparação do 1.3.0rc18

Relatório final da missão H4.5, executada em continuação direta do estado
comprovado ao fim de H4 (commit `845eda6`, rodada anterior). Esta missão
não redescobre nem refaz H4.0/HIGH-01/HIGH-02 — só os revalida onde os
gates de não regressão exigem.

## 1. STATUS_FINAL

```
STATUS_FINAL=H4_5_PASS
BASELINE_HEAD=845eda613fe7a400b2a1ced3d3081e200c5bea60
FINAL_HEAD=<preenchido no commit deste documento — ver `git rev-parse HEAD` após o commit>
VERSION_INITIAL=1.3.0rc17
VERSION_FINAL=1.3.0rc17
COMMITS_CREATED=5 (H4.5-A 62b1927, H4.5-B 845eda6, H4.5-C c665330, H4.5-D 13da85a, docs deste arquivo)
TESTS_PASSED=1973
TESTS_FAILED=0
MYPY_ERRORS=0
RUFF_ERRORS=0
COVERAGE_GENERAL=84.92%
COVERAGE_DIRECTED=95.45%
POLICY_FAIL_CLOSED=PASS
AGENT_CORRUPTION_NON_FATAL=PASS
AGENT_REPAIR_PRESERVES_ORIGINAL=PASS
BOUNDARY_BYPASS_GATE=PASS
COUNCIL_CONTRACTS=PASS_COM_2_GAPS_ARQUITETURAIS_DOCUMENTADOS
WHEEL_SMOKE=PASS
SITE_DOC_CONSISTENCY=13_DE_13
WORKTREE_STATUS=CONTROLADO
PRODUCTION_MUTATED=SIM (só doutor.py, H4.5-B — hash+quarentena+chmod+falha-segura no reparo de arquivo corrompido)
PUSH_PERFORMED=PARCIAL (62b1927 e 845eda6 publicados externamente pelo usuário; c665330/13da85a/docs pendentes)
PUSH_BLOCKER=BLOCKED_BY_CREDENTIALS (sandbox) + bloqueio de UI no GitHub Desktop (dialog do sistema intercepta o clique automatizado)
NEXT_RECOMMENDED_STEP=usuário clicar "Push origin" no GitHub Desktop já aberto; depois avaliar bump local de versão para 1.3.0rc18
```

## 2. Baseline revalidado

Comandos executados antes de qualquer edição, confirmando o estado
declarado no início da missão:

```
git status --short         -> só os 2 untracked pré-existentes (H4.0)
git branch --show-current  -> loop/fase3-agent-boundary-wiring
git rev-parse HEAD         -> 845eda613fe7a400b2a1ced3d3081e200c5bea60
```

Sem divergência de baseline — prosseguiu-se normalmente.

## 3. Achados e objetivos (H4.5-A a H4.5-D)

### H4.5-A — PolicyEngine fail-closed real (commit `62b1927`)

23 testes de integração em
`tests/test_h4_5_a_policy_fail_closed_integration.py`, exercitando o
caminho público real (`cli.main(["agentes","usar",...])` →
`AgentToolBoundary.usar_ferramenta()` → `PolicyEngine.decide()` →
`gate()`), não métodos privados isolados. Prova, para 4 estados não
confiáveis de `policy.json` (JSON inválido, raiz `[]`, raiz `null`, raiz
string) mais 2 controles positivos (ausente → regenera padrão seguro;
dict válido explícito):

- uma ação normalmente-ALLOW (A0) é negada quando a política não é
  confiável — não existe "regra ausente == permita tudo";
- uma ação com efeito externo (`skill_rodar`, A5) é negada, e o callback
  de execução real NUNCA é chamado (prova por rastreamento, não só pelo
  código de retorno);
- `nomos doutor` (diagnóstico) e `nomos doutor --consertar` (sem
  confirmação) continuam funcionando mesmo com `policy.json` corrompido
  — a própria ferramenta de recuperação não fica presa atrás da política
  que ela existe para consertar.

### H4.5-B — Quarentena forense do agent.json (commit `845eda6`)

Reforça o mecanismo genérico já existente em `doutor.consertar()` (usado
por agent.json/localidade.json/policy.json/skills_estado.json/
rotinas.json — não um subsistema paralelo) com: hash SHA-256 do arquivo
corrompido antes de mover (evidência forense verificável, nunca o
conteúdo em si); `os.replace()` atômico para quarentena (`.corrompido`,
`.corrompido.1`, ... nunca sobrescreve); modo 0600 na quarentena; caminho
e hash na resposta e na auditoria; falha de I/O durante o `os.replace()`
preserva o original intacto e pára o restante do reparo, com diagnóstico
verificável (`type(exc).__name__`), não um catch genérico mudo. 10 testes
novos em `tests/test_h4_5_b_agent_json_quarantine.py`.

### H4.5-C — Gate AST contra bypass do AgentToolBoundary (commit `c665330`)

9 testes em `tests/test_h4_5_c_agent_tool_boundary_gate.py`, puramente
aditivo (nenhum código de produção alterado — o inventário prévio
confirmou que a árvore atual já respeita os 3 invariantes abaixo):

1. só `cli.py` e `simple/amigavel.py` podem importar
   `nomos.agents.execucao` diretamente (allowlist exata, checada nos dois
   sentidos);
2. `nomos.agents.*` nunca importa subprocess/rede diretamente;
3. `nomos.council` inteiro (16 arquivos) nunca importa `nomos.agents` nem
   subprocess/rede diretamente — generaliza para o pacote todo o mesmo
   invariante que `tests/council/test_orchestrator_security.py` já
   provava só para `orchestrator.py`.

3 fixtures sintéticas (`tmp_path`) provam que o gate DETECTA um bypass
real quando ele existe — não passa só por não achar arquivos.

### H4.5-D — Contratos residuais do Council (commit `13da85a`)

20 testes em `tests/test_h4_5_d_council_contract_residuals.py`, sobre o
pipeline real (`OfflineCouncilSimulator.run_with_candidates`, o mesmo
núcleo que `CouncilOrchestratorDryRun.run()` chama). Levantamento prévio
(grep + leitura) contra a suíte existente, item a item, registrado no
docstring do módulo:

| # | Cenário pedido pela missão | Cobertura antes | Ação tomada |
|---|---|---|---|
| 1 | timeout de um membro não derruba o conselho | não coberto (só falha do único candidato) | 2 testes novos: timeout parcial segue normal; timeout total bloqueia fail-closed |
| 2 | parecer malformado é rejeitado | só no modelo paralelo `JudgeScore`, não usado pela simulação real | 4 testes novos no objeto REAL (`SimulatedJudgeFixture`): nota fora de 0–5, tipo inválido, alias vazio, prefixo ausente |
| 3 | nenhuma decisão fabricada sem quórum | `test_council_simulator.py:109-116` cobria failure_code+blocked | estendido (não duplicado): prova `final_content`/`selected_candidate_alias` vazios/None + sub-caso zero-juízes |
| 4 | decisão final preserva dissenso/motivo | zero asserções sobre `.reasons` em toda a suíte | 5 testes novos (quórum insuficiente, divergência alta, alerta crítico, gate negado, contraste aprovado) |
| 5 | limite de rodadas é respeitado | **N/A arquitetural** | ver abaixo |
| 6 | orçamento excedido interrompe deliberação | **N/A arquitetural** | ver abaixo |

**Itens 5 e 6 — GAP_ARQUITETURAL, não um bug:** `rg -i "round|rodada"` e
`rg -i "budget|orcamento|orçamento"` em todo `src/nomos/council/` não
encontram nenhuma ocorrência. O Council, nesta fase (MC1–MC8, dry-run), é
um pipeline de UMA passada só, por desenho — não existe deliberação
multi-rodada nem orçamento/custo em lugar nenhum do código atual. Criar
testes para esses dois itens exigiria inventar uma feature de produção
nova, o que violaria `NO_BROAD_REFACTOR` e a restrição explícita da
missão contra criar arquitetura idealizada. Registrado aqui como risco
residual documentado, não escondido — se o Council evoluir para
deliberação real multi-rodada com orçamento de custo/tempo no futuro,
estes 2 itens tornam-se testáveis e devem ser retomados nessa ocasião.

## 4. Testes e comandos (evidência real, não alegada)

```
COMANDO: pytest -q tests/test_h4_5_c_agent_tool_boundary_gate.py
RETORNO: 0
RESULTADO: 9 passed

COMANDO: pytest -q tests/test_h4_5_d_council_contract_residuals.py
RETORNO: 0
RESULTADO: 20 passed

COMANDO: pytest -q <regressão alvo: council/, agentes, boundary, H4.5-A/B/C>
RETORNO: 0
RESULTADO: 472 passed (após H4.5-C) / 463 passed (após H4.5-D, escopo levemente diferente)

COMANDO: pytest -q -n4  (suíte completa)
RETORNO: 0
RESULTADO: 1973 passed, 0 failed

COMANDO: ruff check src tests examples
RETORNO: 0
RESULTADO: All checks passed!

COMANDO: mypy src/nomos --ignore-missing-imports
RETORNO: 0
RESULTADO: Success: no issues found in 112 source files

COMANDO: pytest -q -n4 --cov=nomos --cov-report=term --cov-fail-under=80
RETORNO: 0
RESULTADO: TOTAL coverage 84.92% (gate >=80%)

COMANDO: pytest -q --cov=nomos.kernel.evidencia --cov=nomos.ext.skill_catalogo --cov-report=term --cov-fail-under=90 tests/test_evidencia_pacote.py tests/test_mc29_skills_catalogo.py tests/test_mc29_painel.py tests/test_mc30_onda_a.py
RETORNO: 0
RESULTADO: TOTAL coverage 95.45% (gate >=90%)

COMANDO: python -m build --wheel --outdir /tmp/nomos_wheel_build2
RETORNO: 0
RESULTADO: Successfully built nomos-1.3.0rc17-py3-none-any.whl

COMANDO: pip install <wheel> && nomos init && nomos status && nomos doutor
RETORNO: 0
RESULTADO: STATUS GERAL: PRONTO — 3 agentes catalogados, 8/8 ferramentas com execução ligada

COMANDO: python tools/nomos_update_agent.py --check --json
RETORNO: 0
RESULTADO: checks_total=13, checks_passed=13, checks_failed=0, consistent=true

COMANDO: python docs/missions/repro_known_gap_policy_json_shape.py
RESULTADO: comportamento de alto nível (doutor detecta) confirmado corrigido — consistente com HIGH-02

COMANDO: python docs/missions/repro_known_gap_agent_json_crashes_doutor.py
RESULTADO: comportamento de alto nível (doutor repara) confirmado corrigido — consistente com HIGH-01/H4.5-B
```

## 5. Scripts sentinela (novos, adicionados nesta missão)

- `tests/test_h4_5_a_policy_fail_closed_integration.py` — sentinela de
  fail-closed real da política, pelo caminho público de execução.
- `tests/test_h4_5_b_agent_json_quarantine.py` — sentinela de quarentena
  forense do reparo de arquivo corrompido.
- `tests/test_h4_5_c_agent_tool_boundary_gate.py` — sentinela de gate
  arquitetural contra bypass do `AgentToolBoundary`.
- `tests/test_h4_5_d_council_contract_residuals.py` — sentinela de
  contratos residuais do Council.

Qualquer regressão futura nesses 4 invariantes quebra a suíte.

## 6. Riscos residuais

1. **GAP_ARQUITETURAL (H4.5-D, itens 5–6):** sem limite de rodadas nem
   orçamento no Council porque o pipeline é single-pass por desenho
   nesta fase — não é uma falha de segurança hoje (não há deliberação
   real multi-rodada para exceder), mas se essa capacidade for
   construída no futuro, esses 2 invariantes precisam de testes reais
   nessa ocasião, não antes.
2. **PUSH bloqueado do lado do sandbox** (`BLOCKED_BY_CREDENTIALS`,
   inalterado desde H4) e, nesta sessão, **bloqueio de UI** ao tentar
   usar o GitHub Desktop já aberto via automação (um diálogo do sistema,
   fora da allowlist de apps concedida, intercepta o clique no botão
   "Push origin" sem ficar visível para inspeção). Os commits `c665330`
   e `13da85a` (mais este documento) ficam pendentes de publicação até o
   usuário clicar manualmente ou resolver o diálogo do sistema.
3. **Bump de versão para 1.3.0rc18 não executado nesta missão:** todos
   os critérios do §6 da missão estão com PASS (ver bloco STATUS_FINAL
   acima), mas o plano de commits da missão (§4) não incluía um commit
   de bump, e alterar `pyproject.toml`/`src/nomos/__init__.py`/
   `site/index.html`/`README.md`/`CHANGELOG.md` simultaneamente é uma
   mudança de escopo que preferi deixar como decisão explícita para o
   próximo passo, em vez de expandir silenciosamente o escopo desta
   missão.

## 7. Decisão sobre 1.3.0rc18

Critérios do §6 — todos PASS (ver bloco `STATUS_FINAL` no topo deste
documento). **Pronto para bump local**, mas o bump em si não foi
executado nesta missão (ver risco residual #3 acima) — fica como
`NEXT_RECOMMENDED_STEP`. Nenhuma tag remota ou publicação deve ocorrer
enquanto o push estiver bloqueado, por instrução explícita da missão.

## 8. Estado do push

```
REMOTE_PUSH=BLOCKED_BY_CREDENTIALS (sandbox)
```

`git ls-remote origin loop/fase3-agent-boundary-wiring` mostra
`845eda6...` — os commits H4.5-A e H4.5-B já estão publicados (o usuário
fez o push externamente, fora deste ambiente). H4.5-C, H4.5-D e este
documento ainda não. O GitHub Desktop do usuário já está aberto e mostra
"Push origin (2↑ → 3↑ após este commit)" pronto para clicar.

## 9. Próximo horizonte

1. Usuário publica os 3 commits pendentes (clique manual no GitHub
   Desktop, ou nova tentativa de push externo).
2. Avaliar e decidir explicitamente o bump para `1.3.0rc18` (todos os
   arquivos de versão, coordenados num único commit `chore` dedicado).
3. Se/quando o Council evoluir para deliberação real multi-rodada,
   retomar os itens 5–6 de H4.5-D (limite de rodadas, orçamento) com
   testes reais sobre a nova arquitetura.
