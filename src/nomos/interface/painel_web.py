"""NOMOS interface.painel_web — o NOMOS inteiro numa página, SÓ para ler.

Mesmos princípios do painel de aprovações (R4/C6):
- escuta EXCLUSIVAMENTE em 127.0.0.1 (qualquer outro bind é recusado);
- URL com segmento secreto aleatório — sem ele, 404 para tudo;
- SOMENTE leitura: nenhum POST, nenhuma mutação — mudar as coisas continua
  no terminal e no painel de aprovações (com gate);
- HTML autossuficiente: zero assets externos, zero JavaScript de terceiros;
- mostra metadados da auditoria (evento/hora) — nunca conteúdo sensível
  (a própria auditoria já redige; aqui nem o alvo completo aparece).
"""
from __future__ import annotations

import html
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_PAGE = """<!doctype html><html lang="pt-br"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{meta_refresh}
<title>NOMOS — painel local</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;line-height:1.45}}
 h1{{font-size:1.4rem}} h2{{font-size:1.05rem;margin-top:1.6rem}}
 .card{{border:1px solid #ccc;border-radius:8px;padding:.8rem 1rem;margin:.6rem 0}}
 .ok{{border-left:6px solid #2e7d32}} .warn{{border-left:6px solid #f9a825}}
 .err{{border-left:6px solid #c62828}} small{{color:#666}}
 code{{background:#f4f4f4;padding:.1rem .3rem;border-radius:4px}}
 table{{border-collapse:collapse;width:100%}} td,th{{padding:.25rem .5rem;text-align:left;border-bottom:1px solid #eee}}
</style>
<h1>NOMOS — painel local 🔒</h1>
<p><small>somente leitura · somente 127.0.0.1 · recarregue para atualizar ·
para agir, use o terminal (as aprovações continuam lá)</small></p>
{body}
</html>"""


def dados_dashboard(ctx) -> dict:
    """Coleta tudo que o painel mostra. Só leitura; nada muda de estado."""
    from nomos import __version__
    from nomos.cognition import engine_catalog as cat_mod
    from nomos.ext import skill_status as st
    from nomos.kernel import localidade
    from nomos.simple import doutor as doutor_mod
    from nomos.simple import rotinas as rot

    home = Path(ctx["home"])
    itens = doutor_mod.diagnostico_v011(home, ctx)
    cat = cat_mod.construir(home)
    modalidades = {m: [x.id for x in cat.prontos(m)]
                   for m in cat_mod.MODALIDADES_V011}
    eventos = []
    trilha = home / "logs" / "audit.jsonl"
    if trilha.exists():
        for linha in trilha.read_text().splitlines()[-12:]:
            try:
                reg = json.loads(linha)
                eventos.append({"ts": reg.get("ts"), "evento": reg.get("event")})
            except Exception:
                continue
    # Evidências de missões (MC29): pacotes auditáveis em ~/.nomos/evidencias
    evidencias = []
    dir_ev = home / "evidencias"
    if dir_ev.exists():
        from nomos.kernel import evidencia as ev_mod
        for pac in sorted(dir_ev.glob("EVIDENCIA_*"))[-8:]:
            integro, _ = ev_mod.verificar_pacote(pac)
            evidencias.append({"nome": pac.name, "integro": integro})

    # Motores: catálogo completo com custo/privacidade/prontidão (MC30)
    motores_tab = [{
        "id": m.id, "rotulo": m.rotulo, "local": bool(m.local),
        "custo": m.custo, "qualidade": m.qualidade, "pronto": bool(m.pronto),
    } for m in cat.motores]

    # Auditoria: verificação REAL da cadeia de hash (não só os últimos eventos)
    try:
        cadeia_ok, cadeia_n = ctx["audit"].verify()
    except Exception:
        cadeia_ok, cadeia_n = False, 0

    # Capacidades (MC30-A4): o catálogo completo, com risco visível
    from nomos.ext import skill_catalogo as scat
    try:
        capacidades = scat.capacidades(home, home / "skills")
    except Exception:
        capacidades = []   # catálogo nunca derruba o painel

    # Política viva (MC29): o painel mostra o contrato, não uma cópia dele
    from nomos.council import forbidden_flags as ff
    from nomos.council import local_harness as lh
    from nomos.kernel.policy import DEFAULT_RULES
    politica = {
        "regras": dict(DEFAULT_RULES),
        "execucao_real_council": bool(lh.REAL_LOCAL_ENGINE_EXECUTION_ENABLED),
        "flags_proibidas": len(ff.FORBIDDEN_FLAGS),
    }

    return {
        "versao": __version__,
        "so_local": localidade.esta_ligado(home),
        "status_geral": doutor_mod.status_geral(itens),
        "proximo_passo": doutor_mod.proximo_passo(itens),
        "checkup": itens,
        "modalidades": modalidades,
        "skills": st.status_todas(home, home / "skills"),
        "rotinas": rot.listar(home),
        "eventos": list(reversed(eventos)),
        "evidencias": evidencias,
        "politica": politica,
        "capacidades": capacidades,
        "motores": motores_tab,
        "auditoria": {"cadeia_integra": cadeia_ok, "eventos_total": cadeia_n},
    }


