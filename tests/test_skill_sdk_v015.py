"""v0.15 — SDK de skills: criar, I/O JSON, catálogo assinado, atualizações."""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nomos import cli
from nomos.ext import signing, skill_registry as reg, skill_sdk
from nomos.ext import skills as _skills
from nomos.kernel.policy import PolicyEngine

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ---------------- nomos skills criar ----------------

def test_criar_skill_gera_manifesto_valido_e_executavel(tmp_path):
    destino = skill_sdk.criar_skill("minha-skill", tmp_path)
    mf = json.loads((destino / "skill.json").read_text())
    assert reg.validar_manifesto(mf) == []
    _skills.verify_files(destino, mf)            # checksum bate de fábrica
    # o template roda de verdade e responde JSON estruturado
    args = tmp_path / "args.json"
    args.write_text('{"x": 1}')
    r = subprocess.run([sys.executable, str(destino / "main.py"), str(args)],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    saida = json.loads(r.stdout.strip())
    assert saida["ok"] is True and saida["eco"] == {"x": 1}
    assert (destino / "README.md").exists()


def test_criar_nome_invalido_e_sem_sobrescrever(tmp_path):
    with pytest.raises(skill_sdk.SdkError, match="nome inválido"):
        skill_sdk.criar_skill("Maiúsculo!", tmp_path)
    skill_sdk.criar_skill("dupla", tmp_path)
    with pytest.raises(skill_sdk.SdkError, match="não vou sobrescrever"):
        skill_sdk.criar_skill("dupla", tmp_path)


def test_cli_skills_criar(tmp_path, capsys):
    assert cli.main(["init"]) == 0
    rc = cli.main(["skills", "criar", "nova-skill", "--pasta", str(tmp_path)])
    assert rc == 0 and (tmp_path / "nova-skill" / "skill.json").exists()
    assert "próximos passos" in capsys.readouterr().out


# ---------------- execução com argumentos JSON ----------------

class _R:
    rc, stdout, stderr = 0, '{"ok": true, "eco": {"n": 7}}\n', ""
    timed_out, network_isolated = False, True


def _instala_sdk_skill(tmp_path, nomos_home, nome="io-skill"):
    src = skill_sdk.criar_skill(nome, tmp_path)
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True)
    return engine


def test_executar_passa_argumentos_por_arquivo(tmp_path, nomos_home):
    engine = _instala_sdk_skill(tmp_path, nomos_home)
    capturado = {}

    def fake_run(cmd, timeout=30, allow_network=False):
        capturado["cmd"] = cmd
        # argv agora é LISTA (sem shell): o arquivo de args é o último elemento
        caminho = cmd[-1]
        capturado["args"] = json.loads(Path(caminho).read_text())
        return _R()

    rc, saida = reg.executar("io-skill", nomos_home / "skills", engine,
                             lambda d: True, sandbox_run=fake_run,
                             argumentos={"n": 7})
    assert rc == 0 and capturado["args"] == {"n": 7}
    assert any("skill-args-io-skill" in str(p) for p in capturado["cmd"])
    sobras = list((nomos_home / "sandbox").glob("skill-args-*"))
    assert sobras == []                           # efêmero: limpo após rodar


def test_executar_json_interpreta_resultado(tmp_path, nomos_home):
    engine = _instala_sdk_skill(tmp_path, nomos_home, nome="io-json")
    rc, resultado, bruto = reg.executar_json(
        "io-json", nomos_home / "skills", engine, lambda d: True,
        sandbox_run=lambda *a, **k: _R(), argumentos={"n": 7})
    assert rc == 0 and resultado == {"ok": True, "eco": {"n": 7}}


# ---------------- catálogo assinado + atualizações ----------------

def _catalogo_bruto(versao="2.0.0"):
    return {"name": "catalogo-local", "skills": [
        {"name": "io-skill", "version": versao, "entrypoint": "main.py",
         "permissions": ["A0_READ_LOCAL"], "description": "atualização"}]}


def test_catalogo_assinado_verificado(tmp_path, nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    priv, pub = signing.keygen(tmp_path / "chaves")
    trust = signing.TrustStore(nomos_home / "trust.json")
    trust.add(pub, "editora-oficial")
    assinado = signing.sign_manifest(_catalogo_bruto(), priv)
    p = nomos_home / "registry" / "catalogo.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(assinado))
    skills, ok, publicador = reg.catalogo_info(nomos_home, trust)
    assert ok is True and len(skills) == 1 and publicador


def test_catalogo_adulterado_descartado_inteiro(tmp_path, nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    priv, pub = signing.keygen(tmp_path / "chaves")
    trust = signing.TrustStore(nomos_home / "trust.json")
    trust.add(pub, "editora")
    assinado = signing.sign_manifest(_catalogo_bruto(), priv)
    assinado["skills"][0]["permissions"] = ["A2_NET_EGRESS"]   # adultera!
    p = nomos_home / "registry" / "catalogo.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(assinado))
    skills, ok, _ = reg.catalogo_info(nomos_home, trust)
    assert skills == [] and ok is False           # fail-closed: tudo fora


def test_atualizacoes_disponiveis_e_cli(tmp_path, nomos_home, capsys):
    engine = _instala_sdk_skill(tmp_path, nomos_home)   # io-skill 0.1.0
    del engine
    reg.adicionar_ao_catalogo(nomos_home, _catalogo_bruto("2.0.0")["skills"][0])
    novidades = reg.atualizacoes_disponiveis(nomos_home, nomos_home / "skills")
    assert novidades and novidades[0]["disponivel"] == "2.0.0"
    assert cli.main(["skills", "atualizar"]) == 0
    out = capsys.readouterr().out
    assert "io-skill: 0.1.0 → 2.0.0" in out
    assert "manual" in out                        # nunca instala sozinho


# ---------------- skills oficiais de exemplo ----------------

def test_exemplos_oficiais_validos_e_baixo_risco():
    base = RAIZ / "examples" / "skills"
    pastas = sorted(p for p in base.iterdir() if p.is_dir())
    assert len(pastas) == 4   # v1.2: + busca-arquivos
    for pasta in pastas:
        mf = json.loads((pasta / "skill.json").read_text())
        assert reg.validar_manifesto(mf) == [], pasta.name
        _skills.verify_files(pasta, mf)
        assert reg.normalizar_manifesto(mf)["risk_level"] == "baixo", pasta.name


def test_exemplo_organizador_roda_de_verdade(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "b.md").write_text("y")
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"pasta": str(tmp_path)}))
    main = RAIZ / "examples" / "skills" / "organizador" / "main.py"
    r = subprocess.run([sys.executable, str(main), str(args)],
                       capture_output=True, text=True, timeout=30)
    saida = json.loads(r.stdout.strip())
    assert saida["ok"] is True and saida["arquivos"] >= 2
    assert saida["aviso"].startswith("so leitura")
