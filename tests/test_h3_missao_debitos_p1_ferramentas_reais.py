"""Missão de eliminação de débitos residuais do Horizonte 3 (auditoria de
2026-07-17), Prioridade 1: `arquivo_escrever`, `codigo_gerar` e `skill_rodar`
ganham execução REAL (`src/nomos/agents/execucao.py`), fechando o gap que o
Horizonte 3/item 1 documentou e deixou explicitamente pendente (ver nota em
tests/test_h3_item1_agente_boundary_wiring.py).

Duas camadas de cobertura:
- unitária: chama `agents.execucao.exec_*` diretamente (ctx construído à
  mão, mesmo formato de `cli.py::_paths()`) — rápido, prova cada primitiva
  isoladamente, incluindo os caminhos negativos (path traversal, motor
  ausente, permissão negada) sem depender do parser da CLI;
- ponta-a-ponta: chama `cli.main(["agentes", "usar", ...])` — prova que o
  MESMO `AgentToolBoundary` (gate de política, auditoria) autoriza/nega
  corretamente por cima da execução real, e cobre o critério de aceite
  explícito da missão: o agente oficial 'programador' termina com as 3
  ferramentas (`arquivo_ler`, `arquivo_escrever`, `codigo_gerar`) realmente
  funcionais.

Nenhuma regra de autorização é re-testada aqui (isso é
tests/test_v14_agentes.py) — só o que acontece DEPOIS de autorizado.
"""
import hashlib
import json
import stat
from pathlib import Path

import pytest

from nomos import cli
from nomos.agents import execucao as ex


# --------------------------- ctx unitário (mesmo formato de cli._paths) ---

def _ctx(nomos_home: Path) -> dict:
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    from nomos.kernel.vault import Vault
    return {
        "home": nomos_home,
        "vault": Vault(nomos_home / "vault.json"),
        "policy": PolicyEngine(nomos_home / "policy.json"),
        "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
        "skills": nomos_home / "skills",
    }


def _ativar(nome: str) -> None:
    assert cli.main(["init"]) == 0
    assert cli.main(["agentes", "ativar", nome]) == 0


# =============================== arquivo_escrever ==========================

def test_arquivo_escrever_grava_arquivo_real_dentro_do_workspace(nomos_home):
    ctx = _ctx(nomos_home)
    msg = ex.exec_arquivo_escrever(ctx, "notas/teste.txt", "conteudo real de verdade")
    destino = nomos_home / "workspace" / "notas" / "teste.txt"
    assert destino.exists()
    assert destino.read_text(encoding="utf-8") == "conteudo real de verdade"
    assert str(destino) in msg and "24 caractere" in msg
    # gravado 0600 (mesmo padrão de policy.json/approvals) — não world/group-readable
    modo = stat.S_IMODE(destino.stat().st_mode)
    assert modo == 0o600


def test_arquivo_escrever_sem_alvo_pede_alvo_sem_falhar(nomos_home):
    ctx = _ctx(nomos_home)
    msg = ex.exec_arquivo_escrever(ctx, "", "conteudo")
    assert "informe --alvo" in msg
    assert not (nomos_home / "workspace").exists() or \
        not any((nomos_home / "workspace").iterdir())


def test_arquivo_escrever_recusa_path_traversal_relativo(nomos_home):
    ctx = _ctx(nomos_home)
    with pytest.raises(ex.DestinoInseguroError, match="fora do workspace"):
        ex.exec_arquivo_escrever(ctx, "../../../../../../etc/passwd-nomos-teste",
                                 "conteudo hostil")
    # nada vazou para fora do workspace
    assert not (Path("/etc/passwd-nomos-teste")).exists()
    fora = nomos_home.parent / "passwd-nomos-teste"
    assert not fora.exists()


def test_arquivo_escrever_recusa_caminho_absoluto_fora_do_workspace(nomos_home, tmp_path):
    ctx = _ctx(nomos_home)
    alvo_absoluto = tmp_path / "fora-do-workspace.txt"
    with pytest.raises(ex.DestinoInseguroError, match="fora do workspace"):
        ex.exec_arquivo_escrever(ctx, str(alvo_absoluto), "conteudo hostil")
    assert not alvo_absoluto.exists()


def test_arquivo_escrever_aceita_absoluto_dentro_do_workspace(nomos_home):
    ctx = _ctx(nomos_home)
    workspace = nomos_home / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    alvo_absoluto = workspace / "direto.txt"
    msg = ex.exec_arquivo_escrever(ctx, str(alvo_absoluto), "ok")
    assert alvo_absoluto.exists() and alvo_absoluto.read_text() == "ok"
    assert "gravado" in msg


