"""NH-017a/b — `approvals sugerir` (proposta, nunca aplicação) e
`approvals testar` (dry-run de veredito, nada entra na fila)."""
from __future__ import annotations

import hashlib
import json

from nomos import cli
from nomos.kernel import sugestor_aprovacoes as sug
from nomos.kernel.approvals import ApprovalQueue
from nomos.kernel.audit import AuditLog


def _fila_com_historico(home, decisoes):
    """Gera eventos REAIS de fila (request+decide) na trilha."""
    audit = AuditLog(home / "logs" / "audit.jsonl")
    q = ApprovalQueue(home / "approvals", audit=audit)
    for categoria, alvo, aprovar in decisoes:
        rid, token = q.request(categoria, alvo, "teste")
        q.decide(rid, token, aprovar)
    return audit


def test_sugerir_minera_eventos_reais_da_fila(tmp_path):
    audit = _fila_com_historico(tmp_path, [("A2_NET_EGRESS", "api.x", True)] * 6)
    stats = sug.minerar(tmp_path / "logs" / "audit.jsonl")
    (st,) = [s for s in stats if s.alvo == "api.x"]
    assert st.aprovadas == 6 and st.negadas == 0
    (s,) = sug.sugerir(stats)
    assert s.acao == "ALLOW_POR_ALVO"
    assert audit is not None


def test_sugerir_nunca_propoe_a5_a6(tmp_path):
    _fila_com_historico(tmp_path, [("A5_CODE_EXEC", "x", True)] * 10
                        + [("A6_DESTRUCTIVE", "y", True)] * 10)
    stats = sug.minerar(tmp_path / "logs" / "audit.jsonl")
    assert sug.sugerir(stats) == [], "A5/A6 fora do espaço de sugestão, sempre"


def test_sugerir_exige_historico_limpo(tmp_path):
    _fila_com_historico(tmp_path, [("A2_NET_EGRESS", "api.x", True)] * 6
                        + [("A2_NET_EGRESS", "api.x", False)])
    (s,) = sug.sugerir(sug.minerar(tmp_path / "logs" / "audit.jsonl"))
    assert s.acao == "MANTER", "uma negação ⇒ nunca ALLOW_POR_ALVO"


def test_sugerir_negacoes_dominantes_viram_revisao(tmp_path):
    _fila_com_historico(tmp_path, [("A1_WRITE_LOCAL", "z", False)] * 4
                        + [("A1_WRITE_LOCAL", "z", True)])
    (s,) = sug.sugerir(sug.minerar(tmp_path / "logs" / "audit.jsonl"))
    assert s.acao == "REVISAR_NEGACOES"


def test_sugerir_tolera_linha_invalida_no_audit(tmp_path):
    _fila_com_historico(tmp_path, [("A2_NET_EGRESS", "api.x", True)] * 5)
    with (tmp_path / "logs" / "audit.jsonl").open("a") as fh:
        fh.write("{linha rasgada\n")
    stats = sug.minerar(tmp_path / "logs" / "audit.jsonl")
    assert stats, "linha lixo não derruba a mineração"


def test_proposta_0600_com_ancora_e_nao_toca_policy(tmp_path, monkeypatch):
    import stat
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    (tmp_path / "policy.json").write_text('{"rules": {"A2_NET_EGRESS": "ALLOW"}}')
    sha_antes = hashlib.sha256((tmp_path / "policy.json").read_bytes()).hexdigest()
    _fila_com_historico(tmp_path, [("A2_NET_EGRESS", "api.x", True)] * 6)
    assert cli.main(["approvals", "sugerir"]) == cli.EXIT_OK
    proposta = next((tmp_path / "approvals" / "propostas").glob("*.json"))
    assert stat.S_IMODE(proposta.stat().st_mode) == 0o600
    corpo = json.loads(proposta.read_text())
    assert corpo["ancora_da_trilha"]["entradas"] > 0
    assert "IMPOSSÍVEL" in corpo["aplicacao_automatica"]
    sha_depois = hashlib.sha256((tmp_path / "policy.json").read_bytes()).hexdigest()
    assert sha_antes == sha_depois, "sugerir JAMAIS toca policy.json"
    eventos = [json.loads(x).get("event") for x in
               (tmp_path / "logs" / "audit.jsonl").read_text().splitlines()]
    assert "approvals.sugestao.gerada" in eventos


def test_testar_dry_run_nao_cria_solicitacao_nem_executa(tmp_path, monkeypatch,
                                                         capsys):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    rc = cli.main(["approvals", "testar", "A1_WRITE_LOCAL", "/tmp/x"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "REQUIRE_APPROVAL" in out
    q = ApprovalQueue(tmp_path / "approvals")
    assert q.pending() == [], "dry-run não pode enfileirar nada"


def test_testar_exit_codes_por_efeito(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    assert cli.main(["approvals", "testar", "A0_READ_LOCAL", "x"]) == cli.EXIT_OK
    assert cli.main(["approvals", "testar", "A6_DESTRUCTIVE", "x"]) == \
        cli.EXIT_DENIED


def test_testar_categoria_desconhecida_deny_fail_closed(tmp_path, monkeypatch,
                                                        capsys):
    monkeypatch.setenv("NOMOS_HOME", str(tmp_path))
    rc = cli.main(["approvals", "testar", "A9_INVENTADA", "x"])
    assert rc == cli.EXIT_DENIED
    assert "categorias válidas" in capsys.readouterr().err
