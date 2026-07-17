"""Missão de eliminação de débitos residuais do Horizonte 3 (auditoria de
2026-07-17), Prioridade 1, parte b: roteamento de intenção para AGENTES
especializados dentro da conversa (`simple/amigavel.py::iniciar_chat`) —
mesmo padrão já usado para skills (`ext.skill_intencao`, coberto por
tests/test_v12_agente_age.py). Primeiro caller de produção de
`AgentRegistry.sugerir()` (até aqui só testado em isolamento, em
tests/test_v14_agentes.py).

A ferramenta executada quando o usuário confirma é a MESMA
`agents.execucao.ferramentas_wired()` + `AgentToolBoundary` da parte a
(commit anterior desta missão) — nenhuma lógica de autorização nova, só o
roteamento de QUANDO oferecer.
"""
import io

import pytest

from nomos.agents.manifest import AgentManifest
from nomos.agents.registry import AgentRegistry
from nomos.kernel.policy import PolicyEngine
from nomos.simple import amigavel


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# --------------------------- _sugerir_agente_conversa -----------------------

def test_sugerir_agente_conversa_por_keyword(nomos_home):
    ctx = {"home": nomos_home}
    reg = AgentRegistry(nomos_home)
    reg.definir_ativo("programador", True)
    resultado = amigavel._sugerir_agente_conversa(
        ctx, "escreve uma função que soma dois números")
    assert resultado is not None
    mf, ferramenta = resultado
    assert mf.name == "programador"
    assert ferramenta == "codigo_gerar"          # primeira ferramenta declarada


def test_sugerir_agente_conversa_frase_neutra_nao_sugere(nomos_home):
    ctx = {"home": nomos_home}
    reg = AgentRegistry(nomos_home)
    reg.definir_ativo("programador", True)
    assert amigavel._sugerir_agente_conversa(ctx, "que dia é hoje?") is None


def test_sugerir_agente_conversa_agente_inativo_nao_e_sugerido(nomos_home):
    ctx = {"home": nomos_home}
    reg = AgentRegistry(nomos_home)
    reg.definir_ativo("programador", False)
    assert amigavel._sugerir_agente_conversa(
        ctx, "escreve uma função que soma dois números") is None


# ------------------------------ conversa completa ---------------------------

class _RouterFalsoCompleto:
    """Implementa .chat() (usado por exec_codigo_gerar) E .chat_stream()
    (usado pelo fluxo normal de chat quando a oferta é recusada) — mesma
    dupla superfície do Router real (cognition/router.py)."""
    def __init__(self, texto_gerado="def soma(a, b):\n    return a + b"):
        self.texto_gerado = texto_gerado
        self.chamadas_chat = []
        self.chamadas_stream = None

    def chat(self, mensagens):
        from nomos.cognition.router import ChatOutcome
        self.chamadas_chat.append(mensagens)
        return ChatOutcome(True, "local", self.texto_gerado, "stub", "stub")

    def chat_stream(self, messages, on_token):
        from nomos.cognition.router import ChatOutcome
        self.chamadas_stream = messages
        on_token("resposta normal do motor")
        return ChatOutcome(True, "local", "resposta normal do motor", "stub", "stub")


def _conversa(nomos_home, entradas, router, aprovador=lambda d: True, com_audit=False):
    from nomos.kernel.policy import PolicyEngine as _PE
    feed = iter(entradas)
    tela: list = []
    tokens: list = []
    ctx = {"home": nomos_home, "policy": _PE(nomos_home / "policy.json"),
          "skills": nomos_home / "skills"}
    if com_audit:
        from nomos.kernel.audit import AuditLog
        ctx["audit"] = AuditLog(nomos_home / "logs" / "audit.jsonl")
    rc = amigavel.iniciar_chat(ctx, {"agent_name": "Luna"}, router=router,
                               ask=lambda _: next(feed), say=tela.append,
                               colorido=False, aprovador=aprovador,
                               say_token=tokens.append)
    return rc, "\n".join(str(x) for x in tela) + "\n" + "".join(tokens)


