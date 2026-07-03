"""Fase 2 — registry local: manifesto v2, risco, catálogo e execução governada."""
import hashlib
import json

import pytest

from nomos.ext import skill_registry as reg
from nomos.kernel import localidade
from nomos.kernel.policy import PolicyEngine


def _skill(tmp_path, name="exemplo", permissions=None, extras=None, corpo=None):
    src = tmp_path / f"src-{name}"
    src.mkdir()
    corpo = corpo or 'print("ola da skill")\n'
    (src / "main.py").write_text(corpo)
    mf = {"name": name, "version": "1.0.0",
          "permissions": permissions or ["A0_READ_LOCAL"],
          "entry": "main.py",
          "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}
    mf.update(extras or {})
    (src / "skill.json").write_text(json.dumps(mf))
    return src


# ---------------- risco ----------------

def test_risco_por_permissao():
    assert reg.risco_de(["A0_READ_LOCAL"]) == "baixo"
    assert reg.risco_de(["A1_WRITE_LOCAL"]) == "medio"
    assert reg.risco_de(["A2_NET_EGRESS"]) == "alto"
    assert reg.risco_de(["A5_CODE_EXEC"]) == "alto"
    assert reg.risco_de(["A9_INVENTADA"]) == "alto"   # desconhecida = alto


def test_manifesto_nao_afrouxa_aprovacao():
    mf = reg.normalizar_manifesto({"name": "x", "version": "1", "entry": "m.py",
                                   "permissions": ["A2_NET_EGRESS"], "files": {},
                                   "requires_approval": False})
    assert mf["requires_approval"] is True   # cálculo manda, não o autor


def test_validar_manifesto_v2():
    ok = {"name": "x", "version": "1", "entrypoint": "m.py",
          "permissions": ["A0_READ_LOCAL"], "files": {},
          "risk_level": "baixo", "modalities": ["texto"]}
    assert reg.validar_manifesto(ok) == []
    ruim = dict(ok, risk_level="apocaliptico", modalities=["telepatia"])
    problemas = "; ".join(reg.validar_manifesto(ruim))
    assert "risk_level" in problemas and "telepatia" in problemas


def test_manifesto_contraditorio_cloud():
    mf = {"name": "x", "version": "1", "entry": "m.py", "permissions": [],
          "files": {}, "cloud_required": True, "local_only_capable": True}
    assert any("contraditório" in p for p in reg.validar_manifesto(mf))


# ---------------- instalação v2 ----------------

def test_skill_sem_manifesto_valido_nao_instala(tmp_path, nomos_home):
    src = tmp_path / "quebrada"
    src.mkdir()
    (src / "skill.json").write_text('{"name": "so-nome"}')
    engine = PolicyEngine(nomos_home / "policy.json")
    with pytest.raises(reg.RegistroError, match="manifesto inválido"):
        reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                     confirmar_experimental=lambda mf: True)
    assert not (nomos_home / "skills" / "so-nome").exists()


def test_experimental_sem_confirmador_nega(tmp_path, nomos_home):
    src = _skill(tmp_path)   # não assinada => experimental
    engine = PolicyEngine(nomos_home / "policy.json")
    with pytest.raises(reg.RegistroError, match="experimental"):
        reg.instalar(src, nomos_home / "skills", engine, lambda d: True)


def test_experimental_confirmado_instala(tmp_path, nomos_home):
    src = _skill(tmp_path)
    engine = PolicyEngine(nomos_home / "policy.json")
    mf = reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                      confirmar_experimental=lambda m: True)
    assert mf["risk_level"] == "baixo"
    assert (nomos_home / "skills" / "exemplo" / "main.py").exists()


def test_risco_alto_exige_confirmacao_extra(tmp_path, nomos_home):
    src = _skill(tmp_path, name="arriscada", permissions=["A2_NET_EGRESS"])
    engine = PolicyEngine(nomos_home / "policy.json")
    with pytest.raises(reg.RegistroError, match="não confirmada"):
        reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                     confirmar_experimental=lambda m: False)


# ---------------- catálogo local ----------------

