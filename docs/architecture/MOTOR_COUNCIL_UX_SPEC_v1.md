# NOMOS Motor Council — CLI/Chat UX Specification v1

## 1. Status

```text
SPEC_ONLY=true
IMPLEMENTATION=partial      # atualizado em MC23-UX — ver "Current implementation status"
```

> **Current implementation status (atualizado em MC26-UX).** Este documento
> nasceu SPEC-only, mas parte dele já foi implementada. Estado real por
> comando:
>
> ```text
> nomos conselho            -> registrado; raiz desabilitada (aponta os úteis)
> nomos conselho status     -> INFORMATIVO disponível (MC23-UX; fatos estáticos)
> nomos conselho modos      -> INFORMATIVO disponível (MC23-UX; [--avancado] [--json])
> nomos conselho diagnostico-> INFORMATIVO disponível (MC26-UX; lê a trava AO VIVO)
> nomos conselho simular    -> DRY-RUN disponível (MC15-UX)
> /conselho status|modos|diagnostico|simular -> disponíveis (MC24/MC26-UX)
> {perguntar, revisar, explicar}
>                           -> desabilitados/fail-closed nas duas superfícies
>                              (exigiriam execução real)
> REAL_ENGINE_EXECUTION=false  REAL_POLICY=false  REAL_AUDIT=false
> REAL_VAULT=false  CLOUD=false  PERSISTENCE=false
> ```
>
> As seções abaixo permanecem como o desenho canônico de UX (incluindo
> comandos ainda não implementados); onde já há implementação, ela segue este
> contrato. Ver `MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md` e o índice técnico
> para o mapa por fase.

Este documento é **especificação de experiência (UX)** — parcialmente
implementada (ver acima). As partes ainda não implementadas não criam comando
de CLI real, comando de chat real, código Python, motor real, chamada de
rede/subprocess/cloud, policy/audit/vault real ou persistência; e as já
implementadas (`simular`) rodam só em dry-run. Nenhuma parte funcional nova é
criada ou alterada por este documento.

Ele desenha como o Motor Council — hoje completo em SPEC/DRY-RUN até a Fase
MC8 (`CouncilOrchestratorDryRun` compondo provider local → simulador → policy
gate → audit envelope, tudo em memória) — deve **aparecer** para quem usa o
NOMOS pela CLI (`nomos conselho`) ou pelo chat (`/conselho`), numa fase futura
ainda não aprovada para implementação. Referencia diretamente
`docs/architecture/MOTOR_COUNCIL_SPEC_v1.md` (arquitetura/pipeline/modos) e os
contratos já implementados em `src/nomos/council/*.py` (MC1–MC8).

> **Nota de progresso (MC17-UX).** Parte desta UX já saiu do papel: a CLI
> `nomos conselho` está registrada e o subcomando `nomos conselho simular`
> roda em dry-run desde a Fase MC15-UX; o chat `/conselho` está registrado
> porém desabilitado/fail-closed desde a MC16-UX. A especificação detalhada do
> **chat dry-run** futuro (`/conselho simular`) — contratos, redaction, flags
> proibidas, integração com o orquestrador e plano de fases MC18-UX+ — está em
> `docs/architecture/MOTOR_COUNCIL_CHAT_DRY_RUN_SPEC_v1.md`.
>
> **Unificação de saída/redação (MC20).** A duplicação controlada entre as
> saídas da CLI e do chat dry-run está especificada, para unificação futura,
> em `docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md`
> (SPEC-only; helper ainda não implementado, refactor reservado para MC21+).

## 2. Objective

Definir, de forma canônica e implementável posteriormente sem ambiguidade:

- comandos CLI futuros (`nomos conselho ...`) e seus aliases;
- comandos de chat futuros (`/conselho ...`);
- flags futuras e suas regras de composição/conflito;
- mensagens de erro e de bloqueio, com formato fixo;
- comportamento de UX para modo iniciante, modo avançado, modo privado e modo
  paranoico;
- o que "dry-run" precisa comunicar para nunca ser confundido com execução
  real;
