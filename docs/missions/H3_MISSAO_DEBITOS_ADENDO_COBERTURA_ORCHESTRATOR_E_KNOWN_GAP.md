# Adendo — Cobertura direta de `CouncilOrchestratorDryRun.run()` + KNOWN_GAP (policy.json)

**Complementa:** `docs/missions/H3_MISSAO_DEBITOS_RELATORIO_FINAL.md`
**Motivo do adendo:** o relatório final declarou `MYPY_ERRORS=0` como critério
estático atingido, mas o arquivo mais crítico do lote de correções de tipo
(`council/orchestrator.py`, 22 erros zerados, commit `352fb12`) tinha 99% de
cobertura de LINHA sem uma prova direta e explícita, por cenário, de que os
11 comportamentos exigidos por governança (status/motivo corretos, nenhuma
execução indevida, auditoria registrada quando exigida, invariantes
preservadas, nenhum erro virando sucesso aparente) estavam realmente
cobertos. Este adendo fecha essa lacuna, sem ampliar o escopo da missão.

---

## 1. O que foi feito

### 1.1 Leitura integral de `council/orchestrator.py`

Arquivo completo (693 linhas) relido do zero para reconstituir com precisão
o modelo mental de `CouncilOrchestratorDryRun.run()`: as 8 etapas do
pipeline (`INPUT_VALIDATED` → `LOCAL_PROVIDER_EVALUATED` →
`CANDIDATES_CREATED` → `SIMULATOR_RAN` → `POLICY_GATE_EVALUATED` →
`FINAL_ENVELOPE_CREATED` → `AUDIT_ENVELOPE_CREATED` →
`ORCHESTRATION_COMPLETED`/`ORCHESTRATION_BLOCKED`), a invariante
`_marcar_raiz()` (só a PRIMEIRA falha vira a causa raiz do resultado), e os
3 asserts de estreitamento de tipo adicionados na correção de mypy (linhas
410, 567, 617 — todos defesa em profundidade, nenhum muda lógica de
negócio).

### 1.2 Auditoria da cobertura DIRETA existente (não presumida)

```text
COMANDO_EXECUTADO=pytest tests/council/ -q --cov=nomos.council.orchestrator --cov-report=term-missing
RETORNO=0
EVIDÊNCIA=Name  Stmts Miss Cover Missing
          src/nomos/council/orchestrator.py 262 2 99% 102, 105
          303 passed
RESULTADO=99% de cobertura de LINHA (as 2 linhas faltantes são de uma
          função auxiliar não relacionada a run()). Cobertura de linha
          alta, mas achada insuficiente porque não prova, por si só, que
          CADA um dos 11 cenários pedidos tem asserção direta sobre
          status+motivo, ausência de execução indevida, registro de
          auditoria e não-transformação de erro em sucesso aparente.
```

### 1.3 Novo arquivo de teste dedicado

`tests/council/test_orchestrator_dry_run_direct_coverage.py` — 42 testes
novos, rotulados 1:1 com os 11 cenários exigidos:

| # | Cenário | Testes |
|---|---|---|
| 1 | entrada válida | `test_01_entrada_valida_completa_com_sucesso_real` |
| 2 | falha de entrada | `test_02_falha_de_entrada_pos_construcao_bloqueia_imediatamente`, `test_02b_...max_candidates_invalido...` |
| 3 | aprovação concedida | `test_03_aprovacao_concedida_gate_libera_conteudo_presente` |
| 4 | aprovação recusada ou ausente | `test_04_aprovacao_recusada_ou_ausente_bloqueia_sempre` |
| 5 | falha no gate | `test_05_falha_no_gate_por_excecao_e_fail_closed` |
| 6 | decisão válida do gate | `test_06a_...quando_liberado`, `test_06b_...quando_negado` |
| 7 | falha de auditoria | `test_07a_...por_excecao`, `test_07b_...por_negacao_explicita` |
| 8 | auditoria bem-sucedida | `test_08_...registra_envelopes_redigidos`, `test_08b_...modo_privado_nunca_persiste` |
| 9 | raiz permitida | `test_09_raiz_permitida_significa_nenhuma_falha_raiz_marcada` |
| 10 | raiz fora das permissões | `test_10a_...` (parametrizado, provider), `test_10b_...primeira_falha_gate_nao_sobrescreve_provider`, `test_10c_...simulador` |
| 11 | exceções inesperadas fail-closed | `test_11_excecao_inesperada_de_cada_componente_e_fail_closed` (parametrizado: provider/simulator/gate/audit_builder, cada um com um tipo de exceção CUSTOMIZADO, não um dos já mapeados) |

