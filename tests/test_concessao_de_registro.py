"""Concessão de registro — a autorização durável de REGISTRAR capacidade.

Cobre a matriz A–J da missão ECOSSISTEMA-02/Task #12:

A pedido novo                      -> exige decisão (sem concessão, sem aprovador => negado)
B decisão autorizada               -> registra
C mesma capacidade em NOVO runtime -> registra SEM nova intervenção humana
D restart do serviço               -> idem C (instância nova, processo novo)
E TTL do PEDIDO != TTL da CONCESSÃO
F capacidade fora de registro:*    -> concessão recusada (fail-closed)
G ampliação de escopo              -> digest diferente => cai no gate
H revogação explícita              -> volta a exigir humano
I N registros com a mesma concessão-> zero aprovações duplicadas
J auditoria distingue DECISÃO de USO
"""
from __future__ import annotations

import json

import pytest

from nomos.kernel.audit import AuditLog
from nomos.kernel.concessoes import ConcessaoError, RegistroConcessoes
from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.registro import ErroRegistro, RegistroCapacidades

CAP = "fs-apagar-teste"
ORIGEM = "adapters.filesystem"


def _executor(**_):
    return None


@pytest.fixture
def ambiente(tmp_path):
    policy = PolicyEngine(tmp_path / "policy.json")
    audit = AuditLog(tmp_path / "audit.jsonl")
    concessoes = RegistroConcessoes(tmp_path / "concessoes.json", audit=audit)
    return policy, audit, concessoes, tmp_path


def _registro(policy, audit, concessoes, approver=None):
    return RegistroCapacidades(policy=policy, approver=approver, audit=audit,
                               concessoes=concessoes)


def _conceder(registro, concessoes, *, categoria=Category.WRITE_LOCAL,
              origem=ORIGEM, ttl_dias=30):
    op = registro.operacao_de_registro(CAP, categoria, origem, False)
    return concessoes.conceder(op, ttl_dias=ttl_dias, motivo="teste", dono="dono")


def _eventos(audit_path):
    return [json.loads(l)["event"] for l in
            audit_path.read_text().splitlines() if l.strip()]


# ----------------------------------------------------------------- A, B
def test_a_sem_concessao_e_sem_aprovador_e_negado(ambiente):
    policy, audit, concessoes, _ = ambiente
    reg = _registro(policy, audit, concessoes, approver=None)
    with pytest.raises(ErroRegistro):
        reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)


def test_b_decisao_humana_autoriza_o_registro(ambiente):
    policy, audit, concessoes, _ = ambiente
    reg = _registro(policy, audit, concessoes, approver=lambda _d: True)
    cap = reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)
    assert cap.nome == CAP and reg.conhecida(CAP)


# ----------------------------------------------------------------- C, D
def test_c_novo_runtime_reusa_a_concessao_sem_humano(ambiente):
    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    _conceder(base, concessoes)

    chamadas = []

    def aprovador_que_nao_deveria_ser_chamado(_d):
        chamadas.append(1)
        return False

    novo = _registro(policy, audit, concessoes,
                     approver=aprovador_que_nao_deveria_ser_chamado)
    novo.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)
    assert novo.conhecida(CAP)
    assert chamadas == [], "concessão vigente não pode acionar o aprovador"


def test_d_restart_do_servico_preserva_a_autorizacao(ambiente):
    """Restart = registro NOVO lendo o MESMO arquivo de concessões."""
    policy, audit, concessoes, tmp_path = ambiente
    base = _registro(policy, audit, concessoes)
    _conceder(base, concessoes)

    # simula processo novo: instância nova de RegistroConcessoes sobre o disco
    concessoes_pos_restart = RegistroConcessoes(tmp_path / "concessoes.json",
                                                audit=audit)
    reg = _registro(policy, audit, concessoes_pos_restart, approver=lambda _d: False)
    reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)
    assert reg.conhecida(CAP)


