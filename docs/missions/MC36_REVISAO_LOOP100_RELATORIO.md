# RELATÓRIO FINAL — MC36 · Revisão e aprimoramento completo (Implementation Loop 100%)

Data: 2026-07-06 · Executor: sessão Claude (Cowork) autorizada pelo humano ·
Método: `implementation-loop-100` (SPEC → IMPLEMENTAR → TESTAR → VALIDAR →
APRIMORAR → RE-TESTAR → EVIDENCIAR → ENTREGAR)

## 1. Status

```text
STATUS_FINAL=WARN_PARTIAL_DELIVERY_WITH_EXPLICIT_GAPS
```

Tudo implementado, testado e evidenciado — com **um** gap explícito, externo e
não-mascarável: a validação visual por screenshot real (pixel) não pôde ser
executada (extensão Chrome desconectada; sandbox sem root e com apt bloqueado
para instalar headless). Compensada por validações objetivas equivalentes
(HTML parser, âncoras, contraste WCAG calculado numericamente, `node --check`
no JS, smoke HTTP real do painel, 1.333 testes). Sem esse único item, todos os
critérios fecharam em 100%.

## 2. Objetivo

Revisão e aprimoramento completo do repo `nomos`: código, UX, design,
usabilidade e git — com correção total dos achados (decisão do humano).

## 3. Escopo executado

- Auditoria tripla paralela: núcleo (kernel/cognition/council/ext/runtime),
  camada de aplicação (cli/interface/simple/agents/conversations) e
  UX/design/acessibilidade (site + painel + CLI).
- Correção de TODOS os achados (1 P0 código, 2 P0 UX, 2 P1 concorrência,
  ~30 P1/P2) em 4 blocos commitados separadamente.
- Higiene de git e relatório.

## 4. Arquivos alterados (commits locais, sem push — regra do CLAUDE.md)

| Commit | Tema |
|---|---|
| `c22957e` | fix(security): exec opt-in no doutor, single-use atômico, auditoria sem bifurcação |
| `6f324de` | feat(ux): rótulos humanos, painel sem armadilhas, CLI pt-BR, fluxos honestos |
| `b8b736a` | fix(site): o site diz a verdade (comandos, versão, catálogo, grupos, a11y) |
| `e3d8eef` | chore(git): .gitignore sem duplicatas |
| `cc5e364` | fix(painel): contraste da borda 3.5:1 (WCAG 1.4.11) |

Novos testes: `tests/test_revisao_seguranca_2026.py` (10 casos). Contratos
atualizados com justificativa: refresh via `meta nomos-refresh`, `doutor
--repo`, `evidencia` pelado lista, `NET_EGRESS` alvo vazio ⇒ DENY,
`test_panel` categoria com rótulo + id.

## 5. Arquivos preservados / congelados

`archive/`, `Atlas.app`, material da sessão concorrente (`CLAUDE.md`,
`loop/*`, `site/assets/painel-*.webp`, `docs/missions/MC35_*` — deixados
intactos e não commitados por não serem deste fluxo).

## 6. Comandos executados (principais)

| Comando | Retorno | Resultado |
|---|---:|---|
| `pytest` (suíte completa, 2 blocos) | 636 + 697 | **1.333 passed, 0 failed** |
| `ruff check .` | 0 | All checks passed |
| `python -m compileall src` | 0 | OK |
| `python -m build` | 0 | wheel + sdist 1.3.0rc17 |
| `tools/nomos_update_agent.py --check` | 0 | consistent: True · 13/13 (gate MC33) |
| smoke CLI (`--version`, `doutor`, `status`, `memoria`, `evidencia`, `mcp`) | 0 | saídas corretas |
| smoke HTTP painel (servidor real) | — | GET 200 · health 200 · POST rota errada 405+link · Content-Length inválido 400 |

## 7. Correções de segurança (bloco 1 — as que importam)

1. **`nomos doutor` executava código do CWD sem pedido** (fail-open): rodar o
   comando numa pasta com 3 arquivos certos disparava `tools/*.py`. Agora é
   opt-in `--repo`, com teste que planta um "repo malicioso" e prova que nada
   executa sem a flag.
