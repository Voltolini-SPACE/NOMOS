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
 :root{{--bg:#0A0F0D;--surface:#111814;--line:#1d2a22;--neon:#5AF78E;
   --dim:#2BD968;--txt:#E8FFE8;--fraco:#7c9a84;--rosa:#FF5FA2;--ciano:#56E1E9;
   --amarelo:#F2C14E;--vermelho:#FF5C57;--glow:0 0 8px rgba(90,247,142,.45)}}
 *{{box-sizing:border-box}}
 body{{font-family:'JetBrains Mono','IBM Plex Mono','SF Mono',Menlo,Consolas,monospace;
   background:var(--bg);color:var(--txt);margin:0;line-height:1.5;font-size:14px}}
 .wrap{{max-width:960px;margin:0 auto;padding:0 1.1rem}}
 header{{border-bottom:1px solid var(--line);background:linear-gradient(180deg,#0c1310,transparent)}}
 h1{{font-size:1.25rem;margin:1.3rem 0 .2rem;color:var(--neon);text-shadow:var(--glow)}}
 h1 .lock{{color:var(--dim)}}
 .sub{{color:var(--fraco);font-size:.78rem;margin:0 0 1rem}}
 h2{{font-size:.82rem;text-transform:uppercase;letter-spacing:.14em;
   color:var(--dim);margin:2.2rem 0 .7rem;border-left:3px solid var(--neon);
   padding-left:.6rem}}
 h2::before{{content:"// ";color:var(--line)}}
 .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
   gap:1px;background:var(--line);border:1px solid var(--line);border-radius:8px;
   overflow:hidden;margin:1rem 0 .4rem}}
 .kpi{{background:var(--surface);padding:.7rem .8rem}}
 .kpi b{{display:block;color:var(--neon);font-size:1.15rem;text-shadow:var(--glow)}}
 .kpi span{{color:var(--fraco);font-size:.7rem}}
 nav{{position:sticky;top:0;z-index:9;background:rgba(10,15,13,.94);
   backdrop-filter:blur(6px);border-bottom:1px solid var(--line);
   padding:.5rem 0;margin-bottom:.4rem}}
 nav a{{color:var(--fraco);text-decoration:none;font-size:.74rem;margin-right:.9rem;
   white-space:nowrap}}
 nav a:hover{{color:var(--neon)}}
 nav .badge{{color:var(--bg);background:var(--neon);border-radius:10px;
   padding:0 .4rem;font-size:.66rem;margin-left:.2rem}}
 .card{{background:var(--surface);border:1px solid var(--line);border-radius:8px;
   padding:.75rem .95rem;margin:.55rem 0}}
 .card.ok{{border-left:4px solid var(--neon)}}
 .card.warn{{border-left:4px solid var(--amarelo)}}
 .card.err{{border-left:4px solid var(--vermelho)}}
 small{{color:var(--fraco)}}
 b{{color:var(--txt)}}
 a{{color:var(--ciano)}}
 code,.k{{background:#0c1410;color:var(--neon);padding:.08rem .35rem;
   border-radius:4px;border:1px solid var(--line)}}
 table{{border-collapse:collapse;width:100%;font-size:.82rem}}
 td,th{{padding:.32rem .55rem;text-align:left;border-bottom:1px solid var(--line)}}
 th{{color:var(--fraco);font-weight:normal;text-transform:uppercase;
   font-size:.68rem;letter-spacing:.1em}}
 .pill{{display:inline-block;border:1px solid var(--line);border-radius:20px;
   padding:.05rem .55rem;font-size:.7rem;color:var(--fraco);margin-right:.3rem}}
 .pill.local{{color:var(--neon);border-color:var(--dim)}}
 .pill.nuvem{{color:var(--amarelo);border-color:#4a3f1e}}
 footer{{border-top:1px solid var(--line);margin-top:2.5rem;padding:1rem 0;
   color:var(--fraco);font-size:.72rem}}
</style>
<header><div class="wrap">
<h1>NOMOS <span class="lock">— painel local 🔒</span></h1>
<p class="sub">somente leitura · somente 127.0.0.1 · recarregue para atualizar ·
para agir, use o terminal (as aprovações continuam lá)</p>
</div></header>
<main class="wrap">
{body}
<footer>NOMOS · local por lei · este painel nunca executa nada — só mostra.
Ações passam pelo gate no terminal.</footer>
</main>
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

    # Memória 2.0 (MC31/B5): fila de candidatas visível — aprovar é no terminal
    try:
        from nomos.cognition.memory import Memory
        _mem = Memory(home / "memory.db")
        memoria = {"total": _mem.count(), "candidatas": len(_mem.candidatas())}
    except Exception:
        memoria = {"total": 0, "candidatas": 0}

    # Conversas (MC33): histórico read-only — títulos/metadados, nunca o conteúdo
    conversas = []
    try:
        from nomos.conversations.store import ConversationStore
        from nomos.kernel.audit import redact_text
        _cs = ConversationStore(home / "conversas.db")
        for c in _cs.listar(limite=8):
            # título é metadado (1ªs palavras) — redigido contra padrões de
            # segredo; o CORPO das mensagens nunca é lido nem exibido aqui
            conversas.append({"id": c.id,
                              "titulo": redact_text(c.titulo or "(sem título)"),
                              "motor": c.motor, "fixada": bool(c.fixada),
                              "turnos": c.n_turnos})
        _cs.close()
    except Exception:
        conversas = []

    # Agentes (MC33): oficiais + próprios, com risco máximo e ferramentas
    agentes = []
    try:
        from nomos.agents.registry import AgentRegistry
        for a in AgentRegistry(home).listar():
            agentes.append({"nome": a.nome, "risco_max": a.risco_max,
                            "ferramentas": list(a.ferramentas),
                            "ativo": AgentRegistry(home).ativo(a.nome)})
    except Exception:
        agentes = []

    # MCP (MC33): o NOMOS como servidor (tools read-only) + servers confiáveis
    try:
        from nomos.interface import mcp_catalogo as _mcat
        from nomos.interface import mcp_server as _msrv
        mcp = {"server_tools": [{"nome": t["name"],
                                 "descricao": t["description"]}
                                for t in _msrv.TOOLS],
               "confiaveis": _mcat.listar(home)["confiaveis"],
               "revogadas": _mcat.listar(home)["revogadas"]}
    except Exception:
        mcp = {"server_tools": [], "confiaveis": [], "revogadas": 0}

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
        "memoria": memoria,
        "conversas": conversas,
        "agentes": agentes,
        "mcp": mcp,
    }


def render_html(d: dict, refresh: int | None = None) -> str:
    e = html.escape
    meta_refresh = (f'\n<meta http-equiv="refresh" content="{int(refresh)}">'
                    if refresh else "")
    classe = {"PRONTO": "ok", "PARCIAL": "warn", "BLOQUEADO": "err"}[d["status_geral"]]

    # --- KPIs de saúde (leitura rápida antes de rolar) ---
    memo = d.get("memoria", {})
    aud = d.get("auditoria", {})
    n_prontos = sum(len(v) for v in d["modalidades"].values())
    ev_ok = sum(1 for x in d.get("evidencias", []) if x.get("integro"))
    cadeia_kpi = "íntegra" if aud.get("cadeia_integra") else "verificar"
    kpis = [
        (e(d["status_geral"]), "status geral"),
        ("🔒 local" if d["so_local"] else "🔌 nuvem", "cadeado"),
        (str(n_prontos), "motores prontos"),
        (str(memo.get("total", 0)), "memórias"),
        (str(memo.get("candidatas", 0)), "a revisar"),
        (str(ev_ok), "evidências ok"),
        (cadeia_kpi, "cadeia auditoria"),
    ]
    corpo = ['<div class="kpis">']
    corpo += [f'<div class="kpi"><b>{v}</b><span>{lbl}</span></div>'
              for v, lbl in kpis]
    corpo.append("</div>")

    # --- navegação por âncoras, com badges de atenção ---
    badge_rev = (f' <span class="badge">{memo.get("candidatas", 0)}</span>'
                 if memo.get("candidatas") else "")
    itens_nav = [
        ("#checkup", "check-up", ""),
        ("#motores", "motores", ""),
        ("#skills", "skills", ""),
        ("#agentes", "agentes", ""),
        ("#mcp", "mcp", ""),
        ("#conversas", "conversas", ""),
        ("#memoria", "memória", badge_rev),
        ("#evidencias", "evidências", ""),
        ("#politica", "política", ""),
        ("#auditoria", "auditoria", ""),
    ]
    corpo.append('<nav aria-label="seções do painel">' + "".join(
        f'<a href="{href}">{txt}{bd}</a>' for href, txt, bd in itens_nav) + "</nav>")

    corpo.append(
        f'<div class="card {classe}"><b>STATUS GERAL: {e(d["status_geral"])}</b>'
        f' · NOMOS {e(d["versao"])} · '
        f'{"modo só-local LIGADO 🔒" if d["so_local"] else "motores externos plugados 🔌"}'
        f'<br>próximo passo: <code>{e(d["proximo_passo"])}</code></div>')

    corpo.append('<h2 id="checkup">Check-up</h2>')
    for it in d["checkup"]:
        marca = "✅" if it["ok"] else ("❌" if it.get("bloqueante") else "⚠️")
        det = f' <small>{e(it["detalhe"])}</small>' if it.get("detalhe") else ""
        corpo.append(f'<div class="card">{marca} {e(it["titulo"])}{det}</div>')

    corpo.append('<p><small>ver também: <a href="api/">dados em JSON</a> · '
                 '<a href="audit/">auditoria completa</a> · '
                 '<a href="roteador/">decisões do roteador</a></small></p>')

    corpo.append('<h2 id="motores">Motores prontos por modalidade</h2><table>'
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

    corpo.append('<h2 id="skills">Skills</h2>')
    if not d["skills"]:
        corpo.append("<p>nenhuma instalada. <code>nomos skills</code></p>")
    for s in d["skills"]:
        corpo.append(f'<div class="card">{e(s["name"])}@{e(s["version"])} — '
                     f'{e(s["estado"])} · risco {e(s["risco"])}</div>')

    corpo.append('<h2 id="agentes">Agentes</h2>')
    if not d.get("agentes"):
        corpo.append("<p>nenhum agente. <code>nomos agentes</code></p>")
    for a in d.get("agentes", []):
        estado = "ativo ✓" if a.get("ativo") else "inativo"
        ferr = ", ".join(a.get("ferramentas", [])) or "—"
        corpo.append(f'<div class="card">{e(a["nome"])} '
                     f'<span class="pill">risco máx {e(a["risco_max"])}</span>'
                     f'<span class="pill">{estado}</span><br>'
                     f'<small>ferramentas: {e(ferr)}</small></div>')

    mcp = d.get("mcp", {})
    corpo.append('<h2 id="mcp">MCP — Model Context Protocol</h2>')
    corpo.append(f'<div class="card ok"><b>NOMOS como servidor</b> '
                 f'({len(mcp.get("server_tools", []))} tools somente leitura) — '
                 f'<code>nomos mcp servir</code><br><small>'
                 + " · ".join(e(t["nome"]) for t in mcp.get("server_tools", []))
                 + "</small></div>")
    conf = mcp.get("confiaveis", [])
    if conf:
        corpo.append("<div class=\"card\"><b>Servers confiáveis</b> "
                     f"({len(conf)} · {mcp.get('revogadas', 0)} revogado(s)):<br>"
                     + "<br>".join(f'<small>✓ {e(s["nome"])} '
                                   f'[{e(s.get("impressao", ""))}]</small>'
                                   for s in conf) + "</div>")
    else:
        corpo.append('<p>nenhum server MCP confiável. '
                     '<code>nomos mcp confiar &lt;manifesto&gt;</code></p>')

    corpo.append('<h2 id="conversas">Conversas</h2>')
    if not d.get("conversas"):
        corpo.append("<p>nenhuma conversa ainda. <code>nomos chat</code></p>")
    for c in d.get("conversas", []):
        pino = "📌 " if c.get("fixada") else ""
        corpo.append(f'<div class="card">{pino}<b>#{c["id"]}</b> '
                     f'{e(c["titulo"])} <small>· {c.get("turnos", 0)} turno(s)'
                     f'{" · " + e(c["motor"]) if c.get("motor") else ""}'
                     f'</small></div>')
    if d.get("conversas"):
        corpo.append('<p><small>só títulos e metadados — o conteúdo nunca '
                     'aparece no painel. Abra no terminal: <code>nomos '
                     'conversas</code></small></p>')

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

    memo = d.get("memoria", {})
    if memo:
        pend = memo.get("candidatas", 0)
        aviso = (f'⚠️ <b>{pend}</b> candidata(s) aguardando SUA revisão — '
                 f'<code>nomos memoria revisar</code>' if pend
                 else "fila de candidatas vazia ✓")
        corpo.append(f'<h2 id="memoria">Memória local</h2><div class="card">'
                     f'{memo.get("total", 0)} memórias guardadas · {aviso}'
                     f'<br><small>aprovar/descartar é sempre decisão sua, '
                     f'no terminal — o painel só mostra</small></div>')

    corpo.append('<h2 id="evidencias">Evidências de missões</h2>')
    if not d.get("evidencias"):
        corpo.append('<p>nenhum pacote ainda. '
                     '<code>nomos evidencia criar "título"</code></p>')
    for ev_i in d.get("evidencias", []):
        marca = "✅ íntegro" if ev_i["integro"] else "❌ NÃO confere"
        corpo.append(f'<div class="card">{e(ev_i["nome"])} — {marca} · '
                     f'<a href="ev/{e(ev_i["nome"])}/">abrir relatório</a></div>')

    pol = d.get("politica", {})
    if pol:
        corpo.append('<h2 id="politica">Política de permissões (A0–A6)</h2>'
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
    corpo.append(f'<h2 id="auditoria">Últimos eventos da auditoria</h2>'
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
