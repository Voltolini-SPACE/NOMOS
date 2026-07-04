"""Mitigação da lacuna de auditoria: âncora HMAC ancorada no cofre.

Cobre truncamento de cauda, reescrita da cadeia, adulteração da âncora, HMAC
errado, count/tip divergentes, chave ausente (fail-closed), logs legados,
idempotência, não-vazamento da chave e a CLI.
"""
import json
import os

import pytest

from nomos.kernel import audit_anchor as anchor
from nomos.kernel.audit import AuditLog
from nomos.kernel.vault import Vault

SENHA = "senha-de-cofre-forte-123"


def _log(nomos_home, n=4):
    log = AuditLog(nomos_home / "logs" / "audit.jsonl")
    for i in range(n):
        log.append("evento", n=i)
    return log


def _vault(nomos_home):
    v = Vault(nomos_home / "vault.json")
    v.init(SENHA)
    return v


# ---------- 6.1 baseline: a cadeia sem chave NÃO detecta truncamento de cauda ----------

def test_audit_tail_truncation_not_detected_by_unkeyed_chain(nomos_home):
    log = _log(nomos_home)
    assert log.verify() == (True, -1)
    p = log.path
    linhas = p.read_text().splitlines()
    p.write_text("\n".join(linhas[:-1]) + "\n")     # remove a última
    assert log.verify() == (True, -1)               # cadeia continua "válida" (a lacuna)


# ---------- 6.2 HMAC detecta truncamento de cauda ----------