def render_html(d: dict, refresh: int | None = None) -> str:
    e = html.escape
    meta_refresh = (f'\n<meta http-equiv="refresh" content="{int(refresh)}">'
                    if refresh else "")
    classe = {"PRONTO": "ok", "PARCIAL": "warn", "BLOQUEADO": "err"}[d["status_geral"]]
    corpo = [f'<div class="card {classe}"><b>STATUS GERAL: {e(d["status_geral"])}</b>'
             f' · NOMOS {e(d["versao"])} · '
             f'{"modo só-local LIGADO 🔒" if d["so_local"] else "motores externos plugados 🔌"}'
             f'<br>próximo passo: <code>{e(d["proximo_passo"])}</code></div>']

    corpo.append("<h2>Check-up</h2>")
    for it in d["checkup"]:
        marca = "✅" if it["ok"] else ("❌" if it.get("bloqueante") else "⚠️")
        det = f' <small>{e(it["detalhe"])}</small>' if it.get("detalhe") else ""
        corpo.append(f'<div class="card">{marca} {e(it["titulo"])}{det}</div>')

    corpo.append('<p><small>ver também: <a href="api/">dados em JSON</a> · '
                 '<a href="audit/">auditoria completa</a> · '
                 '<a href="roteador/">decisões do roteador</a></small></p>')

    corpo.append("<h2>Motores prontos por modalidade</h2><table>"
                 "<tr><th>modalidade</th><th>motores</th></tr>")
    for mod, ms in d["modalidades"].items():
        corpo.append(f"<tr><td>{e(mod)}</td>"
                     f"<td>{e(', '.join(ms)) if ms else '—'}</td></tr>")
    corpo.append("</table>")

    corpo.append("<h2>Motores (catálogo completo)</h2><table>"
                 "<tr><th>motor</th><th>onde</th><th>custo</th>"
                 "<th>qualidade</th><th>pronto</th></tr>")
    for m in d.get("motores", []):
        corpo.append(
            f"<tr><td>{e(m['rotulo'])}</td>"
            f"<td>{'🔒 local' if m['local'] else '☁ nuvem (opt-in)'}</td>"
            f"<td>{e(m['custo'])}</td><td>{e(m['qualidade'])}</td>"
            f"<td>{'✓' if m['pronto'] else '—'}</td></tr>")
    corpo.append("</table>")

    corpo.append("<h2>Skills</h2>")
    if not d["skills"]:
        corpo.append("<p>nenhuma instalada. <code>nomos skills</code></p>")
    for s in d["skills"]:
        corpo.append(f'<div class="card">{e(s["name"])}@{e(s["version"])} — '
                     f'{e(s["estado"])} · risco {e(s["risco"])}</div>')

    corpo.append("<h2>Rotinas</h2>")
    if not d["rotinas"]:
        corpo.append("<p>nenhuma rotina. <code>nomos rotinas</code></p>")
    for r in d["rotinas"]:
        marca = "✓" if r.get("ativa", True) else "·"
        corpo.append(f'<div class="card">[{marca}] {e(r["hora"])} — '
                     f'{e(r["nome"])} <small>({e(r["acao"])})</small></div>')

    corpo.append("<h2>Capacidades (catálogo)</h2>")
    if not d.get("capacidades"):
        corpo.append("<p>catálogo vazio. <code>nomos skills catalogo</code></p>")
    for c in d.get("capacidades", []):
        corpo.append(
            f'<div class="card">{e(c["nome"])} <small>[{e(c["status"])} · '
            f'risco {e(c["risco"])}]</small><br>{e(c["descricao"])}<br>'
            f'<small>entrada: {e(c["entrada"])} → {e(c["saida"])}</small></div>')

    corpo.append("<h2>Evidências de missões</h2>")
    if not d.get("evidencias"):
        corpo.append('<p>nenhum pacote ainda. '
                     '<code>nomos evidencia criar "título"</code></p>')
    for ev_i in d.get("evidencias", []):
        marca = "✅ íntegro" if ev_i["integro"] else "❌ NÃO confere"
        corpo.append(f'<div class="card">{e(ev_i["nome"])} — {marca} · '
                     f'<a href="ev/{e(ev_i["nome"])}/">abrir relatório</a></div>')

    pol = d.get("politica", {})
    if pol:
        corpo.append("<h2>Política de permissões (A0–A6)</h2>"
                     "<table><tr><th>categoria</th><th>default</th></tr>")
        for cat_nome, efeito in pol["regras"].items():
            corpo.append(f"<tr><td><code>{e(cat_nome)}</code></td>"
                         f"<td>{e(efeito)}</td></tr>")
        corpo.append("</table>")
        conselho = ("DESLIGADA (dry-run apenas)"
                    if not pol["execucao_real_council"] else "LIGADA")
        corpo.append(f'<div class="card ok">Conselho: execução real de motor '
                     f'<b>{e(conselho)}</b> · {pol["flags_proibidas"]} flags '
                     f'proibidas fail-closed · aprovação humana obrigatória '
                     f'para ações sensíveis</div>')

    aud = d.get("auditoria", {})
    cadeia = ("íntegra ✅" if aud.get("cadeia_integra")
              else "⚠️ verificar (nomos logs verify)")
    corpo.append(f"<h2>Últimos eventos da auditoria</h2>"
                 f"<p><small>cadeia de hash: {cadeia} · "
                 f"{aud.get('eventos_total', 0)} eventos no total</small></p>"
                 "<table><tr><th>quando (ts)</th><th>evento</th></tr>")
    for ev in d["eventos"]:
        corpo.append(f"<tr><td>{e(str(ev['ts']))}</td>"
                     f"<td><code>{e(str(ev['evento']))}</code></td></tr>")
    corpo.append("</table><p><small>a trilha completa (com cadeia de hash) "
                 "está em <code>~/.nomos/logs/audit.jsonl</code> — verifique "
                 "com <code>nomos logs verify</code></small></p>")
    return _PAGE.format(body="\n".join(corpo), meta_refresh=meta_refresh)


