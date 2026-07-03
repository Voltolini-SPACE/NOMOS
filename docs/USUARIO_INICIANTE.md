# NOMOS para quem está começando

Você não precisa entender de IA, terminal ou programação. Este guia usa só o
que aparece na tela.

## 1. Abra o NOMOS

Digite `nomos` e aperte Enter.

- **Primeira vez?** O NOMOS se apresenta, pergunta o nome do seu agente e a
  personalidade dele. Leva um minuto.
- **Depois disso**, abre um menu numerado:

```
O que vamos fazer?
 1. Conversar com meu agente
 2. Ver status do NOMOS
 3. Instalar/gerenciar cérebro
 4. Gerenciar motores
 5. Gerenciar skills
 6. Guardar chaves
 7. Ver modo local
 8. Rodar doutor/check-up
 9. Personalizar tema
10. Sair
```

Digite o número e Enter. Só isso.

## 2. Dê um cérebro ao seu agente (uma vez)

Escolha a opção **3** (ou digite `nomos cerebro baixar`). O NOMOS baixa um
modelo leve (~400 MB) que roda em qualquer computador. Ele pede sua permissão
antes de baixar — essa é a única saída para a internet, e é você quem aprova.

Sem cérebro, o agente funciona em **modo demo honesto**: anota e busca
lembranças, mas avisa que ainda não pensa — nunca finge.

## 3. Converse

Opção **1**. Dentro da conversa, `/ajuda` mostra tudo. Alguns atalhos:
`/memoria anotar ...` (guardar algo), `/doutor` (check-up), `/sair`.

## 4. Está tudo certo? Pergunte ao doutor

Opção **8** (ou `nomos doutor`). Ele mostra um STATUS GERAL (PRONTO, PARCIAL
ou BLOQUEADO), a lista do que está ok/faltando e **um** próximo passo
recomendado. Nada é alterado — ele só olha.

## 5. As perguntas que o NOMOS pode te fazer

- *"Este recurso precisa de internet. Quer permitir só desta vez?"* — nada sai
  da sua máquina sem um "sim" seu, digitado.
- *"Essa skill quer acessar arquivos. Permitir?"* — skills só fazem o que
  declararam, e você aprova.
- Para coisas mais sérias, o NOMOS pede uma palavra exata (como `ACEITO O
  RISCO`) — é de propósito, para ninguém aprovar sem ler.

**Regra de ouro: responder "não" (ou não responder) sempre deixa tudo como
está. O NOMOS nunca se ofende.**

## 6. Palavras que você vai ver por aí

| Palavra | Em português claro |
|---|---|
| cérebro | o modelo de IA que pensa pelo seu agente |
| motor | qualquer capacidade: falar, ouvir, desenhar, programar |
| skill | habilidade extra que você instala |
| modo só-local 🔒 | o cadeado: nada sai do seu computador |
| cofre / caixa-forte | onde suas chaves ficam guardadas, cifradas |
| doutor | o check-up que diz o que falta |

## Se algo der errado

Rode `nomos doutor` e siga o "próximo passo recomendado". O NOMOS nunca joga
uma tela de erro técnico em você — e nada que você fizer apaga suas memórias
sem perguntar.