- como o Policy Gate aparece para quem usa (sem nunca vazar conteúdo negado);
- como o audit envelope (metadata-only) aparece em modo avançado/`--json`;
- o desenho — **ainda sem implementação** — de uma futura aprovação humana;
- exemplos completos comando → saída esperada;
- um plano de testes futuros (nomes exatos, para quando a implementação
  começar);
- as fases de implementação futuras (MC10 em diante) e suas restrições.

Este documento é o contrato de UX que qualquer fase futura de implementação
(`MC12-UX`+, ver nota de renumeração na seção 20) deve seguir literalmente —
divergências exigem revisão desta spec antes do código.

## 3. Non-goals

- Não implementa `nomos conselho` nem `/conselho`.
- Não cria nem altera `src/nomos/cli*`, `src/nomos/chat*`,
  `src/nomos/council/*.py`, `tests/council/*.py`, `tests/cli*`, `tests/chat*`.
- Não chama motor real, Ollama, llama.cpp, subprocess, HTTP local ou externo,
  cloud (OpenAI/Anthropic/Gemini).
- Não chama policy real, audit real ou vault real.
- Não persiste nada em disco.
- Não cria botão de UI, menu real, skill real ou agente real usando o
  Council.
- Não integra com o roteador global (`cognition/router.py`) nem o substitui.
- Não cria tag nem release.
- Não é um convite para pular fases: os comandos aqui descritos só podem ser
  implementados em fases futuras explicitamente aprovadas, uma de cada vez,
  sob `implementation-loop-100` (seção 20).

## 4. UX Principles

1. **Segurança primeiro.** Qualquer ambiguidade de UX se resolve a favor de
   negar/ocultar, nunca de mostrar/executar "só para não incomodar".
2. **Local-first por padrão.** Toda saída, mensagem e exemplo assume motores
   locais por padrão; nada sugere que a nuvem é o caminho normal.
3. **Cloud sempre opt-in futuro, nunca automática.** Nenhuma flag, comando ou
   mensagem pode dar a entender que a nuvem "só funciona"; ela sempre exige um
   passo explícito e separado (cadeado aberto + chave no cofre + aprovação por
   uso — já especificado em `MOTOR_COUNCIL_SPEC_v1.md` §12).
4. **Modo privado deve ser óbvio.** Sempre que `--privado`/"privado on"
   estiver ativo, a UX declara isso na primeira linha da resposta — nunca como
   nota de rodapé.
5. **Gate negado nunca mostra conteúdo bloqueado.** Nem em modo avançado, nem
   em `--json`, nem em modo debug futuro.
6. **Dry-run nunca deve parecer execução real.** Nenhuma mensagem de dry-run
   usa linguagem de sucesso operacional (seção 15).
7. **Mensagens curtas no modo iniciante.** Primeira linha sempre em
   linguagem simples; detalhe técnico fica disponível, mas não é imposto.
8. **Modo avançado pode mostrar trace redigido** (metadata-only, nunca
   conteúdo bruto, nunca `engine_id` em modo privado).
9. **Erros têm sempre 4 partes**: código, causa, ação recomendada e detalhe
   técnico (seção 12).
10. **Comandos futuros não podem ser bypass** de agentes, skills, policy,
    audit ou vault — o Council usa exatamente os mesmos boundaries que já
    existem; nenhum comando novo cria um caminho de autorização paralelo.

## 5. Future CLI Commands

```text
COMMANDS_NOT_IMPLEMENTED_IN_MC9=true
```

Comandos futuros (especificados, **não implementados**):

```bash
nomos conselho perguntar "..."
nomos conselho revisar arquivo.md
nomos conselho simular "..."
nomos conselho status
nomos conselho explicar-ultima-decisao
nomos conselho modos
nomos conselho diagnostico
```

Aliases futuros permitidos pela spec (mesmo comportamento, nomenclatura em
inglês para scripts/automação):

```bash
nomos council ask "..."
nomos council simulate "..."
nomos council status
```

Descrição de cada subcomando futuro:

