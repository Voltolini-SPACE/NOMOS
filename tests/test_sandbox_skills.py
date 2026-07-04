import hashlib
import json

import pytest

from nomos.ext import skills
from nomos.kernel.policy import PolicyEngine
from nomos.runtime import sandbox


# ---------------- sandbox ----------------
# Gate de capacidade (mesmo padrão de test_redaction_pipe): sem user+net
# namespaces (macOS, Windows, kernels restritos) o sandbox recusa rodar por
# projeto — aqui isso vira SKIP explícito, nunca falso-verde nem falso-vermelho.

_netns = pytest.mark.skipif(not sandbox.netns_available(),
                            reason="exige user+net namespaces (unshare -rn)")
_posix = pytest.mark.skipif(__import__("os").name != "posix",
                            reason="sandbox usa /bin/sh (POSIX)")


@_netns
def test_execucao_basica():
    r = sandbox.run("echo ola-nomos", timeout=10)
    assert r.rc == 0 and "ola-nomos" in r.stdout


@_netns
def test_timeout_mata_processo():
    r = sandbox.run("sleep 30", timeout=1)
    assert r.timed_out is True


@_netns
def test_ambiente_nao_herda_segredos(monkeypatch):
    monkeypatch.setenv("SEGREDO_DO_HOST", "sk-nunca-vazar-000111")
    r = sandbox.run('echo "${SEGREDO_DO_HOST:-ausente}"', timeout=10)
    assert r.stdout.strip() == "ausente"


def test_rede_negada_por_padrao_ou_recusa_fail_closed():
    """Com namespaces: conexão externa DEVE falhar dentro do sandbox.
    Sem namespaces: o sandbox DEVE recusar executar (fail-closed)."""
    probe = (
        "python3 -c \"import socket;"
        "s=socket.socket();s.settimeout(3);"
        "s.connect(('1.1.1.1',80));print('REDE_ABERTA')\""
    )
    if sandbox.netns_available():
        r = sandbox.run(probe, timeout=15)
        assert r.network_isolated is True
        assert "REDE_ABERTA" not in r.stdout
        assert r.rc != 0
    else:
        with pytest.raises(sandbox.IsolationUnavailable):
            sandbox.run(probe, timeout=15)


@_posix
def test_allow_network_explicito_dispensa_namespace():
    r = sandbox.run("echo com-rede-aprovada", timeout=10, allow_network=True)
    assert r.rc == 0 and r.network_isolated is False


# ---------------- skills ----------------

def _fabrica_skill(tmp_path, corromper=False, com_assinatura=False):
    src = tmp_path / "skill-src"
    src.mkdir()
    corpo = 'print("skill de exemplo")\n'
    (src / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(corpo.encode()).hexdigest()
    manifest = {
        "name": "exemplo",
        "version": "1.0.0",
        "permissions": ["A0_READ_LOCAL"],
        "entry": "main.py",
        "files": {"main.py": "0" * 64 if corromper else digest},
    }
    if com_assinatura:
        manifest["signature"] = "ed25519:placeholder"
    (src / "skill.json").write_text(json.dumps(manifest))
    return src


def test_instalacao_com_checksum_e_aprovacao(tmp_path):
    src = _fabrica_skill(tmp_path)
    engine = PolicyEngine(tmp_path / "policy.json")
    dest = tmp_path / "skills"
    mf = skills.install(src, dest, engine, approver=lambda d: True)
    assert mf["name"] == "exemplo"
    assert (dest / "exemplo" / "main.py").exists()
    assert skills.list_installed(dest)[0]["version"] == "1.0.0"


def test_checksum_divergente_recusa(tmp_path):
    src = _fabrica_skill(tmp_path, corromper=True)
    engine = PolicyEngine(tmp_path / "policy.json")
    with pytest.raises(skills.SkillError, match="checksum"):
        skills.install(src, tmp_path / "skills", engine, approver=lambda d: True)


def test_sem_aprovacao_nao_instala(tmp_path):
    src = _fabrica_skill(tmp_path)
    engine = PolicyEngine(tmp_path / "policy.json")
    with pytest.raises(skills.SkillError, match="não aprovada"):
        skills.install(src, tmp_path / "skills", engine, approver=lambda d: False)
    assert skills.list_installed(tmp_path / "skills") == []


def test_assinatura_nao_verificavel_recusada_fail_closed(tmp_path):
    src = _fabrica_skill(tmp_path, com_assinatura=True)
    engine = PolicyEngine(tmp_path / "policy.json")
    with pytest.raises(skills.SkillError, match="assinatura"):
        skills.install(src, tmp_path / "skills", engine, approver=lambda d: True)


def test_permissao_desconhecida_no_manifesto_recusada(tmp_path):
    src = _fabrica_skill(tmp_path)
    mf = json.loads((src / "skill.json").read_text())
    mf["permissions"] = ["A9_SUPERPODER"]
    (src / "skill.json").write_text(json.dumps(mf))
    engine = PolicyEngine(tmp_path / "policy.json")
    with pytest.raises(skills.SkillError, match="permissão desconhecida"):
        skills.install(src, tmp_path / "skills", engine, approver=lambda d: True)