2. **Single-use de aprovações não era atômico**: N decisores simultâneos
   (duas abas, painel+terminal, duplo-clique) podiam todos passar na checagem.
   Agora `decide()` reivindica por `os.replace` atômico + lock: exatamente UM
   vence (teste com 8 threads em barreira); claim órfão de crash expira
   fail-closed.
3. **Cadeia de auditoria bifurcava sob concorrência** e uma cauda parcial de
   crash quebrava `verify()` para sempre. Agora: lock por trilha + `flock`
   best-effort + reparo de cauda no próximo append (testes de concorrência e
   de reparo).
4. Cadeado só-local: alvo vazio/não-parseável não é mais "loopback".
5. Redação de segredos cobre `chave`/`credencial`; fila de aprovações tolera
   arquivo corrompido; POST do painel valida Content-Length/UTF-8.
6. `nomos chaves` não destrói mais a chave colada quando a senha-mestra está
   errada (`Vault.verify_passphrase` valida ANTES do wipe).

## 8. UX / design / usabilidade

Site: comandos que não existiam corrigidos, versão honesta (wheel real da
release é 1.3.0rc16), link direto do `.whl`, card SDK sem promessa falsa,
catálogo 15/15, 20 cards agrupados em 3 blocos, ~30 emojis `aria-hidden`,
`scope=col`, "cofre" unificado, `--fraco` sincronizado (6.3:1).
Painel: rótulos humanos nas aprovações ("A2 · sair para a rede"), auto-reload
pausável com estado visível, botões desabilitam ao expirar, contador do
filtro, ↗ em navegação externa, botão buscar, tipografia ≥ .72rem, bordas
3.5:1, erros com caminho de volta. Painel antigo herdou headers + PRG.
CLI: help 100% pt-BR (13 subcomandos descritos), comandos pelados com default
útil, `--sem-abrir`/`--somente-leitura`, onboarding honesto (cofre existente
não pede senha; cérebro embutido antes do Ollama).

## 9. Anti-regressão

Suíte completa executada após CADA bloco e ao final: 1.333/1.333. Baseline
inicial (1.324) preservada — 9 testes novos somados, nenhum removido, nenhum
skip novo. Gate MC33 (site⇄produto) verde. Build ok.

## 10. Gaps conhecidos

```text
KNOWN_GAPS=1
```

- **Screenshot pixel-real do site/painel não executado** (extensão Chrome
  desconectada; sandbox sem root p/ headless). Mitigação já entregue:
  `_preview_painel.html` na pasta selecionada — abra no navegador para
  conferência visual em segundos. Validações estruturais/numéricas todas
  verdes.

Notas de governança (sem ação minha, decisão humana):
- Commits feitos direto na `main` local por instrução explícita do humano
  nesta sessão — diverge da regra 3 do CLAUDE.md; reconciliar se desejado.
- Duas sessões de agente na mesma árvore hoje: o loop autônomo abortou
  fail-closed (Rodadas 1–2) ao detectar esta sessão — guardrails funcionaram;
  recomendo rodar um de cada vez.
- `origin/main` está 7 commits atrás do local; push é humano.

## 11. Critérios de aceite

| Critério | Status | Evidência |
|---|---|---|
| ruff limpo | ✅ | "All checks passed!" |
| pytest 100% verde | ✅ | 1.333 passed / 0 failed |
| build OK | ✅ | nomos-1.3.0rc17 (whl+sdist) |
| site validado | ✅ estrutural / ⚠️ pixel | parser sem erros, âncoras 100%, contraste calculado, 11 testes de site; screenshot = gap |
| tree limpo (meu escopo) | ✅ | só restos da outra sessão, documentados |
| zero regressão | ✅ | suíte completa após cada bloco |

## 12. Veredito

Entrega íntegra com evidência real em tudo que pôde ser executado no
ambiente; um único gap externo, explícito e com mitigação pronta. O produto
sai mais seguro (3 fixes de concorrência/fail-open), mais honesto (site =
produto) e mais usável (painel e CLI falam a língua de quem decide).
