# Roteador automático de motores

O roteador escolhe o melhor motor para cada tarefa **sem você precisar
entender de modelos**. A ordem de prioridade é fixa e auditável:

**privacidade > disponibilidade > qualidade > custo**

## O que ele considera

Tipo da tarefa (conversa, código, resumo, raciocínio), modalidade, presença de
dados sensíveis, tamanho do contexto, modo só-local, motores prontos, chave de
nuvem configurada, custo, e se a tarefa pede ferramenta/memória.

## Regras invioláveis

1. **Só-local ligado ⇒ nuvem nunca é escolhida** — nem como reserva.
2. Texto simples usa motor leve local (rápido e suficiente).
3. Raciocínio complexo tenta motor local forte; se só houver o leve, o NOMOS
   avisa em vez de fingir confiança.
4. Nuvem exige: `nomos local off` + chave no cofre + aprovação A2+A3 na hora.
5. Skill sensível passa pelo policy gate (o roteador não autoriza nada).
6. Sem motor adequado ⇒ **não inventa resposta**: devolve diagnóstico com o
   próximo passo ("rode: nomos cerebro baixar").
7. Tarefa grande pode virar pipeline (resumir contexto → responder).

## A decisão (EngineRouteDecision)

Cada roteamento produz um registro com: `selected_engine`, `fallback_engine`,
`reason`, `privacy_level`, `approval_required`, `estimated_cost`,
`local_only_preserved`, `confidence` e `steps` (pipeline, quando houver).
O roteador **decide, mas não executa**: quem executa continua passando pelo
gate de aprovação. Não existe caminho novo de autorização.

## Pipelines (junção de motores)

Quando útil, o NOMOS encadeia motores — por exemplo:

- áudio → transcrever (whisper local) → resumir (texto local) → memória local;
- arquivo → extrair pontos → resumir → sugerir ação;
- contexto grande → resumir → responder.

Regras do pipeline: cada etapa passa pela política; a primeira etapa negada ou
com erro **para tudo** (sem resultado pela metade); a auditoria guarda decisão
e metadados, nunca o conteúdo; ao final você vê uma explicação simples:

> "Usei: transcrever (whisper, local) → resumir (embutido, local). Nada saiu
> da sua máquina."

## Comandos

```bash
nomos motores recomendar <modalidade>   # o que o roteador escolheria e por quê
nomos motores auto on|off               # liga/desliga o modo automático
nomos motores diagnostico               # modalidades com/sem motor
```
