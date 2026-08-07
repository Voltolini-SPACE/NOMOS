"""H4.5-A (missão de selagem arquitetural, 2026-08-04): prova de fail-closed
REAL do PolicyEngine — não só "não crasha" (isso já é HIGH-02, ver
tests/test_policy.py), mas "nunca autoriza uma ação governada quando a
política está indisponível ou de formato inválido", exercitado pelo caminho
público mais próximo da execução real: `nomos agentes usar` (o mesmo
`cmd_agente_usar` -> `AgentToolBoundary.usar_ferramenta()` -> `PolicyEngine.
decide()` -> `gate()` que qualquer usuário real percorre), não uma chamada
isolada a `PolicyEngine.rules()`/`.decide()`.

Casos mínimos cobertos, para cada um dos 6 estados de `policy.json`
(ausente, JSON inválido, raiz `[]`, raiz `null`, raiz string, dict válido):
- nenhuma exceção não tratada escapa do caminho real;
- uma ação NORMALMENTE permitida por padrão (A0/READ_LOCAL, `doutor` via
  agente 'seguranca') só é permitida quando a política é de fato confiável
  (ausente-regenerada ou dict válido — os 2 controles positivos); nos 4
  estados de política não confiável, essa MESMA ação passa a ser negada —
  a prova mais forte de que "regras vazias" não é tratado como "permita
  tudo" (`rules()` devolvendo `{"rules": {}}` não pode virar ALLOW por
  ausência de entrada no dict);
- uma ação governada com escrita (A1/WRITE_LOCAL, `arquivo_escrever` via
  agente 'programador') é negada nos 4 estados de política inválida;
- uma ação de efeito externo (A5/SKILL_INSTALL, `skill_rodar` — nenhum
  agente oficial do catálogo declara essa ferramenta, então usa-se
  `AgentToolBoundary` diretamente, o MESMO mecanismo de enforcement
  compartilhado por `cmd_agente_usar`, não uma reimplementação) é negada
  nos 4 estados de política inválida;
- o caminho de diagnóstico/recuperação (`nomos doutor` / `nomos doutor
  --consertar`) continua funcional em TODOS os 6 estados — ele
  deliberadamente não passa por `PolicyEngine` (ver `cli.py::cmd_doutor`),
  porque é o próprio mecanismo usado para detectar e reparar esse tipo de
  corrupção; sem isso, um `policy.json` corrompido se tornaria
  irrecuperável pela própria ferramenta feita para recuperá-lo.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from nomos import cli
from nomos.agents.boundary import AgentToolBoundary
from nomos.agents.manifest import AgentManifest
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import DEFAULT_RULES, PolicyEngine


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    # não-interativo de propósito: prova que REQUIRE_APPROVAL nega sem TTY,
    # e que "consertar" sem confirmação não aplica nada (fail-closed duplo).
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _ativar(nome: str) -> None:
    assert cli.main(["init"]) == 0
    assert cli.main(["agentes", "ativar", nome]) == 0


def _set_policy(home: Path, conteudo: str | None) -> None:
    """Estado real de policy.json antes da PRÓXIMA chamada a cli.main() —
    _paths() constrói um PolicyEngine NOVO a cada invocação, então isso
    reflete fielmente o que um usuário real veria na próxima execução."""
    p = home / "policy.json"
    if conteudo is None:
        if p.exists():
            p.unlink()
    else:
        p.write_text(conteudo, encoding="utf-8")


# Os 4 estados que tornam a política NÃO confiável (fail-closed esperado
# em TODAS as categorias, inclusive a normalmente-ALLOW).
ESTADOS_INVALIDOS = [
    pytest.param("json_invalido", "{ isso nao eh json valido ::: }", id="json_invalido"),
    pytest.param("raiz_lista", "[]", id="raiz_lista"),
    pytest.param("raiz_null", "null", id="raiz_null"),
    pytest.param("raiz_string", '"nao eh um objeto"', id="raiz_string"),
]


# --------------------------------------------------------------------------
# 1) Ação normalmente ALLOW (A0/READ_LOCAL, "doutor" via agente 'seguranca')
#    — o teste mais importante: prova que "regras vazias" NÃO vira "permita
#    tudo" mesmo para a categoria que É permitida por padrão.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("_id, conteudo", ESTADOS_INVALIDOS)
def test_a0_normalmente_allow_e_negado_com_politica_nao_confiavel(
        nomos_home, capsys, _id, conteudo):
    _ativar("seguranca")
    capsys.readouterr()
    _set_policy(nomos_home, conteudo)

    rc = cli.main(["agentes", "usar", "seguranca", "doutor"])

    assert rc == cli.EXIT_DENIED, (
        f"estado={_id}: uma política não confiável permitiu uma ação "
        f"normalmente ALLOW (A0) — isso é 'regras vazias == permita tudo', "
        f"exatamente o que o fail-closed deve impedir")
    err = capsys.readouterr().err
    assert "negada" in err or "precisa de aprovação" in err


def test_a0_controle_positivo_ausente_regenera_padrao_seguro_e_permite(
        nomos_home, capsys):
    """Controle positivo #1: policy.json AUSENTE não é o mesmo que
    'corrompido' — PolicyEngine.__init__ regenera o default seguro
    (read-only) quando o arquivo não existe. Sem este controle, o teste
    acima seria inútil (poderia estar sempre negando por acidente)."""
    _ativar("seguranca")
    capsys.readouterr()
    _set_policy(nomos_home, None)          # ausente

    rc = cli.main(["agentes", "usar", "seguranca", "doutor"])

    assert rc == cli.EXIT_OK, "policy.json ausente deveria regenerar o " \
        "default seguro (read-only) e permitir A0, não negar tudo"
    assert "STATUS GERAL" in capsys.readouterr().out


def test_a0_controle_positivo_dict_valido_permite(nomos_home, capsys):
    """Controle positivo #2: um dict de regras explicitamente válido
    também permite A0 — prova que a negação nos 4 estados inválidos é
    especificamente por causa do formato ruim, não um bug que nega tudo
    incondicionalmente."""
    _ativar("seguranca")
    capsys.readouterr()
    import json
    payload = {"version": 1, "mode": "read_only_default",
               "fail_closed": True, "rules": DEFAULT_RULES}
    _set_policy(nomos_home, json.dumps(payload))

    rc = cli.main(["agentes", "usar", "seguranca", "doutor"])

    assert rc == cli.EXIT_OK
    assert "STATUS GERAL" in capsys.readouterr().out


# --------------------------------------------------------------------------
# 2) Ação governada de escrita (A1/WRITE_LOCAL, "arquivo_escrever" via
#    agente 'programador') — negada nos 4 estados inválidos.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("_id, conteudo", ESTADOS_INVALIDOS)
def test_a1_escrita_negada_com_politica_nao_confiavel(
        nomos_home, capsys, _id, conteudo):
    _ativar("programador")
    capsys.readouterr()
    _set_policy(nomos_home, conteudo)

    rc = cli.main(["agentes", "usar", "programador", "arquivo_escrever",
                   "--alvo", "notas/nao-deveria-existir.txt"])

    assert rc == cli.EXIT_DENIED, (
        f"estado={_id}: uma escrita (A1) foi permitida com política "
        f"não confiável")
    assert not (nomos_home / "workspace" / "notas" /
                "nao-deveria-existir.txt").exists()


# --------------------------------------------------------------------------
# 3) Ação de efeito externo (A5/SKILL_INSTALL, "skill_rodar") — nenhum
#    agente oficial declara essa ferramenta; usa-se AgentToolBoundary
#    diretamente (mesmo mecanismo de enforcement de cmd_agente_usar, não
#    uma reimplementação/duplicação da lógica de policy).
# --------------------------------------------------------------------------

def _boundary_skill_rodar(nomos_home: Path) -> AgentToolBoundary:
    mf = AgentManifest(name="operador-skill", objetivo="rodar skills",
                       ferramentas=("skill_rodar",), risco_max="A5",
                       pode_executar_skill=True)
    policy = PolicyEngine(nomos_home / "policy.json")
    audit = AuditLog(nomos_home / "logs" / "audit.jsonl")
    return AgentToolBoundary(mf, policy, approver=lambda d: True, audit=audit)


@pytest.mark.parametrize("_id, conteudo", ESTADOS_INVALIDOS)
def test_a5_efeito_externo_negado_com_politica_nao_confiavel(
        nomos_home, _id, conteudo):
    import nomos.kernel.config as config
    config.ensure_home()
    _set_policy(nomos_home, conteudo)
    b = _boundary_skill_rodar(nomos_home)

    executado = {"chamou": False}

    def _executar_skill():
        executado["chamou"] = True
        return "skill rodou"

    ok, resultado = b.usar_ferramenta("skill_rodar", _executar_skill,
                                      alvo="skill-qualquer")

    assert ok is False, (
        f"estado={_id}: uma ação de efeito externo (A5/skill_rodar) foi "
        f"permitida com política não confiável")
    assert executado["chamou"] is False, (
        f"estado={_id}: a skill FOI EXECUTADA mesmo negada pelo gate — "
        f"isso seria um bypass real, não apenas um retorno incorreto")


def test_a5_controle_positivo_com_aprovador_e_politica_valida_permite(nomos_home):
    """Controle positivo: com política válida E aprovador que confirma,
    skill_rodar (A5, REQUIRE_APPROVAL por padrão) É permitido — prova que
    o boundary não está simplesmente configurado para negar A5 sempre."""
    import nomos.kernel.config as config
    config.ensure_home()
    # política padrão explícita e válida (mesma forma do controle acima)
    import json
    payload = {"version": 1, "mode": "read_only_default",
               "fail_closed": True, "rules": DEFAULT_RULES}
    _set_policy(nomos_home, json.dumps(payload))
    b = _boundary_skill_rodar(nomos_home)

    ok, resultado = b.usar_ferramenta("skill_rodar", lambda: "skill rodou",
                                      alvo="skill-qualquer")

    assert ok is True
    assert resultado == "skill rodou"


# --------------------------------------------------------------------------
# 4) Diagnóstico/recuperação continuam disponíveis mesmo com política
#    corrompida — deliberadamente não passam por PolicyEngine.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("_id, conteudo", ESTADOS_INVALIDOS)
def test_doutor_diagnostico_funciona_mesmo_com_politica_corrompida(
        nomos_home, capsys, _id, conteudo):
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    _set_policy(nomos_home, conteudo)

    rc = cli.main(["doutor"])

    assert rc == cli.EXIT_OK, (
        f"estado={_id}: o diagnóstico (nomos doutor, sem agente/boundary) "
        f"não deveria depender de PolicyEngine e não pode falhar aqui — "
        f"senão um policy.json corrompido fica irrecuperável pela própria "
        f"ferramenta feita para recuperá-lo")
    assert "STATUS GERAL" in capsys.readouterr().out


@pytest.mark.parametrize("_id, conteudo", ESTADOS_INVALIDOS)
def test_doutor_consertar_sem_confirmacao_nao_crasha_e_nao_aplica_nada(
        nomos_home, capsys, _id, conteudo):
    """Recuperação exige autorização explícita (TTY interativo digitando
    'CONSERTAR') — sem ela, nada muda (fail-closed duplo: o diagnóstico
    funciona, mas o reparo em si continua gated). Aqui provamos que essa
    checagem de autorização não crasha mesmo com policy.json corrompido."""
    assert cli.main(["init"]) == 0
    capsys.readouterr()
    conteudo_antes = None
    p = nomos_home / "policy.json"
    _set_policy(nomos_home, conteudo)
    if p.exists():
        conteudo_antes = p.read_text(encoding="utf-8")

    rc = cli.main(["doutor", "--consertar"])

    assert rc == cli.EXIT_DENIED   # sem TTY -> _confirmar() nega -> rc=3
    err = capsys.readouterr().err
    assert "terminal interativo" in err
    # nada foi alterado: o policy.json corrompido continua exatamente como
    # estava (a evidência da corrupção não foi destruída por um reparo
    # não autorizado)
    if conteudo_antes is not None:
        assert p.read_text(encoding="utf-8") == conteudo_antes