| Comando | Papel futuro |
|---|---|
| `perguntar` / `ask` | roda o Council (via orquestrador) sobre uma pergunta digitada |
| `revisar` | roda o Council sobre o conteúdo de um arquivo local, envelopado como DADO (nunca como instrução) |
| `simular` / `simulate` | força `--simular` (nunca executa motor real, mesmo quando `MC13-UX` existir) |
| `status` | mostra se o Council está ligado/desligado e o modo padrão configurado |
| `explicar-ultima-decisao` | mostra o trace redigido (modo avançado) da última execução da sessão atual |
| `modos` | lista os 4 modos (rápido/balanceado/crítico/paranoico) e o que cada um implica |
| `diagnostico` | roda checagens equivalentes ao `nomos doutor`, mas focadas no Council (ex.: cadeado local, motor disponível) |

### 5.1 Future Flags

```bash
--modo rapido
--modo balanceado
--modo critico
--modo paranoico
--privado
--local-only
--sem-memoria
--simular
--explicar
--json
--iniciante
--avancado
```

Regras futuras obrigatórias (a valer desde a primeira implementação, `MC12-UX`+):

- `--privado` força `persist_allowed=false` em todos os envelopes (final e de
  auditoria) — igual ao que `CouncilOrchestrationInput.private_mode=true` já
  garante hoje em dry-run.
- `--local-only` nega qualquer motor de cloud, mesmo que o cadeado esteja
  aberto para outros fluxos do NOMOS.
- `--modo paranoico` **implica** `--local-only --privado --sem-memoria` —
  essas três flags são automaticamente ativadas e não podem ser desativadas
  junto com `--modo paranoico` na mesma chamada (conflito ⇒ falha fechada,
  ver abaixo).
- `--simular` nunca executa motor real, em nenhuma fase futura anterior a uma
  fase explicitamente aprovada para execução real (ver seção 20).
- `--json` nunca inclui prompt ou conteúdo sensível quando `--privado` está
  ativo (mesma garantia que `CouncilOrchestrationResult.to_json()` já prova
  hoje: nunca há prompt, nunca há conteúdo de candidato, nunca há conteúdo
  final quando bloqueado).
- Flags conflitantes (ex.: `--modo paranoico --local-only=false`, se um dia
  existir uma forma explícita de desligar) devem **falhar fechado**: erro de
  validação de entrada, comando não executa, nada é simulado.
- **Nenhuma flag pode ativar execução real.** Isso só pode vir de uma fase
  futura explicitamente aprovada que remova o equivalente ao
  `REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False` do harness (MC5) — nenhuma
  flag de CLI jamais é o mecanismo para isso.
- **Nenhuma flag pode ativar audit real.** O envelope de auditoria (MC7)
  continua dry-run até uma fase futura explicitamente aprovada para
  integração real com `kernel/audit.py`.
- **Nenhuma flag pode pular o Policy Gate.** Não existe `--forcar`,
  `--ignorar-gate` ou equivalente nesta spec, e nenhuma fase futura deve
  introduzir um.

## 6. Future Chat Commands

```text
/conselho perguntar ...
/conselho revisar ...
/conselho simular ...
/conselho status
/conselho modos
/conselho explicar
/conselho privado on
/conselho privado off
```

Regras futuras:

- Chat command **não pode** bypassar o Policy Gate — toda resposta final
  passa pelo mesmo `CouncilPolicyGateDryRun` (ou, numa fase futura aprovada,
  pelo gate real), exatamente como no fluxo de CLI.
- Chat command **não pode** bypassar o modo privado — `/conselho privado on`
  ativa o mesmo `private_mode=true` que a CLI usa, com as mesmas garantias de
  `persist_allowed=false`.
- Chat command **não pode** chamar skill sem permissão — o `agent
  boundary`/`skill boundary` já existentes continuam valendo; o Council não
  cria um caminho novo de autorização.
- Chat command **não pode** acionar motor real fora de uma fase explicitamente
  aprovada para isso.
- Chat command **não pode** persistir nada se `privado` estiver ativo na
  sessão de chat.
- Chat command **não pode** ativar cloud silenciosamente — qualquer menção a
  motor de nuvem no chat exige o mesmo opt-in explícito (cadeado + cofre +
  aprovação por uso) que a CLI exige.
- Chat command **não pode** executar ação sensível sem uma aprovação humana
  futura explícita (seção 16) — nesta fase (e em todas até `MC16-UX`), toda
  ação sensível é dry-run/bloqueada por padrão.