Mais 6 testes de invariante transversal, aplicados sistematicamente a 5
cenários diferentes (sucesso, gate nega A6, gate nega dado sensível,
sucesso em modo privado, provider sem motor): nenhuma execução indevida
(`dry_run`/`would_execute`/`would_write_audit`), `blocked == not allowed`
sempre, `failure_code is not None` se-e-somente-se `allowed is False`,
ordem das etapas sempre preservada quando todas presentes, e auditoria
genuinamente AUSENTE (`audit_result == {}`, não um dict parcial) quando a
etapa não é alcançada.

Destaque de rigor: o teste do cenário 11 usa um tipo de exceção
**customizado** (`_ExcecaoCustomizadaDoTeste`, não `RuntimeError` nem
qualquer outro tipo já mapeado no código), provando que o `except
Exception` de cada etapa plugável é genuinamente genérico — não uma lista
de tipos conhecidos que por acaso cobre os testes existentes.

---

## 2. Evidência de validação (bateria completa, comando + retorno real)

```text
COMANDO_EXECUTADO=pytest tests/council/test_orchestrator_dry_run_direct_coverage.py -v
RETORNO=0
EVIDÊNCIA=42 passed
RESULTADO=PASS — todos os 42 testes novos isolados

COMANDO_EXECUTADO=pytest tests/council/ -q
RETORNO=0
EVIDÊNCIA=345 passed (303 pré-existentes + 42 novos)
RESULTADO=PASS — nenhuma regressão nos testes de council

COMANDO_EXECUTADO=pytest tests/council/test_orchestrator_security.py -v
RETORNO=0
EVIDÊNCIA=11 passed
RESULTADO=PASS — teste de pureza AST (AST_PURITY_GATE) intacto e verde

COMANDO_EXECUTADO=mypy src/nomos --ignore-missing-imports
RETORNO=0
EVIDÊNCIA=Success: no issues found in 112 source files
RESULTADO=PASS — MYPY_ERRORS=0 mantido

COMANDO_EXECUTADO=ruff check src tests examples
RETORNO=0 (após corrigir 1 import não usado e 2 variáveis locais não usadas
          no próprio arquivo de teste novo, achados pelo próprio ruff)
EVIDÊNCIA=All checks passed!
RESULTADO=PASS — RUFF_ERRORS=0

COMANDO_EXECUTADO=pytest -q -n4  (suíte completa)
RETORNO=0
EVIDÊNCIA=1908 passed (1866 antes deste adendo + 42 novos; 0 regressões)
RESULTADO=PASS — FULL_SUITE=PASS

COMANDO_EXECUTADO=pytest --cov=nomos --cov-report=term-missing --cov-fail-under=80 -q -n4
RETORNO=0
EVIDÊNCIA=Required test coverage of 80% reached. Total coverage: 84.83%. 1908 passed
RESULTADO=PASS — gate de cobertura geral do CI

COMANDO_EXECUTADO=pytest -q -p no:cacheprovider --cov=nomos.kernel.evidencia
          --cov=nomos.ext.skill_catalogo --cov-report=term --cov-fail-under=90
          tests/test_evidencia_pacote.py tests/test_mc29_skills_catalogo.py
          tests/test_mc29_painel.py tests/test_mc30_onda_a.py
RETORNO=0
EVIDÊNCIA=Required test coverage of 90% reached. Total coverage: 95.45%. 33 passed
RESULTADO=PASS — gate dirigido MC30-A5 do CI (comando exato do ci.yml)

COMANDO_EXECUTADO=python -m build --wheel
RETORNO=0
EVIDÊNCIA=Successfully built nomos-1.3.0rc17-py3-none-any.whl
RESULTADO=PASS — WHEEL_BUILD=PASS

COMANDO_EXECUTADO=pip install <wheel> em venv limpo; nomos --version;
          python -c "from nomos.council.orchestrator import
          CouncilOrchestratorDryRun; print('...')"
RETORNO=0
EVIDÊNCIA=nomos 1.3.0rc17 / "orchestrator importa OK do wheel instalado"
RESULTADO=PASS — wheel instala e o módulo corrigido funciona de dentro dele

COMANDO_EXECUTADO=tools/nomos_update_agent.py --check --json
RETORNO=0
EVIDÊNCIA=consistent=true, checks_passed=13/13
RESULTADO=PASS — SITE_CONSISTENCY=TRUE
```

