"""F3 — agentes locais: manifesto, boundary, gate compartilhado, sem bypass."""
import io
from pathlib import Path

import pytest

from nomos import cli
from nomos.agents.boundary import AgentToolBoundary
from nomos.agents.manifest import AgentManifest, risco_exigido, validar
from nomos.agents.registry import AgentError, AgentRegistry
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ---------------- manifesto ----------------

def test_ferramenta_fora_da_allowlist_invalida():
    mf = AgentManifest(name="x", objetivo="teste", ferramentas=("teleporte",))
    assert any("allowlist" in p for p in validar(mf))


def test_nao_pode_declarar_risco_menor_que_ferramentas(monkeypatch):
    # arquivo_escrever exige A1; declarar A0 é proibido
    mf = AgentManifest(name="x", objetivo="t",
                       ferramentas=("arquivo_escrever",), risco_max="A0")
    assert any("MENOR que o exigido" in p for p in validar(mf))
    assert risco_exigido(("arquivo_escrever",)) == "A1"
    assert risco_exigido(("memoria_buscar",)) == "A0"


def test_skill_rodar_exige_flag():
    mf = AgentManifest(name="x", objetivo="t", ferramentas=("skill_rodar",),
                       risco_max="A5", pode_executar_skill=False)
    assert any("contradição" in p for p in validar(mf))


# ---------------- boundary: agente NÃO é bypass ----------------

def _boundary(nomos_home, ferramentas, approver):
    mf = AgentManifest(name="ag", objetivo="t", ferramentas=tuple(ferramentas),
                       risco_max=risco_exigido(ferramentas))
    return AgentToolBoundary(mf, PolicyEngine(nomos_home / "p.json"), approver,
                             audit=AuditLog(nomos_home / "logs" / "a.jsonl"))


def test_ferramenta_fora_do_manifesto_negada(nomos_home):
    b = _boundary(nomos_home, ["memoria_buscar"], approver=lambda d: True)
    ok, msg = b.usar_ferramenta("arquivo_escrever", lambda: "escreveu")
    assert ok is False and "não tem a ferramenta" in msg


def test_ferramenta_a0_passa_direto(nomos_home):
    b = _boundary(nomos_home, ["memoria_buscar"], approver=None)
    ok, res = b.usar_ferramenta("memoria_buscar", lambda: ["achou"])
    assert ok and res == ["achou"]            # A0 é permitido pela política


def test_ferramenta_a1_exige_aprovacao_e_gate_manda(nomos_home):
    # sem aprovador (CI/script): A1 é negado — o gate do kernel decide
    b = _boundary(nomos_home, ["arquivo_escrever"], approver=None)
    ok, msg = b.usar_ferramenta("arquivo_escrever", lambda: "gravou")
    assert ok is False and "aprovação" in msg
    # com humano aprovando: passa
    b2 = _boundary(nomos_home, ["arquivo_escrever"], approver=lambda d: True)
    ok2, res2 = b2.usar_ferramenta("arquivo_escrever", lambda: "gravou")
    assert ok2 and res2 == "gravou"


def test_agente_nao_herda_permissao_de_outro(nomos_home):
    """Cada boundary é do seu manifesto; um agente A0 não ganha A1 de outro."""
    pesquisador = _boundary(nomos_home, ["memoria_buscar"], approver=lambda d: True)
    ok, msg = pesquisador.usar_ferramenta("arquivo_escrever", lambda: "x")
    assert ok is False                        # não tem A1 mesmo com aprovador


def test_auditoria_registra_uso_e_negacao(nomos_home):
    b = _boundary(nomos_home, ["memoria_buscar"], approver=lambda d: True)
    b.usar_ferramenta("memoria_buscar", lambda: 1)
    b.usar_ferramenta("arquivo_escrever", lambda: 2)   # fora do manifesto
    log = (nomos_home / "logs" / "a.jsonl").read_text()
    assert "agente.ferramenta.usada" in log and "agente.ferramenta.negada" in log


# ---------------- registry + oficiais ----------------

def test_instalar_valida(nomos_home):
    reg = AgentRegistry(nomos_home)
    with pytest.raises(AgentError, match="inválido"):
        reg.instalar(AgentManifest(name="Maiúsculo!", objetivo="",
                                   ferramentas=()))
    mf = reg.instalar(AgentManifest(name="ok", objetivo="faz algo",
                                    ferramentas=("memoria_buscar",)))
    assert reg.obter("ok") == mf


def test_agentes_oficiais_validos():
    reg = AgentRegistry("/tmp/nao-existe-home",
                        extras_dir=RAIZ / "examples" / "agents")
    nomes = {m.name for m in reg.listar()}
    assert {"pesquisador-local", "programador", "seguranca"} <= nomes
    for m in reg.listar():
        assert validar(m) == []


def test_sugerir_por_keyword_do_texto_digitado(nomos_home):
    reg = AgentRegistry(nomos_home, extras_dir=RAIZ / "examples" / "agents")
    reg.definir_ativo("seguranca", True)
    s = reg.sugerir("está tudo seguro no meu sistema?")
    assert s and s.name == "seguranca"
    assert reg.sugerir("que dia é hoje?") is None    # neutro não chama agente


def test_agente_inativo_nao_e_sugerido(nomos_home):
    reg = AgentRegistry(nomos_home, extras_dir=RAIZ / "examples" / "agents")
    reg.definir_ativo("seguranca", False)
    assert reg.sugerir("faça um diagnóstico de segurança agora") is None


# ---------------- CLI ----------------

def test_cli_agentes_listar_e_info(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["agentes", "listar"]) == 0
    out = capsys.readouterr().out
    assert "pesquisador-local" in out and "risco máx" in out
    assert cli.main(["agentes", "info", "programador"]) == 0
    assert "risco máximo: A1" in capsys.readouterr().out


def test_cli_agentes_ativar_diagnostico(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["agentes", "ativar", "seguranca"]) == 0
    assert cli.main(["agentes", "diagnostico"]) == 0
    out = capsys.readouterr().out
    assert "seguranca" in out and "ATIVO" in out