## 7. Council Modes

Os 4 modos já especificados em `MOTOR_COUNCIL_SPEC_v1.md` §5 mapeiam
diretamente para `--modo` (CLI) e para o campo `mode` de
`CouncilOrchestrationInput` (já implementado em MC1/MC8):

| `--modo` | `CouncilMode` | UX esperada |
|---|---|---|
| `rapido` | `fast` | resposta rápida; Council pode nem rodar completo; UX não menciona "conselho" se não rodou |
| `balanceado` | `balanced` | modo padrão; UX mostra que houve comparação entre candidatos, sem detalhe técnico por padrão |
| `critico` | `critical` | UX avisa explicitamente que o modo exige gate obrigatório e audit mais detalhado (redigido) |
| `paranoico` | `paranoid` | UX avisa que a chamada é **só local, privada e sem memória** antes mesmo de rodar |

`nomos conselho modos` (futuro) deve listar essa tabela para o usuário em
linguagem simples, sem termos internos (`CouncilMode`, `ORCH_*`, etc.) no modo
iniciante, e com esses termos disponíveis no modo avançado (`--avancado`).

## 8. Private Mode UX

Mensagem humana obrigatória sempre que `--privado`/"privado on" estiver ativo:

```text
Modo privado ativo.
O Council não vai persistir candidatos, reviews, decisões nem envelope detalhado.
Logs futuros, quando habilitados, serão metadata-only e redigidos.
```

Saída JSON futura esperada (`--json --privado`):

```json
{
  "private_mode": true,
  "persist_allowed": false,
  "content_redacted": true,
  "audit_metadata_only": true
}
```

Regras (já provadas em dry-run pelo orquestrador MC8, e que qualquer
implementação futura deve preservar):

- prompt não aparece no JSON privado (nem em nenhum modo, na verdade — só
  `prompt_chars`);
- conteúdo final não aparece se o gate negar;
- conteúdo de candidato não aparece;
- conteúdo de review não aparece;
- `engine_id` não aparece em modo privado;
- o trace em modo privado é sempre redigido (`redacted=true`,
  `private_mode=true` no `CouncilOrchestrationTrace`).

## 9. Local-only / Cloud-denied UX

Por padrão, e sempre com `--local-only`/`--modo paranoico`, a UX deve deixar
claro que **só motores locais** participam — nunca um "silêncio" que faça o
usuário supor que a nuvem foi usada. Mapeamento para os failure codes já
existentes:

| Situação | Código interno | Mensagem futura (resumo) |
|---|---|---|
| nenhum motor local elegível | `NO_ELIGIBLE_LOCAL_ENGINE` / `ORCH_NO_CANDIDATES` | "sem motor local disponível — a nuvem não foi tentada" |
| motor declara cloud/rede | `CLOUD_BLOCKED_BY_LOCAL_LOCK` / `ORCH_PROVIDER_FAILED` | "esse motor exige rede/nuvem — bloqueado pelo cadeado local" |
| dado sensível sem motor que suporte | `SENSITIVE_DATA_CLOUD_DENIED` | "dado sensível: nuvem negada, mesmo com cadeado aberto" |

Regra permanente: **fallback nunca aciona cloud**. Se não há motor local
elegível, a UX comunica isso como um estado terminal (com ação recomendada:
instalar/ativar um motor local), nunca como um redirecionamento silencioso
para nuvem.

## 10. Policy Gate UX

Exemplo obrigatório de mensagem quando o gate nega:

```text
Resposta bloqueada pelo Policy Gate.

Motivo: risco alto em dry-run.
Nada foi enviado.
Nada foi executado.
Nada foi persistido.
```

Regras:

- não mostrar o conteúdo bloqueado, em nenhum modo (iniciante, avançado ou
  `--json`);
- não mostrar o candidato vencedor quando o gate nega — a informação de
  "quem venceria" também é conteúdo, e fica redigida;