# -------------------------------------------------------------------- E
def test_e_ttl_do_pedido_nao_e_o_ttl_da_concessao(ambiente):
    """O pedido da fila expira em 300 s; a concessão tem prazo próprio, em dias.

    Uma concessão de 30 dias continua vigente muito depois de qualquer pedido
    ter expirado — é exatamente a confusão que travava o serviço em laço.
    """
    from nomos.kernel.approvals import DEFAULT_TTL_S

    policy, audit, concessoes, tmp_path = ambiente
    relogio = {"t": 1000.0}
    conc = RegistroConcessoes(tmp_path / "c2.json", audit=audit,
                              clock=lambda: relogio["t"])
    base = _registro(policy, audit, conc)
    op = base.operacao_de_registro(CAP, Category.WRITE_LOCAL, ORIGEM, False)
    conc.conceder(op, ttl_dias=30)

    relogio["t"] += DEFAULT_TTL_S * 10          # muito além do TTL do PEDIDO
    assert conc.vigente(op.digest()), "TTL do pedido não pode matar a concessão"

    relogio["t"] += 31 * 86400                  # além do TTL da CONCESSÃO
    assert not conc.vigente(op.digest())


def test_e2_concessao_expirada_persiste_revogada(ambiente):
    policy, audit, concessoes, tmp_path = ambiente
    relogio = {"t": 1000.0}
    conc = RegistroConcessoes(tmp_path / "c3.json", audit=audit,
                              clock=lambda: relogio["t"])
    base = _registro(policy, audit, conc)
    op = base.operacao_de_registro(CAP, Category.WRITE_LOCAL, ORIGEM, False)
    conc.conceder(op, ttl_dias=1)
    relogio["t"] += 2 * 86400
    assert not conc.vigente(op.digest())
    assert op.digest() not in json.loads(
        (tmp_path / "c3.json").read_text())["concessoes"]


# -------------------------------------------------------------------- F
def test_f_alvo_fora_de_registro_e_recusado(ambiente):
    """Concessão jamais pré-autoriza execução ou outra categoria."""
    from nomos.pdp.aprovacao import OperacaoAprovavel

    _, _, concessoes, _ = ambiente
    for recurso in ("exec:rm -rf /", "skill:qualquer", "", "registroX:fs-apagar"):
        op = OperacaoAprovavel(sujeito="x", capacidade="c", recurso=recurso,
                               classe_de_risco="A5")
        with pytest.raises(ConcessaoError):
            concessoes.conceder(op)


def test_f2_ttl_nao_positivo_e_recusado(ambiente):
    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    op = base.operacao_de_registro(CAP, Category.WRITE_LOCAL, ORIGEM, False)
    for ttl in (0, -1):
        with pytest.raises(ConcessaoError):
            concessoes.conceder(op, ttl_dias=ttl)


# -------------------------------------------------------------------- G
@pytest.mark.parametrize("mudanca", ["categoria", "origem", "politica"])
def test_g_ampliacao_de_escopo_nao_e_coberta(ambiente, mudanca):
    """Conceder fs-apagar@A1@filesystem não autoriza um homônimo diferente."""
    policy, audit, concessoes, tmp_path = ambiente
    base = _registro(policy, audit, concessoes)
    _conceder(base, concessoes, categoria=Category.WRITE_LOCAL, origem=ORIGEM)

    if mudanca == "categoria":
        cat, origem = Category.DESTRUCTIVE, ORIGEM
    elif mudanca == "origem":
        cat, origem = Category.WRITE_LOCAL, "skill.maliciosa"
    else:
        # Editar policy.json DEVE invalidar toda concessão: o "APROVO" foi dado
        # sob as regras antigas. Provado aqui de forma DIRETA (o digest muda),
        # não só pelo efeito colateral no registrar().
        cat, origem = Category.WRITE_LOCAL, ORIGEM
        digest_antes = base.operacao_de_registro(CAP, cat, origem, False).digest()
        regras = json.loads((tmp_path / "policy.json").read_text())
        regras["_regra_nova_do_dono"] = "ALLOW"
        (tmp_path / "policy.json").write_text(json.dumps(regras))
        policy = PolicyEngine(tmp_path / "policy.json")
        outro = _registro(policy, audit, concessoes)
        assert outro.operacao_de_registro(CAP, cat, origem, False).digest() \
            != digest_antes, "mudar policy.json tem de mudar o digest"

    reg = _registro(policy, audit, concessoes, approver=lambda _d: False)
    with pytest.raises(ErroRegistro):
        reg.registrar(CAP, cat, _executor, origem)


