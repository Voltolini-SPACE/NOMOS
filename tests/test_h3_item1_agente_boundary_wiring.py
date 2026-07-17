"""Horizonte 3, item 1 (auditoria de 2026-07-17): wiring real e fail-closed
do AgentToolBoundary — fecha o achado P2-6 (Horizonte 2).

`nomos agentes usar <nome> <ferramenta>` é o primeiro caller de produção do
AgentToolBoundary (agents/boundary.py, lógica intocada — só o docstring foi
atualizado). Este arquivo cobre exclusivamente o NOVO caminho (cli.py::
cmd_agente_usar e os `_exec_*` que ele usa); o contrato do boundary em si
(fora do manifesto nega, A1+ exige aprovação, auditoria de uso/negação,
nenhuma herança entre agentes) já está coberto por tests/test_v14_agentes.py
e não é duplicado aqui — todos os 14 testes daquele arquivo continuam
passando sem nenhuma alteração, prova de que a lógica de autorização não
mudou.

Ferramentas com execução real ligada nesta rodada (todas Category.READ_LOCAL,
== A0, sempre permitidas pela política sem necessidade de aprovação):
memoria_buscar, arquivo_ler, arquivo_resumir, doutor, logs_verificar.
arquivo_escrever, codigo_gerar e skill_rodar ficam EXPLICITAMENTE sem
execução ligada (gap documentado, não escondido) — cobertos aqui pelos
testes que provam a recusa clara, fail-closed, sem fingir sucesso.
"""
import json
from pathlib import Path

import pytest

from nomos import cli


def _ativar(nome: str) -> None:
    assert cli.main(["init"]) == 0
    assert cli.main(["agentes", "ativar", nome]) == 0


# --------------------- validações antes do boundary ---------------------

