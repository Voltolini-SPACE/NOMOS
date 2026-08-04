"""H4.5-C (missão de selagem arquitetural, 2026-08-04): gate arquitetural
mínimo contra bypass de `AgentToolBoundary` — prova por AST (biblioteca
padrão, nenhuma dependência nova) que:

1. só os 2 callers de produção conhecidos (`cli.py::cmd_agente_usar`,
   `simple/amigavel.py::_usar_agente_conversa` — ambos já provados, por
   leitura de código, a só invocar as funções `exec_*` de
   `agents.execucao` DEPOIS de passar por `AgentToolBoundary.
   usar_ferramenta()`) importam `nomos.agents.execucao` diretamente.
   Qualquer OUTRO módulo que passe a importar esse executor concreto é,
   por definição, um candidato a bypass — nenhum caminho de execução
   governada deveria chamar `exec_*` sem primeiro passar pelo gate;
2. os próprios módulos de `nomos.agents` (`boundary.py`, `execucao.py`,
   `manifest.py`, `registry.py`, `__init__.py`) nunca importam
   subprocess/rede diretamente — se uma ferramenta precisar disso
   (`skill_rodar`), a chamada real vive em outro módulo já dedicado a
   isso (`ext.skill_registry`), nunca inline aqui;
3. nenhum módulo de `nomos.council` (o orquestrador dry-run) importa
   `nomos.agents` OU subprocess/rede diretamente — generaliza, para o
   PACOTE inteiro, o mesmo invariante que
   `tests/council/test_orchestrator_security.py` já prova só para
   `orchestrator.py` (reaproveita a MESMA técnica AST — `ast.walk` sobre
   `ast.Import`/`ast.ImportFrom` —, não duplica um framework novo).

Este arquivo reaproveita a convenção de "pureza por AST" já estabelecida
em `tests/council/test_orchestrator_security.py` e
`tests/test_council_safe_output.py`, generalizada para varrer PASTAS
inteiras (não um módulo fixo) e parametrizada, para poder ser exercitada
tanto contra o código real quanto contra uma fixture sintética — a
própria missão exige que o gate NÃO passe apenas "por não encontrar
arquivos" (`test_gate_detecta_bypass_sintetico_*` abaixo prova isso).
"""
from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "src" / "nomos"


# --------------------------------------------------------------------------
# Motor do gate (reutilizável — mesma técnica de
# tests/council/test_orchestrator_security.py, generalizada para pastas)
# --------------------------------------------------------------------------

def _imports_de(caminho: Path) -> set[str]:
    """Nomes de módulo importados por um arquivo .py (Import e ImportFrom),
    por AST — não por regex/grep, então comentários e strings não geram
    falso positivo/negativo."""
    src = caminho.read_text(encoding="utf-8")
    nomes: set[str] = set()
    for node in ast.walk(ast.parse(src, filename=str(caminho))):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _arquivos_py(pasta: Path) -> list[Path]:
    return sorted(p for p in pasta.rglob("*.py") if "__pycache__" not in p.parts)


def _bate(usados: set[str], alvo: str) -> bool:
    """True se `alvo` foi importado, direto OU como pai de um submódulo
    importado (ex.: alvo='nomos.agents' bate com 'nomos.agents.execucao')."""
    return any(m == alvo or m.startswith(alvo + ".") for m in usados)


def _quem_importa(pasta: Path, alvo: str, *, excluir: set[Path] = frozenset()) -> dict[Path, set[str]]:
    """{arquivo: imports} para todo .py sob `pasta` (recursivo) cujos
    imports batem com `alvo` (ver `_bate`). `excluir` é absoluto."""
    achados: dict[Path, set[str]] = {}
    for p in _arquivos_py(pasta):
        if p.resolve() in excluir:
            continue
        usados = _imports_de(p)
        if _bate(usados, alvo):
            achados[p] = usados
    return achados


PROIBIDOS_EXECUCAO_DIRETA = {
    "subprocess", "socket", "ssl", "http", "http.client",
    "urllib.request", "requests", "httpx", "aiohttp", "ftplib", "smtplib",
}


def _quem_importa_qualquer(pasta: Path, proibidos: set[str],
                           *, excluir: set[Path] = frozenset()) -> dict[Path, set[str]]:
    achados: dict[Path, set[str]] = {}
    for p in _arquivos_py(pasta):
        if p.resolve() in excluir:
            continue
        usados = _imports_de(p)
        bateu = usados & proibidos
        if bateu:
            achados[p] = bateu
    return achados


# --------------------------------------------------------------------------
# 1) Allowlist EXATA de quem pode importar nomos.agents.execucao
#    (o executor concreto das 8 ferramentas — só deve ser chamado DEPOIS
#    do gate do AgentToolBoundary)
# --------------------------------------------------------------------------

ALLOWLIST_IMPORTA_EXECUCAO = {
    (SRC / "cli.py").resolve(),
    (SRC / "simple" / "amigavel.py").resolve(),
}


def test_so_a_allowlist_declarada_importa_agents_execucao_diretamente():
    achados = _quem_importa(SRC, "nomos.agents.execucao",
                            excluir={(SRC / "agents" / "execucao.py").resolve()})
    encontrados = set(achados.keys())
    inesperados = encontrados - ALLOWLIST_IMPORTA_EXECUCAO
    assert not inesperados, (
        f"módulo(s) fora da allowlist importando nomos.agents.execucao "
        f"diretamente (candidato a bypass do AgentToolBoundary): "
        f"{[str(p.relative_to(RAIZ)) for p in inesperados]}")
    faltando = ALLOWLIST_IMPORTA_EXECUCAO - encontrados
    assert not faltando, (
        f"allowlist desatualizada — arquivo(s) que deveriam importar "
        f"agents.execucao não importam mais (allowlist deve refletir a "
        f"realidade, não ficar frouxa por inércia): "
        f"{[str(p.relative_to(RAIZ)) for p in faltando]}")