def test_catalogo_disponivel_vs_instalada(tmp_path, nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    reg.adicionar_ao_catalogo(nomos_home, {
        "name": "clima", "version": "0.1", "entrypoint": "main.py",
        "permissions": ["A2_NET_EGRESS"], "description": "previsão do tempo"})
    disp = reg.disponiveis(nomos_home, nomos_home / "skills")
    assert [d["name"] for d in disp] == ["clima"]
    assert disp[0]["risk_level"] == "alto"   # pede rede

    src = _skill(tmp_path, name="clima")
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True)
    assert reg.disponiveis(nomos_home, nomos_home / "skills") == []


def test_catalogo_corrompido_fail_closed(nomos_home):
    p = nomos_home / "registry" / "catalogo.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{isso não é json")
    assert reg.catalogo(nomos_home) == []


# ---------------- execução governada ----------------

def test_permissao_nao_declarada_nao_e_concedida(nomos_home):
    """Skill que só declara A0 não passa por nenhum gate extra — e nada mais."""
    engine = PolicyEngine(nomos_home / "policy.json")
    ok, motivo = reg.preparar_execucao(
        {"name": "x", "version": "1", "entry": "m.py",
         "permissions": ["A0_READ_LOCAL"], "files": {}}, engine, approver=None)
    assert ok   # leitura local é o piso; nada além disso foi concedido


def test_skill_com_rede_cai_no_gate_e_cadeado(nomos_home):
    engine = PolicyEngine(nomos_home / "policy.json")
    mf = {"name": "net", "version": "1", "entry": "m.py",
          "permissions": ["A2_NET_EGRESS"], "files": {}}
    # cadeado ligado (padrão): nega mesmo com humano aprovando
    ok, motivo = reg.preparar_execucao(mf, engine, approver=lambda d: True)
    assert not ok and "A2_NET_EGRESS" in motivo
    # cadeado desligado + humano aprovando: passa
    localidade.definir(nomos_home, False)
    ok, _ = reg.preparar_execucao(mf, engine, approver=lambda d: True)
    assert ok
    # cadeado desligado, SEM aprovador (CI): nega — fail-closed
    ok, _ = reg.preparar_execucao(mf, engine, approver=None)
    assert not ok


def test_skill_arquivo_exige_a1_aprovada(nomos_home):
    engine = PolicyEngine(nomos_home / "policy.json")
    mf = {"name": "fs", "version": "1", "entry": "m.py",
          "permissions": ["A1_WRITE_LOCAL"], "files": {}}
    assert reg.preparar_execucao(mf, engine, approver=None)[0] is False
    assert reg.preparar_execucao(mf, engine, approver=lambda d: True)[0] is True


def test_executar_skill_quebrada_nao_roda(tmp_path, nomos_home):
    dest = nomos_home / "skills" / "zumbi"
    dest.mkdir(parents=True)
    (dest / "skill.json").write_text("{nem json é}")
    engine = PolicyEngine(nomos_home / "policy.json")
    rc, msg = reg.executar("zumbi", nomos_home / "skills", engine, lambda d: True)
    assert rc == 3 and "quebrada" in msg


class _FakeResult:
    rc, stdout, stderr = 0, "saida-ok\n", ""
    timed_out, network_isolated = False, True


def test_executar_governado_com_sandbox_injetado(tmp_path, nomos_home):
    src = _skill(tmp_path, name="segura", permissions=["A5_CODE_EXEC"])
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True)
    chamadas = []

    def fake_run(cmd, timeout=30, allow_network=False):
        chamadas.append({"cmd": cmd, "rede": allow_network})
        return _FakeResult()

    rc, out = reg.executar("segura", nomos_home / "skills", engine,
                           lambda d: True, sandbox_run=fake_run)
    assert rc == 0 and "saida-ok" in out
    assert chamadas[0]["rede"] is False   # não declarou rede => sandbox sem rede

    rc, _ = reg.executar("segura", nomos_home / "skills", engine, approver=None,
                         sandbox_run=fake_run)
    assert rc == 3   # sem aprovador, A5 nega — nunca roda
