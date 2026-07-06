# ARBITRAGEM ENTRE MOTORES — validação + construção real

## 1. Status

```
STATUS_FINAL=PASS_ARBITRAGEM_REAL_DELIVERY_READY
```

## 2. Validação: o que já existia

- **Roteamento** (`cognition/engine_router.py`): escolhe **1** melhor motor. Existe e funciona.
- **Council** (`council/*`): o **modelo e o contrato** de arbitragem já existiam —
  `AnswerCandidate → BlindReview → JudgeScore → ArbiterDecision → DisagreementReport`,
  com honestidade embutida (candidato sem conteúdo exige `failure_code`; árbitro pode
  `blocked=True`; desacordo HIGH força `requires_clarification`). **Porém dry-run/simulado**:
  `local_harness.REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` — nunca executa motor real.

**Conclusão:** faltava a **orquestração REAL** onde vários motores prontos geram
candidatos, debatem e convergem. Foi o que construí.

## 3. Construído: `cognition/arbitragem.py` (arbitragem real)

Fluxo (tudo execução real, local-first, fail-closed):
1. **Seleção** — só motores `available()` de fato; nuvem só com opt-in; local primeiro.
2. **Candidatos** — cada motor `run()` de verdade → `AnswerCandidate`. Falha/vazio ⇒
   `failure_code=ENGINE_FAILED` (sem conteúdo inventado), com retries limitados.
3. **Debate (rodadas)** — juiz cego pontua os candidatos dos OUTROS (consenso mensurável);
   os motores veem os pares anônimos e **revisam** (re-execução real) até estabilizar.
4. **Árbitro** — agrega `JudgeScore` → `ArbiterDecision`; calcula `score_spread` →
   `DisagreementReport`. Vencedor = melhor agregado, com `final_content` **idêntico** ao
   candidato real vencedor.

Reutiliza os modelos puros e já testados do `council`. **Não** altera o gate dry-run do
council (não flipei `REAL_LOCAL_ENGINE_EXECUTION_ENABLED`).

## 4. Invariantes de honestidade (nunca supor/mentir/inventar) — todas testadas

| Invariante | Evidência |
|---|---|
| 0 motor pronto ⇒ bloqueia sem inventar (`NO_ELIGIBLE_LOCAL_ENGINE`, `final_len=0`) | `test_sem_motor_bloqueia_sem_inventar`, execução real no sandbox |
| `final_content` sempre = candidato real (nunca sintetizado) | `test_final_content_vem_de_candidato_real` |
| Motor que falha ⇒ candidato com `failure_code`, sem conteúdo | `test_motor_que_falha_nao_gera_conteudo` |
| Todos falham ⇒ bloqueia sem conteúdo | `test_todos_falham_bloqueia` |
| Nuvem só com opt-in explícito | `test_cloud_excluida_sem_opt_in` / `..._com_opt_in` |
| Saída perigosa (segredo/`rm -rf`) ⇒ bloqueada (`ARBITER_UNSAFE_OUTPUT`) | `test_saida_perigosa_bloqueada` |
| Desacordo alto ⇒ confiança LOW + clarificação (nunca finge certeza) | `test_desacordo_alto_exige_clarificacao` |
| Esforço máximo: log de `available`+`run`+retries | `test_log_de_esforco_real` |
| Debate multi-rodada re-executa motores | `test_debate_revisa_em_rodadas` |
| Só participa quem está pronto | `test_selecao_so_de_prontos` |
| Determinístico (auditável) | `test_deterministico` |

## 5. Ação usável (além do roteamento)

`nomos motores arbitrar "<pergunta>"` — CLI real. Monta os motores locais reais
(cérebro embutido + Ollama) e arbitra. No sandbox (sem motor):

```
$ nomos motores arbitrar "explique local-first"
nenhum motor pronto para arbitrar — nada foi inventado.
  ligue o Ollama ou baixe o cérebro: nomos cerebro baixar
(exit 1)
```

## 6. Comandos executados (evidência real)

| Comando | Retorno | Resultado |
|---|---:|---|
| `python -c "arbitrar(...)"` no sandbox | — | `status=no_engine`, `blocked`, `NO_ELIGIBLE_LOCAL_ENGINE`, `final_len=0` |
| `nomos motores arbitrar "..."` (sandbox) | 1 | "nada foi inventado" (honesto) |
| `pytest tests/test_arbitragem.py -q` | 0 | 16 passed |
| `ruff check .` | 0 | All checks passed! |
| `pytest -q` (bare, anti-regressão) | 0 | 1133 passed |
| `git diff --stat .github pyproject.toml setup.cfg` | 0 | vazio (intactos) |

## 7. Arquivos

Criados: `src/nomos/cognition/arbitragem.py`, `tests/test_arbitragem.py`,
`docs/missions/ARBITRAGEM_SPEC.md`, este relatório.
Alterados: `src/nomos/cli.py` (subcomando `motores arbitrar`), `site/index.html`
(+card e comando de arbitragem), `tests/test_site_polish.py` (capacidade travada).
Não tocados: `.github/`, `pyproject.toml`, `setup.cfg`, `src/nomos/council/*`
(gate dry-run preservado).

## 8. Evidência de segurança

```
NUNCA_INVENTA=YES        (0 motor ⇒ bloqueia; teste + execução real provam)
FINAL_CONTENT_REAL=YES   (sempre idêntico a um candidato executado)
LOCAL_FIRST=YES          (nuvem só opt-in; runners de produção são locais)
FAIL_CLOSED=YES          (falha/desacordo/perigo ⇒ bloqueia ou pede humano)
COUNCIL_DRYRUN_PRESERVADO=YES  (REAL_LOCAL_ENGINE_EXECUTION_ENABLED intacto)
FORBIDDEN_FILES_INTACT=YES · NO_DEPLOY=YES · NO_PUSH (por mim)=YES
```

## 9. Limitações honestas

- No sandbox não há motor local rodando; a **convergência real** é provada com dublês
  determinísticos (que SÃO o motor no teste) + o comportamento honesto de "no_engine" com
  motores de produção. Em máquina com Ollama/cérebro, o mesmo código arbitra de verdade.
- Arbitragem com **nuvem** ainda não entra pela CLI (precisa de chave do cofre) — é opt-in
  e fica para a próxima etapa; o núcleo já aceita `allow_cloud=True`.
- O juiz é heurístico/determinístico por consenso; um juiz baseado em motor (structured
  review) é um gancho previsto, a evoluir.

## 10. Próximo passo recomendado

Ligar a arbitragem à nuvem via cofre (opt-in, A2/A3 no gate), adicionar juiz baseado em
motor (review estruturado) e expor `nomos motores arbitrar --json` para auditoria/CI.
