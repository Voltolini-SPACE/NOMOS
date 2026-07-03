"""C6 — assinatura ed25519: confiável instala; adulterada/estranha/revogada/repinada recusa."""
import hashlib
import json

import os

import pytest

from nomos.ext import signing, skills as skills_mod
from nomos.ext.signing import TrustStore
from nomos.kernel.policy import PolicyEngine


def aprova(decision):
    return True


def _skill(tmp_path, name="exemplo", corpo='print("oi")\n'):
    h = hashlib.sha256(corpo.encode()).hexdigest()[:6]
    src = tmp_path / f"src-{name}-{h}"
    src.mkdir()
    (src / "main.py").write_text(corpo)
    mf = {"name": name, "version": "1.0.0", "permissions": ["A0_READ_LOCAL"],
          "entry": "main.py",
          "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}
    (src / "skill.json").write_text(json.dumps(mf))
    return src


@pytest.fixture()
def base(tmp_path):
    keydir = tmp_path / "keys"
    priv, pub = signing.keygen(keydir)
    trust = TrustStore(tmp_path / "trust.json")
    fp = trust.add(pub, "editora-teste")
    engine = PolicyEngine(tmp_path / "policy.json")
    skills_dir = tmp_path / "skills"
    return dict(priv=priv, pub=pub, fp=fp, trust=trust, engine=engine,
                skills=skills_dir, tmp=tmp_path)


def _sign_inplace(src, priv):
    mf = json.loads((src / "skill.json").read_text())
    (src / "skill.json").write_text(json.dumps(signing.sign_manifest(mf, priv)))


def test_assinada_confiavel_instala_e_pina(base, tmp_path):
    src = _skill(tmp_path)
    _sign_inplace(src, base["priv"])
    mf = skills_mod.install(src, base["skills"], base["engine"], aprova, trust=base["trust"])
    assert (base["skills"] / "exemplo" / "main.py").exists()
    assert base["trust"].pin_of("exemplo") == base["fp"]        # TOFU
    assert mf["signature"]["publisher"] == base["fp"]


def test_manifesto_adulterado_pos_assinatura_recusa(base, tmp_path):
    src = _skill(tmp_path)
    _sign_inplace(src, base["priv"])
    mf = json.loads((src / "skill.json").read_text())
    mf["permissions"] = ["A6_DESTRUCTIVE"]                       # escalada!
    (src / "skill.json").write_text(json.dumps(mf))
    with pytest.raises(skills_mod.SkillError, match="INVÁLIDA"):
        skills_mod.install(src, base["skills"], base["engine"], aprova, trust=base["trust"])


def test_publicador_nao_confiavel_recusa_mesmo_aprovado(base, tmp_path):
    outro_priv, _outro_pub = signing.keygen(tmp_path / "k2")
    src = _skill(tmp_path, name="intrusa")
    _sign_inplace(src, outro_priv)
    with pytest.raises(skills_mod.SkillError, match="não confiável"):
        skills_mod.install(src, base["skills"], base["engine"], aprova, trust=base["trust"])


def test_revogacao_bloqueia_publicador(base, tmp_path):
    src = _skill(tmp_path, name="depois-revogada")
    _sign_inplace(src, base["priv"])
    assert base["trust"].revoke(base["fp"]) is True
    with pytest.raises(skills_mod.SkillError, match="REVOGADO"):
        skills_mod.install(src, base["skills"], base["engine"], aprova, trust=base["trust"])


def test_pin_tofu_troca_de_publicador_recusa(base, tmp_path):
    src1 = _skill(tmp_path, name="app")
    _sign_inplace(src1, base["priv"])
    skills_mod.install(src1, base["skills"], base["engine"], aprova, trust=base["trust"])
    priv2, pub2 = signing.keygen(tmp_path / "k2")
    base["trust"].add(pub2, "outra-editora-tambem-confiavel")
    src2 = _skill(tmp_path, name="app", corpo='print("v2")\n')
    _sign_inplace(src2, priv2)
    with pytest.raises(skills_mod.SkillError, match="pin divergente"):
        skills_mod.install(src2, base["skills"], base["engine"], aprova, trust=base["trust"])


def test_mesma_editora_atualiza_ok(base, tmp_path):
    src1 = _skill(tmp_path, name="app2")
    _sign_inplace(src1, base["priv"])
    skills_mod.install(src1, base["skills"], base["engine"], aprova, trust=base["trust"])
    src2 = _skill(tmp_path, name="app2", corpo='print("v2")\n')
    _sign_inplace(src2, base["priv"])
    mf = skills_mod.install(src2, base["skills"], base["engine"], aprova, trust=base["trust"])
    assert mf["files"]["main.py"] == hashlib.sha256(b'print("v2")\n').hexdigest()


def test_nao_assinada_continua_exigindo_so_aprovacao(base, tmp_path):
    src = _skill(tmp_path, name="livre")
    skills_mod.install(src, base["skills"], base["engine"], aprova, trust=base["trust"])
    assert base["trust"].pin_of("livre") is None                 # sem pin p/ não assinada


def test_trust_store_corrompido_fail_closed(base, tmp_path):
    base["trust"].path.write_text("{quebrado")
    src = _skill(tmp_path, name="x1")
    _sign_inplace(src, base["priv"])
    with pytest.raises(skills_mod.SkillError, match="corrompido"):
        skills_mod.install(src, base["skills"], base["engine"], aprova, trust=base["trust"])


@__import__("pytest").mark.skipif(os.name == "nt", reason="permissões POSIX (0600) não se aplicam ao Windows")
def test_chave_privada_0600(base):
    assert oct(base["priv"].stat().st_mode & 0o777) == "0o600"
