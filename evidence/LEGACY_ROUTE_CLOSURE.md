# FASE 1 — FECHAMENTO DAS ROTAS LEGADAS

Commit: `9db3027 feat(nomos): route legacy callers through the governed PDP path`

## Antes
A ABSORPTION-01 entregou PDP/PEP obrigatórios **no runtime**, mas deixou duas
rotas alcançando as 8 ferramentas só pelo boundary:

| rota | boundary A0–A6 | token/escopo/TTL/nonce |
|---|---|---|
| `cli.py` — `nomos agentes usar` | sim | **não** |
| `simple/amigavel.py` — conversa | sim | **não** |

Não eram bypass de política (o gate do kernel decidia e negava), mas não tinham
autorização assinada, escopo, prazo nem anti-replay.

## Depois
Ambas delegam a `runtime.governado.usar_ferramenta_governada`, que percorre:

```
caller → identidade/manifesto (boundary) → registry → PDP → PEP
       → boundary (gate A0–A6) → adapter → efeito → audit
```

`simple/amigavel.py` deixou de importar `agents.execucao` e **saiu da allowlist**
do guard de boundary — o conjunto de rotas até o adapter encolheu de 3 para 2.

### Fonte única de autorização
`sessao_pdp()` foi extraída como o **único** emissor de autorização, usada tanto
pelo `RuntimeGovernado` quanto pelo caminho de ferramenta única. Não existe
`legacy_pdp`, `simple_policy` nem `agent_gate_v2` — verificado por teste que
procura o termo como IDENTIFICADOR (def/class/import/atribuição), não como
substring, e por teste que exige `.assinar(` só em `runtime/governado.py`.

### Escopo pelo manifesto
A autorização emitida carrega as capacidades **do manifesto do agente**, não a
allowlist inteira: `pesquisador-local` (memoria_buscar, arquivo_ler,
arquivo_resumir) recebe autorização para exatamente essas três, com
`risco_max=A0`.

## Ordem: manifesto ANTES do PDP
"Essa ferramenta não é sua" é pergunta de identidade. Quem responde continua
sendo o boundary, com a mensagem e o evento `agente.ferramenta.negada` de
sempre. A primeira versão desta fase colocou o filtro de manifesto dentro de
`executores_nativos`, curto-circuitando o boundary — e
`test_ferramenta_wired_mas_fora_do_manifesto_do_agente_e_negada` pegou a
regressão de diagnóstico. Corrigido.

## Evidência executável

```
$ nomos agentes usar pesquisador-local doutor
o agente 'pesquisador-local' não tem a ferramenta 'doutor' no manifesto
  trilha: agente.ferramenta.negada          (boundary, ANTES do PDP)

$ nomos agentes usar pesquisador-local memoria_buscar --alvo "teste"
nenhuma memória encontrada.
  trilha: pdp.decisao → pep.aplicacao → agente.ferramenta.usada

$ nomos agentes usar programador arquivo_escrever --alvo x.txt --conteudo y </dev/null
[NOMOS-E002] NEGADO (fail-closed): aprovação exige terminal interativo.
'arquivo_escrever' precisa de aprovação (A1_WRITE_LOCAL) e foi negada
```

## Gates
```
LEGACY_ROUTE_WITHOUT_PDP=0
DIRECT_MUTATING_EXECUTOR_CALLERS=0
UNKNOWN_CAPABILITY_DEFAULT_DENY=PASS
EXPIRED_AUTH_DENY=PASS
REPLAY_DENY=PASS
WRONG_SCOPE_DENY=PASS
```
Cobertos por `tests/test_absorption02_rotas_legadas.py` (10 testes) e pelo censo
estrutural `test_rotas_ate_o_adapter_sao_exatamente_estas`, que agora exige
`{cli.py, runtime/governado.py}` e que ambas referenciem aplicador.
