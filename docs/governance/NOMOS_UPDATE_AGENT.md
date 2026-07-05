# 🤖 NOMOS Update Agent

**Versão:** 1.0.0  
**Data:** 2026-07-05  
**Status:** Documentado para MC25

---

## Visão Geral

O **NOMOS Update Agent** é um processo de governança que mantém **sempre sincronizados e consistentes**:

- 📖 README.md
- 📦 Manual de Instalação (docs/INSTALL.md + docs/installation/NOMOS_INSTALLATION_MANUAL.md)
- 🎨 Brandbook (docs/brand/NOMOS_BRANDBOOK.md)
- 🌐 Landing Page (site/index.html)
- 📋 CHANGELOG.md
- 🔗 Índice de documentação (docs/README.md ou similar)

O agente **não executa automaticamente** — apenas:
1. ✅ Detecta inconsistências
2. ✅ Gera plano de atualização
3. ✅ Cria diff proposto
4. ✅ Roda testes/checks locais
5. ✅ Cria relatório
6. ✅ **Pede aprovação humana** antes de qualquer commit/push

### Princípios Fundamentais

- **Fail-Closed:** Nunca executa automaticamente
- **Approval-First:** Pede OK humano antes de cada mudança
- **Transparency:** Todo diff é visualizável antes de aplicar
- **Dry-run Default:** Tudo roda em modo simulação
- **No Push:** Nunca faz `git push`, `git tag` ou release automático
- **Local-First:** Sem rede, sem segredos, sem execução real

---

## Casos de Uso

### 1. Após Atualizar README

Se você modificou `README.md` com nova feature:

```bash
tools/nomos_update_agent.py --check
```

Agente detecta:
- ❌ Brandbook não menciona essa feature
- ❌ Manual não tem seção sobre isso
- ❌ Landing page não mostra isso

Gera plano:
```
Inconsistências detectadas:

1. README.md: Feature "X" nova
   → Brandbook precisa de seção em "5. Mensagens Canônicas"
   → Manual precisa de seção em "Como Funciona"
   → Landing page precisa de atualização em "Features"

2. Recomendação: Atualizar na ordem:
   a) Brandbook (1 linha)
   b) Manual (3 linhas)
   c) Landing page (5 linhas)
```

### 2. Atualizar Versão

Se você vai lançar v1.4.0:

```bash
tools/nomos_update_agent.py --version 1.4.0 --dry-run
```

Agente calcula:
- ✅ Atualizar `pyproject.toml`
- ✅ Atualizar `CHANGELOG.md`
- ✅ Atualizar referências em README
- ✅ Atualizar versão em `__init__.py`
- ✅ Gerar `CHANGELOG` entry

Mostra diff:
```diff
- version = "1.3.0rc16"
+ version = "1.4.0"

- ## [Unreleased]
+ ## [1.4.0] - 2026-07-05
+ - Feature X
+ - Bugfix Y
+
+ ## [Unreleased]
```

Pede confirmação:
```
✓ Diff gerado. 5 linhas mudadas em 3 arquivos.
✓ Testes passam (ruff, pytest).
✓ Pronto para aplicar?

[y/n/show-diff]
```

### 3. Auditoria de Consistência

Verificar que tudo está sincronizado:

```bash
tools/nomos_update_agent.py --audit
```

Relatório:
```
✓ README menciona v1.3.0rc16
✓ pyproject.toml tem v1.3.0rc16
✓ CHANGELOG tem entry para v1.3.0rc16
✓ Brandbook está atualizado (MC25)
✓ Manual está atualizado (MC25)
✓ Landing page está atualizado
✓ Todos os links funcionam
✓ Nenhum segredo exposto
✓ Nenhuma tag orfã

✅ Estado: CONSISTENTE
```

---

## Comando: `tools/nomos_update_agent.py`

### Disponível? Opções?

```bash
# Ver ajuda
python tools/nomos_update_agent.py --help

# Sintaxe geral
python tools/nomos_update_agent.py [ACTION] [--flags]
```

### Actions

