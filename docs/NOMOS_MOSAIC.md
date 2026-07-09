# NOMOS Mosaic (V0) — painel de telas ao vivo, isoladas

Uma tela só, com **N painéis em mosaico** que se auto-organiza. Você vai
**adicionando telas** (e-mail, rede social, marketplace — qualquer site); cada
painel é **isolado** (login/cookies próprios, sem interferir nos outros); e o
agente **vistoria** cada página para já saber o conteúdo quando você pedir.
Monitorar **+ agir com aprovação**.

> **Vive dentro do `nomos painel` (aba "Mosaic") — sem janelas separadas.** As
> telas são tiles numa aba do painel local (127.0.0.1); ler é livre, vistoriar e
> agir passam pelo caminho governado. O `--panel` da CLI é só um export avulso
> opcional.

> Substitui integrações difíceis (OAuth/IMAP por provedor) por "abrir o webmail
> e observar" — o agente acompanha tudo num lugar só.

## Fronteira de segurança (leia)

Isto é um **subsistema consentido e separado** do núcleo do NOMOS. O núcleo é
`EGRESS_ZERO` / `NO_SECRET_STORAGE` (e o motor de memória MC28 até **rejeita**
cookies). O Mosaic, por natureza, **navega (rede)** e mantém **sessões logadas**
por tela. Por isso ele:

- vive **fora** das garantias egress-zero, claramente rotulado;
- guarda cada login num **perfil isolado** (`~/.nomos/mosaic/profiles/<tela>`, 0700);
- guarda a vistoria em `~/.nomos/mosaic/knowledge/` (0600) — **nunca** é enviada
  ao motor de memória fail-closed, que permanece limpo;
- ações que mexem na conta (marcar lido, responder, arquivar) são **dry-run** e
  exigem **aprovação humana**.

## Arquitetura (`src/nomos/mosaic/`)

| Módulo | Papel |
|---|---|
| `layout` | Grid que se auto-organiza (1→1×1, 4→2×2, 9→3×3, 16→4×4). |
| `registry` | Telas + **perfil isolado por tela** (`screens.json` 0600). |
| `knowledge` | Vistoria por tela (título, resumo, sinais, thumb). |
| `browser` | Adaptador: `DemoAdapter` (sem rede, agora) · `PlaywrightAdapter` (go-live). |
| `engine` | Orquestra: add/scan/panel/act — **dry-run por padrão**. |
| `panel` | Renderiza o mosaico em HTML autocontido. |
| `cli` | `python -m nomos.mosaic.cli …` |

## Comandos

```bash
python -m nomos.mosaic.cli --add mail.google.com --label "Gmail" --apply
python -m nomos.mosaic.cli --add instagram.com --apply
python -m nomos.mosaic.cli --list
python -m nomos.mosaic.cli --scan --apply          # vistoria todas as telas
python -m nomos.mosaic.cli --panel --apply         # gera ~/.nomos/mosaic/panel.html
python -m nomos.mosaic.cli --context               # o que o agente já sabe
python -m nomos.mosaic.cli --act <id> --action reply --approve --apply
python -m nomos.mosaic.cli --remove <id> --apply
```

Regras: sem `--apply` = **dry-run** (não grava/age). `--act` sem `--approve` só
**propõe**. Ação desconhecida → `ACTION_REJECTED_FAIL_CLOSED` (saída 3). Sem
ação → saída 2. `--adapter demo|playwright`, `--base-dir` isola o armazenamento.

## Go-live (navegador real)

```bash
pip install playwright && playwright install chromium
python -m nomos.mosaic.cli --scan --apply --adapter playwright
```

O `PlaywrightAdapter` abre cada tela num **contexto persistente**
(`user_data_dir = profile_dir` da tela) → login real, isolado, que **persiste**
entre execuções. O primeiro login de cada conta é **humano** (uma vez por tela).

## Limitações (V0)

- **`<iframe>` de Gmail/Outlook não funciona** (X-Frame-Options/CSP) — por isso o
  mosaico usa screenshots/telas isoladas, não iframes.
- O modo demo é sintético (sem rede) — serve para UX e testes. O modo ao vivo
  não foi exercitado neste build (requer Playwright + login).
- Ações no modo demo são **registradas** (`actions.jsonl`), não executadas; a
  execução real vem com o `PlaywrightAdapter`.
- Vistoria e thumbs podem conter conteúdo sensível — por isso ficam locais, 0600,
  e fora do motor de memória.

## Próximos passos

- `PlaywrightAdapter` end-to-end + login assistido por tela.
- Painel servido ao vivo (auto-refresh) e botões de ação ligados à fila de
  aprovação do NOMOS.
- Vistoria incremental (só o que mudou) para custo baixo.
