#!/usr/bin/env python3
"""Preview e validação local do site NOMOS (stdlib apenas, sem rede externa).

Uso:
    python site/preview.py --check    # valida assets, links e SEO/a11y básicos (exit 0/1)
    python site/preview.py            # serve o site em http://localhost:8000
    python site/preview.py --port 8080

O modo --check é read-only: não escreve nada, não acessa a internet. Serve como
gate local antes de publicar (a publicação é sempre ação humana).
"""
import argparse
import sys
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
PAGES = ["index.html", "404.html"]
REQUIRED_ASSETS = ["assets/favicon.svg", "assets/og-image.png", "assets/og-image.svg"]


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.local_refs = []   # href/src locais (não http/#/mailto)
        self.h1 = 0
        self.has_main = False
        self.has_skip = False
        self.lang_ok = False
        self.imgs_sem_alt = 0
        self.favicon = False
        self.og_image = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "html" and d.get("lang"):
            self.lang_ok = True
        if tag == "h1":
            self.h1 += 1
        if tag == "main":
            self.has_main = True
        if tag == "a" and "skip-link" in (d.get("class") or ""):
            self.has_skip = True
        if tag == "img" and not d.get("alt"):
            self.imgs_sem_alt += 1
        if tag == "link" and "icon" in (d.get("rel") or ""):
            self.favicon = True
        if tag == "meta" and d.get("property") == "og:image":
            self.og_image = True
        for attr in ("href", "src"):
            v = d.get(attr)
            if v and not v.startswith(("http://", "https://", "#", "mailto:", "data:")):
                self.local_refs.append(v)


def _parse(page: Path) -> _Extractor:
    ex = _Extractor()
    ex.feed(page.read_text(encoding="utf-8", errors="ignore"))
    return ex


def check() -> int:
    errors = []
    warnings = []

    # 1. Assets obrigatórios existem e não vazios
    for rel in REQUIRED_ASSETS:
        p = SITE_DIR / rel
        if not p.exists() or p.stat().st_size == 0:
            errors.append(f"asset ausente/vazio: {rel}")

    # 2. Páginas existem e parseiam; refs locais resolvem
    for page_name in PAGES:
        page = SITE_DIR / page_name
        if not page.exists():
            errors.append(f"página ausente: {page_name}")
            continue
        ex = _parse(page)
        for ref in ex.local_refs:
            alvo = (page.parent / ref).resolve()
            if not alvo.exists():
                errors.append(f"{page_name}: link/asset quebrado -> {ref}")
        if page_name == "index.html":
            if ex.h1 != 1:
                errors.append(f"index.html deve ter exatamente 1 <h1> (tem {ex.h1})")
            if not ex.has_main:
                errors.append("index.html sem <main>")
            if not ex.has_skip:
                warnings.append("index.html sem skip-link")
            if not ex.lang_ok:
                errors.append("index.html <html> sem atributo lang")
            if not ex.favicon:
                errors.append("index.html sem <link rel=icon>")
            if not ex.og_image:
                errors.append("index.html sem meta og:image")
            if ex.imgs_sem_alt:
                errors.append(f"index.html tem {ex.imgs_sem_alt} <img> sem alt")

    # Relatório
    print("NOMOS site — validação local (--check)\n")
    if warnings:
        for w in warnings:
            print(f"  ! {w}")
    if errors:
        for e in errors:
            print(f"  x {e}")
        print(f"\nRESULTADO: INCONSISTENTE ({len(errors)} erro(s))")
        return 1
    print("  ok  assets presentes")
    print("  ok  páginas parseiam e links locais resolvem")
    print("  ok  acessibilidade básica (1 h1, main, lang, favicon, og:image)")
    print("\nRESULTADO: OK — site consistente (NO_WRITE, NO_NETWORK)")
    return 0


def serve(port: int) -> int:
    import os
    os.chdir(SITE_DIR)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), SimpleHTTPRequestHandler)
    print(f"NOMOS site em http://localhost:{port}  (Ctrl+C para parar)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview/validação local do site NOMOS")
    parser.add_argument("--check", action="store_true", help="Valida sem servir (exit 0/1)")
    parser.add_argument("--port", type=int, default=8000, help="Porta do preview (default 8000)")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    return serve(args.port)


if __name__ == "__main__":
    sys.exit(main())