| Action | Descrição |
|--------|-----------|
| `--check` | Detectar inconsistências entre README, Brandbook, Manual, Landing |
| `--audit` | Auditoria completa (links, termos, conteúdo, segredos) |
| `--version <V>` | Preparar atualização de versão para V |
| `--report` | Gerar relatório de estado (sem aplicar) |
| `--apply` | **[REQUER FLAG EXTRA]** Aplicar mudanças aprovadas |

### Flags

| Flag | Efeito |
|------|--------|
| `--dry-run` | Padrão: simular sem escrever (seguro) |
| `--no-dry-run` | **[NÃO USE]** Requer `--i-understand-this-writes-files` |
| `--i-understand-this-writes-files` | Necessário para `--apply` |
| `--show-diff` | Mostrar diff antes de aplicar |
| `--no-tests` | Pular testes (não recomendado) |
| `--verbose` | Output detalhado |
| `--quiet` | Output mínimo |

### Exemplos

```bash
# Ver inconsistências (SEGURO — apenas lê)
python tools/nomos_update_agent.py --check

# Auditoria completa (SEGURO — apenas lê)
python tools/nomos_update_agent.py --audit

# Preparar atualização para v1.4.0 (SEGURO — simula)
python tools/nomos_update_agent.py --version 1.4.0

# Ver diff em detalhes (SEGURO — apenas mostra)
python tools/nomos_update_agent.py --version 1.4.0 --show-diff

# Aplicar mudanças (NÃO SEGURO — escreve em disk)
python tools/nomos_update_agent.py --version 1.4.0 --apply --i-understand-this-writes-files

# Gerar relatório (SEGURO — apenas lê e salva relatório em texto)
python tools/nomos_update_agent.py --report
```

---

## Detecção de Inconsistências

O agente verifica automaticamente:

### README ↔ Brandbook

```
❌ README menciona "feature X"
✅ Brandbook menciona "feature X"?
   Se não, adicionar em:
   - 5. Mensagens Canônicas (se for message relevante)
   - 2. Posicionamento (se for diferencial)
```

### README ↔ Manual

```
✅ README diz "instalação em um comando"
✅ Manual tem seção "Instalação Rápida"?
   Se não, adicionar
```

### Manual ↔ Landing Page

```
✅ Manual menciona "dry-run"
✅ Landing menciona "dry-run"?
   Se não, adicionar em "Como Funciona"
```

### Brandbook ↔ Todos

```
✅ Brandbook define termos canônicos (agente, skill, motor, etc.)
✅ README usa esses termos?
✅ Manual usa esses termos?
✅ Landing usa esses termos?

Se não, sinalizaaviso (não força, educacional)
```

### Documentação ↔ Código

```
✅ pyproject.toml tem version = "1.3.0rc16"
✅ README menciona v1.3.0rc16?
✅ docs/INSTALL.md menciona v1.3.0rc16?
✅ CHANGELOG tem entry para v1.3.0rc16?

Se divergências, sinalizar
```

### Links

```
✅ README → docs/INSTALL.md
✅ README → GitHub
✅ Landing → docs/
✅ Manual → Brandbook
✅ Brandbook → Roadmap

Verificar que não estão quebrados
```

### Segurança

```
❌ Nenhum secret (API key, password, token) em:
   - README
   - Docs
   - Brandbook
   - Manual
   - Landing page
   - CHANGELOG
   
Se encontrar, erro crítico
```

---

## Relatório de Saída

Quando roda `--check` ou `--report`, gera:

