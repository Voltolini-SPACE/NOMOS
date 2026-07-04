# SPEC — Missão v1.2 "Agente que age" (skills na conversa)

(versão de pacote: 1.2.0rc1)

## Objetivo
Skills instaladas deixam de ser um comando escondido: o chat OFERECE a skill
certa quando a intenção bate, executa só com o "sim" do usuário (e com o gate
de sempre), e devolve o resultado JSON como resposta. Auditoria liga a cadeia.

## Escopo incluído
1. **Manifesto ganha `keywords`** (opcional, lista de strings) — validado e
   normalizado; é o gatilho declarado da skill.
2. **`sugerir_skill(texto, home, skills_dir)`** em `ext/skill_intencao.py`:
   heurística local e determinística — casa keywords declaradas (ou o nome da
   skill) com o texto; ignora skills desativadas/quebradas; devolve no máximo
   UMA sugestão (a de mais keywords casadas).
3. **Oferta na conversa** (chat amigável): antes de mandar ao motor, se houver
   sugestão → "posso usar a skill 'X' para isso — quer? (sim/não)". "sim" ⇒
   `executar_json` com o aprovador humano (gate por permissão, como sempre);
   "não"/qualquer outra coisa ⇒ conversa normal segue para o motor. Resultado
   JSON vira resposta legível; falha é honesta.
4. **`/skills usar <nome> [json]`** no chat: invocação explícita, mesmo fluxo.
5. **Skill oficial nº 4 — `busca-arquivos`** (A0): recebe {pasta, termo},
   procura por nome e por conteúdo (txt/md/log pequenos), devolve matches;
   limites de profundidade/quantidade; nunca escreve nada.
6. **Auditoria da cadeia**: evento `skill.conversa` com nome, origem
   (oferta|explicito), ok e rc — metadados, nunca conteúdo.

## Fora de escopo
Function-calling pelo modelo (a heurística é determinística de propósito);
skills em rotinas já existem (v0.16); painel (v1.4).

## Arquivos que poderei alterar
`src/nomos/ext/skill_registry.py` (keywords, aditivo),
`src/nomos/ext/skill_intencao.py` (novo), `src/nomos/simple/amigavel.py`,
`examples/skills/busca-arquivos/` (novo), versão/CHANGELOG/README/docs/SKILLS.md,
`tests/test_v12_agente_age.py` (novo).

## Arquivos proibidos
Kernel; testes existentes (somente adições).

## Critérios de aceite
| # | Critério | Verificação |
|---|---|---|
| 1 | keyword casada ⇒ oferta; "sim" ⇒ executa com gate; resultado vira resposta | teste de conversa com executar_json monkeypatchado |
| 2 | "não" ⇒ NADA executa e o motor responde normalmente | RouterFake recebe a mensagem |
| 3 | skill desativada/quebrada nunca é oferecida | teste |
| 4 | `/skills usar` explícito funciona e respeita o gate | teste com skill A1 sem aprovação ⇒ negada |
| 5 | busca-arquivos acha por nome e conteúdo, A0, com limites | execução real via subprocess |
| 6 | auditoria `skill.conversa` só com metadados | inspeção do log |
| 7 | conversa sem intenção não é sequestrada | frase neutra vai direto ao motor |
| 8 | suíte 100% + ruff + compat | pytest/ruff |

## Riscos
Falso positivo de intenção — mitigado: só keywords DECLARADAS, oferta sempre
pergunta, "não" é caminho feliz. Rollback: git (1 commit).
