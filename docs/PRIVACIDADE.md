# Privacidade — "local por lei"

O NOMOS foi construído para uma coisa: **o que é seu fica com você**.

## O que nunca acontece sem a sua permissão explícita

- Nenhum dado sai da sua máquina (o cadeado só-local vem **ligado** de fábrica
  e a própria política nega qualquer saída de rede que não seja local).
- Nenhum motor de nuvem é usado (exige `nomos local off` — decisão consciente
  digitada por você — mais aprovação A2+A3 a cada uso, mais a chave no cofre).
- Nenhuma skill roda além do que declarou no manifesto.
- Nenhum arquivo é criado/alterado, código executado, microfone/câmera/tela
  acessados sem aprovação.
- Ações destrutivas são negadas por padrão (DENY, sem flag de bypass).

## Como isso é garantido (não é promessa, é mecanismo)

| Garantia | Mecanismo |
|---|---|
| Local por padrão | `localidade.json` ausente/corrompido ⇒ modo só-local LIGADO |
| Fail-closed | política ilegível, categoria desconhecida ou sem aprovador ⇒ NEGA |
| Sem bypass | não existe flag/env/modo dev que pule o gate — por projeto |
| CI nega | aprovação exige terminal interativo com confirmação digitada |
| Segredos fora dos logs | auditoria redige por nome de campo E por padrão de valor (sk-, AKIA, JWT, Bearer...) |
| Cofre | chaves cifradas (Argon2id/PBKDF2), arquivo 0600, sem cache de senha |
| Auditoria íntegra | cadeia de hash; qualquer adulteração aponta a linha violada |
| Sandbox | execução isolada; sem namespaces de rede ⇒ recusa rodar (não roda "aberto") |
| Skills | checksum por arquivo, assinatura ed25519, trust store, pin TOFU |

## Telemetria: nunca

O NOMOS **não tem e não terá telemetria**, analytics, crash reporting remoto
ou qualquer "ping" para servidores. Isso é verificado por teste automatizado
(`test_egress_zero.py`): todo destino externo hardcoded no código precisa
estar numa lista permitida e justificada — hoje, apenas `api.anthropic.com`
(nuvem opcional), `huggingface.co` (download do cérebro, opt-in) e
`api.github.com` (checagem de versão via `nomos atualizar`, opt-in). Todos
atrás do gate A2 e do cadeado só-local.

`nomos atualizar` envia zero dados seus: é um GET público que lê o número da
última versão. E mesmo isso só acontece com o cadeado aberto e sua aprovação.

## O que fica na sua máquina (`~/.nomos`)

Perfil do agente, memórias (SQLite), cofre de chaves, política, trilha de
auditoria, skills e o cérebro baixado. Apagar `~/.nomos` remove tudo.

## E quando eu QUERO usar a nuvem?

1. `nomos local off` — o NOMOS explica e pede confirmação digitada;
2. guarde sua chave: `nomos chaves` (vai para o cofre cifrado, nunca em texto);
3. use `/nuvem <pergunta>` no chat ou `nomos chat --cloud` — a cada uso o NOMOS
   pede A2 (sair para a internet) e A3 (usar a chave);
4. volte quando quiser: `nomos local on` — o caminho mais seguro nunca é barrado.

A auditoria registra que houve egress e qual credencial foi usada — nunca o
valor da chave nem o conteúdo da conversa.