Nenhuma correção de lógica de negócio foi necessária durante o loop — os
únicos ajustes foram 2 achados do PRÓPRIO ruff no arquivo de teste novo
(um import não usado, duas variáveis locais não usadas), corrigidos e
re-validados antes do commit. `council/orchestrator.py` em si não foi
tocado neste adendo — só ganhou testes.

---

## 3. Checklist de encerramento (critério do usuário, item a item)

```text
MYPY_ERRORS=0
RUFF_ERRORS=0
FULL_SUITE=PASS (1908 passed, 0 regressões)
COUNCIL_DRY_RUN_DIRECT_COVERAGE=PASS (42 testes novos, 11/11 cenários
  cobertos com asserção direta de status/motivo/execução/auditoria/
  invariantes/não-mascaramento de erro — ver §1.3 e §2)
AST_PURITY_GATE=PASS (11 testes de tests/council/test_orchestrator_security.py)
WHEEL_BUILD=PASS
SITE_CONSISTENCY=TRUE
LOCAL_GIT_STATUS=CLEAN (após o commit deste adendo)
REMOTE_PUSH=BLOCKED_BY_CREDENTIALS (ver §5 — reconfirmado, não tratado
  como concluído)
```

---

## 4. KNOWN_GAP registrado — não corrigido neste corte

### Achado: `policy.json` sintaticamente válido mas de tipo errado derruba `PolicyEngine.decide()`, e `nomos doutor` não detecta

**Onde:** `src/nomos/kernel/policy.py` (`PolicyEngine.rules()` e
`PolicyEngine.decide()`) + `src/nomos/simple/doutor.py`
(`diagnosticar_consertos()` / `_ilegivel()`).

**O problema, em uma frase:** o detector de corrupção do `nomos doutor` só
testa se o arquivo faz parse como JSON (`json.loads()` sem exceção) — não
se o resultado tem o FORMATO esperado (um objeto/dict). Um `policy.json`
contendo `[]` (uma lista — JSON perfeitamente válido) passa despercebido
pelo `doutor`, mas faz `PolicyEngine.decide()` — a função de decisão do
gate, usada em TODO caminho protegido por política — lançar um
`AttributeError` não tratado em vez de negar de forma controlada.

**Por que isso importa:** os outros 3 arquivos que `doutor.py` monitora
(`localidade.json`, `skills_estado.json`, `rotinas.json`) já têm essa
mesma classe de problema coberta nos seus próprios loaders — verificado
neste adendo, não presumido:
- `localidade.esta_ligado()` envolve TANTO o `json.loads()` QUANTO o
  `.get()` subsequente no mesmo `try/except`, então falha fechado para
  `True` mesmo com `[]` como conteúdo (reproduzido: ver comando abaixo).
- `rotinas._ler()` faz `isinstance(dados, dict)` explicitamente antes de
  chamar `.get()`, então `[]`/`null`/`42` viram `[]` (lista vazia de
  rotinas) sem exceção.
