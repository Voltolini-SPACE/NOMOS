# MC43 — Prontidão de release: cockpit + conexões

Preparação validada localmente em 2026-07-07 (espelhando o job do CI):
`python -m build` ✓ wheel+sdist · venv limpa + `pip install *.whl` ✓ ·
`nomos --version` ✓ · `nomos doutor` ✓ · `nomos rotinas briefing` ✓ ·
`rotinas agendar --telegram` ✓ · suíte 1395 ✓ · ruff ✓ · gate do site 13/13 ✓.
Correção incluída: **MANIFEST.in** — o sdist agora carrega `examples/`
(conectores MCP telegram/whatsapp-cloud) e `docs/` (antes: 0 arquivos ⇒ quem
baixava o pacote não recebia os conectores).

## Tag sugerida (padrão das anteriores)

```
v1.3.0rc17-cockpit-conexoes
```

## Rascunho das notas (colar na release do GitHub)

NOMOS v1.3.0rc17 leva o painel a outra categoria e liga o NOMOS ao mundo —
sem abrir mão de nenhuma lei da casa.

**Painel 4.0 → cockpit (MC34–MC38)**: layout de app com abas, tema
escuro/claro, chat local com histórico, aprovações com token de uso único
direto no navegador (POST existe numa única porta), `health/` com sinais
reais, `api/?secao=`, busca na auditoria, headers de segurança (CSP
restritiva) — e o site com seção de downloads (macOS/Windows/git) com
SHA256 conferido.

**NOMOS Dash (MC39)**: mission control ao vivo — 4 sinais vitais, sparkline
24h↔7d da trilha real, placar de decisões, motores por modalidade, uptime e
memória do processo; atualiza sozinho, pausa quando a aba se esconde e diz
"reconectando…" em vez de fingir. Dash Hub (MC40): conexões (o que está
ligado, o que dá para ligar, com o comando exato) e atalhos do dia a dia.

**Conexões sociais oficiais (MC40)**: conectores MCP para Telegram (Bot API
— enviar, ler, validar) e WhatsApp Business Cloud API (texto + template).
Credencial só por ambiente, redigida de qualquer erro; toda tool A3 = sua
aprovação a cada chamada; trust store por impressão SHA-256. Instagram/
TikTok: mapa honesto em docs/CONECTORES_SOCIAIS.md (exigem apps aprovados;
nada de bibliotecas não-oficiais).

**A primeira automação de ponta a ponta (MC41–MC42)**: `nomos rotinas
briefing --telegram CHAT` entrega o briefing do dia com o seu OK; a ação de
rotina `briefing-telegram:<chat>` + `rotinas executar --panel` fazem isso
sozinhos todo dia às 08:00 — com aprovação just-in-time na fila do painel
(TTL 5 min). Sem aprovação, não sai. A3 nunca se auto-aprova, nem no cron.

Também: MC35/MC36 (vistoria de segurança: providers só-loopback, escrita
atômica, single-use atômico) e MC37 (desdensificação + temas).

Instalação: como sempre — `install.sh`/`install.ps1` + `.whl` da release,
verificação com `SHA256SUMS`. Conectores MCP: no sdist ou no clone do repo.

## Checklist de publicação (na sua máquina — credencial é sua)

```bash
cd ~/Desktop/NOMOS_REPO/nomos
git push origin main                                  # 1) commits MC40→43
git tag v1.3.0rc17-cockpit-conexoes                   # 2) a tag dispara o CI
git push origin v1.3.0rc17-cockpit-conexoes           #    (valida e publica)
# 3) release publicada → atualizar o site (2 lugares marcados com
#    comentário MANUTENÇÃO em site/index.html): trocar a tag nos hrefs dos
#    botões install.sh/install.ps1/.whl e o texto de versão; commit + push.
#    O teste tests/test_site_downloads.py acusa se os botões divergirem.
```

Fail-closed honesto: nada foi publicado a partir daqui — o push e a tag são
seus, com a sua credencial.