```
╔════════════════════════════════════════════════════════════════╗
║          NOMOS Update Agent — Relatório de Estado             ║
╠════════════════════════════════════════════════════════════════╣
║ Data: 2026-07-05 15:30:45                                     ║
║ HEAD: bbe28206... (main)                                       ║
║ Versão NOMOS: 1.3.0rc16                                        ║
╚════════════════════════════════════════════════════════════════╝

✅ CONSISTÊNCIA

README.md:
  ✓ Versão correta (1.3.0rc16)
  ✓ Linkspara docs, install, GitHub funcionam
  ✓ Tagline "Local por lei" presente

Brandbook:
  ✓ Existe em docs/brand/NOMOS_BRANDBOOK.md
  ✓ Termos canônicos definidos
  ✓ Mensagens para 3 públicos presentes

Manual:
  ✓ Existe em docs/installation/NOMOS_INSTALLATION_MANUAL.md
  ✓ Todas as 7 seções presentes
  ✓ Código de exemplo atualizado

Landing Page:
  ✓ Existe em site/index.html
  ✓ Hero, features, instalação presentes
  ✓ Links funcionam
  ✓ Responsivo

CHANGELOG:
  ✓ Entry mais recente é v1.3.0rc16
  ✓ Formato correto

❌ ISSUES (1)

Landing Page:
  ⚠ Seção "Roadmap" ainda menciona MC24
  ℹ Recomendação: Atualizar para MC25

⚠ AVISOS (0)

⚠ SEGURANÇA

✓ Nenhum secret detectado
✓ Nenhuma chave exposta
✓ Nenhum token em docs

TESTE

✓ ruff check: 0 errors
✓ pytest: 952 passed
✓ Links: 12/12 funcionando

RESUMO

Status: ✅ CONSISTENTE (com 1 aviso menor)

Ações recomendadas:
  1. Atualizar Landing Page com MC25

Próxima execução sugerida: 2026-08-05

────────────────────────────────────────────────────────────────
Relatório salvo em: docs/governance/UPDATE_AGENT_REPORT_20260705.txt
```

---

## Workflow Recomendado

### Quando Você Muda README

```bash
# 1. Faz edit em README.md
# 2. Verifica inconsistências
python tools/nomos_update_agent.py --check

# 3. Se houver, agente mostra o que precisa atualizar
# 4. Você atualiza Brandbook/Manual/Landing manualmente

# 5. Verifica de novo
python tools/nomos_update_agent.py --check
# ✅ Tudo consistente agora

# 6. Commit normalmente
git add README.md docs/brand/ docs/installation/ site/
git commit -m "Update README with feature X"
git push origin main
```

### Quando Você Vai Lançar Versão

```bash
# 1. Você decide lançar v1.4.0
python tools/nomos_update_agent.py --version 1.4.0

# 2. Agente mostra diff
# 3. Você revisa (--show-diff se quiser detalhe)
python tools/nomos_update_agent.py --version 1.4.0 --show-diff

# 4. Você aprova manualmente
# 5. Agente aplica (COM sua aprovação)
python tools/nomos_update_agent.py --version 1.4.0 --apply --i-understand-this-writes-files

# 6. Você revisa que mudou
git diff

# 7. Você faz commit (você, não o agente)
git add .
git commit -m "Version bump to 1.4.0"

# 8. Você faz tag (você, não o agente)
git tag -a v1.4.0 -m "Release 1.4.0"

# 9. Você faz push (você, não o agente)
git push origin main --tags
```

**Nunca o agente pushes, tags, ou releases — você controla tudo.**

---

## Testes Automáticos

O agente **sempre** roda esses checks localmente:

```bash
# Lint
python -m ruff check src tests docs

# Tests
python -m pytest

# Links (verifica se existem)
python -c "verificar_links()"

# Segredos (busca por patterns)
grep -r "API_KEY\|password\|secret" .

# Termos (verifica uso de canônicos)
grep -r "agente pessoal" .  # deve encontrar em docs
```

Se **algum falhar**, agente avisa e **não deixa aplicar mudanças**.

---

## Arquitetura do Agente

```
tools/nomos_update_agent.py
├── main()
│   ├── parse_args()
│   ├── run_checks()
│   ├── generate_plan()
│   ├── generate_diff()
│   ├── run_tests()
│   ├── create_report()
│   ├── ask_approval()  ← HUMAN APPROVAL REQUIRED
│   └── apply_changes() ← ONLY IF APPROVED
└── helpers/
    ├── detect_inconsistencies()
    ├── check_links()
    ├── check_secrets()
    ├── check_version()
    └── run_local_tests()
```

### Comportamento Fail-Closed

