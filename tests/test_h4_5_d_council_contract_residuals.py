"""H4.5-D (missão de selagem arquitetural, 2026-08-04): cenários residuais de
maior valor do contrato do Council, sobre o pipeline REAL compartilhado por
`OfflineCouncilSimulator.run_with_candidates()` (o mesmo núcleo que
`CouncilOrchestratorDryRun.run()` chama — ver orchestrator.py, seção
"5. SIMULATOR_RAN").

Antes de escrever qualquer teste novo, foi feito um levantamento (grep +
leitura de código) da cobertura já existente em tests/council/ e
tests/test_council_simulator.py / tests/test_council_models.py /
tests/test_arbitragem.py para os 6 cenários pedidos pela missão. Resultado,
por item (arquivo:linha quando já coberto):

1. "timeout de um membro não derruba o conselho inteiro" — NÃO coberto.
   test_council_simulator.py:127 (`test_simulator_engine_failure_returns_
   failure_code`) só testa um ÚNICO candidato que falha (fica sem motor
   elegível nenhum) — não um MIX de um saudável + um com timeout.
2. "parecer malformado é rejeitado" — parcialmente coberto em
   test_council_models.py:124-134, mas isso testa `JudgeScore`, um modelo
   PARALELO que a simulação real não usa (o simulador consome
   `SimulatedJudgeFixture`, que tem sua própria validação em
   simulator.py:90-93). O objeto que de fato entra no pipeline real nunca
   foi testado com dado malformado — gap real no limite público correto.
3. "nenhuma decisão é fabricada quando não há quórum insuficiente" —
   test_council_simulator.py:109-116 (`test_simulator_insufficient_judges_
   warns_or_fails_closed`) já cobre failure_code+blocked para o caso
   "juiz é autor do único candidato", mas não afirma que NENHUM conteúdo/
   vencedor foi fabricado, nem cobre o caso "zero juízes" (mensagem
   diferente: "nenhum juiz no conselho"). Estende sem duplicar.
4. "decisão final preserva dissenso ou motivo de rejeição" — NÃO coberto:
   grep por `.reasons` em tests/ não encontra nenhuma asserção sobre
   `ArbiterDecision.reasons` em nenhum caminho bloqueado.
5. "limite de rodadas é respeitado" — NÃO APLICÁVEL ao código atual.
   Levantamento (`rg -i "round|rodada"` em todo src/nomos/council/) não
   encontra NENHUMA ocorrência: o Council, nesta fase (MC1-MC8, dry-run),
   é um pipeline de UMA passada só — não existe conceito de "rodadas de
   deliberação" em lugar nenhum do código. Criar um teste para isso
   exigiria inventar uma feature de produção nova, o que viola
   NO_BROAD_REFACTOR e "não criar... apenas para cumprir arquitetura
   idealizada" (restrição explícita da missão H4.5). Registrado como
   GAP_ARQUITETURAL, não como teste fabricado sobre comportamento
   inexistente.
6. "orçamento excedido interrompe nova deliberação" — NÃO APLICÁVEL, mesma
   razão do item 5: `rg -i "budget|orcamento|orçamento"` em todo
   src/nomos/council/ não encontra nenhuma ocorrência. Sem conceito de
   orçamento/custo em lugar nenhum do pipeline atual.

Itens 5 e 6 ficam documentados aqui e no relatório final da missão como
GAP_ARQUITETURAL (o Council MC1-MC8 é single-pass por design nesta fase —
não é um bug, é o estado real e declarado da arquitetura), não como testes
que passam vacuamente ou como produção alterada fora do escopo pedido.
"""
from __future__ import annotations

from nomos.council.models import (
    AnswerCandidate,
    CouncilDisagreementLevel,
    CouncilFailureCode,
)
from nomos.council.simulator import (
    OfflineCouncilSimulator,
    SimulatedEngineFixture,
    SimulatedJudgeFixture,
    SimulatedPolicyGateResult,
    SimulatorError,
)

import pytest

SIM = OfflineCouncilSimulator()


def _cands(n=2):
    return [SimulatedEngineFixture(f"fixture:e{i}", f"cand_{i}", f"resposta {i}")
            for i in range(n)]


def _judges(pairs):
    return [SimulatedJudgeFixture(f"fixture:j{i}", a, overall=o)
            for i, (a, o) in enumerate(pairs)]


# --------------------------------------------------------------------------
# 1) Timeout de um membro não derruba o conselho inteiro
# --------------------------------------------------------------------------

