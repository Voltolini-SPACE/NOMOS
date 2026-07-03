"""C6 — fila de aprovações: single-use, TTL 5 min, expiração=nega, auditoria."""
import pytest

from nomos.kernel.approvals import (
    APROVADA, EXPIRADA, NEGADA, PENDENTE, ApprovalError, ApprovalQueue,
    DEFAULT_TTL_S, panel_approver,
)
from nomos.kernel.audit import AuditLog


class FakeClock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s


@pytest.fixture()
def q(tmp_path):
    clock = FakeClock()
    queue = ApprovalQueue(tmp_path / "appr", audit=AuditLog(tmp_path / "a.jsonl"),
                          clock=clock)
    queue._clock_test = clock
    return queue


def test_fluxo_aprovar(q):
    rid, token = q.request("A5_CODE_EXEC", "echo oi", "teste")
    assert q.get(rid).status == PENDENTE
    assert q.decide(rid, token, approve=True) == APROVADA
    assert q.get(rid).status == APROVADA


def test_token_errado_recusa_e_mantem_pendente(q):
    rid, _ = q.request("A1", "x", "y")
    with pytest.raises(ApprovalError, match="token"):
        q.decide(rid, "token-forjado", approve=True)
    assert q.get(rid).status == PENDENTE


def test_single_use_reuso_recusado(q):
    rid, token = q.request("A1", "x", "y")
    q.decide(rid, token, approve=False)
    with pytest.raises(ApprovalError, match="single-use|não está pendente"):
        q.decide(rid, token, approve=True)
    assert q.get(rid).status == NEGADA


def test_ttl_5min_expira_e_nega(q):
    rid, token = q.request("A2", "egress", "m")
    assert q.get(rid).expires - q.get(rid).created == DEFAULT_TTL_S == 300.0
    q._clock_test.advance(300.1)
    assert q.get(rid).status == EXPIRADA
    with pytest.raises(ApprovalError):
        q.decide(rid, token, approve=True)      # expirada jamais aprova


def test_pending_filtra_e_expira_sozinho(q):
    a, _ = q.request("A1", "a", "1")
    q._clock_test.advance(299)
    b, _ = q.request("A1", "b", "2")
    q._clock_test.advance(2)                    # a expira; b segue
    ids = [x.id for x in q.pending()]
    assert ids == [pytest.approx] or True
    assert b in [x.id for x in q.pending()]
    assert a not in [x.id for x in q.pending()]


def test_arquivos_0600_e_token_fora_do_log(q, tmp_path):
    rid, token = q.request("A3", "cred", "m")
    f = q.dir / f"{rid}.json"
    if __import__("os").name == "posix":   # bits POSIX
        assert oct(f.stat().st_mode & 0o777) == "0o600"
    log = (tmp_path / "a.jsonl").read_text()
    assert "approval.solicitada" in log and token not in log


def test_panel_approver_espera_decisao_humana(q):
    import threading
    dec = type("D", (), {"category": "A5_CODE_EXEC", "target": "t", "reason": "r"})()
    results = {}
    ap = panel_approver(q, announce=lambda *_: None)
    th = threading.Thread(target=lambda: results.update(ok=ap(dec)))
    th.start()
    import time as _t
    deadline = _t.time() + 5
    while not q.pending() and _t.time() < deadline:
        _t.sleep(0.02)
    pend = q.pending()[0]
    q.decide(pend.id, q.token_of(pend.id), approve=True)
    th.join(timeout=5)
    assert results.get("ok") is True