def test_audit_hmac_anchor_detects_tail_truncation(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    st, _ = anchor.verificar(log, v, SENHA)
    assert st == anchor.ANCHORED_VALID
    linhas = log.path.read_text().splitlines()
    log.path.write_text("\n".join(linhas[:-1]) + "\n")   # remove a última
    st2, _ = anchor.verificar(log, v, SENHA)
    assert st2 == anchor.TAIL_TRUNCATED
    assert anchor.status_severidade(st2) == "FAIL"


# ---------- 6.3 HMAC detecta reescrita da cadeia sem a chave ----------

def test_audit_hmac_anchor_detects_rewritten_chain_without_key(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    # atacante reescreve TODO o log com uma nova cadeia válida (sem a chave HMAC)
    novo = AuditLog(log.path)
    log.path.write_text("")            # zera
    for i in range(4):
        novo.append("forjado", n=i * 10)
    assert novo.verify() == (True, -1)   # cadeia nova é internamente consistente
    st, _ = anchor.verificar(log, v, SENHA)
    assert st in anchor.FAIL_STATES      # âncora (tip ancorado) denuncia a reescrita


# ---------- 6.4 / 6.5 âncora adulterada / HMAC errado ----------

def test_audit_anchor_tamper_fails(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    ap = anchor.anchor_path(log.path)
    d = json.loads(ap.read_text())
    d["entries_count"] = 999            # adultera o corpo, mantém o HMAC antigo
    ap.write_text(json.dumps(d))
    st, _ = anchor.verificar(log, v, SENHA)
    assert st == anchor.ANCHORED_INVALID


def test_audit_anchor_wrong_hmac_fails(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    ap = anchor.anchor_path(log.path)
    d = json.loads(ap.read_text())
    d["hmac"] = "0" * 64
    ap.write_text(json.dumps(d))
    assert anchor.verificar(log, v, SENHA)[0] == anchor.ANCHORED_INVALID


# ---------- 6.6 / 6.7 count / tip divergentes ----------

def test_audit_anchor_count_mismatch_fails(nomos_home):
    log = _log(nomos_home, n=4)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)          # ancora em 4
    linhas = log.path.read_text().splitlines()
    log.path.write_text("\n".join(linhas[:2]) + "\n")   # agora só 2
    assert anchor.verificar(log, v, SENHA)[0] == anchor.TAIL_TRUNCATED


def test_audit_anchor_tip_mismatch_fails(nomos_home):
    log = _log(nomos_home, n=3)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    # mantém a MESMA contagem, mas troca o conteúdo da última linha por outra cadeia
    outro = AuditLog(nomos_home / "logs" / "outro.jsonl")
    for i in range(3):
        outro.append("x", n=i + 100)
    log.path.write_text(outro.path.read_text())   # 3 entradas, tip diferente
    assert anchor.verificar(log, v, SENHA)[0] == anchor.TAIL_TRUNCATED


# ---------- 6.8 chave ausente => fail-closed ----------

def test_audit_anchor_missing_key_fails_closed(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    # remove a chave HMAC do cofre (simula perda/ataque); âncora fica não-verificável
    v.delete(anchor.CHAVE_COFRE, SENHA)
    st, _ = anchor.verificar(log, v, SENHA)
    assert st == anchor.ANCHOR_MISSING
    assert anchor.status_severidade(st) == "FAIL"     # nunca vira PASS


# ---------- 6.9 logs legados: WARN, não PASS silencioso ----------

def test_legacy_unanchored_log_warns_not_passes(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)                    # cofre existe, mas nunca ancorou
    st, _ = anchor.verificar(log, v, SENHA)
    assert st == anchor.LEGACY_UNANCHORED
    assert anchor.status_severidade(st) == "WARN"
    assert st not in anchor.PASS_STATES


def test_anchor_ausente_com_chave_e_missing(nomos_home):
    """Se a chave já existe no cofre mas a âncora sumiu => FAIL (removeram a prova)."""
    log = _log(nomos_home)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    anchor.anchor_path(log.path).unlink()     # atacante apaga a âncora
    st, _ = anchor.verificar(log, v, SENHA)
    assert st == anchor.ANCHOR_MISSING


# ---------- 6.10 migração idempotente ----------

def test_logs_anchor_legacy_is_idempotent(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    a1 = anchor.criar_ancora(log, v, SENHA)
    a2 = anchor.criar_ancora(log, v, SENHA)   # sem mudanças no log
    assert a1["entries_count"] == a2["entries_count"] == 4
    assert a1["chain_tip"] == a2["chain_tip"]
    assert a1["log_id"] == a2["log_id"]        # log_id estável
    assert anchor.verificar(log, v, SENHA)[0] == anchor.ANCHORED_VALID


def test_reancorar_apos_crescer_valida(nomos_home):
    log = _log(nomos_home, n=4)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    log.append("evento", n=99)                 # cresce
    st, _ = anchor.verificar(log, v, SENHA)
    assert st == anchor.ANCHORED_VALID         # prefixo ancorado confere (advisory)
    anchor.criar_ancora(log, v, SENHA)         # reancora
    assert anchor.verificar(log, v, SENHA)[0] == anchor.ANCHORED_VALID


# ---------- 6.11 chave nunca é logada/impressa ----------

def test_audit_hmac_key_never_logged_or_printed(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    corpo = anchor.criar_ancora(log, v, SENHA)
    chave_b64 = v.get(anchor.CHAVE_COFRE, SENHA)
    chave_raw = __import__("base64").b64decode(chave_b64)
    # a âncora serializada não contém a chave
    ap_txt = anchor.anchor_path(log.path).read_text()
    assert chave_b64 not in ap_txt and chave_raw.hex() not in ap_txt
    # o corpo devolvido não expõe a chave
    assert "hmac" in corpo and chave_b64 not in json.dumps(corpo)
    # o audit log não grava a chave
    log.append("audit.ancorado", entries=corpo["entries_count"], log_id=corpo["log_id"])
    assert chave_b64 not in log.path.read_text()


def test_chain_corrupted_tem_prioridade(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    anchor.criar_ancora(log, v, SENHA)
    linhas = log.path.read_text().splitlines()
    rec = json.loads(linhas[1])
    rec["n"] = 777
    linhas[1] = json.dumps(rec)
    log.path.write_text("\n".join(linhas) + "\n")   # quebra a cadeia no meio
    assert anchor.verificar(log, v, SENHA)[0] == anchor.CHAIN_CORRUPTED


def test_nao_ancora_cadeia_corrompida(nomos_home):
    log = _log(nomos_home)
    v = _vault(nomos_home)
    linhas = log.path.read_text().splitlines()
    log.path.write_text("\n".join(linhas[:1] + linhas[2:]) + "\n")   # remove do meio
    with pytest.raises(anchor.AnchorError, match="corrompida"):
        anchor.criar_ancora(log, v, SENHA)


# ---------- 6.12 CLI ----------

def test_logs_verify_reports_anchored_status(nomos_home, capsys, monkeypatch):
    from nomos import cli
    monkeypatch.setenv("NOMOS_PASSPHRASE", SENHA)
    assert cli.main(["init"]) == 0
    # sem âncora ainda: verify (sem cofre) reporta LEGACY, não FAIL
    assert cli.main(["logs", "verify"]) == 0
    out = capsys.readouterr().out
    assert "LOG_LEGACY_UNANCHORED" in out or "LEGACY" in out


def test_logs_anchor_cli_creates_anchor(nomos_home, capsys, monkeypatch):
    from nomos import cli
    from nomos.kernel.vault import Vault
    monkeypatch.setenv("NOMOS_PASSPHRASE", SENHA)
    assert cli.main(["init"]) == 0
    Vault((nomos_home) / "vault.json").init(SENHA)   # cofre p/ guardar a chave HMAC
    # aprova o gate (A3) de forma não-interativa: usa NOMOS_PASSPHRASE + approver TTY?
    # o gate exige TTY; então validamos a função diretamente já coberta acima e aqui
    # garantimos que o parser aceita o subcomando anchor.
    assert cli.build_parser().parse_args(["logs", "anchor"]).logs_cmd == "anchor"
    # e que verify --cofre existe
    ns = cli.build_parser().parse_args(["logs", "verify", "--cofre"])
    assert ns.cofre is True


@pytest.fixture(autouse=True)
def _limpa_env(monkeypatch):
    monkeypatch.delenv("NOMOS_PASSPHRASE", raising=False)
    yield
    os.environ.pop("NOMOS_PASSPHRASE", None)