def test_oferta_de_agente_sim_executa_ferramenta_real(nomos_home):
    AgentRegistry(nomos_home).definir_ativo("programador", True)
    router = _RouterFalsoCompleto()
    rc, tela = _conversa(nomos_home,
                         ["escreve uma função que soma dois números", "sim", "/sair"],
                         router)
    assert rc == 0
    assert "posso acionar o agente 'programador'" in tela
    assert "ferramenta 'codigo_gerar'" in tela
    assert "def soma(a, b):" in tela                  # resultado real virou resposta
    assert len(router.chamadas_chat) == 1             # .chat() foi chamado de verdade
    assert router.chamadas_stream is None             # NÃO caiu no chat normal


def test_oferta_de_agente_nao_segue_para_resposta_normal(nomos_home):
    AgentRegistry(nomos_home).definir_ativo("programador", True)
    router = _RouterFalsoCompleto()
    rc, tela = _conversa(nomos_home,
                         ["escreve uma função que soma dois números", "não", "/sair"],
                         router)
    assert rc == 0
    assert "ok, sigo eu mesmo" in tela
    assert router.chamadas_chat == []                 # codigo_gerar NÃO rodou
    assert router.chamadas_stream is not None          # seguiu para o chat normal
    assert "resposta normal do motor" in tela


def test_oferta_de_agente_so_quando_nenhuma_skill_casa(nomos_home, tmp_path):
    """Skill e agente casando a MESMA frase: skill tem prioridade — nunca
    duas ofertas no mesmo turno."""
    import hashlib
    import json
    from nomos.ext import skill_registry as reg
    AgentRegistry(nomos_home).definir_ativo("programador", True)
    src = tmp_path / "src-escreve-codigo"
    src.mkdir()
    corpo = 'import json\nprint(json.dumps({"ok": True}))\n'
    (src / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    (src / "skill.json").write_text(json.dumps({
        "name": "escreve-codigo", "version": "1.0.0", "entry": "main.py",
        "permissions": ["A0_READ_LOCAL"], "keywords": ["escreve uma função"],
        "description": "gera código", "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}))
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                confirmar_experimental=lambda m: True)
    router = _RouterFalsoCompleto()
    rc, tela = _conversa(nomos_home,
                         ["escreve uma função que soma dois números", "não", "/sair"],
                         router)
    assert "posso usar a skill 'escreve-codigo'" in tela
    assert "posso acionar o agente" not in tela        # agente nunca ofertado


def test_oferta_de_agente_negada_pelo_gate_nada_e_escrito(nomos_home, capsys):
    """Agente customizado com arquivo_escrever (A1) como primeira
    ferramenta; aprovador nega -> mensagem honesta, NADA é gravado. Prova
    que o gate do AgentToolBoundary continua valendo vindo da conversa,
    não só da CLI."""
    reg = AgentRegistry(nomos_home)
    reg.instalar(AgentManifest(name="redator", objetivo="grava anotações no workspace",
                               ferramentas=("arquivo_escrever",), risco_max="A1",
                               keywords=("grava uma nota",)))
    reg.definir_ativo("redator", True)
    router = _RouterFalsoCompleto()
    rc, tela = _conversa(nomos_home,
                         ["grava uma nota sobre o projeto", "sim", "/sair"],
                         router, aprovador=lambda d: False)
    assert "posso acionar o agente 'redator'" in tela
    assert "precisa de aprovação" in tela or "negada" in tela
    assert not (nomos_home / "workspace").exists()


def test_auditoria_registra_uso_de_agente_via_conversa(nomos_home):
    reg = AgentRegistry(nomos_home)
    reg.definir_ativo("programador", True)
    router = _RouterFalsoCompleto()
    _conversa(nomos_home,
             ["escreve uma função que soma dois números", "sim", "/sair"],
             router, com_audit=True)
    bruto = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "agente.ferramenta.usada" in bruto
    assert '"agente":"programador"' in bruto.replace(" ", "") or "programador" in bruto
