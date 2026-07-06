# NOMOS — Política Formal de Segurança e Permissões (v1.0)

**Status:** vigente · **Data:** 2026-07-05 · **Dono:** Se7enpay (NOMOS Team)
**Contrato executável:** cada invariante desta política tem ID estável (`SEC-NN`)
e é **provada por teste** em `tests/test_security_policy_contract.py`. Se o código
divergir da política, a suíte falha (CI vermelho). Mudar a política = editar este
documento **e** os testes, em commit dedicado com aprovação humana.

> Princípio-mãe: **fail-closed**. Na dúvida, na ausência, na corrupção ou no erro,
> a resposta do NOMOS é **não**. Local por lei; nuvem por opt-in; aprovação humana
> para tudo que é sensível.

---

## 1. Escada de risco A0–A6 (defaults invioláveis)

| Nível | Categoria | Default | Significado |
|---|---|---|---|
| A0 | Leitura local | **ALLOW** | ler arquivo/estado local |
| A1 | Escrita local | REQUIRE_APPROVAL | criar/alterar arquivo |
| A2 | Egress de rede | REQUIRE_APPROVAL¹ | qualquer saída da máquina |
| A3 | Credencial / conector | REQUIRE_APPROVAL | usar chave do cofre, conector externo |
| A4 | Dispositivos (mic/câmera/tela) | REQUIRE_APPROVAL | captura de ambiente |
| A5 | Exec. de código / instalar skill | REQUIRE_APPROVAL | rodar código, instalar habilidade |
| A6 | Destrutivo / irreversível | **DENY** | apagar, sobrescrever sem volta |

¹ A2 é adicionalmente barrada pelo **cadeado de localidade**: com o modo só-local
ligado (default; ausência do arquivo = ligado), o egress é **DENY** antes mesmo do
gate de aprovação — loopback (127.0.0.1) não conta como egress.

Fonte: `src/nomos/kernel/policy.py` (`DEFAULT_RULES`), `src/nomos/kernel/localidade.py`.

## 2. Invariantes (contrato testado)

| ID | Invariante | Fonte no código | Prova |
|---|---|---|---|
| SEC-01 | Execução real do Motor Council **desligada** por trava literal, sem API para ligar; dry-run é o único modo | `council/local_harness.py::REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` | `test_sec01_*` + `tests/test_council_local_harness_security.py` |
| SEC-02 | Contrato **único** de 10 flags proibidas (CLI e chat), igualdade estrita, sem eco da flag | `council/forbidden_flags.py::FORBIDDEN_FLAGS` | `test_sec02_*` + `tests/council/test_forbidden_flags_contract.py` |
| SEC-03 | Padrão read-only: **somente A0** é ALLOW por default | `kernel/policy.py::DEFAULT_RULES` | `test_sec03_*` |
| SEC-04 | A6 (destrutivo) é **DENY** por default — não é "aprovável" | `kernel/policy.py::DEFAULT_RULES` | `test_sec04_*` |
| SEC-05 | Categoria desconhecida ⇒ DENY (fail-closed) | `kernel/policy.py::PolicyEngine.decide` | `test_sec05_*` |
| SEC-06 | Política corrompida/ilegível ⇒ **tudo** negado (inclusive A0) | `kernel/policy.py::PolicyEngine.rules` | `test_sec06_*` |
| SEC-07 | REQUIRE_APPROVAL **sem aprovador** (script/CI) ⇒ nega; não existe flag de bypass | `kernel/policy.py::gate` | `test_sec07_*` |
| SEC-08 | Aprovador que lança exceção **nunca** autoriza | `kernel/policy.py::gate` | `test_sec08_*` |
| SEC-09 | Cadeado de localidade: ausência de estado = **ligado**; egress não-loopback ⇒ DENY | `kernel/localidade.py::esta_ligado/bloqueia_egress` | `test_sec09_*` |
| SEC-10 | Segredos nunca ecoam em saída/auditoria (redação em caminhos novos e antigos) | `council/safe_output.py`, `kernel/audit.py` | `test_sec10_*` + `tests/test_no_secret_leak_regression.py` |
| SEC-11 | Docs oficiais **não** recomendam `pip install nomos` puro (nome no PyPI é de terceiros) | docs + site | `test_sec11_*` + `tests/test_missao_validacao_anti_regressao.py` |
| SEC-12 | Brandbook congelado íntegro por SHA-256; mudança exige nova versão aprovada | `docs/brand/frozen/SHA256SUMS` | `test_sec12_*` + `tests/test_missao_validacao_anti_regressao.py` |

## 3. Superfícies e comandos

- **Dry-run é o default** de toda superfície do Conselho: `nomos conselho simular`
  e `/conselho simular` são os únicos subcomandos ativos; os demais permanecem
  desabilitados fail-closed. Flags proibidas (SEC-02) nunca são ecoadas.
- **Agentes de manutenção são read-only/proposal-only**: o update agent
  (`tools/nomos_update_agent.py`) tem `--apply` bloqueado fail-closed e
  `auto_push_enabled=false`; qualquer agente futuro de git segue o mesmo molde —
  **push jamais é automático**.
- **Instalação oficial**: GitHub/instaladores de release. `pip install nomos`
  puro é proibido nos docs (SEC-11).
- **Arbitragem/roteador**: local-first; nuvem só participa com opt-in explícito;
  sem motor pronto ⇒ bloqueia e explica (nunca inventa resposta).

## 4. Segredos

Chaves vivem no cofre (Argon2id + cryptography), nunca em texto plano no repo
(verificado por grep de auditoria e testes de não-vazamento). Saídas humanas e
JSON passam por redação; auditoria grava metadados, não conteúdo sensível.

## 5. Mudança desta política

1. Propor alteração em PR dedicado alterando **doc + testes juntos**.
2. Aprovação humana explícita (dono do projeto).
3. Nunca reduzir um default de A0–A6 sem registrar razão e teste novo.
4. O histórico desta política é auditável pelo git; versão no topo.
