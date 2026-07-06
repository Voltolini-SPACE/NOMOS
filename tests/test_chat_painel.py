"""MC38 — chat local no painel (estilo ChatGPT), 2ª porta de escrita.

Contratos:
- painel puro (render_html sem chat) e chat desligado ⇒ SEM <form> (read-only);
- servidor com chat ligado ⇒ aba chat traz composer + token CSRF;
- token errado ⇒ 403; mensagem vazia ⇒ 400;
- envio válido SEM motor local ⇒ fail-closed: grava a fala do usuário + uma
  NOTA honesta (nunca inventa resposta) e audita; PRG para a conversa;
- o conteúdo exibido é redigido (padrões de segredo não vazam);
- chat desligado ⇒ POST em chat/enviar responde 405.
"""
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import DashboardServer, dados_dashboard, render_html
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    # nenhum motor local pronto ⇒ o chat deve cair no fail-closed honesto
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _ctx(home):
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    return {"home": home, "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl"),
            "skills": home / "skills"}


def _post(url, path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url.rstrip("/") + path, data=body)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310 loopback
            return r.status, r.geturl(), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode()


# ------------------------------------------------------ render-level
def test_render_puro_tem_aba_chat_read_only(nomos_home):
    corpo = render_html(dados_dashboard(_ctx(nomos_home)))
    assert 'data-aba="chat"' in corpo
    assert 'id="chat"' in corpo and 'id="conversas"' in corpo
    assert "<form" not in corpo   # sem servidor/chat: nada de composer


# ------------------------------------------------------ servidor (HTTP real)
def test_chat_ligado_mostra_composer_e_token(nomos_home):
    srv = DashboardServer(_ctx(nomos_home), chat_habilitado=True)
    url = srv.start()
    try:
        with urllib.request.urlopen(url, timeout=10) as r:  # nosec B310
            c = r.read().decode()
        assert 'action="/d/' in c and "/chat/enviar" in c   # composer
        assert re.search(r'name="token" value="[^"]+"', c)  # token CSRF
    finally:
        srv.stop()


def test_chat_token_errado_403_e_vazia_400(nomos_home):
    srv = DashboardServer(_ctx(nomos_home), chat_habilitado=True)
    url = srv.start()
    try:
        with urllib.request.urlopen(url, timeout=10) as r:  # nosec B310
            tok = re.search(r'name="token" value="([^"]+)"',
                            r.read().decode()).group(1)
        st, _, _ = _post(url, "/chat/enviar",
                         {"token": "errado", "conversa": "nova", "mensagem": "oi"})
        assert st == 403
        st, _, _ = _post(url, "/chat/enviar",
                         {"token": tok, "conversa": "nova", "mensagem": "   "})
        assert st == 400
    finally:
        srv.stop()


def test_chat_sem_motor_e_fail_closed_e_honesto(nomos_home):
    ctx = _ctx(nomos_home)
    srv = DashboardServer(ctx, chat_habilitado=True)
    url = srv.start()
    try:
        with urllib.request.urlopen(url, timeout=10) as r:  # nosec B310
            tok = re.search(r'name="token" value="([^"]+)"',
                            r.read().decode()).group(1)
        st, loc, _ = _post(url, "/chat/enviar",
                           {"token": tok, "conversa": "nova",
                            "mensagem": "olá agente"})
        # urllib segue o 303 (PRG) → chega em 200 na conversa
        assert st == 200 and "conversa=" in (loc or "")
        cid = re.search(r"conversa=(\d+)", loc).group(1)
        with urllib.request.urlopen(url.rstrip("/") + f"/?conversa={cid}",
                                    timeout=10) as r:  # nosec B310
            conv = r.read().decode()
        assert "olá agente" in conv                       # a fala do usuário
        assert "sem motor local pronto" in conv           # nota honesta
        assert "agente" in conv                            # rótulo da nota
        trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
        assert "chat.painel.enviou" in trilha
        assert "chat.painel.sem_motor" in trilha
        assert "chat.painel.respondeu" not in trilha       # NÃO fingiu resposta
    finally:
        srv.stop()


def test_chat_desligado_recusa_post_405(nomos_home):
    srv = DashboardServer(_ctx(nomos_home), chat_habilitado=False)
    url = srv.start()
    try:
        st, _, _ = _post(url, "/chat/enviar",
                         {"token": "x", "conversa": "nova", "mensagem": "oi"})
        assert st == 405
        with urllib.request.urlopen(url, timeout=10) as r:  # nosec B310
            assert "<form" not in r.read().decode()   # sem composer
    finally:
        srv.stop()


def test_chat_redige_segredo_na_exibicao(nomos_home):
    # grava um turno com padrão de segredo direto no store e confirma que o
    # painel o exibe REDIGIDO (redact_text), nunca em claro
    ctx = _ctx(nomos_home)
    from nomos.conversations.store import ConversationStore
    cs = ConversationStore(nomos_home / "conversas.db")
    cid = cs.nova_conversa(motor="teste")
    cs.add_turno(cid, "user", "minha chave é sk-ABCDEF0123456789 ok?")
    cs.close()
    srv = DashboardServer(ctx, chat_habilitado=True)
    url = srv.start()
    try:
        with urllib.request.urlopen(url.rstrip("/") + f"/?conversa={cid}",
                                    timeout=10) as r:  # nosec B310
            conv = r.read().decode()
        assert "sk-ABCDEF0123456789" not in conv    # nunca em claro
        assert "[REDIGIDO]" in conv                  # redigido
    finally:
        srv.stop()
