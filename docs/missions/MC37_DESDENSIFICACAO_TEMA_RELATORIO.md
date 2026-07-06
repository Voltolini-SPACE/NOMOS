# RELATÓRIO FINAL — MC37 · Menos poluição visual + tema claro/escuro (loop-100)

Data: 2026-07-06 · Método: `implementation-loop-100`

## 1. Status

```text
STATUS_FINAL=WARN_PARTIAL_DELIVERY_WITH_EXPLICIT_GAPS
```

Tudo implementado, testado e evidenciado. Um gap externo: screenshot
pixel-real (extensão Chrome desconectada; sandbox sem root p/ headless) —
compensado por 4 previews HTML abríveis, contraste WCAG calculado
numericamente, parser de HTML, `node --check` no JS e smoke HTTP real.

## 2. Objetivo

Reduzir a densidade visual (painel, site, CLI) e garantir que a ferramenta
tenha tema claro E escuro.

## 3. O que mudou

**Painel (`nomos painel`) — de 16 seções numa página para 5 abas:**
`visão geral` · `cérebro` · `capacidades` · `operação` · `ajuda`. Uma aba por
vez; a visão geral abre por padrão. Rail lateral eliminado (motor ao vivo,
"precisa de você" e atividade migraram para a visão geral). KPIs 8 → 5.
Catálogo de motores, tabela A0–A6 e eventos da auditoria viraram `<details>`
fechados. Deep-links antigos (`#motores`…) continuam válidos via subnav + JS
que ativa a aba da âncora.

**Tema claro/escuro (painel e site):** escuro é o padrão (brandbook
congelado); tema claro com paleta de contraste WCAG AA verificada; botão de
alternância acessível (`aria-pressed`), respeito a `prefers-color-scheme`,
persistência em localStorage e boot antes do CSS pintar (sem flash).

**Site:** hero 6 → 4 números; ~20 cards de recursos em 3 grupos recolhíveis
(1º aberto); tabela de 15 motores recolhível; navegação do topo enxuta.

**CLI:** `nomos --help` sem a chave gigante `{start,cerebro,…}` — metavar
`<comando>`; epílogo aponta o menu amigável e o `--help` por comando.

## 4. Comandos executados (evidência)

| Verificação | Resultado |
|---|---|
| `pytest` (suíte completa) | **1.344 passed, 0 failed** |
| `ruff check .` | All checks passed |
| `python -m build` | wheel + sdist 1.3.0rc17 OK |
| `nomos_update_agent --check` (gate MC33) | consistent True · 13/13 |
| contraste WCAG tema claro (painel+site) | todos os pares ≥ mínimo AA |
| parser HTML do site | 0 erro, 0 tag não fechada, 0 âncora quebrada |
| `node --check` no JS do painel | OK |
| smoke HTTP real (painel: abas, tema, rotas técnicas, POST) | 200/405/400 corretos |

## 5. Contratos de teste atualizados (com justificativa)

- `test_painel_v4_hermes`: `..._sidebar_rail_e_sysbox` → `..._abas_...` (rail
  removido → abas); `roteador_vivo_no_rail` → `..._na_visao_geral`.
- `test_mc29_painel`: "Motores (catálogo completo)" → "catálogo completo de
  motores" (virou `<details>`).
- Novo: `tests/test_painel_tema_e_abas.py` (6 casos — 5 abas, deep-links,
  KPIs=5, tema claro+escuro definidos, botão+boot, read-only).

## 6. Commits (locais, sem push)

```text
e553c92 feat(painel): MC37 — cockpit em 5 abas + tema claro/escuro
f9dcbef feat(cli):    MC37 — help sem a chave gigante (metavar <comando>)
f903cd1 feat(site):   MC34.2 — 'painel por dentro' (checkpoint da sessão paralela)
ae5f1ba feat(site):   MC37 — tema claro/escuro + menos densidade
```

## 7. Gaps conhecidos

```text
KNOWN_GAPS=1
```
- Screenshot pixel-real não executado (Chrome MCP off; sandbox sem root).
  Mitigação: `_preview_painel.html`, `_preview_painel_claro.html`,
  `_preview_site_escuro.html`, `_preview_site_claro.html` — abra no navegador.

Governança: commits diretos na `main` local por instrução do humano; a
sessão paralela teve o WIP do site preservado num commit de checkpoint antes
de eu editar; push é humano.

## 8. Veredito

Painel, site e CLI ficaram mais enxutos e navegáveis, e a ferramenta passou a
ter tema claro e escuro em ambas as superfícies, com contraste AA verificado.
Suíte 1.344 verde após cada bloco; zero regressão.