- `skill_status._ler()` envolve `json.loads()` inteiro em `try/except` e
  devolve `{}` em qualquer falha (embora não valide shape, seu uso
  posterior — `.get(name, {})` — funciona igual para `[]` quanto para
  `{}` vazio, então não crasha na prática).

`PolicyEngine` é o ÚNICO dos 4 onde essa lacuna de validação de formato
tem um efeito observável real: um crash não tratado em vez de uma negação
educada.

**Reprodução (comando real, executado, saída real):**

```text
COMANDO_EXECUTADO=python3 docs/missions/repro_known_gap_policy_json_shape.py
RETORNO=1 (o script devolve 1 quando reproduz a falha documentada, para
          servir de sentinela: se um dia isso mudar, o script passa a
          devolver 0 e sinaliza que este KNOWN_GAP precisa ser revisado)
EVIDÊNCIA=1) PolicyEngine.rules() não lança exceção: []
          2) PolicyEngine.decide() CRASHOU (não tratado): AttributeError:
             'list' object has no attribute 'get'
          3) 'nomos doutor' detectou o policy.json como corrompido? False

          RESULTADO: falha reproduzida como documentado em KNOWN_GAPS
          (crash não tratado + doutor não detecta).
RESULTADO=CONFIRMADO — script em docs/missions/repro_known_gap_policy_json_shape.py
```

Verificação de controle (mesma técnica, mas no loader que JÁ é resiliente,
para confirmar que a lacuna é específica de `PolicyEngine`, não um
padrão geral não testado):

```text
COMANDO_EXECUTADO=python3 -c "... localidade.esta_ligado(home) com
          localidade.json='[]' ..."
EVIDÊNCIA=True (fail-closed correto, sem crash)
RESULTADO=confirma que a lacuna NÃO é geral — é específica de PolicyEngine
```

**Por que não foi corrigido neste corte:** corrigir exigiria decidir uma
política de tratamento (validar shape em `PolicyEngine.rules()` e tratar
como se fosse ilegível? ensinar `doutor._ilegivel()` a checar
`isinstance(..., dict)` também?) — uma mudança de comportamento real do
kernel de política, fora do escopo declarado deste adendo (que é
exclusivamente cobertura de teste de `council/orchestrator.py`). Misturar
essa correção aqui violaria a regra de não agrupar correções de domínios
diferentes no mesmo commit.

**Ação recomendada para uma rodada futura dedicada:** (a) em
`PolicyEngine.rules()`, tratar `not isinstance(resultado, dict)` como
equivalente a uma exceção de parse (mesmo fallback fail-closed já
existente); (b) em `doutor.py._ilegivel()`, checar `isinstance(dict)`
além do parse OK, para os arquivos que esperam um objeto JSON
(`policy.json`, `localidade.json`, `skills_estado.json`); (c) adicionar um
teste de regressão permanente em `tests/test_policy.py` e
`tests/test_v011_doutor_conserta.py` (ou equivalente) cobrindo
especificamente "JSON válido, shape errado" para os 4 arquivos
monitorados, não só "JSON inválido".

---

## 5. Site/git (instrução permanente do usuário) e push

Aplicado, como em todos os commits anteriores desta missão:

```text
COMANDO_EXECUTADO=tools/nomos_update_agent.py --check --json
RETORNO=0
EVIDÊNCIA=consistent=true, checks_passed=13/13
RESULTADO=PASS

COMANDO_EXECUTADO=git push origin loop/fase3-agent-boundary-wiring
RETORNO=1 (falha, idêntica às tentativas anteriores)
EVIDÊNCIA=fatal: could not read Password for
          'https://Voltolini-SPACE@github.com': No such device or address
RESULTADO=REMOTE_PUSH=BLOCKED_BY_CREDENTIALS — bloqueio externo confirmado
          de novo, não tratado como push concluído. Trabalho íntegro e
          commitado localmente; ação externa necessária (credencial Git
          não-interativa) para publicar no remoto.
```