class DashboardServer:
    """Servidor do painel — leitura apenas, loopback apenas."""

    def __init__(self, ctx, host: str = "127.0.0.1", port: int = 0):
        if host != "127.0.0.1":
            raise ValueError("painel é LOCAL por projeto: bind permitido só em 127.0.0.1")
        self.ctx = ctx
        self.secret = secrets.token_urlsafe(16)
        painel = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _responder(self, code, texto, tipo="text/html"):
                data = texto.encode()
                self.send_response(code)
                self.send_header("Content-Type", f"{tipo}; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                caminho, _, query = self.path.partition("?")
                caminho = caminho.rstrip("/")
                base = f"/d/{painel.secret}"
                if caminho == base:
                    refresh = None
                    m = re.search(r"(?:^|&)refresh=(\d{1,4})(?:&|$)", query)
                    if m and 5 <= int(m.group(1)) <= 3600:
                        refresh = int(m.group(1))   # fora da faixa: ignorado
                    try:
                        corpo = render_html(dados_dashboard(painel.ctx),
                                            refresh=refresh)
                    except Exception as exc:   # painel nunca derruba nada
                        return self._responder(
                            500, f"painel indisponível: {type(exc).__name__}",
                            "text/plain")
                    return self._responder(200, corpo)
                if caminho == base + "/api":
                    try:
                        dados = dados_dashboard(painel.ctx)
                    except Exception as exc:
                        return self._responder(
                            500, f"api indisponível: {type(exc).__name__}",
                            "text/plain")
                    return self._responder(
                        200, json.dumps(dados, ensure_ascii=False, indent=2,
                                        default=str), "application/json")
                if caminho == base + "/audit":
                    return self._pagina_audit()
                if caminho == base + "/roteador":
                    return self._pagina_roteador()
                if caminho.startswith(base + "/ev/"):
                    return self._servir_evidencia(caminho[len(base) + 4:])
                return self._responder(404, "não encontrado", "text/plain")

            def _pagina_audit(self):
                """Auditoria completa: verificação de cadeia + últimos 100 eventos."""
                e = html.escape
                try:
                    ok, total = painel.ctx["audit"].verify()
                except Exception:
                    ok, total = False, 0
                linhas = [f"<h2>Auditoria — cadeia de hash "
                          f"{'íntegra ✅' if ok else '⚠️ verificar'} · "
                          f"{total} eventos</h2>",
                          "<table><tr><th>quando (ts)</th><th>evento</th></tr>"]
                trilha = Path(painel.ctx["home"]) / "logs" / "audit.jsonl"
                if trilha.exists():
                    for linha in trilha.read_text(encoding="utf-8",
                                                  errors="ignore").splitlines()[-100:][::-1]:
                        try:
                            reg = json.loads(linha)
                        except Exception:
                            continue
                        linhas.append(f"<tr><td>{e(str(reg.get('ts')))}</td>"
                                      f"<td><code>{e(str(reg.get('event')))}</code></td></tr>")
                linhas.append("</table><p><small>metadados apenas — conteúdo "
                              "nunca aparece; trilha completa em "
                              "<code>~/.nomos/logs/audit.jsonl</code></small></p>")
                self._responder(200, _PAGE.format(body="\n".join(linhas),
                                                  meta_refresh=""))

            def _pagina_roteador(self):
                """Decisões do roteador, explicadas, por modalidade — só leitura."""
                e = html.escape
                try:
                    from nomos.cognition import engine_catalog as cat_mod
                    from nomos.cognition import engine_router as er
                    home = Path(painel.ctx["home"])
                    linhas = ["<h2>Roteador — decisão explicada por modalidade</h2>"]
                    for mod in cat_mod.MODALIDADES_V011:
                        rel = er.relatorio_decisao(
                            er.Tarefa(tipo=mod, modalidade=mod), home=home)
                        dec = rel["decisao"]
                        escolhido = dec["selected_engine"] or "— (nenhum pronto)"
                        linhas.append(
                            f'<div class="card"><b>{e(mod)}</b> → '
                            f'<code>{e(escolhido)}</code><br>'
                            f'<small>{e(dec["reason"])}</small><br>'
                            f'<small>regras: '
                            f'{e(" · ".join(rel["trace"]["regras_aplicadas"]))}'
                            f'</small></div>')
                    linhas.append("<p><small>dados, não ação: executar continua "
                                  "passando pelo gate de aprovação</small></p>")
                except Exception as exc:
                    return self._responder(
                        500, f"roteador indisponível: {type(exc).__name__}",
                        "text/plain")
                self._responder(200, _PAGE.format(body="\n".join(linhas),
                                                  meta_refresh=""))

            def _servir_evidencia(self, nome: str):
                """RELATORIO.md de um pacote — leitura, nome estrito, sem traversal."""
                if not re.fullmatch(r"EVIDENCIA_[A-Za-z0-9_-]+", nome):
                    return self._responder(404, "não encontrado", "text/plain")
                raiz = (Path(painel.ctx["home"]) / "evidencias").resolve()
                alvo = (raiz / nome / "RELATORIO.md").resolve()
                # cinto e suspensório: mesmo com o regex, o alvo TEM de estar na raiz
                if raiz not in alvo.parents or not alvo.is_file():
                    return self._responder(404, "não encontrado", "text/plain")
                self._responder(200, alvo.read_text(encoding="utf-8"),
                                "text/plain")

            def do_POST(self):
                # somente leitura — POST não existe aqui, por projeto
                self._responder(405, "painel é somente leitura", "text/plain")

        self._server = ThreadingHTTPServer((host, port), Handler)
        self.port = self._server.server_port
        self.url = f"http://127.0.0.1:{self.port}/d/{self.secret}/"
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
