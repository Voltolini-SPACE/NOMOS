# Motores do NOMOS

"Motor" é qualquer coisa que dá uma capacidade ao seu agente: conversar,
programar, transcrever áudio, gerar imagem, lembrar. O NOMOS organiza os
motores por **modalidade** e escolhe sempre o caminho **local primeiro**.

## Modalidades (v0.11)

| Modalidade | O que é | Motores típicos |
|---|---|---|
| texto | conversar e escrever | cérebro embutido, Ollama, nuvem (opt-in) |
| codigo | programar | Ollama coder, motor de texto (reserva) |
| raciocinio | planejar/analisar | modelo local forte; leve com aviso |
| resumo | sintetizar textos | mesmo motor de texto |
| memoria | lembrar de coisas | memória local (SQLite) — sempre pronta |
| voz_stt | transcrever áudio | whisper |
| voz_tts | falar em voz alta | piper |
| imagem | gerar imagens | Stable Diffusion WebUI, ComfyUI |
| visao | entender imagens | modelo de visão no Ollama (llava etc.) |
| embeddings | busca nas memórias | FTS5 local — sempre pronta |
| ferramentas | skills instaladas | suas skills |
| roteamento | escolher motor | roteador do NOMOS — sempre pronto |

## Tipos de motor

- **embutido** — vem com o NOMOS (cérebro leve via llama.cpp, memória, busca);
- **ollama / llama.cpp local** — modelos que você instala na sua máquina;
- **cloud (opt-in)** — só funciona com o cadeado só-local desligado, chave no
  cofre e a sua aprovação a cada uso (gates A2+A3);
- **mock/test** — usado pela suíte de testes;
- **skill-provided** — capacidade trazida por uma skill instalada;
- **conector externo** — apenas se você plugar explicitamente.

## Comandos

```bash
nomos motores                 # tabela clássica (compatível com v0.10)
nomos motores listar          # tabela completa v0.11 (custo, privacidade...)
nomos motores status          # idem
nomos motores menu            # menu guiado
nomos motores recomendar texto    # qual motor usar para uma tarefa
nomos motores usar codigo ollama-coder   # escolha manual (persistida)
nomos motores auto on|off     # roteador automático liga/desliga
nomos motores testar embutido # sonda um motor específico
nomos motores diagnostico     # visão geral por modalidade
```

A tabela v0.11 mostra por motor: modalidade, local/nuvem, instalado, pronto,
custo estimado, privacidade, velocidade, qualidade, se requer chave, se requer
aprovação e o status.

## Regras que nenhum motor escapa

1. Com o modo só-local LIGADO, motores de nuvem ficam **desplugados** — não é
   escolha do roteador, é a política (DENY antes do gate).
2. Motor ausente nunca vira resposta inventada: você recebe o status honesto e
   a instrução de instalação em uma linha.
3. Motor de nuvem exige: `nomos local off` (decisão consciente) + chave no
   cofre + aprovação A2+A3 na hora do uso.

Veja também: [ROTEADOR.md](ROTEADOR.md) e [PRIVACIDADE.md](PRIVACIDADE.md).