def test_g2_deny_nunca_vira_permissao(ambiente, tmp_path):
    """Concessão só substitui o passo humano de REQUIRE_APPROVAL."""
    from nomos.kernel.policy import Effect

    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    _conceder(base, concessoes)

    class PolicyDeny:
        def decide(self, *_a, **_k):
            class D:
                effect = Effect.DENY
                reason = "negado por política"
            return D()

        def rules(self):
            return policy.rules()

    reg = RegistroCapacidades(policy=PolicyDeny(), approver=lambda _d: True,
                              audit=audit, concessoes=concessoes)
    with pytest.raises(ErroRegistro):
        reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)


# -------------------------------------------------------------------- H
def test_h_revogacao_volta_a_exigir_humano(ambiente):
    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    entrada = _conceder(base, concessoes)

    assert concessoes.revogar(entrada["digest"]) is True
    reg = _registro(policy, audit, concessoes, approver=lambda _d: False)
    with pytest.raises(ErroRegistro):
        reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)


def test_h2_panic_revoga_tudo(ambiente):
    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    _conceder(base, concessoes)
    assert concessoes.panic() == 1
    assert concessoes.listar() == []


def test_h3_arquivo_corrompido_nao_concede_nada(ambiente, tmp_path):
    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    entrada = _conceder(base, concessoes)
    (tmp_path / "concessoes.json").write_text("{ isto não é json")
    assert concessoes.vigente(entrada["digest"]) is False


# -------------------------------------------------------------------- I
def test_i_n_registros_com_uma_concessao_zero_aprovacoes(ambiente):
    """O caso real: N construções de runtime, uma única decisão humana."""
    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    _conceder(base, concessoes)

    chamadas = []
    for _ in range(5):
        reg = _registro(policy, audit, concessoes,
                        approver=lambda _d: chamadas.append(1) or True)
        reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)
        assert reg.conhecida(CAP)
    assert chamadas == []


# -------------------------------------------------------------------- J
def test_j_auditoria_distingue_decisao_de_uso(ambiente, tmp_path):
    """A trilha não pode fabricar aprovações que ninguém deu."""
    policy, audit, concessoes, _ = ambiente
    base = _registro(policy, audit, concessoes)
    _conceder(base, concessoes)

    reg = _registro(policy, audit, concessoes, approver=lambda _d: False)
    reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)

    eventos = _eventos(tmp_path / "audit.jsonl")
    assert "registro.concessao.concedida" in eventos      # a decisão, uma vez
    assert "registro.concessao.consumida" in eventos      # o uso, depois
    assert eventos.count("registro.concessao.concedida") == 1
    assert "approval.aprovada" not in eventos, \
        "uso de concessão não pode aparecer como nova aprovação humana"


def test_sem_concessoes_o_comportamento_e_o_antigo(ambiente):
    """Regressão: com concessoes=None nada muda."""
    policy, audit, _, _ = ambiente
    reg = RegistroCapacidades(policy=policy, approver=None, audit=audit)
    with pytest.raises(ErroRegistro):
        reg.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM)
    reg2 = RegistroCapacidades(policy=policy, approver=lambda _d: True, audit=audit)
    assert reg2.registrar(CAP, Category.WRITE_LOCAL, _executor, ORIGEM).nome == CAP


# ------------------------------------------------------- CLI: nomos capacidades
def test_cli_conceder_grava_e_listar_mostra(tmp_path, monkeypatch, capsys):
    """Caminho feliz da CLI com aprovador injetado (stub), nunca gate real."""
    from nomos import cli

    home = tmp_path / "home"
    (home / "dados").mkdir(parents=True)
    monkeypatch.setenv("NOMOS_HOME", str(home))
    monkeypatch.setattr(cli, "interactive_approver", lambda _d: True)

    rc = cli.main(["capacidades", "conceder", "--raiz", str(home / "dados"),
                   "--ttl-dias", "7", "--motivo", "teste"])
    assert rc == 0
    saida = capsys.readouterr().out
    assert "concessão(ões) gravada(s)" in saida

    assert cli.main(["capacidades", "listar"]) == 0
    listagem = capsys.readouterr().out
    assert "fs-ler" in listagem and "expira em" in listagem


