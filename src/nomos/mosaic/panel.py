"""NOMOS Mosaic — renderização do painel (HTML autocontido, auto-organizável).

Função pura: recebe os "tiles" prontos e devolve HTML. O grid usa
`layout.grid_for(n)`, então o mosaico se reorganiza sozinho conforme telas são
adicionadas. Sem rede, sem dependências — dá para abrir o arquivo direto.
"""
from __future__ import annotations

import hashlib
import html

from nomos.mosaic import layout


def _esc(s: str) -> str:
    # P2-7 da auditoria de 2026-07-17: `str(s or "")` apagava valores
    # "falsy" LEGÍTIMOS (0, False) como se fossem vazios — ex.: um contador
    # zerado virava "" em vez de "0". Só None deve virar string vazia; tudo
    # o mais passa por str() antes de escapar. Cópia deliberadamente LOCAL
    # (não importada de outro pacote nomos.*): mosaic/ não tem nenhuma
    # dependência de nomos.* de propósito (roda como HTML autocontido, sem
    # instalar o pacote todo) — mesmo princípio de isolamento já usado em
    # kernel/audit.py (SECRET_PATTERNS duplicado em vez de importar
    # nomos.memory.policy). Contrato alinhado ao de nomos.interface._html.esc.
    return html.escape("" if s is None else str(s), quote=True)


def _hue(s: str) -> int:
    """Cor determinística por host (sem imagens/URLs externas)."""
    return int(hashlib.sha256((s or "x").encode("utf-8")).hexdigest()[:4], 16) % 360


def _badge(signals: dict) -> str:
    if not signals:
        return "monitorando"
    if "unread" in signals:
        return f"✉ {signals['unread']} não lidos"
    if "messages" in signals:
        return f"💬 {signals['messages']} conversas"
    if "notifications" in signals:
        return f"🔔 {signals['notifications']}"
    if "orders" in signals:
        return f"📦 {signals['orders']} pedidos"
    if "avisos" in signals:
        return f"🏦 {signals['avisos']} avisos"
    k, v = next(iter(signals.items()))
    return f"{_esc(k)}: {_esc(v)}"


def render(tiles: list[dict], generated_at: str = "") -> str:
    g = layout.grid_for(len(tiles))
    cols = max(g.cols, 1)
    cards = []
    for t in tiles:
        img = t.get("image") or ""
        label = t.get("label")
        if img:
            img_html = f'<img src="{_esc(img)}" alt="{_esc(label)}"/>'
        else:
            hue = _hue(t.get("host") or label or "x")
            img_html = (f'<div class="ph" style="background:'
                        f'linear-gradient(135deg,hsl({hue},40%,20%),hsl({hue},44%,11%))">'
                        f'<span>{_esc(t.get("host"))}</span></div>')
        cards.append(f"""
      <article class="tile" data-screen="{_esc(t.get('id'))}">
        <header><span class="dot"></span>{_esc(t.get('label'))}
          <small>{_esc(t.get('host'))}</small></header>
        <div class="shot">{img_html}<span class="badge">{_esc(_badge(t.get('signals') or {}))}</span></div>
        <p class="sum">{_esc(t.get('summary'))}</p>
        <footer>
          <button data-action="monitor">Monitorar</button>
          <button data-action="mark_read">Marcar lido</button>
          <button data-action="reply">Responder</button>
        </footer>
      </article>""")

    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NOMOS Mosaic</title><style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:#0b0d12;color:#e8eaed;font:14px/1.4 system-ui,sans-serif}}
header.top{{display:flex;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #1d2230}}
header.top h1{{font-size:16px;margin:0;font-weight:650}}
header.top .grow{{flex:1}}
.addbar{{display:flex;gap:8px}}
.addbar input{{background:#12151d;border:1px solid #2a3040;color:#e8eaed;border-radius:8px;padding:8px 10px;width:280px}}
.addbar button,footer button{{background:#2b6cff;border:0;color:#fff;border-radius:8px;padding:8px 12px;cursor:pointer;font-weight:600}}
footer button{{background:#1a2030;color:#cdd3e0;font-weight:500;padding:6px 10px;font-size:12px}}
.grid{{display:grid;grid-template-columns:repeat({cols},1fr);gap:12px;padding:14px}}
.tile{{background:#12151d;border:1px solid #202636;border-radius:12px;overflow:hidden;display:flex;flex-direction:column}}
.tile header{{display:flex;align-items:center;gap:8px;padding:10px 12px;font-weight:600;border-bottom:1px solid #1c2230}}
.tile header small{{color:#7c88a1;font-weight:400;margin-left:auto}}
.dot{{width:8px;height:8px;border-radius:50%;background:#37d67a;box-shadow:0 0 8px #37d67a}}
.shot{{position:relative;aspect-ratio:16/10;background:#0e1017}}
.shot img{{width:100%;height:100%;object-fit:cover;display:block}}
.noimg{{display:grid;place-items:center;height:100%;color:#5b6478}}
.ph{{display:grid;place-items:center;height:100%;color:#dfe4ee;font-size:15px;font-weight:600;letter-spacing:.3px}}
.badge{{position:absolute;left:8px;bottom:8px;background:#0009;border:1px solid #2a3142;border-radius:999px;padding:3px 10px;font-size:12px}}
.sum{{margin:0;padding:10px 12px;color:#aab3c5;min-height:38px}}
.tile footer{{display:flex;gap:6px;padding:10px 12px;border-top:1px solid #1c2230}}
.hint{{padding:0 18px 18px;color:#6b7488;font-size:12px}}
</style></head><body>
<header class="top">
  <h1>🟦 NOMOS Mosaic</h1>
  <span class="grow"></span>
  <form class="addbar" onsubmit="return false">
    <input placeholder="adicionar tela: email, rede social, marketplace…" aria-label="url">
    <button type="submit">＋ Adicionar</button>
  </form>
</header>
<section class="grid">{''.join(cards) or '<p class="hint">Nenhuma tela ainda. Adicione a primeira acima.</p>'}</section>
<p class="hint">{len(tiles)} tela(s) · grid {g.rows}×{g.cols} auto-organizado · vistoria {_esc(generated_at)} ·
ações (marcar/responder) são <b>dry-run</b> e exigem aprovação. Cada tela usa perfil isolado (login não interfere entre telas).</p>
</body></html>"""