1. **Padrão:** `--dry-run` ativo (nada é escrito)
2. **Perguntar:** Antes de `--apply`, pedir `--i-understand-this-writes-files`
3. **Testar:** Rodar todos os checks antes de aplicar
4. **Parar em erro:** Se lint/test/link falha, **não aplica**
5. **Nunca push:** Script nunca executa `git push`, `git tag`, release

---

## Implementação

O arquivo `tools/nomos_update_agent.py` evoluiu de scaffold (MC25) para **verificador
CI-safe** (MC26) e, no MC27, ganhou **gate read-only para CI** e o modo **`--diff`
proposal-only**.

### Status Atual (MC27.0)

- [x] Documentação completa
- [x] Especificação de comando
- [x] Casos de uso definidos
- [x] Arquitetura desenhada
- [x] `--version` (imprime `MC27.0`)
- [x] `--check` real (existência, seções, links da landing, secrets, git) com exit 0/1
- [x] `--check --json` determinístico com campos de gate CI (`agent_version`, `mode`,
      `consistent`, `checks_total/passed/failed`, `human_approval_required`,
      `real_execution_enabled`, `auto_push_enabled`, `diff_proposer_available`)
- [x] `--diff` proposal-only (marcadores `PROPOSTA_DIFF_ONLY` / `NO_WRITE` /
      `HUMAN_APPROVAL_REQUIRED`) e `--diff --json` (`proposal_only`, `writes_enabled=false`,
      `patches[]`) — **nunca escreve, nunca executa git**
- [x] Testes reais: `tests/test_mc26_update_agent_check.py` (13) +
      `tests/test_mc27_update_agent_diff.py` (18)
- [x] Incapaz de executar processos (sem chamadas de sistema) -> sem push/tag/release
- [ ] `--apply` (escrita real) — permanece **bloqueado/fail-closed**, missão futura

> **Gate CI read-only:** `python tools/nomos_update_agent.py --check --json` é o comando
> canônico para CI. Exit 0 = consistente; exit 1 = inconsistente. O agente não escreve
> nem executa processos, então é seguro rodar em pipeline. Ver
> `docs/missions/MC27_UPDATE_AGENT_CI_DIFF.md`.
>
> **`--diff` é proposal-only:** sugere ajustes de documentação (ex.: links faltando no
> README) mas **nunca aplica**. A aplicação é sempre decisão e ação humana.

### Próximas Fases

**MC28 ou depois:**
- `--diff --write-proposal caminho.patch`: exportar proposta como arquivo `.patch` com
  hash SHA256 e nonce de aprovação humana — ainda **sem** `git apply`, commit ou push
- Integrar `--check --json` como job de CI (read-only), publicando o relatório como artifact
- Adicionar mais detectors (breaking changes, deprecations)

---

## FAQ

### "O agente pode fazer push automático?"

❌ **Nunca.** Agente:
- ✅ Detecta mudanças necessárias
- ✅ Gera diffs
- ✅ Pede aprovação
- ❌ Nunca executa `git push`
- ❌ Nunca executa `git tag`
- ❌ Nunca executa release

Você faz push, você faz tag, você faz release.

### "E se agente detectar algo que não consigo aprovar?"

Você pode:
1. Reverter a mudança (`git restore .`)
2. Reportar issue ("Agente detectou errado")
3. Ignorar se não faz sentido para seu caso

O agente **educacional**, não mandatório.

### "Posso rodar agente em CI/CD?"

Sim, mas **sem `--apply`**. Em CI:

```yaml
- name: Check consistency
  run: python tools/nomos_update_agent.py --check --no-fail-on-warnings
```

Isso **alerta** se tem inconsistência, mas não executa.

Para **auto-fix em CI**, use versão futura com `--apply --ci-mode`, que cria PR automático (não push direto).

### "Agente pode detectar breaking changes?"

Futura feature. Hoje detecta:
- ✅ Inconsistência em texto
- ✅ Links quebrados
- ✅ Versão desatualizada
- ❌ Breaking changes (próximo agente)

---

## Suporte

- 📖 Documentação: Este arquivo
- 🐛 Bug no agente? Abra issue em GitHub
- 💡 Feature request? Crie discussão em GitHub

---

**Agente de atualização NOMOS — Mantendo documentação sincronizada e confiável.**