def test_timeout_de_um_candidato_nao_bloqueia_conselho_com_membro_saudavel():
    """Dois candidatos: cand_0 sofre ENGINE_TIMEOUT (sem conteúdo), cand_1 é
    saudável. O conselho deve seguir normalmente com o(s) candidato(s)
    elegível(is) restante(s) — o timeout de UM membro não é motivo para
    bloquear/derrubar a deliberação inteira."""
    candidatos = [
        AnswerCandidate(candidate_id="cand_timeout", engine_id="fixture:lento",
                        content="", failure_code=CouncilFailureCode.ENGINE_TIMEOUT),
        AnswerCandidate(candidate_id="cand_saudavel", engine_id="fixture:ok",
                        content="resposta ok"),
    ]
    alias_por_candidato = {"cand_timeout": "A", "cand_saudavel": "B"}
    engine_por_alias = {"A": "fixture:lento", "B": "fixture:ok"}
    # só o candidato saudável (alias B) é julgado por um juiz limpo (não-autor)
    juizes = [SimulatedJudgeFixture("fixture:juiz-independente", "B", overall=5)]

    r = SIM.run_with_candidates(
        candidates=candidatos, alias_por_candidato=alias_por_candidato,
        engine_por_alias=engine_por_alias, judge_fixtures=juizes,
        provider_failure=None, session_id="teste-timeout-parcial")

    assert r.failure_code is None, (
        f"timeout de um membro não deveria bloquear o conselho: {r.failure_code}")
    assert r.arbiter_decision.blocked is False
    # o candidato que sofreu timeout nunca foi anonimizado/julgado — só o saudável
    assert len(r.anonymized_candidates) == 1
    assert r.anonymized_candidates[0].candidate_id == "B"
    # a decisão final selecionou o candidato saudável, não o que expirou
    assert r.arbiter_decision.selected_candidate_alias == "B"


def test_timeout_de_todos_os_membros_bloqueia_fail_closed_sem_crash():
    """Contraste do teste acima: se TODOS os candidatos sofrem timeout (não
    sobra nenhum elegível), o conselho bloqueia de forma fail-closed — não
    finge uma resposta, e não lança exceção."""
    candidatos = [
        AnswerCandidate(candidate_id="cand_a", engine_id="fixture:lento1",
                        content="", failure_code=CouncilFailureCode.ENGINE_TIMEOUT),
        AnswerCandidate(candidate_id="cand_b", engine_id="fixture:lento2",
                        content="", failure_code=CouncilFailureCode.ENGINE_TIMEOUT),
    ]
    r = SIM.run_with_candidates(
        candidates=candidatos,
        alias_por_candidato={"cand_a": "A", "cand_b": "B"},
        engine_por_alias={"A": "fixture:lento1", "B": "fixture:lento2"},
        judge_fixtures=[], provider_failure=CouncilFailureCode.ENGINE_TIMEOUT,
        session_id="teste-timeout-total")

    assert r.failure_code is CouncilFailureCode.ENGINE_TIMEOUT
    assert r.arbiter_decision.blocked is True
    assert r.arbiter_decision.final_content == ""
    assert r.arbiter_decision.selected_candidate_alias is None


# --------------------------------------------------------------------------
# 2) Parecer malformado é rejeitado — no limite REAL de entrada do pipeline
#    (SimulatedJudgeFixture, não o modelo paralelo JudgeScore que a
#    simulação não usa). Fail-closed por construção: um parecer malformado
#    não consegue nem existir como objeto para entrar no pipeline.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("overall_invalido", [6, -1, 100, -50])
def test_parecer_com_nota_fora_do_intervalo_e_rejeitado_na_construcao(overall_invalido):
    with pytest.raises(SimulatorError, match="0–5"):
        SimulatedJudgeFixture("fixture:juiz", "A", overall=overall_invalido)


@pytest.mark.parametrize("overall_invalido", ["5", 5.0, None, True, False])
def test_parecer_com_tipo_de_nota_invalido_e_rejeitado_na_construcao(overall_invalido):
    with pytest.raises(SimulatorError, match="inteiro"):
        SimulatedJudgeFixture("fixture:juiz", "A", overall=overall_invalido)


def test_parecer_sem_alias_de_candidato_e_rejeitado_na_construcao():
    with pytest.raises(SimulatorError, match="candidate_alias"):
        SimulatedJudgeFixture("fixture:juiz", "", overall=4)


def test_parecer_de_juiz_sem_prefixo_fixture_e_rejeitado_na_construcao():
    """Um "juiz" que não seja claramente uma fixture simulada (prefixo
    'fixture:') nunca deveria conseguir se passar por participante do
    conselho simulado — mesma disciplina fail-closed."""
    with pytest.raises(SimulatorError, match="fixture:"):
        SimulatedJudgeFixture("motor-real-nao-simulado", "A", overall=4)


# --------------------------------------------------------------------------
# 3) Nenhuma decisão é fabricada quando não há quórum suficiente
#    (estende test_council_simulator.py:109-116 sem duplicar: aquele teste
#    já prova failure_code+blocked para "juiz é autor do único candidato";
#    aqui provamos especificamente que NADA foi fabricado — nem conteúdo
#    nem vencedor — e cobrimos também o sub-caso "zero juízes", que aquele
#    teste não exercita.)
# --------------------------------------------------------------------------