def test_usar_agente_inexistente_da_erro_claro(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    rc = cli.main(["agentes", "usar", "fantasma", "doutor"])
    assert rc == cli.EXIT_ERROR
    assert "não existe" in capsys.readouterr().err


def test_usar_agente_inativo_e_negado(nomos_home, capsys):
    # descoberta ao rodar de verdade: agentes catalogados vêm ATIVOS por
    # padrão (nomos.ext.skill_status.esta_ativa — "instalou, funciona";
    # desativação é explícita) — diferente da suposição inicial deste teste.
    # Para exercitar o ramo "inativo" é preciso desativar explicitamente.
    assert cli.main(["init"]) == 0
    assert cli.main(["agentes", "desativar", "seguranca"]) == 0
    capsys.readouterr()
    rc = cli.main(["agentes", "usar", "seguranca", "doutor"])
    assert rc == cli.EXIT_DENIED
    err = capsys.readouterr().err
    assert "inativo" in err and "agentes ativar" in err


def test_usar_ferramenta_desconhecida_da_erro_claro(nomos_home, capsys):
    _ativar("seguranca")
    rc = cli.main(["agentes", "usar", "seguranca", "teleporte"])
    assert rc == cli.EXIT_ERROR
    assert "não é uma ferramenta conhecida" in capsys.readouterr().err


@pytest.mark.parametrize("ferramenta", ["arquivo_escrever", "codigo_gerar", "skill_rodar"])
def test_ferramentas_deliberadamente_nao_wired_recusam_sem_fingir_sucesso(
        nomos_home, capsys, ferramenta):
    """arquivo_escrever/codigo_gerar/skill_rodar: gap documentado, não escondido.

    'programador' declara arquivo_escrever e codigo_gerar no manifesto oficial;
    para skill_rodar usamos um agente customizado só para o teste (nenhum
    oficial declara). Em nenhum caso o comando finge sucesso.
    """
    _ativar("programador")
    if ferramenta == "skill_rodar":
        # instala um agente custom com skill_rodar só para exercitar este
        # ramo — precisa de pode_executar_skill=True para o manifesto validar
        from nomos.agents.manifest import AgentManifest
        from nomos.agents.registry import AgentRegistry
        reg = AgentRegistry(nomos_home)
        reg.instalar(AgentManifest(name="operador", objetivo="t",
                                   ferramentas=("skill_rodar",), risco_max="A5",
                                   pode_executar_skill=True))
        assert cli.main(["agentes", "ativar", "operador"]) == 0
        agente = "operador"
    else:
        agente = "programador"
    rc = cli.main(["agentes", "usar", agente, ferramenta])
    assert rc == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert "ainda não tem execução ligada" in err
    assert "Horizonte 3" in err
    # nada foi silenciosamente aprovado/negado no boundary — o pedido nunca
    # chegou a construir a boundary, então não há entrada de auditoria dele
    log = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert f'"ferramenta": "{ferramenta}"' not in log


def test_ferramenta_wired_mas_fora_do_manifesto_do_agente_e_negada(nomos_home, capsys):
    """arquivo_ler está wired, mas 'seguranca' não o declara — o boundary
    (não o dispatch de wiring) é quem recusa; mesma garantia do Horizonte 1/2:
    agente não herda ferramenta que não é sua."""
    _ativar("seguranca")
    rc = cli.main(["agentes", "usar", "seguranca", "arquivo_ler", "--alvo", "x.txt"])
    assert rc == cli.EXIT_DENIED
    assert "não tem a ferramenta" in capsys.readouterr().err
    log = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "agente.ferramenta.negada" in log


# ------------------------- ferramentas wired: sucesso -------------------------

def test_memoria_buscar_sucesso_e_redige_segredo(nomos_home, capsys):
    # redact_text() é por PADRÃO de segredo real (chaves sk-/AKIA/gh_/Bearer/
    # JWT/etc — kernel/audit.py:SECRET_PATTERNS), não por palavra-gatilho
    # como "senha" — descoberta ao rodar de verdade (1ª versão deste teste
    # usava "supersecreta123", que nenhum padrão reconhece, e falhava). Usa
    # um formato de chave real reconhecido para testar a redação de verdade.
    from nomos.cognition.memory import Memory
    _ativar("pesquisador-local")
    mem = Memory(nomos_home / "memory.db")
    mem.remember("user", "minha chave de wifi/API é sk-abcdefgh12345678")
    mem.close()
    rc = cli.main(["agentes", "usar", "pesquisador-local", "memoria_buscar",
                   "--alvo", "wifi"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "wifi" in out
    assert "sk-abcdefgh12345678" not in out         # redigido, igual ao MCP


def test_memoria_buscar_sem_alvo_pede_alvo_sem_falhar(nomos_home, capsys):
    _ativar("pesquisador-local")
    rc = cli.main(["agentes", "usar", "pesquisador-local", "memoria_buscar"])
    assert rc == cli.EXIT_OK                        # autorizado, só faltou o argumento
    assert "informe --alvo" in capsys.readouterr().out


def test_arquivo_ler_sucesso(nomos_home, capsys, tmp_path):
    _ativar("pesquisador-local")
    alvo = tmp_path / "doc.md"
    alvo.write_text("# Título\n\nConteúdo relevante do documento de teste.\n")
    rc = cli.main(["agentes", "usar", "pesquisador-local", "arquivo_ler",
                   "--alvo", str(alvo)])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "formato: md" in out and "Título" in out


def test_arquivo_ler_arquivo_inexistente_nega_sem_crashar(nomos_home, capsys, tmp_path):
    _ativar("pesquisador-local")
    rc = cli.main(["agentes", "usar", "pesquisador-local", "arquivo_ler",
                   "--alvo", str(tmp_path / "nao-existe.md")])
    assert rc == cli.EXIT_DENIED
    assert "falhou" in capsys.readouterr().err


def test_arquivo_resumir_sem_motor_usa_heuristica_e_nunca_grava_arquivo(
        nomos_home, capsys, tmp_path):
    _ativar("pesquisador-local")
    alvo = tmp_path / "relatorio.txt"
    alvo.write_text("- primeiro ponto importante\n- segundo ponto relevante\n")
    rc = cli.main(["agentes", "usar", "pesquisador-local", "arquivo_resumir",
                   "--alvo", str(alvo), "--sem-motor"])
    assert rc == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "sem cérebro de IA" in out or "Pontos do documento" in out
    # salvar=False é hardcoded em _exec_arquivo_resumir — nenhum .resumo.md
    assert not (tmp_path / "relatorio.txt.resumo.md").exists()


def test_doutor_sucesso(nomos_home, capsys):
    _ativar("seguranca")
    rc = cli.main(["agentes", "usar", "seguranca", "doutor"])
    assert rc == cli.EXIT_OK
    assert "STATUS GERAL" in capsys.readouterr().out


def test_logs_verificar_sucesso_log_vazio_e_integro(nomos_home, capsys):
    _ativar("seguranca")
    rc = cli.main(["agentes", "usar", "seguranca", "logs_verificar"])
    assert rc == cli.EXIT_OK
    assert "íntegro" in capsys.readouterr().out


# ------------------------- auditoria real -------------------------

def test_uso_real_grava_auditoria_com_agente_e_ferramenta(nomos_home, capsys):
    _ativar("seguranca")
    assert cli.main(["agentes", "usar", "seguranca", "doutor"]) == cli.EXIT_OK
    capsys.readouterr()
    log = (nomos_home / "logs" / "audit.jsonl").read_text()
    linhas = [json.loads(linha) for linha in log.splitlines() if linha.strip()]
    usados = [r for r in linhas if r.get("event") == "agente.ferramenta.usada"]
    assert any(r.get("agente") == "seguranca" and r.get("ferramenta") == "doutor"
              for r in usados)


# ------------------------- doutor reflete o estado novo -------------------------

def test_doutor_cli_menciona_comando_real_de_uso(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["doutor"]) == 0
    out = capsys.readouterr().out
    assert "nomos agentes usar" in out
    assert "5/8" in out


RAIZ = Path(__file__).resolve().parent.parent


def test_agentes_oficiais_continuam_validos_apos_mudanca_de_docstrings(nomos_home):
    """Só docstrings de agents/__init__.py e agents/boundary.py mudaram —
    prova indireta de que nenhuma validação de manifesto foi afetada."""
    from nomos.agents.registry import AgentRegistry
    from nomos.agents.manifest import validar
    reg = AgentRegistry("/tmp/nao-existe-home-h3", extras_dir=RAIZ / "examples" / "agents")
    for m in reg.listar():
        assert validar(m) == []
