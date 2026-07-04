"""Auditoria de segurança do kernel — ataques simulados (red-team).

Cada teste representa um ataque do escopo da missão. Onde há correção aplicada,
o teste garante a defesa; onde há limitação documentada, o teste fixa o
comportamento REAL para não regredir silenciosamente.
"""
import hashlib
import io
import json

import pytest

from nomos.ext import skills
from nomos.kernel.policy import Category, Effect, PolicyEngine, gate


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _pkg(tmp_path, manifesto, corpo='print("ok")\n'):
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    (src / "skill.json").write_text(json.dumps(manifesto), encoding="utf-8",
                                    newline="\n")
    return src


# ---------- ATAQUE 12/13: path traversal e caminho absoluto no manifesto ----------

def test_entry_absoluto_e_recusado(nomos_home, tmp_path):
    """entry com caminho absoluto NÃO pode instalar: na execução `dest/entry`
    escaparia do diretório da skill para um arquivo externo sem checksum."""
    h = hashlib.sha256(b'print("ok")\n').hexdigest()
    src = _pkg(tmp_path, {"name": "malabs", "version": "1", "entry": "/tmp/evil",
                          "permissions": ["A0_READ_LOCAL"], "files": {"main.py": h}})
    with pytest.raises(skills.SkillError, match="inseguro|traversal|absoluto"):
        skills.install(src, nomos_home / "skills",
                       PolicyEngine(nomos_home / "p.json"), approver=lambda d: True)


def test_files_com_traversal_e_recusado(nomos_home, tmp_path):
    h = hashlib.sha256(b'print("ok")\n').hexdigest()
    src = _pkg(tmp_path, {"name": "maltrav", "version": "1", "entry": "main.py",
                          "permissions": ["A0_READ_LOCAL"],
                          "files": {"main.py": h, "../../pwned": h}})
    with pytest.raises(skills.SkillError, match="inseguro|traversal"):
        skills.install(src, nomos_home / "skills",
                       PolicyEngine(nomos_home / "p.json"), approver=lambda d: True)


def test_entry_precisa_estar_no_files_checksummado(nomos_home, tmp_path):
    """entry deve ser um arquivo verificado por checksum (estar em files)."""
    h = hashlib.sha256(b'print("ok")\n').hexdigest()
    # entry 'outro.py' não está em files => não é checksummado => recusado
    src = _pkg(tmp_path, {"name": "malentry", "version": "1", "entry": "outro.py",
                          "permissions": ["A0_READ_LOCAL"], "files": {"main.py": h}})
    with pytest.raises(skills.SkillError):
        skills.install(src, nomos_home / "skills",
                       PolicyEngine(nomos_home / "p.json"), approver=lambda d: True)


def test_skill_boa_ainda_instala(nomos_home, tmp_path):
    """Regressão: uma skill legítima (entry=main.py em files) continua instalando."""
    h = hashlib.sha256(b'print("ok")\n').hexdigest()
    src = _pkg(tmp_path, {"name": "boa", "version": "1.0.0", "entry": "main.py",
                          "permissions": ["A0_READ_LOCAL"], "files": {"main.py": h}})
    mf = skills.install(src, nomos_home / "skills",
                        PolicyEngine(nomos_home / "p.json"), approver=lambda d: True)
    assert mf["name"] == "boa"
    assert (nomos_home / "skills" / "boa" / "main.py").exists()


# ---------- ATAQUE 6: aprovação em CI/sem TTY sempre nega ----------

def test_ci_nunca_aprova_acao_sensivel(nomos_home):
    eng = PolicyEngine(nomos_home / "p.json")
    d = eng.decide(Category.WRITE_LOCAL, target="x")
    assert d.effect is Effect.REQUIRE_APPROVAL
    assert gate(d, approver=None) is False           # sem humano => nega


def test_destrutivo_sempre_negado(nomos_home):
    eng = PolicyEngine(nomos_home / "p.json")
    d = eng.decide(Category.DESTRUCTIVE, target="rm -rf")
    assert d.effect is Effect.DENY
    assert gate(d, approver=lambda x: True) is False  # nem com "humano" dizendo sim


# ---------- ATAQUE 5/18: cloud com cadeado local ativo é negada ----------

def test_egress_externo_negado_com_cadeado(nomos_home):
    eng = PolicyEngine(nomos_home / "p.json")   # cadeado LIGADO por padrão
    d = eng.decide(Category.NET_EGRESS, target="https://api.openai.com/v1")
    assert d.effect is Effect.DENY
    # loopback (motor local) continua livre para aprovação
    d2 = eng.decide(Category.NET_EGRESS, target="http://127.0.0.1:11434")
    assert d2.effect is Effect.REQUIRE_APPROVAL


# ---------- ATAQUE 15: audit log — o que é e o que NÃO é detectado ----------

def test_audit_detecta_modificacao_e_reordenacao(nomos_home):
    from nomos.kernel.audit import AuditLog
    p = nomos_home / "logs" / "a.jsonl"
    log = AuditLog(p)
    for i in range(4):
        log.append("ev", n=i)
    assert log.verify() == (True, -1)
    linhas = p.read_text().splitlines()
    # modificar uma linha do meio quebra a cadeia
    import json as _j
    rec = _j.loads(linhas[1])
    rec["n"] = 999
    linhas[1] = _j.dumps(rec)
    p.write_text("\n".join(linhas) + "\n")
    ok, idx = log.verify()
    assert ok is False and idx >= 1


def test_audit_truncamento_de_cauda_e_limitacao_conhecida(nomos_home):
    """LIMITAÇÃO DOCUMENTADA: hash-chain sem chave não detecta truncamento de
    cauda (remover as últimas linhas). Fixa o comportamento real p/ o relatório."""
    from nomos.kernel.audit import AuditLog
    p = nomos_home / "logs" / "b.jsonl"
    log = AuditLog(p)
    for i in range(4):
        log.append("ev", n=i)
    linhas = p.read_text().splitlines()
    p.write_text("\n".join(linhas[:-1]) + "\n")   # remove a última
    ok, _ = log.verify()
    assert ok is True     # NÃO detectado — documentado como risco residual