def test_arquivo_escrever_cria_subdiretorios_automaticamente(nomos_home):
    ctx = _ctx(nomos_home)
    ex.exec_arquivo_escrever(ctx, "a/b/c/arquivo.md", "# título\n")
    destino = nomos_home / "workspace" / "a" / "b" / "c" / "arquivo.md"
    assert destino.exists() and destino.read_text() == "# título\n"


def test_arquivo_escrever_conteudo_vazio_grava_arquivo_vazio(nomos_home):
    """Sem --conteudo: grava arquivo vazio (não recusa, não inventa texto)."""
    ctx = _ctx(nomos_home)
    msg = ex.exec_arquivo_escrever(ctx, "vazio.txt")
    destino = nomos_home / "workspace" / "vazio.txt"
    assert destino.exists() and destino.read_text() == ""
    assert "0 caractere" in msg


# =============================== codigo_gerar ===============================

def test_codigo_gerar_sem_alvo_pede_pedido_sem_falhar(nomos_home):
    ctx = _ctx(nomos_home)
    msg = ex.exec_codigo_gerar(ctx, "", router=object())
    assert "informe --alvo" in msg


def test_codigo_gerar_sem_motor_e_fail_closed_sem_exception_nem_escrita(nomos_home):
    ctx = _ctx(nomos_home)
    msg = ex.exec_codigo_gerar(ctx, "escreva uma função de soma", router=None)
    assert "nenhum motor configurado" in msg
    assert "nunca inventa código sem motor" in msg
    # codigo_gerar é A0 (READ_LOCAL) — em NENHUMA hipótese grava em disco
    assert not (nomos_home / "workspace").exists()


class _RouterFalso:
    """Dublê do cognition.router.Router — só a superfície usada por
    exec_codigo_gerar (`.chat(mensagens) -> ChatOutcome`). Prova que
    exec_codigo_gerar CHAMA o motor de verdade (mesma classe ChatOutcome do
    Router real), não que o motor em si é fake — o Router real já tem sua
    própria suíte (tests/test_*router*)."""
    def __init__(self, outcome):
        self.outcome = outcome
        self.chamadas = []

    def chat(self, mensagens):
        self.chamadas.append(mensagens)
        return self.outcome


def test_codigo_gerar_com_motor_disponivel_devolve_texto_gerado(nomos_home):
    from nomos.cognition.router import ChatOutcome
    ctx = _ctx(nomos_home)
    outcome = ChatOutcome(ok=True, route="local", text="def soma(a, b):\n    return a + b",
                          provider="ollama", model="qwen2.5-coder")
    router = _RouterFalso(outcome)
    msg = ex.exec_codigo_gerar(ctx, "escreva uma função de soma em python", router=router)
    assert msg == outcome.text
    assert len(router.chamadas) == 1
    mensagens = router.chamadas[0]
    assert mensagens[-1] == {"role": "user", "content": "escreva uma função de soma em python"}
    assert mensagens[0]["role"] == "system"
    # nunca grava em disco (A0) mesmo com motor disponível e sucesso
    assert not (nomos_home / "workspace").exists()


def test_codigo_gerar_motor_degradado_surge_motivo_sem_exception(nomos_home):
    from nomos.cognition.router import ChatOutcome
    ctx = _ctx(nomos_home)
    outcome = ChatOutcome(ok=False, route="degradada", text="[MODO DEGRADADO]",
                          reason="Ollama não respondeu em http://127.0.0.1:11434")
    router = _RouterFalso(outcome)
    msg = ex.exec_codigo_gerar(ctx, "escreva uma função", router=router)
    assert "não consegui gerar código" in msg
    assert "Ollama não respondeu" in msg


# =============================== skill_rodar ================================

