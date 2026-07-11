import json
import time

from nomos.kernel.audit import REDACTED, AuditLog, redact
from nomos.kernel.consent import ConsentRegistry


# ---------------- auditoria ----------------

def test_cadeia_integra_e_verificavel(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for i in range(5):
        log.append("evento.teste", indice=i)
    ok, bad = log.verify()
    assert ok is True and bad == -1


def test_adulteracao_detectada(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    for i in range(3):
        log.append("evento", indice=i)
    lines = path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["indice"] = 999  # adulteração silenciosa
    lines[1] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")
    ok, bad = log.verify()
    assert ok is False and bad == 1


def test_redacao_por_chave_e_por_padrao(tmp_path):
    clean = redact({
        "api_key": "sk-real-9999999999",
        "mensagem": "usar Bearer abcDEF123456 no header",
        "aninhado": {"password": "hunter2-forte", "ok": "texto normal"},
    })
    assert clean["api_key"] == REDACTED
    assert "abcDEF123456" not in clean["mensagem"]
    assert clean["aninhado"]["password"] == REDACTED
    assert clean["aninhado"]["ok"] == "texto normal"


def test_redacao_por_padrao_em_campo_de_nome_inesperado(tmp_path):
    """Fase 0: campo com nome comum ('detalhe', 'nota') carregando um segredo
    precisa ser redigido pelo PADRÃO do valor, não só pelo nome do campo —
    SENSITIVE_KEYS sozinho não pega isso."""
    clean = redact({
        "detalhe": 'chamada com password="hunter2-super-forte" no corpo',
        "nota": "export SLACK_TOKEN=xoxb-1234567890-abcdefghij",
        "webhook_google": "chave AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ01234",
    })
    assert "hunter2-super-forte" not in clean["detalhe"]
    assert REDACTED in clean["detalhe"]
    assert "xoxb-1234567890-abcdefghij" not in clean["nota"]
    assert "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ01234" not in clean["webhook_google"]


def test_log_nunca_contem_padrao_de_segredo(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("vault.set", entry="CHAVE", secret="sk-vazamento-simulado-123456")
    log.append("nota", texto="token AKIAABCDEFGHIJKLMNOP em campo comum")
    raw = path.read_text()
    assert "sk-vazamento-simulado-123456" not in raw
    assert "AKIAABCDEFGHIJKLMNOP" not in raw
    ok, _ = log.verify()
    assert ok is True


# ---------------- consentimento ----------------

def test_dispositivos_desligados_por_padrao(tmp_path):
    reg = ConsentRegistry(tmp_path / "consent.json")
    assert reg.status() == {"microfone": False, "camera": False, "tela": False}


def test_concessao_com_ttl_e_revogacao(tmp_path):
    reg = ConsentRegistry(tmp_path / "consent.json")
    reg.grant("microfone", ttl_minutes=15)
    assert reg.is_granted("microfone") is True
    reg.revoke("microfone")
    assert reg.is_granted("microfone") is False


def test_expiracao_automatica_persistida(tmp_path, monkeypatch):
    reg = ConsentRegistry(tmp_path / "consent.json")
    reg.grant("tela", ttl_minutes=1)
    futuro = time.time() + 120
    monkeypatch.setattr(time, "time", lambda: futuro)
    assert reg.is_granted("tela") is False
    # estado revogado deve ter sido PERSISTIDO no disco
    data = json.loads((tmp_path / "consent.json").read_text())
    assert data["tela"]["granted"] is False


def test_panic_revoga_tudo(tmp_path):
    reg = ConsentRegistry(tmp_path / "consent.json")
    for dev in ("microfone", "camera", "tela"):
        reg.grant(dev, ttl_minutes=30)
    reg.panic()
    assert reg.status() == {"microfone": False, "camera": False, "tela": False}


def test_dispositivo_desconhecido_fail_closed(tmp_path):
    reg = ConsentRegistry(tmp_path / "consent.json")
    assert reg.is_granted("gps") is False
