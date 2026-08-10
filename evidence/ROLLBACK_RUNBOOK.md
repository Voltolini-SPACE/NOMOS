# ROLLBACK RUNBOOK — ABSORPTION-02

## Situação atual: rollback é TRIVIAL porque nada foi promovido

Esta missão **não** mutou produção. Todo o trabalho vive numa branch local, numa
worktree isolada. Não houve push, merge, PR, tag, deploy, instalação de serviço,
alteração de LaunchAgent, mudança de porta nem escrita em `~/.hermes`.

```
main NOMOS            2cea197eb188121fcd507b53f02935b5edf435ad   (intocada)
branch da missão      feat/nomos-absorption-02
worktree              ~/Projects/nomos-absorption-02/wt
guard planner Hermes  2ecc5ff7051603675ccdf7ba087340759c246f26148a99b7db3be95628317ecc
Hermes :9119 PID 1336 · OpenClaw :18789 PID 996 · ambos vivos e inalterados
WhatsApp enabled=false · antitamper carregado
```

## R1 — Descartar o trabalho da missão (reversível, 1 comando)
```bash
git -C /Users/AI/Desktop/NOMOS_REPO/nomos worktree remove /Users/AI/Projects/nomos-absorption-02/wt
git -C /Users/AI/Desktop/NOMOS_REPO/nomos branch -D feat/nomos-absorption-02
```
Efeito: some tudo o que a 02 produziu. `main` e a branch da 01 seguem intactas.
**Não afeta produção** — nada da 02 está em produção.

## R2 — Voltar ao estado pré-ABSORPTION-01
Só se a 01 também for descartada:
```bash
git -C /Users/AI/Desktop/NOMOS_REPO/nomos worktree remove /Users/AI/Projects/nomos-runtime-absorption/wt
git -C /Users/AI/Desktop/NOMOS_REPO/nomos branch -D feat/nomos-runtime-absorption-01
```

## R3 — Restaurar Hermes (NÃO necessário hoje)
Não há o que restaurar: Hermes não foi tocado nesta missão. Se uma missão
futura mexer nele, os pontos de rollback herdados continuam válidos:
```
~/planner_pre_v2_promotion_20260809_173123.py      (guard v2 → v1)
~/planner_pre_injection_guard_20260809_165750.py   (guard → sem guard)
```
Verificação de integridade antes e depois de qualquer mudança:
```bash
shasum -a 256 "$HOME/Library/Application Support/Pantheon/apps/HERMES_AGENT_PANTHEON_20260701/source/hermes-agent/pantheon_orchestrator_runner.py"
# deve continuar 2ecc5ff7051603675ccdf7ba087340759c246f26148a99b7db3be95628317ecc
```

## R4 — Restaurar OpenClaw (NÃO necessário hoje)
Não foi tocado. Invariantes a preservar em qualquer missão futura:
- **não** habilitar o WhatsApp (`channels.whatsapp.enabled` segue `false`);
- **não** desativar `com.pantheon.openclaw.whatsapp-antitamper` — é controle de
  segurança vivo, roda a cada 60 s e só aperta, nunca afrouxa;
- **não** apagar `~/.hermes`: `~/.local/bin/{node,npm,npx}` apontam para
  `~/.hermes/node/bin/`, e removê-lo quebra o toolchain Node do host.

## R5 — Se um daemon do NOMOS vier a ser instalado (missão futura)
Ainda não existe. Quando existir, o rollback exigido é:
```bash
launchctl bootout gui/$UID/<label>     # descarrega
rm ~/Library/LaunchAgents/<label>.plist
launchctl list | grep <label>          # deve não retornar nada
```
Requisito da 02 registrado e **não cumprido**: `DAEMON_REMOVABLE` só pode ser
declarado PASS depois de instalar e remover de verdade, com evidência.

## Verificação pós-rollback (qualquer cenário)
```bash
git -C /Users/AI/Desktop/NOMOS_REPO/nomos rev-parse main    # 2cea197e…
lsof -nP -iTCP:9119 -sTCP:LISTEN | tail -1                  # Hermes vivo
lsof -nP -iTCP:18789 -sTCP:LISTEN | tail -1                 # OpenClaw vivo
launchctl list | grep -c whatsapp-antitamper                # 1
python3 -c "import json;print(json.load(open('$HOME/.openclaw/openclaw.json'))['channels']['whatsapp']['enabled'])"  # False
```

## ROLLBACK_PROVEN
```
ROLLBACK_PROVEN=TRUE para o escopo desta missão — porque não há promoção a
desfazer e o baseline foi reverificado íntegro no fecho. NÃO é uma prova de
rollback de daemon/serviço: esse cenário não existe ainda e está marcado como
pendente, não como aprovado.
```
