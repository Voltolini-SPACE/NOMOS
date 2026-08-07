# Horizonte 3 — Missão de eliminação de débitos residuais — Prioridade 3

## Validação real em browser do seletor de tema do NOMOS Dash

**Data:** 2026-07-17
**Escopo:** validar em um browser real — não apenas por asserção de string em teste
automatizado — que o seletor de tema claro/escuro do NOMOS Dash (`render_dash()`,
`src/nomos/interface/painel_web.py`) funciona de fato: clique real, mudança real de
CSS computado, persistência real via `localStorage`.

**Contexto do débito:** o commit `77a79cb` (Horizonte 3, Item 4 — "ativação completa
do seletor de tema do Dash") já implementou e testou o mecanismo por asserção de
string (`"root.setAttribute('data-tema'" in _JS_DASH`) e por fetch HTTP real do HTML
servido (`urllib.request.urlopen` contra um `DashboardServer` real, confirmando que
`id="tema-btn"` está presente na resposta). Esse mesmo commit documentou
explicitamente a lacuna, verbatim:

> "Tentativa adicional (documentada, não bloqueante): tentei validação visual real
> via Playwright/Chromium headless (clique real no botão + leitura de
> getComputedStyle + reload para provar persistência). O download do browser
> funcionou, mas 'playwright install --with-deps' precisa de apt-get como root para
> instalar libXdamage.so.1 e outras libs de sistema, indisponível neste sandbox
> (sudo bloqueado: 'no new privileges')."

Este documento fecha essa lacuna especificamente catalogada.

---

## 1. Reprodução do bloqueio original (confirmação, não suposição)

Antes de tentar qualquer alternativa, o bloqueio documentado em `77a79cb` foi
reproduzido de verdade nesta sessão, não apenas assumido como ainda válido:

- `playwright` (pip) e o binário `chromium_headless_shell-1228` já estavam
  presentes em `~/.cache/ms-playwright` (resíduo da tentativa anterior).
- Lançar esse binário (`p.chromium.launch(channel='chromium-headless-shell')`)
  falha porque falta `libXdamage.so.1` (pacote `libxdamage1`) no sistema —
  confirmado checando ~19 bibliotecas tipicamente exigidas (nss, atk, cups, drm,
  X11, cairo, pango, gbm, asound etc.); todas presentes exceto essa.
- `sudo -n true` falha com "no new privileges flag is set" — sem caminho para
  root, confirmando que `playwright install-deps`/`apt-get install libxdamage1`
  são inviáveis.
- `apt-get download libxdamage1` (que não exige root por si só) resolve o pacote
  mas o download é bloqueado pelo proxy de saída do sandbox (403 Forbidden em
  `ports.ubuntu.com`) — só CDNs específicos (ex.: `cdn.playwright.dev`) estão na
  allowlist.
- Firefox e WebKit foram checados como alternativas: piores (17 e 90 bibliotecas
  faltantes, respectivamente) — trocar de engine não ajuda.

**Conclusão confirmada:** lançar um browser real (headless ou não) *dentro deste
sandbox Linux* continua genuinamente inviável sem root. Este é o mesmo bloqueio
documentado em `77a79cb`, agora reproduzido e reconfirmado, não presumido.

---

## 2. Alternativa sem sudo: browser real do usuário, HTML real do NOMOS

O sandbox Linux (onde o pytest roda) e o computador real do usuário (onde o Chrome
dele roda, controlável via MCP `claude-in-chrome`) são sistemas de arquivos e redes
**separados** — um servidor Python subido no sandbox não é alcançável pelo Chrome
real do usuário, e vice-versa. A trilha viável encontrada não depende de rodar um
browser dentro do sandbox nem de expor uma porta entre os dois sistemas:

1. **Gerar o HTML de produção real**, byte-a-byte, chamando a própria função de
   produção `render_dash(__version__)` (não uma reconstrução manual do HTML/CSS/JS
   — o objeto realmente servido pelo `DashboardServer` em produção). Confirmado
   por leitura direta do handler HTTP:
   ```python
   # painel_web.py — dentro do handler /dash/
   from nomos import __version__ as _v
   return self._responder(200, render_dash(_v))
   ```
   `render_dash()` não recebe `ctx`/`dados` — é uma "casca estática" intencional
   (todo dado dinâmico chega depois via polling `fetch()` same-origin, conforme o
   próprio docstring do módulo). Isso significa que o HTML gerado por
   `render_dash(__version__)` é **idêntico**, byte a byte, ao que o servidor real
   entregaria — nenhuma aproximação.

2. **Injetar esse HTML real no DOM de uma aba real do Chrome do usuário**, via
   `document.open(); document.write(html); document.close();`, executado através
   do MCP `claude-in-chrome`. Duas tentativas anteriores de navegação direta
   falharam por restrições genuínas e distintas do próprio Chrome (documentadas
   abaixo, não contornadas) — a injeção via DOM foi a alternativa que efetivamente
   funciona sem exigir nenhuma permissão extra do usuário:
   - `file:///...` — bloqueado porque a extensão do Chrome usada pelo MCP não tem
     a permissão "Allow access to file URLs" (desligada por padrão em toda
     extensão Chrome, por design de segurança do próprio navegador).
   - `data:text/html;base64,...` como navegação de topo — bloqueado pela proteção
     anti-phishing nativa do Chrome contra navegação de topo para URLs `data:`
     (não é uma restrição de extensão; é do navegador).
   - `document.write()` **funciona** porque não é uma navegação — é reescrita do
     DOM de uma aba já carregada (usei `https://example.com` como "tela em
     branco" descartável) — sem trocar de esquema de URL, então nenhuma das duas
     restrições acima se aplica.

3. **Decodificar o HTML como UTF-8 de verdade** antes de escrever no DOM — uma
   primeira tentativa usando só `atob()` produziu *mojibake* visível
   ("carregandoâ€¦" em vez de "carregando…") porque `atob()` trata a saída como
   Latin-1 byte-a-byte, corrompendo qualquer caractere multibyte UTF-8. Esse
   artefato era do MEU método de validação, não do NOMOS (o servidor real manda
   `<meta charset="utf-8">` e o browser decodifica corretamente via HTTP). Corrigido
   decodificando com `TextDecoder('utf-8')` sobre os bytes brutos, eliminando o
   mojibake por completo (confirmado visualmente, ver evidência §3).

Cada um desses três bloqueios foi genuíno e verificado por tentativa real (erro
reproduzido, não hipotetizado) antes de ser contornado — nenhum foi assumido.

---

## 3. Evidência — antes do clique (tema escuro, padrão)

Estado inicial, HTML real recém-injetado, sem nenhuma escolha de tema salva:

```json
{
  "data_tema_antes": null,
  "localStorage_antes": null,
  "btn_texto_antes": "◐ claro",
  "btn_aria_pressed_antes": "false",
  "bg_computado_antes": "#0A0F0D",
  "body_bg_real_antes": "rgb(10, 15, 13)",
  "txt_color_real_antes": "rgb(232, 255, 232)"
}
```

`rgb(10, 15, 13)` = `#0A0F0D` — a variável CSS `--bg` do tema escuro **realmente
aplicada** pelo browser (não apenas presente no texto do CSS), confirmada via
`getComputedStyle(document.body).backgroundColor` — o valor que o motor de
renderização do Chrome de fato usa para pintar a página.

## 4. Evidência — clique real no botão (mouse, não evento sintético)

Localizado o botão via `find` (MCP `claude-in-chrome`, que devolveu a referência
`ref_8`, rotulado pela própria acessibilidade da página como `"mudar para tema
claro"`) e clicado com `computer.left_click` — um clique de mouse genuíno
disparado pelo Chrome real, não um `.click()` sintético via JavaScript.

Estado imediatamente após o clique:

```json
{
  "data_tema_depois": "claro",
  "localStorage_depois": "claro",
  "btn_texto_depois": "◐ escuro",
  "btn_aria_pressed_depois": "true",
  "btn_aria_label_depois": "mudar para tema escuro",
  "bg_var_depois": "#f4f7f4",
  "body_bg_real_depois": "rgb(244, 247, 244)",
  "txt_color_real_depois": "rgb(16, 38, 26)"
}
```

`rgb(244, 247, 244)` = `#f4f7f4` e `rgb(16, 38, 26)` = `#10261a` — batendo
exatamente com `:root[data-tema="claro"]{--bg:#f4f7f4;...--txt:#10261a;...}` do
CSS real (`_CSS_DASH`, `painel_web.py`). Confirmado visualmente por screenshot: a
página realmente pintou em fundo claro com texto escuro, botão relabelado, `aria-
pressed` invertido.

## 5. Evidência — persistência num carregamento fresco simulado

Sem tocar `localStorage`, o mesmo HTML real foi reinjetado do zero (simulando uma
visita nova ao Dash depois de fechar/reabrir), para provar que o script pre-paint
(`_BOOT_TEMA`, o primeiro `<script>` do documento, que roda antes de qualquer
`<style>`) sozinho honra a preferência salva — sem depender do resto do JS
principal já ter rodado antes:

```json
{
  "data_tema_apos_reload_simulado": "claro",
  "localStorage_apos_reload_simulado": "claro",
  "btn_texto_apos_reload": "◐ escuro",
  "btn_aria_pressed_apos_reload": "true",
  "bg_var_apos_reload": "#f4f7f4"
}
```

O tema claro já estava aplicado (`data-tema="claro"`, `--bg:#f4f7f4`) no instante
seguinte ao parse — sem nenhum flash de tema escuro perceptível, confirmando na
prática a razão de existir do `_BOOT_TEMA` (aplicar antes do `<style>`, documentada
no próprio código-fonte).

## 6. Evidência — volta ao tema escuro (fecha o ciclo simétrico)

Um segundo clique real, no botão agora rotulado `"mudar para tema escuro"`
(`ref_71`), confirma que o alternador funciona nos dois sentidos, não só
unidirecionalmente:

```json
{
  "data_tema_volta_escuro": "escuro",
  "localStorage_volta_escuro": "escuro",
  "btn_texto_volta": "◐ claro",
  "bg_var_volta": "#0A0F0D",
  "body_bg_real_volta": "rgb(10, 15, 13)"
}
```

---

## 7. Veredito

| Alegação (do commit `77a79cb`, nunca antes provada com browser real) | Verificado agora com evidência real |
|---|---|
| Clique no botão troca `data-tema` no `<html>` | Sim — `null` → `"claro"` → `"escuro"` |
| A troca é persistida em `localStorage['nomos-tema']` | Sim — mesmo valor em ambos |
| A troca realmente muda a cor computada (não só o atributo) | Sim — `getComputedStyle` bate exatamente com o CSS de produção |
| O rótulo/estado ARIA do botão é atualizado | Sim — texto e `aria-pressed`/`aria-label` corretos nos dois sentidos |
| Uma carga fresca honra a preferência salva, sem flash | Sim — tema correto já presente no primeiro `getComputedStyle` pós-parse |
| O alternador funciona nos dois sentidos (não só claro→escuro) | Sim — ciclo completo escuro→claro→escuro confirmado |

Nenhum bug foi encontrado. O mecanismo implementado em `77a79cb` funciona
exatamente como projetado, agora com prova de execução real em browser — não
apenas por leitura de código ou asserção de string.

**Nota de transparência sobre o método:** esta validação usou o HTML real
extraído via `render_dash(__version__)` (não uma reconstrução manual) injetado por
`document.write()` numa aba do Chrome real do usuário, em vez de servir o
`DashboardServer` real por HTTP para esse mesmo browser — porque o sandbox Linux
onde o `DashboardServer` rodaria e o computador real do usuário (onde o Chrome
controlável por MCP roda) são sistemas separados, sem rota de rede entre si. A
única diferença prática entre os dois métodos é a origem da página
(`https://example.com`, descartável, em vez de `http://127.0.0.1:<porta>/...`) — o
HTML, CSS e JS executados são byte-a-byte os mesmos que o servidor real entrega, e
toda a lógica de tema testada aqui é 100% client-side (sem chamada ao servidor),
então a origem não afeta a validade do resultado. O único artefato do método (não
do NOMOS) foi um mojibake inicial por decodificação incorreta de base64
(`atob()` sozinho, sem `TextDecoder`), identificado e corrigido antes de qualquer
medição ser registrada como evidência.

## 8. Item da missão

```
DASH_BROWSER_VALIDATION=PASS
```

Prioridade 3 do Horizonte 3 / missão de eliminação de débitos residuais:
concluída com evidência real de execução em browser, fechando a lacuna
documentada em `77a79cb`. Nenhuma alteração de código foi necessária — a
Prioridade 3 era puramente de validação.