def test_ambos_callers_da_allowlist_de_fato_usam_agenttoolboundary():
    """Não basta importar `agents.execucao` — checa (textualmente, o mais
    simples que prova a intenção sem reimplementar um linter de fluxo de
    dados) que os 2 arquivos permitidos também referenciam
    AgentToolBoundary no mesmo arquivo, ou seja, não é só um import solto
    sem uso do gate."""
    for caminho in sorted(ALLOWLIST_IMPORTA_EXECUCAO):
        src = caminho.read_text(encoding="utf-8")
        assert "AgentToolBoundary" in src, (
            f"{caminho.relative_to(RAIZ)} importa agents.execucao mas não "
            f"referencia AgentToolBoundary — chamaria o executor sem gate?")


# --------------------------------------------------------------------------
# 2) nomos.agents.* nunca importa subprocess/rede diretamente
# --------------------------------------------------------------------------

def test_modulos_agents_nao_importam_execucao_direta_de_processo_ou_rede():
    pasta_agents = SRC / "agents"
    achados = _quem_importa_qualquer(pasta_agents, PROIBIDOS_EXECUCAO_DIRETA)
    assert not achados, {
        str(p.relative_to(RAIZ)): sorted(m) for p, m in achados.items()}


# --------------------------------------------------------------------------
# 3) nomos.council nunca importa nomos.agents nem executa processo/rede
#    diretamente — generaliza, para o pacote inteiro, o mesmo invariante
#    que tests/council/test_orchestrator_security.py já prova só para
#    orchestrator.py.
# --------------------------------------------------------------------------

def test_pacote_council_nunca_importa_nomos_agents():
    pasta_council = SRC / "council"
    achados = _quem_importa(pasta_council, "nomos.agents")
    assert not achados, {
        str(p.relative_to(RAIZ)): sorted(m) for p, m in achados.items()}


def test_pacote_council_nao_importa_execucao_direta_de_processo_ou_rede():
    pasta_council = SRC / "council"
    achados = _quem_importa_qualquer(pasta_council, PROIBIDOS_EXECUCAO_DIRETA)
    assert not achados, {
        str(p.relative_to(RAIZ)): sorted(m) for p, m in achados.items()}


# --------------------------------------------------------------------------
# 4) Fixtures sintéticas — provam que o gate DETECTA um bypass real,
#    não passa apenas "por não encontrar arquivos" (exigência explícita
#    da missão).
# --------------------------------------------------------------------------

def test_gate_detecta_bypass_sintetico_de_execucao_direta(tmp_path):
    pasta = tmp_path / "pacote_fake"
    pasta.mkdir()
    (pasta / "orquestrador_suspeito.py").write_text(
        "from nomos.agents.execucao import ferramentas_wired\n"
        "\n"
        "def rodar_sem_gate(ctx):\n"
        "    return ferramentas_wired(ctx)['skill_rodar']()\n",
        encoding="utf-8")
    (pasta / "modulo_inocente.py").write_text(
        "import json\n\ndef ok():\n    return json.dumps({})\n",
        encoding="utf-8")

    achados = _quem_importa(pasta, "nomos.agents.execucao")

    assert len(achados) == 1, achados
    (caminho,) = achados.keys()
    assert caminho.name == "orquestrador_suspeito.py"


def test_gate_detecta_agente_sintetico_chamando_subprocess_direto(tmp_path):
    pasta = tmp_path / "agents_fake"
    pasta.mkdir()
    (pasta / "ferramenta_perigosa.py").write_text(
        "import subprocess\n\n"
        "def roda_comando_sem_boundary(cmd):\n"
        "    return subprocess.run(cmd, shell=True)\n",
        encoding="utf-8")

    achados = _quem_importa_qualquer(pasta, PROIBIDOS_EXECUCAO_DIRETA)

    assert len(achados) == 1, achados
    (caminho, proibidos_usados), = achados.items()
    assert caminho.name == "ferramenta_perigosa.py"
    assert "subprocess" in proibidos_usados


def test_gate_detecta_orquestrador_sintetico_importando_agents(tmp_path):
    pasta = tmp_path / "council_fake"
    pasta.mkdir()
    (pasta / "orchestrator_bypass.py").write_text(
        "from nomos.agents.boundary import AgentToolBoundary\n\n"
        "def atalho():\n"
        "    return AgentToolBoundary\n",
        encoding="utf-8")

    achados = _quem_importa(pasta, "nomos.agents")

    assert len(achados) == 1, achados
    (caminho,) = achados.keys()
    assert caminho.name == "orchestrator_bypass.py"


def test_gate_nao_falha_positivo_em_arvore_vazia_mas_tambem_nao_finge_sucesso(tmp_path):
    """Uma pasta vazia devolve 'nada encontrado' — mas isso não pode ser
    confundido com 'o gate passou porque verificou e está tudo bem': os 3
    testes acima (com conteúdo sintético real) são a prova positiva de
    detecção; este aqui só documenta que o caso degenerado não lança
    exceção nem esconde nada."""
    pasta_vazia = tmp_path / "vazia"
    pasta_vazia.mkdir()
    assert _quem_importa(pasta_vazia, "nomos.agents.execucao") == {}
    assert _arquivos_py(pasta_vazia) == []