def _instalar_skill_de_teste(nomos_home, tmp_path, name="skill-real-p1",
                             permissions=None, corpo=None) -> None:
    from nomos.ext import skill_registry as reg
    from nomos.kernel.policy import PolicyEngine
    src = tmp_path / f"src-{name}"
    src.mkdir()
    corpo = corpo or (
        'import json\n'
        'print(json.dumps({"ok": True, "mensagem": "rodou de verdade"}))\n'
    )
    (src / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    mf = {"name": name, "version": "1.0.0",
          "permissions": permissions or ["A0_READ_LOCAL"],
          "entry": "main.py",
          "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}
    (src / "skill.json").write_text(json.dumps(mf))
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                confirmar_experimental=lambda m: True)


def test_skill_rodar_sem_alvo_pede_nome_sem_falhar(nomos_home):
    ctx = _ctx(nomos_home)
    msg = ex.exec_skill_rodar(ctx, "", aprovador=lambda d: True)
    assert "informe --alvo" in msg


def test_skill_rodar_skill_inexistente_retorna_motivo_claro(nomos_home):
    ctx = _ctx(nomos_home)
    msg = ex.exec_skill_rodar(ctx, "fantasma", aprovador=lambda d: True)
    assert "não está instalada" in msg


def test_skill_rodar_sucesso_real_via_sandbox_real(nomos_home, tmp_path):
    """Execução real: subprocess python3 de verdade dentro do
    runtime.sandbox (unshare -rn), skill instalada de verdade em disco —
    nenhuma parte do caminho de execução é dublê."""
    from nomos.ext import skill_status as st
    _instalar_skill_de_teste(nomos_home, tmp_path)
    ctx = _ctx(nomos_home)
    assert st.marcar_uso.__module__   # smoke: módulo importável antes do teste real
    msg = ex.exec_skill_rodar(ctx, "skill-real-p1", aprovador=lambda d: True)
    assert "rodou de verdade" in msg
    # marcar_uso() realmente rodou — efeito colateral real, observável em disco
    status = st.status_todas(nomos_home, nomos_home / "skills")
    alvo = next(i for i in status if i["name"] == "skill-real-p1")
    assert alvo.get("usos", 0) >= 1 or alvo.get("ultimo_uso") is not None


def test_skill_rodar_permissao_negada_nao_executa(nomos_home, tmp_path):
    """Skill declara A1_WRITE_LOCAL; aprovador nega -> nunca chega a rodar
    (defesa em profundidade: gate PRÓPRIO do skill_registry, além do gate
    do AgentToolBoundary que autorizou só a ferramenta skill_rodar em si)."""
    from nomos.ext import skill_status as st
    _instalar_skill_de_teste(nomos_home, tmp_path, name="skill-negada",
                             permissions=["A1_WRITE_LOCAL"])
    ctx = _ctx(nomos_home)
    msg = ex.exec_skill_rodar(ctx, "skill-negada", aprovador=lambda d: False)
    assert "negada" in msg or "permissão" in msg
    status = st.status_todas(nomos_home, nomos_home / "skills")
    alvo = next(i for i in status if i["name"] == "skill-negada")
    assert alvo.get("usos", 0) == 0 and alvo.get("ultimo_uso") is None


# ============================ ponta-a-ponta (CLI) ===========================

def test_cli_arquivo_escrever_aprovado_grava_de_verdade(nomos_home, capsys, monkeypatch):
    monkeypatch.setattr(cli, "_approver_for", lambda ctx, args: (lambda d: True))
    _ativar("programador")
    rc = cli.main(["agentes", "usar", "programador", "arquivo_escrever",
                   "--alvo", "codigo/ola.py", "--conteudo", "print('ola')\n"])
    assert rc == cli.EXIT_OK
    destino = nomos_home / "workspace" / "codigo" / "ola.py"
    assert destino.exists() and destino.read_text() == "print('ola')\n"
    assert "gravado" in capsys.readouterr().out


def test_cli_arquivo_escrever_sem_aprovacao_e_negado_e_nada_e_escrito(nomos_home, capsys):
    """Sem monkeypatch: interactive_approver de verdade, sem TTY em pytest
    => nega fail-closed (mesmo comportamento provado em test_v14_agentes.py
    para A1 sem aprovador)."""
    _ativar("programador")
    rc = cli.main(["agentes", "usar", "programador", "arquivo_escrever",
                   "--alvo", "nao-deveria-existir.txt", "--conteudo", "x"])
    assert rc == cli.EXIT_DENIED
    assert not (nomos_home / "workspace" / "nao-deveria-existir.txt").exists()


def test_cli_arquivo_escrever_path_traversal_negado_mesmo_aprovado(nomos_home, capsys, monkeypatch):
    """Defesa em profundidade ponta-a-ponta: MESMO com o gate A1 aprovado
    pelo humano, o caminho fora do workspace ainda é recusado — a
    aprovação autoriza a FERRAMENTA, não qualquer caminho no sistema."""
    monkeypatch.setattr(cli, "_approver_for", lambda ctx, args: (lambda d: True))
    _ativar("programador")
    rc = cli.main(["agentes", "usar", "programador", "arquivo_escrever",
                   "--alvo", "../../../../../../tmp/nomos-p1-traversal-teste",
                   "--conteudo", "hostil"])
    assert rc == cli.EXIT_DENIED
    err = capsys.readouterr().err
    assert "DestinoInseguroError" in err or "falhou" in err
    assert not Path("/tmp/nomos-p1-traversal-teste").exists()


def test_cli_codigo_gerar_sem_motor_configurado_e_exit_ok_com_mensagem_honesta(nomos_home, capsys):
    """codigo_gerar é A0 — não precisa de aprovador; sem Ollama/OpenAI-compat
    reais neste ambiente de teste, degrada de forma transparente (nunca
    inventa código, nunca lança exceção não tratada)."""
    _ativar("programador")
    rc = cli.main(["agentes", "usar", "programador", "codigo_gerar",
                   "--alvo", "escreva uma função que soma dois números"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "não consegui gerar código" in out or "motor" in out


def test_cli_skill_rodar_ferramenta_de_agente_customizado_executa_de_verdade(
        nomos_home, capsys, monkeypatch, tmp_path):
    from nomos.agents.manifest import AgentManifest
    from nomos.agents.registry import AgentRegistry
    _instalar_skill_de_teste(nomos_home, tmp_path, name="skill-via-agente")
    assert cli.main(["init"]) == 0
    reg = AgentRegistry(nomos_home)
    reg.instalar(AgentManifest(name="operador", objetivo="roda skills sob demanda",
                               ferramentas=("skill_rodar",), risco_max="A5",
                               pode_executar_skill=True))
    assert cli.main(["agentes", "ativar", "operador"]) == 0
    monkeypatch.setattr(cli, "_approver_for", lambda ctx, args: (lambda d: True))
    rc = cli.main(["agentes", "usar", "operador", "skill_rodar",
                   "--alvo", "skill-via-agente"])
    assert rc == cli.EXIT_OK
    assert "rodou de verdade" in capsys.readouterr().out
    linhas = [json.loads(ln) for ln in
             (nomos_home / "logs" / "audit.jsonl").read_text().splitlines() if ln.strip()]
    usados = [r for r in linhas if r.get("event") == "agente.ferramenta.usada"]
    assert any(r.get("agente") == "operador" and r.get("ferramenta") == "skill_rodar"
              for r in usados)


def test_agente_programador_termina_com_as_3_ferramentas_funcionais(
        nomos_home, capsys, monkeypatch):
    """Critério de aceite explícito da missão: 'Agente programador deve
    terminar com as 3 ferramentas funcionais: arquivo_ler, arquivo_escrever,
    codigo_gerar.' As 3 chamadas abaixo são ponta-a-ponta reais (mesmo
    AgentToolBoundary + agents/execucao.py que qualquer uso em produção)."""
    monkeypatch.setattr(cli, "_approver_for", lambda ctx, args: (lambda d: True))
    _ativar("programador")

    # codigo_gerar: A0, sem motor real disponível -> degrada, mas RODA
    # (não é "ferramenta desconhecida"/"não wired" — é o motor que falta)
    rc = cli.main(["agentes", "usar", "programador", "codigo_gerar",
                   "--alvo", "escreva uma função fatorial"])
    assert rc == cli.EXIT_OK
    assert "não é uma ferramenta conhecida" not in capsys.readouterr().out

    # arquivo_ler: A0, lê um arquivo real
    alvo_leitura = nomos_home / "workspace" / "leitura.md"
    alvo_leitura.parent.mkdir(parents=True, exist_ok=True)
    alvo_leitura.write_text("# Documento\n\nConteúdo de verdade para leitura.\n")
    rc = cli.main(["agentes", "usar", "programador", "arquivo_ler",
                   "--alvo", str(alvo_leitura)])
    assert rc == cli.EXIT_OK
    assert "Documento" in capsys.readouterr().out

    # arquivo_escrever: A1, grava um arquivo real dentro do workspace
    rc = cli.main(["agentes", "usar", "programador", "arquivo_escrever",
                   "--alvo", "saida/gerado.py", "--conteudo", "x = 1\n"])
    assert rc == cli.EXIT_OK
    destino = nomos_home / "workspace" / "saida" / "gerado.py"
    assert destino.exists() and destino.read_text() == "x = 1\n"