def test_quorum_insuficiente_por_autojulgamento_nao_fabrica_conteudo_nem_vencedor():
    cands = _cands(1)
    juizes = [SimulatedJudgeFixture("fixture:e0", "A", overall=5)]  # autor = único juiz
    r = SIM.run(_offline_input(cands, juizes))

    assert r.failure_code is CouncilFailureCode.INSUFFICIENT_JUDGES
    assert r.arbiter_decision.blocked is True
    assert r.arbiter_decision.final_content == "", (
        "quórum insuficiente não pode produzir final_content não-vazio")
    assert r.arbiter_decision.selected_candidate_alias is None, (
        "quórum insuficiente não pode eleger um vencedor")


def test_quorum_insuficiente_por_zero_juizes_nao_fabrica_conteudo_nem_vencedor():
    """Sub-caso distinto do teste acima: nenhum juiz foi sequer designado
    (lista vazia), não apenas "todos em conflito"."""
    cands = _cands(2)
    r = SIM.run(_offline_input(cands, judge_fixtures=[]))

    assert r.failure_code is CouncilFailureCode.INSUFFICIENT_JUDGES
    assert r.arbiter_decision.blocked is True
    assert r.arbiter_decision.final_content == ""
    assert r.arbiter_decision.selected_candidate_alias is None


# --------------------------------------------------------------------------
# 4) Decisão final preserva dissenso ou motivo de rejeição
#    (nenhum teste em toda a suíte hoje afirma nada sobre
#    ArbiterDecision.reasons — gap real, confirmado por grep.)
# --------------------------------------------------------------------------

def test_decisao_bloqueada_por_quorum_insuficiente_preserva_motivo():
    cands = _cands(1)
    juizes = [SimulatedJudgeFixture("fixture:e0", "A", overall=5)]
    r = SIM.run(_offline_input(cands, juizes))

    assert r.arbiter_decision.reasons, "motivo de rejeição não pode ficar vazio"
    assert any("autor" in m or "conflito" in m for m in r.arbiter_decision.reasons), \
        r.arbiter_decision.reasons


def test_decisao_bloqueada_por_divergencia_alta_preserva_dissenso():
    cands = _cands(1)
    juizes = _judges([("A", 5), ("A", 1)])   # spread 4 >= limiar HIGH (3)
    r = SIM.run(_offline_input(cands, juizes))

    assert r.disagreement.level is CouncilDisagreementLevel.HIGH
    assert r.disagreement.requires_clarification is True
    assert r.arbiter_decision.blocked is True
    assert r.arbiter_decision.reasons, "dissenso alto precisa deixar rastro no motivo"
    assert any("diverg" in m for m in r.arbiter_decision.reasons), \
        r.arbiter_decision.reasons


def test_decisao_bloqueada_por_alerta_critico_preserva_motivo():
    cands = _cands(1)
    juizes = [SimulatedJudgeFixture("fixture:j", "A", overall=4, alerts=["critical"])]
    r = SIM.run(_offline_input(cands, juizes))

    assert r.failure_code is CouncilFailureCode.ARBITER_UNSAFE_OUTPUT
    assert r.arbiter_decision.reasons
    assert any("crítico" in m or "critico" in m for m in r.arbiter_decision.reasons), \
        r.arbiter_decision.reasons


def test_decisao_bloqueada_por_gate_negado_preserva_motivo_do_gate():
    cands = _cands(2)
    juizes = _judges([("A", 4), ("B", 4)])
    r = SIM.run(_offline_input(
        cands, juizes,
        gate=SimulatedPolicyGateResult(allowed=False, code="DENY_SIM",
                                       reason="motivo-de-teste-especifico")))

    assert r.failure_code is CouncilFailureCode.POLICY_GATE_DENIED
    assert r.arbiter_decision.reasons
    assert any("motivo-de-teste-especifico" in m for m in r.arbiter_decision.reasons), \
        r.arbiter_decision.reasons


def test_decisao_aprovada_nao_precisa_de_motivo_de_rejeicao():
    """Contraste: quando a decisão NÃO é bloqueada, reasons pode ficar
    vazio — o contrato é sobre preservar motivo QUANDO há rejeição/
    dissenso, não sobre popular reasons sempre."""
    cands = _cands(2)
    juizes = _judges([("A", 5), ("B", 5)])
    r = SIM.run(_offline_input(cands, juizes))

    assert r.failure_code is None
    assert r.arbiter_decision.blocked is False
    assert r.arbiter_decision.reasons == []


# --------------------------------------------------------------------------
# helper compartilhado (equivalente ao OfflineCouncilInput já usado em
# test_council_simulator.py — reaproveita o mesmo padrão, não introduz um
# construtor paralelo)
# --------------------------------------------------------------------------

def _offline_input(cands, judge_fixtures, gate=None):
    from nomos.council.simulator import OfflineCouncilInput
    return OfflineCouncilInput(prompt="x", candidate_fixtures=cands,
                               judge_fixtures=judge_fixtures, gate=gate)