- não mostrar o prompt sensível em nenhuma circunstância;
- não sugerir que houve execução real ("tentamos", "rodamos e bloqueamos
  depois" — linguagem proibida, ver seção 15);
- não usar linguagem de sucesso operacional para um bloqueio (nunca "concluído
  com bloqueio" — é apenas "bloqueado").

## 11. Audit Envelope UX

O envelope de auditoria (MC7, dry-run) é **metadata-only** por desenho —
a UX avançada/`--json` só pode mostrar o que o próprio
`CouncilAuditDryRunResult`/`CouncilAuditEnvelope` já expõem hoje:
`envelope_count`, `failure_code`, `redaction_profile` e `persist_allowed` por
envelope. Nunca prompt, nunca conteúdo, nunca `engine_id`.

Exemplo de bloco `--avancado`/`--json` (ilustrativo, alinhado ao schema já
implementado):

```json
{
  "audit_result": {
    "allowed": true,
    "would_write_audit": false,
    "envelopes": [
      {"persist_allowed": false, "metadata": {"candidate_count": 2, "review_count": 2}}
    ]
  }
}
```

Regra permanente: `would_write_audit` é sempre `false` em qualquer saída de
UX até uma fase futura explicitamente aprovada para integração real com
`kernel/audit.py` — e mesmo nessa fase futura, a UX deve continuar mostrando
somente metadata (nunca conteúdo bruto).

## 12. Error Messages

Formato obrigatório para toda mensagem de erro/bloqueio:

```text
[NOMOS-MC-XXX] Mensagem curta.

Causa:
Ação recomendada:
Detalhe técnico:
```

Exemplo:

```text
[NOMOS-MC-403] Resposta bloqueada pelo Policy Gate.

Causa: o risco exige aprovação ou está acima do permitido para dry-run.
Ação recomendada: revise o pedido, reduza o risco ou aguarde uma fase com aprovação humana real.
Detalhe técnico: ORCH_POLICY_GATE_DENIED.
```

Mensagens humanas futuras para os códigos mínimos exigidos:

| Código interno | `[NOMOS-MC-XXX]` | Mensagem curta | Causa | Ação recomendada |
|---|---|---|---|---|
| `ORCH_PROVIDER_FAILED` | 410 | "O provedor local não conseguiu gerar candidatos." | motor local recusou ou falhou a avaliação | verifique se há um motor local elegível instalado/ativo |
| `ORCH_NO_CANDIDATES` | 411 | "Nenhum candidato foi gerado." | nenhum motor local elegível respondeu | instale/ative um motor local, ou tente novamente |
| `ORCH_POLICY_GATE_DENIED` | 403 | "Resposta bloqueada pelo Policy Gate." | risco alto, dado sensível ou aprovação exigida em dry-run | reduza o risco, remova o dado sensível, ou aguarde aprovação humana futura |
| `ORCH_AUDIT_ENVELOPE_DENIED` | 450 | "O registro de auditoria não pôde ser criado com segurança." | metadata sensível detectada, ou modo privado com persistência indevida | reporte como bug — este estado não deveria ocorrer em uso normal |
| `ORCH_PRIVATE_MODE_PERSIST_DENIED` | 451 | "Modo privado impediu a persistência." | um envelope tentou persistir sob modo privado | reporte como bug — este estado não deveria ocorrer em uso normal |
| `GATE_A6_DENIED` | 406 | "Ação destrutiva (A6) sempre negada." | risco classificado como destrutivo | reformule o pedido para um risco menor |
| `GATE_REQUIRES_APPROVAL` | 402 | "Esta ação exige aprovação humana." | aprovação humana ainda não está habilitada nesta fase | aguarde uma fase futura com aprovação real, ou reduza o risco |
| `GATE_SENSITIVE_DATA_REQUIRES_STRICT_MODE` | 409 | "Dado sensível exige modo estrito." | dado sensível detectado sem modo paranoico/privado | use `--modo paranoico` ou `--privado`, ou remova o dado sensível |
| `REAL_EXECUTION_DISABLED` | 501 | "Execução real está desligada nesta fase." | trava de segurança do harness (MC5) | não há ação disponível — execução real só existe numa fase futura aprovada |
| `AUDIT_ENVELOPE_SENSITIVE_METADATA` | 452 | "Metadata sensível detectada no envelope de auditoria." | uma chave/valor sensível (ex.: prompt, token) tentou entrar na metadata | reporte como bug — a metadata deveria ser sempre contagens/códigos |

## 13. Beginner Mode Messages

Mensagens simples obrigatórias:

```text
O Conselho comparou opções em modo seguro.
Nenhum motor real foi chamado nesta fase.
A resposta só aparece se passar pelas regras de segurança.
```

Regras:

- esconder o trace interno por padrão (só aparece com `--avancado`);
- evitar códigos longos na primeira linha (o código `[NOMOS-MC-XXX]` vem
  depois da mensagem curta, nunca antes dela);
- sempre mostrar causa e próxima ação, mesmo no modo iniciante — só o detalhe
  técnico fica reservado ao modo avançado;
- nunca esconder bloqueios: modo iniciante simplifica a explicação, mas não
  omite que algo foi bloqueado.

## 14. Advanced Mode Messages

Mensagens técnicas com trace redigido:

```text
trace_order=[
  INPUT_VALIDATED,
  LOCAL_PROVIDER_EVALUATED,
  CANDIDATES_CREATED,
  SIMULATOR_RAN,
  POLICY_GATE_EVALUATED,
  FINAL_ENVELOPE_CREATED,
  AUDIT_ENVELOPE_CREATED,
  ORCHESTRATION_COMPLETED
]
```

Regras (idênticas às já garantidas por `CouncilOrchestrationTrace`/`Result`
em dry-run):

- trace sem prompt;
- trace sem conteúdo de candidato;
- trace sem conteúdo final;
- trace sem `engine_id` em modo privado;
- mostrar `failure_code` quando bloqueado;
- mostrar `dry_run=true`;
- mostrar `would_execute=false`;
- mostrar `would_write_audit=false`.

## 15. Dry-run Explanation

Toda saída de dry-run deve declarar, no modo avançado/`--json`:

```text
DRY_RUN=true
REAL_ENGINE_EXECUTION=false
REAL_POLICY=false
REAL_AUDIT=false
```

Linguagem **proibida** em dry-run (nunca usar):

```text
executado com sucesso
enviado com sucesso
gravado com sucesso
processado no motor real
```

Linguagem **permitida** em dry-run:

```text
simulado com sucesso
validado em dry-run
bloqueado em dry-run
pré-validado sem execução real
```

Esta regra vale para **toda** fase até que exista uma fase futura
explicitamente aprovada para execução real — inclusive `MC12-UX`/`MC13-UX`
(CLI skeleton/dry-run run command), que continuam 100% dry-run (seção 20).

## 16. Human Approval Future UX

Esta seção especifica apenas o **desenho futuro**. Não implementa aprovação
real — nenhuma fase até `MC16-UX` (inclusive) tem aprovação humana real
habilitada.

Mensagem futura obrigatória sempre que uma ação exigir aprovação:

```text
Esta ação exige aprovação humana.
Nesta fase, aprovações reais ainda não estão habilitadas.
Nada foi executado.
```

Regras futuras:

- aprovação humana **não pode** ser simulada como se fosse real — a UX nunca
  finge que um humano aprovou algo quando não aprovou;
- aprovação futura deve ter **nonce, envelope e escopo** (isto é: um pedido de
  aprovação vale para uma ação específica, uma vez, com validade limitada —
  nunca uma aprovação genérica "para sempre");
- aprovação futura **não pode** liberar cloud sem um opt-in **separado**
  (aprovar uma ação de risco não equivale a abrir o cadeado local);
- aprovação futura **não pode** persistir nada se `private_mode` estiver
  ativo — mesmo um registro de "isto foi aprovado" respeita
  `persist_allowed=false`.

## 17. Examples

### 17.1 Pergunta simples em modo balanceado

```bash
nomos conselho perguntar "resuma este texto" --modo balanceado --simular
```

- **Saída humana esperada:**
  ```text
  O Conselho comparou opções em modo seguro.
  Nenhum motor real foi chamado nesta fase.
  Resposta liberada pelo Policy Gate.
  ```
- **Saída JSON esperada:**
  ```json
  {"allowed": true, "blocked": false, "dry_run": true,
   "would_execute": false, "would_write_audit": false}
  ```
- **Observação de segurança:** nenhum motor real chamado; gate avaliado antes
  de qualquer conteúdo aparecer; nada persistido além do padrão normal (não
  privado).

### 17.2 Modo privado

```bash
nomos conselho perguntar "analise isto" --privado --simular
```

- **Saída humana esperada:**
  ```text
  Modo privado ativo.
  O Council não vai persistir candidatos, reviews, decisões nem envelope detalhado.
  Resposta liberada pelo Policy Gate.
  ```
- **Saída JSON esperada:**
  ```json
  {"private_mode": true, "persist_allowed": false,
   "content_redacted": true, "audit_metadata_only": true}
  ```
- **Observação de segurança:** `persist_allowed=false` em todos os envelopes;
  prompt nunca aparece no JSON.

### 17.3 Modo paranoico

```bash
nomos conselho perguntar "verifique este contrato" --modo paranoico --simular
```

- **Saída humana esperada:**
  ```text
  Modo paranoico ativo: só motores locais, privado e sem memória.
  Nenhum motor real foi chamado nesta fase.
  Resposta liberada pelo Policy Gate.
  ```
- **Saída JSON esperada:**
  ```json
  {"mode": "paranoid", "local_only": true, "private_mode": true,
   "cloud_allowed": false, "dry_run": true}
  ```
- **Observação de segurança:** `--local-only --privado --sem-memoria`
  implícitos; cloud negada por construção, não por configuração opcional.

### 17.4 Gate negado

```bash
nomos conselho perguntar "faça uma ação destrutiva" --modo critico --simular
```

- **Saída humana esperada:**
  ```text
  Resposta bloqueada pelo Policy Gate.

  Motivo: risco destrutivo (A6).
  Nada foi enviado.
  Nada foi executado.
  Nada foi persistido.
  ```
- **Saída JSON esperada:**
  ```json
  {"allowed": false, "blocked": true, "failure_code": "ORCH_POLICY_GATE_DENIED",
   "final_envelope": {"content": null}}
  ```
- **Observação de segurança:** conteúdo nunca aparece; nenhuma linguagem de
  sucesso operacional é usada.

### 17.5 Chat futuro

```text
/conselho simular revisar este texto em modo privado
```

- **Saída humana esperada (chat):**
  ```text
  Modo privado ativo. Revisão simulada em dry-run — nenhum motor real foi chamado.
  ```
- **Saída JSON esperada:** não aplicável por padrão no chat (só via um futuro
  `--json`/modo avançado explícito).
- **Observação de segurança:** o chat command usa exatamente o mesmo
  orquestrador dry-run e os mesmos boundaries de gate/private mode que a CLI —
  nenhum caminho paralelo.

## 18. Security Constraints

- CLI **não pode** ativar execução real.
- Chat **não pode** ativar execução real.
- Env **não pode** ativar execução real.
- Config **não pode** ativar execução real.
- Modo privado **não persiste**, em nenhuma circunstância.
- Gate negado **remove conteúdo** — sempre, em todo modo de saída.
- Audit envelope é **metadata-only**, sempre.
- Prompt/conteúdo **não aparece** no JSON privado (nem em nenhum outro modo).
- Comandos futuros **devem** passar pelo Policy Gate — sem exceção, sem flag
  de bypass.
- Skills/agentes **não podem** usar o Council como bypass de suas próprias
  permissões (`agents/boundary.py`, `ext/skills.py` continuam valendo
  integralmente).
- Cloud continua **proibida por padrão** — opt-in explícito, por uso, exigido
  em toda fase futura.
- Execução real **só pode existir** numa fase explicitamente aprovada para
  isso (não MC9, não MC10, nem implicitamente em nenhuma fase futura que não
  declare isso no próprio texto da missão).
- Audit real **só pode existir** numa fase explicitamente aprovada para isso.

## 19. Future Test Plan

Testes futuros (nomes exatos; **não implementados nesta fase**):

```text
test_cli_conselho_not_registered_before_implementation_phase
test_chat_conselho_not_registered_before_implementation_phase
test_cli_private_mode_outputs_persist_false
test_cli_dry_run_never_claims_executed
test_cli_gate_denied_hides_content
test_cli_json_private_redacts_prompt
test_chat_private_mode_no_persist
test_chat_gate_denied_hides_content
test_cli_local_only_denies_cloud
test_cli_paranoid_implies_private_local_only
test_cli_cannot_enable_real_execution
test_chat_cannot_enable_real_execution
test_cli_error_message_has_code_cause_action
test_beginner_mode_hides_internal_trace
test_advanced_mode_shows_redacted_trace
```

## 20. Implementation Phases

```text
MC10    — Documentation Index + RC4 Preparation
MC11-RC4 — RC4 Tag Preparation/Validation (release engineering track)
MC12-UX — CLI Skeleton Disabled
MC13-UX — CLI Dry-run Command
MC14-UX — Chat Command SPEC/DISABLED
MC15-UX — Chat Dry-run Command
MC16-UX — Human Approval UX Dry-run
MC17-UX — Real Local Engine Harness Review
```

> **Nota de renumeração (MC11-RC4, 2026-07-05)**: esta seção originalmente
> numerava a trilha de UX como MC11–MC16. Uma colisão foi identificada
> quando uma segunda missão, independente desta trilha, também reivindicou o
> número MC11 para "RC4 Tag Preparation/Validation" (release engineering,
> não UX). Resolução adotada: `MC11-RC4` passa a designar exclusivamente a
> trilha de release engineering (tag/release/PyPI); toda a trilha de UX
> originalmente MC11–MC16 foi renumerada para `MC12-UX`–`MC17-UX`, mantendo a
> ordem relativa e todas as regras abaixo inalteradas — apenas os números
> mudaram, não o conteúdo de nenhuma fase. Ver também
> `docs/architecture/MOTOR_COUNCIL_INDEX_v1.md` (seção 19) para o roteiro das
> duas trilhas em paralelo.

Regras (numeração atualizada; conteúdo de cada fase inalterado):

- `MC12-UX` pode **registrar** o comando (`nomos conselho` aparece em
  `--help`), mas **desabilitado** (executar sem `--simular` explica que a
  fase ainda não libera nada, e mesmo com `--simular` só chama o orquestrador
  dry-run).
- `MC13-UX` pode chamar **apenas** o orquestrador dry-run
  (`CouncilOrchestratorDryRun`) já existente — nenhuma nova lógica de
  negócio, nenhum motor real.
- Motor real continua **proibido** até uma fase explicitamente aprovada para
  isso (não é `MC17-UX` automaticamente — "review" nesse nome significa
  auditoria do harness, não habilitação).
- Chat real só vem **depois** da CLI dry-run estar estável (`MC15-UX` depois
  de `MC13-UX`), nunca em paralelo na mesma fase.

## 21. Acceptance Criteria

Checklist para considerar esta **spec de UX** aceita:

- [x] `SPEC_ONLY=true`, `IMPLEMENTATION=false`.
- [x] Comandos CLI futuros especificados, com `COMMANDS_NOT_IMPLEMENTED_IN_MC9=true`.
- [x] Comandos de chat futuros especificados.
- [x] Flags futuras especificadas com regras de conflito e de fail-closed.
- [x] Os 4 modos do Council mapeados para UX (`--modo`).
- [x] UX de modo privado especificada (mensagem + JSON + regras).
- [x] UX de local-only/cloud-denied especificada.
- [x] UX do Policy Gate especificada (gate negado nunca mostra conteúdo).
- [x] UX do audit envelope especificada (metadata-only).
- [x] Formato de mensagem de erro fixo (código, causa, ação, detalhe técnico)
      aplicado a 10 códigos mínimos.
- [x] Mensagens de modo iniciante e modo avançado especificadas.
- [x] Explicação de dry-run com linguagem proibida/permitida.
- [x] UX de aprovação humana futura especificada (sem implementar).
- [x] 5 exemplos completos (comando, saída humana, saída JSON quando
      aplicável, observação de segurança).
- [x] Restrições de segurança repetidas explicitamente.
- [x] Plano de testes futuros (15 nomes) listado.
- [x] Fases de implementação futuras (MC10, MC11-RC4, MC12-UX–MC17-UX)
      descritas com restrições (numeração reconciliada em MC11-RC4, ver
      seção 20).
- [x] Nenhum código funcional, comando real ou alteração de runtime.
