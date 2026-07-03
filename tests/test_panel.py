"""C6 — painel local: HTTP REAL em 127.0.0.1, caminho secreto, decide via POST."""
import urllib.error
import urllib.parse
import urllib.request

import pytest

from nomos.interface.panel import PanelServer
from nomos.kernel.approvals import APROVADA, PENDENTE, ApprovalQueue


@pytest.fixture()
def env(tmp_path):
    q = ApprovalQueue(tmp_path / "appr")
    srv = PanelServer(q)
    url = srv.start()
    yield q, srv, url
    srv.stop()


def _get(url):
    with urllib.request.urlopen(url, timeout=3) as r:
        return r.status, r.read().decode()


def _post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body)
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, r.read().decode()


def test_bind_apenas_loopback(tmp_path):
    with pytest.raises(ValueError):
        PanelServer(ApprovalQueue(tmp_path / "a"), host="0.0.0.0")


def test_sem_segredo_404(env):
    q, srv, url = env
    base = url.split("/p/")[0]
    with pytest.raises(urllib.error.HTTPError) as ei:
        _get(base + "/")
    assert ei.value.code == 404
    with pytest.raises(urllib.error.HTTPError):
        _get(base + "/p/segredo-errado/")


def test_lista_pendentes_no_html(env):
    q, srv, url = env
    q.request("A5_CODE_EXEC", "python payload.py", "instalar dependência")
    status, html = _get(url)
    assert status == 200
    assert "A5_CODE_EXEC" in html and "python payload.py" in html
    assert "APROVAR" in html and "NEGAR" in html


def test_aprovar_via_post_reflete_na_fila(env):
    q, srv, url = env
    rid, _ = q.request("A2_NET_EGRESS", "api.exemplo.com", "sincronizar")
    token = q.token_of(rid)
    status, html = _post(url + "decide", {"id": rid, "token": token, "action": "aprovar"})
    assert status == 200 and "aprovada" in html
    assert q.get(rid).status == APROVADA


def test_post_token_errado_409_e_continua_pendente(env):
    q, srv, url = env
    rid, _ = q.request("A1_WRITE_LOCAL", "/tmp/x", "m")
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(url + "decide", {"id": rid, "token": "forjado", "action": "aprovar"})
    assert ei.value.code == 409
    assert q.get(rid).status == PENDENTE


def test_post_reuso_409(env):
    q, srv, url = env
    rid, _ = q.request("A1_WRITE_LOCAL", "/tmp/x", "m")
    token = q.token_of(rid)
    _post(url + "decide", {"id": rid, "token": token, "action": "negar"})
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(url + "decide", {"id": rid, "token": token, "action": "aprovar"})
    assert ei.value.code == 409
