"""NOMOS Mosaic — adaptadores de navegador (vistoria de uma tela).

`scan(screen)` abre a página no **perfil isolado** da tela e devolve um
`Snapshot` (título, texto, sinais e uma imagem). Dois adaptadores:

- `DemoAdapter` — 100% local, sem rede, determinístico. Serve para desenvolver,
  testar e mostrar o mosaico sem login real.
- `PlaywrightAdapter` — go-live: usa um contexto persistente com
  `user_data_dir=profile_dir` (isolamento real de cookies/login), navega e tira
  screenshot. Import preguiçoso: o módulo carrega sem Playwright instalado.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class Snapshot:
    screen_id: str
    url: str
    ok: bool
    title: str = ""
    text: str = ""
    signals: dict = field(default_factory=dict)
    image_data_uri: str = ""
    error: str = ""


def _host(url: str) -> str:
    return (urlparse(url).hostname or url).replace("www.", "")


def _seeded(url: str, mod: int) -> int:
    return int(hashlib.sha256(url.encode("utf-8")).hexdigest()[:4], 16) % mod


class DemoAdapter:
    """Vistoria sintética e determinística (sem rede). Não gera imagem: o painel
    desenha um placeholder em CSS. A imagem real (PNG) vem do PlaywrightAdapter."""

    name = "demo"

    def scan(self, screen_id: str, url: str, profile_dir: str | None = None) -> Snapshot:
        host = _host(url)
        h = host.lower()
        if any(k in h for k in ("mail", "gmail", "outlook", "proton")):
            n = _seeded(url, 12)
            title, signals = "Caixa de entrada", {"unread": n}
            text = f"Vistoria: {n} e-mails não lidos; {_seeded(url,4)} marcados importantes."
        elif any(k in h for k in ("whatsapp", "telegram", "messenger", "signal")):
            n = _seeded(url, 15)
            title, signals = "Mensagens", {"messages": n}
            text = f"Vistoria: {n} conversas com mensagem nova; {_seeded(url,5)} não lidas."
        elif any(k in h for k in ("bb.com", "bancodobrasil", "itau", "bradesco",
                                  "nubank", "santander", "caixa", "banco")):
            n = _seeded(url, 4)
            title, signals = "Banco", {"avisos": n}
            text = (f"Vistoria: {n} aviso(s) na conta; extrato observado. "
                    "Nenhum dado financeiro é armazenado.")
        elif any(k in h for k in ("instagram", "facebook", "x.com", "twitter",
                                  "linkedin", "tiktok")):
            n = _seeded(url, 30)
            title, signals = "Rede social", {"notifications": n}
            text = f"Vistoria: {n} notificações; {_seeded(url,9)} mensagens diretas."
        elif any(k in h for k in ("amazon", "mercadolivre", "shopee", "marketplace", "ebay")):
            n = _seeded(url, 6)
            title, signals = "Marketplace", {"orders": n}
            text = f"Vistoria: {n} pedidos ativos; {_seeded(url,3)} aguardando envio."
        else:
            title, signals = "Página", {}
            text = f"Vistoria: página {host} carregada e observada."
        return Snapshot(
            screen_id=screen_id, url=url, ok=True, title=title, text=text,
            signals=signals, image_data_uri="",
        )


class PlaywrightAdapter:
    """Go-live: navegador real com perfil isolado por tela. Requer Playwright
    (`pip install playwright && playwright install chromium`). Import preguiçoso."""

    name = "playwright"

    def __init__(self, headless: bool = True, timeout_ms: int = 15000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    def scan(self, screen_id: str, url: str, profile_dir: str | None = None) -> Snapshot:
        try:
            from playwright.sync_api import sync_playwright  # import preguiçoso
        except Exception as exc:  # pragma: no cover - depende de ambiente externo
            return Snapshot(screen_id, url, ok=False,
                            error=f"playwright indisponível: {exc}")
        try:  # pragma: no cover - requer navegador + rede (go-live)
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=profile_dir or f"/tmp/{screen_id}",
                    headless=self.headless,
                )
                page = ctx.new_page()
                page.goto(url, timeout=self.timeout_ms)
                title = page.title()
                text = (page.inner_text("body")[:4000]) if page.query_selector("body") else ""
                png = page.screenshot(type="png")
                ctx.close()
            uri = "data:image/png;base64," + base64.b64encode(png).decode()
            return Snapshot(screen_id, url, ok=True, title=title,
                            text=text, image_data_uri=uri)
        except Exception as exc:  # pragma: no cover
            return Snapshot(screen_id, url, ok=False, error=str(exc))


def get_adapter(name: str = "demo", **kw):
    if name == "playwright":
        return PlaywrightAdapter(**kw)
    return DemoAdapter()
