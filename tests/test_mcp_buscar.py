"""Fase 5 — descoberta curada: `nomos mcp buscar <termo>`.

Acha um conector EMBARCADO por nome, pasta ou descrição, sem acento e sem caso,
sem caçar arquivo. Só lista os oficiais; confiar segue manual (não afrouxa nada).
"""
import json
from pathlib import Path

from nomos.interface import mcp_catalogo as cat

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "examples" / "mcp"


def test_busca_por_nome(nomos_home):
    achados = cat.buscar_conectores(nomos_home, "telegram", raiz=EXEMPLOS)
    assert [c["nome"] for c in achados] == ["telegram-bot"]


def test_busca_por_descricao_sem_acento(nomos_home):
    # 'agenda' aparece na descrição do calendário; 'calendario' bate com
    # 'calendário' (sem acento) no nome/descrição
    for termo in ("agenda", "calendario", "CALENDÁRIO"):
        achados = cat.buscar_conectores(nomos_home, termo, raiz=EXEMPLOS)
        assert any(c["nome"] == "calendario-ics" for c in achados), termo


def test_busca_casa_varios_do_mesmo_tema(nomos_home):
    nomes = {c["nome"]
             for c in cat.buscar_conectores(nomos_home, "email", raiz=EXEMPLOS)}
    assert {"email-imap", "email-smtp"} <= nomes


def test_varios_termos_e_conjuncao(nomos_home):
    # dois termos: TODOS precisam bater (E)
    achados = cat.buscar_conectores(nomos_home, "email imap", raiz=EXEMPLOS)
    assert [c["nome"] for c in achados] == ["email-imap"]


def test_termo_vazio_devolve_todos(nomos_home):
    todos = cat.conectores_exemplo(nomos_home, raiz=EXEMPLOS)
    vazio = cat.buscar_conectores(nomos_home, "   ", raiz=EXEMPLOS)
    assert {c["nome"] for c in vazio} == {c["nome"] for c in todos}


def test_sem_correspondencia_e_lista_vazia(nomos_home):
    assert cat.buscar_conectores(nomos_home, "xyzzy-nao-existe", raiz=EXEMPLOS) == []


# --- CLI -------------------------------------------------------------------
def _ctx(nomos_home):
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    nomos_home.mkdir(parents=True, exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
            "skills": nomos_home / "skills"}


def test_cli_buscar_texto_e_json(nomos_home, monkeypatch, capsys):
    from nomos.cli import cmd_mcp
    monkeypatch.chdir(RAIZ)                         # examples/ no cwd
    ctx = _ctx(nomos_home)

    class _Args:
        mcp_cmd = "buscar"
        termo = "agenda"
        json = True

    assert cmd_mcp(ctx, _Args()) == 0
    dados = json.loads(capsys.readouterr().out)
    assert dados["termo"] == "agenda"
    assert any(c["nome"] == "calendario-ics" for c in dados["conectores"])

    _Args.json = False
    assert cmd_mcp(ctx, _Args()) == 0
    saida = capsys.readouterr().out
    assert "calendario-ics" in saida
    assert "ligar: nomos mcp confiar calendario" in saida


def test_cli_buscar_sem_correspondencia(nomos_home, monkeypatch, capsys):
    from nomos.cli import cmd_mcp
    monkeypatch.chdir(RAIZ)
    ctx = _ctx(nomos_home)

    class _Args:
        mcp_cmd = "buscar"
        termo = "naoexistecanal"
        json = False

    assert cmd_mcp(ctx, _Args()) == 0
    saida = capsys.readouterr().out
    assert "nenhum conector" in saida and "nomos mcp exemplos" in saida


def test_parser_tem_mcp_buscar():
    from nomos.cli import build_parser
    a = build_parser().parse_args(["mcp", "buscar", "agenda", "--json"])
    assert a.mcp_cmd == "buscar" and a.termo == "agenda" and a.json is True
