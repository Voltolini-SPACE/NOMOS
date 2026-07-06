# SITE EXPAND — Landing completa: recursos, motores, agentes, skills, segurança

## 1. Status

```
STATUS_FINAL=PASS_SITE_EXPAND_DELIVERY_READY
```

## 2. Objetivo

Expandir a landing para mostrar **todas as funcionalidades, agentes e integrações**
do NOMOS, com marketing/copy/branding caprichados — **sem inventar** (regra 5 do
brandbook congelado: sem promessa exagerada). Todo conteúdo é ancorado no código-fonte.

## 3. Inventário real usado (do código, não inventado)

- **Motores/conectores (12+ na tabela):** cérebro embutido, Ollama (texto/coder),
  visão local, Stable Diffusion WebUI, ComfyUI, Piper (TTS), Whisper (STT),
  memória-local (SQLite), busca-local (FTS5), Claude (nuvem opt-in), roteador.
  Fonte: `src/nomos/cognition/engine_catalog.py`.
- **Escada de risco A0–A6:** ler/escrever local, egress de rede, conector/credencial,
  câmera/mic/tela, exec código/instalar skill, destrutivo. Fonte: `src/nomos/kernel/policy.py`.
- **Agentes oficiais (3):** pesquisador-local (A0), programador, segurança + SDK
  (`nomos agent create`). Fonte: `src/nomos/agents/oficiais/*.json`.
- **Skills de exemplo (4):** busca-arquivos, lembrete, organizador, sistema-info.
  Fonte: `examples/skills/*`.
- **Subsistemas:** vault/caixa-forte, auditoria + âncora HMAC, fila de aprovação,
  conselho/council, sandbox, painel web, rotinas/briefing, conversas/retenção,
  backup, pânico, doutor. Fonte: `src/nomos/{kernel,council,interface,simple}`.

## 4. Seções da landing (novas/expandidas)

hero + **faixa de stats** · o que é · **recursos (12 cards)** · **motores & integrações
(tabela + pills local/conector/nuvem)** · **agentes (3 + SDK)** · **skills (4 + assinatura)**
· **segurança: escada A0–A6 + do/don't** · como funciona (6 passos) · instalação (cheat
sheet real) · para quem · roadmap · footer.

## 5. Marca e honestidade

- Marca congelada v1.0 preservada: terminal escuro `#0A0F0D`, verde-neon `#5AF78E`,
  monospace, logo ASCII, glow. Zero cor inventada.
- Copy honesta: nuvem sempre marcada **opt-in**; conectores marcados como "você pluga";
  nenhuma promessa de "segurança absoluta"/"impossível hackear" (teste garante).

## 6. Comandos executados (evidência real)

| Comando | Retorno | Resultado |
|---|---:|---|
| `python site/preview.py --check` | 0 | site consistente |
| `python tools/nomos_update_agent.py --check` | 0 | links da landing resolvem |
| `ruff check .` | 0 | All checks passed! |
| smoke `curl /` (preview :8044) | — | HTTP 200, 31.506 bytes |
| grep conteúdo servido | — | Ollama, Whisper, Stable Diffusion, ComfyUI, Piper, A6, pesquisador-local, HMAC, opt-in — todos presentes |
| `pytest tests/test_site_polish.py tests/test_mc25_deliverables.py -q` | 0 | 63 passed |
| `pytest -q` (bare) | 0 | 1117 passed |
| `git diff --stat .github pyproject.toml` | 0 | vazio (intactos) |

## 7. Testes novos (anti-recaída)

- `test_index_tem_secoes_ricas`: exige recursos/motores/agentes/skills/segurança/como/instalar.
- `test_index_capacidades_reais_presentes`: exige Ollama, Whisper, Stable Diffusion,
  ComfyUI, Piper, pesquisador-local, roteador, FTS5, dry-run, HMAC + níveis A0/A2/A5/A6.
- `test_index_honesto_sem_promessa_exagerada`: proíbe "100% seguro", "impossível hackear",
  "segurança absoluta" etc.; exige "opt-in" para nuvem.
- Correção: padrão de secret do MC25 agora **shape-aware** (regex), sem falso-positivo
  com ids como `sk-t`.

## 8. Evidência de segurança

```
CONTEUDO_ANCORADO_NO_CODIGO=YES   (nada inventado; fontes citadas)
FROZEN_BRAND_RESPEITADO=YES       (terminal/neon/mono; 0 cor inventada)
NO_EXAGGERATED_PROMISE=YES        (teste de honestidade passa)
LOCAL_FIRST=YES · NO_DEPLOY=YES · NO_PUSH=YES (por mim) · NO_TAG=YES · NO_RELEASE=YES
FORBIDDEN_FILES_INTACT=YES        (.github/, pyproject.toml sem diff)
```

## 9. Nota sobre o git (honestidade)

Os commits `841a81f` (site MC25), `0e80275` (update agent MC27) e `d96e96a`
(changelog+MC28) foram feitos **pelo usuário** (Se7enpay), não por mim. Minha expansão
atual (`site/index.html` +226/−131, testes) está no **working tree, não commitada** —
commit/push seguem sendo ação humana.

## 10. Limitações honestas

- Sem captura de tela renderizada da página completa neste ambiente; fidelidade visual
  vem dos tokens CSS congelados + smoke HTTP + testes. Para ver: `python site/preview.py`.
- og-image não foi regenerada (permanece a versão de marca correta; conteúdo textual da
  página cresceu, a imagem social continua válida).
- Landing segue single-page (rica). Multi-página fica para incremento futuro.

## 11. Próximo passo recomendado

Adicionar uma página `docs/` navegável (índice visual dos manuais/brandbook/threat model)
e permitir que o `nomos_update_agent --diff` proponha sincronizar a lista de motores da
landing com o `engine_catalog.py` (proposal-only), fechando o ciclo doc↔código.