def test_cli_conceder_negado_nao_grava_nada(tmp_path, monkeypatch):
    from nomos import cli

    home = tmp_path / "home"
    (home / "dados").mkdir(parents=True)
    monkeypatch.setenv("NOMOS_HOME", str(home))
    monkeypatch.setattr(cli, "interactive_approver", lambda _d: False)

    assert cli.main(["capacidades", "conceder", "--raiz", str(home / "dados")]) != 0
    assert not (home / "concessoes.json").exists()


def test_cli_revogar_tudo(tmp_path, monkeypatch, capsys):
    from nomos import cli

    home = tmp_path / "home"
    (home / "dados").mkdir(parents=True)
    monkeypatch.setenv("NOMOS_HOME", str(home))
    monkeypatch.setattr(cli, "interactive_approver", lambda _d: True)
    cli.main(["capacidades", "conceder", "--raiz", str(home / "dados")])
    capsys.readouterr()

    assert cli.main(["capacidades", "revogar", "--tudo"]) == 0
    assert "revogada(s)" in capsys.readouterr().out
    cli.main(["capacidades", "listar"])
    assert "nenhuma concessão vigente" in capsys.readouterr().out


def test_panic_revoga_concessoes(tmp_path, monkeypatch):
    """Pânico que deixa autorização durável de pé não é pânico."""
    from nomos import cli
    from nomos.kernel.concessoes import RegistroConcessoes

    home = tmp_path / "home"
    (home / "dados").mkdir(parents=True)
    monkeypatch.setenv("NOMOS_HOME", str(home))
    monkeypatch.setattr(cli, "interactive_approver", lambda _d: True)
    cli.main(["capacidades", "conceder", "--raiz", str(home / "dados")])
    assert RegistroConcessoes(home / "concessoes.json").listar()

    cli.main(["panic"])
    assert RegistroConcessoes(home / "concessoes.json").listar() == []


def test_conjunto_concedido_cobre_o_que_o_servico_registra(tmp_path, monkeypatch, capsys):
    """O conjunto de `conceder` tem de casar com o que o RUNTIME registra.

    Achado em operação (22/08): `conceder` cobria só o filesystem, mas
    `AgendadorGovernado._runtime()` passa `scheduler=` ao construtor, que
    registra também as `sched-*`. O dono concederia 8, o serviço travaria na 9ª
    — e pareceria falha da concessão, não conjunto incompleto. Este teste prende
    as duas listas.
    """
    from nomos import cli
    from nomos.adapters.wiring import registrar_filesystem, registrar_scheduler
    from nomos.kernel.concessoes import RegistroConcessoes

    home = tmp_path / "home"
    (home / "dados").mkdir(parents=True)
    monkeypatch.setenv("NOMOS_HOME", str(home))
    monkeypatch.setattr(cli, "interactive_approver", lambda _d: True)
    assert cli.main(["capacidades", "conceder", "--raiz", str(home / "dados")]) == 0
    capsys.readouterr()

    concedidas = {e["capacidade"]
                  for e in RegistroConcessoes(home / "concessoes.json").listar()}

    # o que o runtime do serviço registra, pelo MESMO wiring
    espelho = RegistroCapacidades(policy=PolicyEngine(home / "policy.json"),
                                  approver=lambda _d: True, audit=None)
    esperadas = set(registrar_filesystem(espelho, raizes=(str(home / "dados"),),
                                         audit=None, apenas_leitura=False,
                                         destrutivas=False))
    esperadas |= set(registrar_scheduler(espelho, None))

    faltando = esperadas - concedidas
    assert not faltando, f"o serviço registra o que não foi concedido: {sorted(faltando)}"
    assert any(n.startswith("sched-") for n in concedidas), "sched-* tem de entrar"
