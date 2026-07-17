"""NOMOS interface.panel — painel LOCAL de aprovações (R4/C6).

Garantias:
- escuta EXCLUSIVAMENTE em 127.0.0.1 (recusa qualquer outro bind);
- URL contém segmento secreto aleatório — sem ele, 404 em tudo;
- aprovar/negar é POST com o token single-use da solicitação; token errado,
  reutilizado ou expirado = recusa (a fila garante; o painel só transporta);
- HTML autossuficiente (zero assets externos, zero JS de terceiros);
- mesmos headers de segurança do painel 4.0 (CSP/nosniff/no-referrer/
  no-store — páginas carregam tokens; nada pode ir ao cache) e o mesmo
  PRG: decidir → 303 → recarregar (F5 não reenvia a decisão).
"""
from __future__ import annotations

import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from nomos.interface._html import esc as html_escape
from nomos.interface.painel_web import _HEADERS_SEGURANCA
from nomos.kernel.approvals import ApprovalError, ApprovalQueue
from nomos.kernel.policy import rotulo_categoria

_PAGE = """<!doctype html><html lang="pt-br"><meta charset="utf-8">
<title>NOMOS — aprovações</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem}}
 .req{{border:1px solid #ccc;border-radius:8px;padding:1rem;margin:1rem 0}}
 .cat{{font-weight:700}} .alvo{{font-family:monospace}}
 button{{padding:.5rem 1rem;border-radius:6px;border:1px solid #888;cursor:pointer}}
 .ok{{background:#e6ffe6}} .no{{background:#ffe6e6}} small{{color:#666}}
</style>
<h1>NOMOS — painel local de aprovações</h1>
<p><small>single-use · TTL 5 min · somente 127.0.0.1 · recarregue para atualizar</small></p>
{body}
</html>"""

_ITEM = """<div class="req">
 <div class="cat">{category} <small>({cat_raw})</small></div>
 <div>alvo: <span class="alvo">{target}</span></div>
 <div>motivo: {reason}</div>
 <div><small>expira em {left:.0f}s · id {rid}</small></div>
 <form method="post" action="{base}/decide" style="display:inline">
  <input type="hidden" name="id" value="{rid}">
  <input type="hidden" name="token" value="{token}">
  <input type="hidden" name="action" value="aprovar">
  <button class="ok" type="submit">APROVAR</button>
 </form>
 <form method="post" action="{base}/decide" style="display:inline">
  <input type="hidden" name="id" value="{rid}">
  <input type="hidden" name="token" value="{token}">
  <input type="hidden" name="action" value="negar">
  <button class="no" type="submit">NEGAR</button>
 </form>
</div>"""


class PanelServer:
    def __init__(self, queue: ApprovalQueue, host: str = "127.0.0.1", port: int = 0):
        if host != "127.0.0.1":
            raise ValueError("painel é LOCAL por projeto: bind permitido só em 127.0.0.1")
        self.queue = queue
        self.secret = secrets.token_urlsafe(16)
        panel = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _deny(self, code=404, msg="não encontrado"):
                data = msg.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in _HEADERS_SEGURANCA.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _html(self, code, text):
                data = text.encode()
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in _HEADERS_SEGURANCA.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                base = f"/p/{panel.secret}"
                caminho, _, query = self.path.partition("?")
                if caminho.rstrip("/") != base:
                    return self._deny()
                items = []
                # feedback pós-PRG: só valores do vocabulário (nunca eco livre)
                decidido = (parse_qs(query).get("decidido") or [""])[0]
                if decidido in ("aprovada", "negada"):
                    items.append(f"<p>✔ solicitação <b>{decidido}</b>.</p>")
                now = panel.queue.clock()
                for a in panel.queue.pending():
                    try:
                        token = panel.queue.token_of(a.id)
                    except ApprovalError:
                        continue
                    items.append(_ITEM.format(
                        base=base, rid=a.id,
                        # P2-7: helper único do pacote interface — null-safe
                        # (era html.escape(...) puro, quebrava em None)
                        token=html_escape(token),
                        category=html_escape(rotulo_categoria(a.category)),
                        cat_raw=html_escape(a.category),
                        target=html_escape(a.target),
                        reason=html_escape(a.reason),
                        left=max(0.0, a.expires - now),
                    ))
                body = "\n".join(items) or "<p>nenhuma solicitação pendente.</p>"
                self._html(200, _PAGE.format(body=body))

            def do_POST(self):
                base = f"/p/{panel.secret}"
                if not self.path.startswith(base):
                    return self._deny()          # sem o segredo: 404 uniforme
                if self.path != f"{base}/decide":
                    return self._deny(405, "só existe POST em decide")
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._deny(400, "Content-Length inválido")
                if not 0 <= length <= 65536:      # formulário pequeno por natureza
                    return self._deny(400, "corpo grande demais")
                try:
                    form = parse_qs(self.rfile.read(length).decode("utf-8",
                                                                   errors="strict"))
                except UnicodeDecodeError:
                    return self._deny(400, "corpo não é UTF-8")
                rid = (form.get("id") or [""])[0]
                token = (form.get("token") or [""])[0]
                action = (form.get("action") or [""])[0]
                try:
                    status = panel.queue.decide(rid, token, approve=(action == "aprovar"))
                except ApprovalError as exc:
                    return self._deny(409, f"recusado: {exc}")
                # PRG: F5 depois de decidir NÃO reenvia o POST (que daria 409)
                self.send_response(303)
                self.send_header("Location", f"{base}/?decidido={status}")
                for k, v in _HEADERS_SEGURANCA.items():
                    self.send_header(k, v)
                self.end_headers()

        self._server = ThreadingHTTPServer((host, port), Handler)
        self.port = self._server.server_port
        self.url = f"http://127.0.0.1:{self.port}/p/{self.secret}/"
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
