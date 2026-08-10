# FASE 2 — PDP REAL NO CAMINHO DE EXECUÇÃO

Commit: `829c5cf feat(nomos): enforce PDP on runtime execution path`

## Antes
O PDP existia em `~/Projects/nomos-hermes-architecture/gate/src/nomos_pdp.py` —
código provado, fora do NOMOS e fora de qualquer caminho real. Dentro de
`NOMOS/src/` a busca por `PDP|nonce|audience|attenuat` dava **1 hit**, e era um
comentário não relacionado.

## Depois — a cadeia, comprovada na trilha de uma execução real
```
planejador.plano.ok
runtime.execucao.inicio
orquestracao.missao.inicio
pdp.decisao          ← decide
pep.aplicacao        ← aplica
agente.ferramenta.usada  ← boundary A0–A6
orquestracao.no.ok
orquestracao.missao.fim
runtime.execucao.fim
```
(extraída de `logs/audit.jsonl` após `nomos orquestrar ... --executar`)

## Módulos
- **`pdp/autorizacao.py`** — contrato assinado. HMAC-SHA256 sobre serialização
  canônica (JSON ordenado, sem o campo de assinatura), comparação em tempo
  constante, `Chaveiro` com rotação, `ArmazemNonce` anti-replay com expiração,
  `atenuar()`/`e_atenuacao()` que só estreitam.
- **`pdp/decisor.py`** — o PDP. **Default deny**: só `Efeito.ALLOW` explícito
  passa; erro inesperado vira DENY (nunca exceção que o chamador leia como
  "seguiu"). O risco NÃO é inventado aqui — vem do registro de capacidades.
- **`pdp/pep.py`** — o ponto de aplicação. O executor bruto fica **só na
  closure**; `PontoDeAplicacao` tem `__slots__`, não expõe atributo com o
  callable e não aceita enxerto.

## Lista de negação — cada uma com teste
| Requisito | Motivo | Teste |
|---|---|---|
| default deny | — | `test_default_deny_e_a_regra` |
| contexto incompleto | CONTEXTO_INCOMPLETO | `test_default_deny_e_a_regra` |
| capability inexistente | CAPACIDADE_DESCONHECIDA | `test_capacidade_desconhecida_e_negada` |
| policy/registro indisponível | REGISTRO/POLITICA_INDISPONIVEL | `test_registro_indisponivel_nega`, `test_registro_que_explode_nega_sem_propagar` |
| token inválido | ASSINATURA_INVALIDA | `test_token_forjado_com_chave_errada_e_negado` |
| token expirado | EXPIRADA | `test_token_expirado_e_negado` |
| replay | NONCE_REPETIDO | `test_nonce_repetido_e_negado`, `test_replay_do_envelope_inteiro_e_negado` |
| nonce inválido/ausente | NONCE_AUSENTE | `test_nonce_ausente_e_negado_quando_exigido` |
| attenuation inválida | — | `test_filho_forjado_mais_amplo_nao_e_atenuacao` |
| privilege escalation | RISCO_ACIMA_DO_AUTORIZADO | `test_risco_acima_do_teto_e_negado` |
| capability ≠ concedida | CAPACIDADE_NAO_CONCEDIDA | `test_capacidade_nao_concedida_e_negada` |
| argumento fora do escopo | ARGUMENTO_FORA_DO_ESCOPO | `test_argumento_contrabandeia_recurso_e_negado` |
| mutação acima do nível | RISCO_ACIMA_DO_AUTORIZADO | idem |
| storage indisponível | ARMAZEM_INDISPONIVEL | `test_armazem_de_nonce_indisponivel_nega` |
| integridade não comprovável | ASSINATURA_INVALIDA | `test_adulteracao_pos_assinatura_invalida_a_assinatura` |

## PEP obrigatório — e o que isso significa exatamente

No caminho do runtime governado: **DIRECT_ROUTE_BYPASS = 0**. Todo executor é
um `PontoDeAplicacao`; não existe modo "executor cru", nem mesmo quando o
chamador injeta os próprios executores (`test_executor_injetado_ainda_passa_pelo_pep`).

**Achado honesto — duas rotas legadas.** O censo estrutural
(`test_rotas_ate_o_adapter_sao_exatamente_estas`) enumera TODA rota de `src/`
até `ferramentas_wired`:

| rota | boundary A0–A6 | PDP de capacidade |
|---|---|---|
| `runtime/governado.py` | sim | **sim** |
| `cli.py` (`nomos agentes usar`) | sim | não |
| `simple/amigavel.py` | sim | não |

As duas últimas **não são bypass do A0–A6** — o gate do kernel decide e nega
normalmente. Mas não atravessam o PDP de token/escopo/TTL/replay. Isso está
fixado por teste: uma quarta rota, ou uma rota sem aplicador, quebra a suíte.
Fechar as duas é item declarado da ABSORPTION-02, não dívida escondida.

## Autorização de sessão
Sem decisor entregue, o runtime emite a própria autorização: capacidades = as do
manifesto, teto de risco = `risco_max` do manifesto, TTL = 3600 s, audiência
`nomos:runtime-governado`, nonce fresco por chamada. A raiz de confiança é o
dono que abriu o CLI; o gate humano continua no boundary. Um token de outra
audiência não executa (`test_runtime_com_token_de_outra_audiencia_nao_executa`).
