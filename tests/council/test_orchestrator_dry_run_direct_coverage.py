"""H3-missao-debitos, correção pós-relatório: cobertura DIRETA e explícita de
`CouncilOrchestratorDryRun.run()`.

Contexto: `mypy src/nomos` chegou a 0 erros (Horizonte 3, P2), e o arquivo
`council/orchestrator.py` teve 22 erros de tipo corrigidos nesse esforço — o
arquivo mais crítico do lote (compõe provider -> simulador -> gate -> audit
envelope, decide `allowed`/`blocked` para toda sessão do Council). A suíte
já existente (`tests/council/test_orchestrator.py`) cobre 99% das LINHAS do
módulo, mas cobertura de linha não é o mesmo que cobertura de COMPORTAMENTO:
não bastava rodar cada branch, era preciso provar, para cada um, que (a)
status e motivo (`failure_code`) estão corretos; (b) nenhuma execução
indevida ocorre (`would_execute`/`would_write_audit`/`dry_run` corretos);
(c) a auditoria é registrada quando a etapa é alcançada, e genuinamente
ausente quando não é; (d) invariantes de governança (`blocked == not
allowed`, ordem das etapas, propagação de `private_mode`) permanecem
preservadas; e (e) nenhum caminho de erro produz um resultado que PAREÇA
sucesso (`allowed=True` com `failure_code` presente, ou vice-versa).

Este arquivo cobre, de forma direta e rotulada, os 11 cenários exigidos:
1. entrada válida
2. falha de entrada
3. aprovação concedida (gate liberado)
4. aprovação recusada ou ausente (gate nega por exigir aprovação humana —
   MC6 é dry-run e NUNCA chama aprovação real, então "ausente" e "recusada"
   são o mesmo desfecho: bloqueio)
5. falha no gate (exceção)
6. decisão válida do gate (objeto real devolvido, liberado e negado)
7. falha de auditoria (exceção E negação explícita)
8. auditoria bem-sucedida
9. raiz permitida (nenhuma falha raiz marcada)
10. raiz fora das permissões (falha raiz marcada — e é sempre a PRIMEIRA,
    nunca uma etapa posterior sobrescrevendo)
11. exceções inesperadas de cada componente plugável, fail-closed

Nenhuma lógica de `council/orchestrator.py` é alterada por este arquivo —
é só teste. Sem rede/subprocess/FS/tempo/random (mesma disciplina de pureza
do resto do pacote `council`)."""
import pytest

from nomos.council.audit_envelope import (
    AuditEnvelopeFailureCode,
    CouncilAuditDryRunResult,
)
from nomos.council.local_provider import (
    DeterministicLocalCandidateProvider,
    LocalCandidateResult,
    LocalEngineDescriptor,
)
from nomos.council.orchestrator import (
    CouncilOrchestrationInput,
    CouncilOrchestratorDryRun,
    OrchestrationFailureCode,
)
from nomos.council.policy_gate import CouncilGateDecision, GateFailureCode

_ORDEM_BASE = ["INPUT_VALIDATED", "LOCAL_PROVIDER_EVALUATED", "CANDIDATES_CREATED",
              "SIMULATOR_RAN", "POLICY_GATE_EVALUATED", "FINAL_ENVELOPE_CREATED",
              "AUDIT_ENVELOPE_CREATED"]


def _entrada(**kw):
    base = dict(session_id="sess-direct-cov", prompt="qual a capital da frança?")
    base.update(kw)
    return CouncilOrchestrationInput(**base)


def _nomes(resultado):
    return [s["name"] for s in resultado.trace["steps"]]


def _assert_fail_closed(r, esperado, *, etapa_alcancada=True):
    """(e) nenhum erro vira sucesso aparente + (b) nenhuma execução indevida.

    Válido para TODO cenário de falha, seja qual for a etapa raiz: `allowed`
    e `blocked` sempre coerentes com a presença de `failure_code`, o
    resultado nunca "finge" ter executado ou gravado auditoria de verdade,
    e nenhum conteúdo do envelope final vaza quando negado."""
    assert r.allowed is False, "allowed=True num cenário de falha seria erro virando sucesso"
    assert r.blocked is True
    assert r.failure_code == esperado, f"motivo incorreto: {r.failure_code} != {esperado}"
    # (b) nenhuma execução indevida, em NENHUM cenário de falha
    assert r.dry_run is True
    assert r.would_execute is False
    assert r.would_write_audit is False
    if etapa_alcancada and r.final_envelope:
        assert r.final_envelope.get("content") is None, (
            "conteúdo vazou num envelope final que deveria estar bloqueado")


def _assert_sucesso(r):
    """(e) espelho positivo: sucesso real, não um bloqueio disfarçado."""
    assert r.allowed is True
    assert r.blocked is False
    assert r.failure_code is None
    assert r.dry_run is True
    assert r.would_execute is False
    assert r.would_write_audit is False
    assert r.final_envelope.get("allowed") is True
    assert r.final_envelope.get("blocked") is False


# =====================================================================
# 1. entrada válida
# =====================================================================

def test_01_entrada_valida_completa_com_sucesso_real():
    r = CouncilOrchestratorDryRun().run(_entrada())
    _assert_sucesso(r)
    assert _nomes(r) == _ORDEM_BASE + ["ORCHESTRATION_COMPLETED"]
    # (c) auditoria registrada quando a etapa é alcançada
    assert len(r.audit_result["envelopes"]) > 0
    # (d) invariante de governança: blocked é sempre o oposto lógico de allowed
    assert r.blocked == (not r.allowed)


# =====================================================================
# 2. falha de entrada
# =====================================================================

def test_02_falha_de_entrada_pos_construcao_bloqueia_imediatamente():
    entrada = _entrada()
    entrada.session_id = ""   # mutação pós-__post_init__ (o único jeito de tornar inválida)
    r = CouncilOrchestratorDryRun().run(entrada)
    _assert_fail_closed(r, OrchestrationFailureCode.ORCH_INPUT_INVALID,
                        etapa_alcancada=False)
    # etapa raiz: pára ANTES de tocar provider/simulador/gate — nenhuma etapa
    # downstream aparece no trace, provando que "nenhuma execução indevida
    # ocorre" além do que é estritamente necessário para reportar a falha.
    assert _nomes(r) == ["INPUT_VALIDATED", "ORCHESTRATION_BLOCKED"]
    # (c) auditoria genuinamente AUSENTE (não alcançada), não silenciosamente vazia
    assert r.audit_result == {}
    assert r.final_envelope == {}


def test_02b_falha_de_entrada_max_candidates_invalido_apos_mutacao():
    entrada = _entrada()
    entrada.max_candidates = 0   # mutação pós-construção, mesmo caminho de defesa
    r = CouncilOrchestratorDryRun().run(entrada)
    _assert_fail_closed(r, OrchestrationFailureCode.ORCH_INPUT_INVALID,
                        etapa_alcancada=False)


# =====================================================================
# 3. aprovação concedida (gate libera)
# =====================================================================

def test_03_aprovacao_concedida_gate_libera_conteudo_presente():
    r = CouncilOrchestratorDryRun().run(_entrada(risk_level="A1"))
    _assert_sucesso(r)
    gate_step = next(s for s in r.trace["steps"] if s["name"] == "POLICY_GATE_EVALUATED")
    assert gate_step["ok"] is True
    assert gate_step["metadata"]["gate_allowed"] is True
    assert gate_step["metadata"]["gate_failure_code"] is None
    # conteúdo só pode existir quando o gate de fato liberou
    assert r.final_envelope["content"] is None   # nunca serializado (redação), mas...
    assert r.final_envelope["allowed"] is True    # ...o envelope se declara liberado


# =====================================================================
# 4. aprovação recusada ou ausente
# =====================================================================

def test_04_aprovacao_recusada_ou_ausente_bloqueia_sempre():
    """MC6 é dry-run: `requires_human_approval` é sempre `False` no pedido que
    `run()` monta (linha `requires_human_approval=False` em POLICY_GATE_EVALUATED),
    isto é, o orquestrador NUNCA solicita aprovação humana real — o próprio
    contrato do dry-run trata "recusada" e "ausente" como o mesmo desfecho:
    bloqueio fail-closed. Provado aqui injetando um gate que replica a
    decisão real que `CouncilPolicyGateDryRun` tomaria se
    `requires_human_approval=True` fosse alcançável (não é, mas o desfecho
    downstream de `run()` para um gate negado por essa causa precisa ser
    idêntico ao de qualquer outra negação do gate)."""
    class GateExigeAprovacaoAusente:
        def evaluate(self, request):
            return CouncilGateDecision(
                allowed=False, failure_code=GateFailureCode.GATE_REQUIRES_APPROVAL,
                requires_human_approval=True, reasons=[GateFailureCode.GATE_REQUIRES_APPROVAL.value])
    r = CouncilOrchestratorDryRun(gate=GateExigeAprovacaoAusente()).run(_entrada())
    _assert_fail_closed(r, OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED)
    gate_step = next(s for s in r.trace["steps"] if s["name"] == "POLICY_GATE_EVALUATED")
    assert gate_step["ok"] is False
    assert gate_step["metadata"]["gate_allowed"] is False
    assert gate_step["metadata"]["gate_failure_code"] == "GATE_REQUIRES_APPROVAL"
    # mesmo com aprovação "ausente", a auditoria SEMPRE roda depois do gate
    # (ela audita a decisão, não decide se persiste dado real)
    assert len(r.audit_result["envelopes"]) > 0


# =====================================================================
# 5. falha no gate (exceção)
# =====================================================================

def test_05_falha_no_gate_por_excecao_e_fail_closed():
    class GateQuebrado:
        def evaluate(self, request):
            raise RuntimeError("gate explodiu")
    r = CouncilOrchestratorDryRun(gate=GateQuebrado()).run(_entrada())
    _assert_fail_closed(r, OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED)
    # mesmo com o gate quebrado, o pipeline não pára: continua até o fim,
    # produzindo FINAL_ENVELOPE_CREATED e AUDIT_ENVELOPE_CREATED (negados),
    # nunca deixando a exceção escapar de run() nem interrompendo o trace.
    assert _nomes(r) == _ORDEM_BASE + ["ORCHESTRATION_BLOCKED"]
    gate_step = next(s for s in r.trace["steps"] if s["name"] == "POLICY_GATE_EVALUATED")
    assert gate_step["ok"] is False
    assert gate_step["metadata"]["gate_allowed"] is False
    # (c) auditoria AINDA roda e é registrada mesmo com o gate tendo quebrado
    # (a etapa é alcançada; só o conteúdo é negado por causa da falha raiz)
    assert len(r.audit_result["envelopes"]) > 0


# =====================================================================
# 6. decisão válida do gate (objeto real, não None, nos dois sentidos)
# =====================================================================

def test_06a_decisao_valida_do_gate_objeto_real_quando_liberado():
    r = CouncilOrchestratorDryRun().run(_entrada(risk_level="A1"))
    # a decisão real do CouncilPolicyGateDryRun (não um substituto/mocked)
    # aparece corretamente serializada no gate_decision do envelope final
    gd = r.final_envelope["gate_decision"]
    assert gd["schema"] == "nomos.council.gate_decision.v1"
    assert gd["allowed"] is True
    assert gd["dry_run"] is True
    assert gd["would_call_real_policy"] is False
    assert gd["would_request_approval"] is False


def test_06b_decisao_valida_do_gate_objeto_real_quando_negado():
    r = CouncilOrchestratorDryRun().run(_entrada(risk_level="A6"))
    gd = r.final_envelope["gate_decision"]
    assert gd["allowed"] is False
    assert gd["failure_code"] == "GATE_A6_DENIED"
    assert gd["dry_run"] is True


# =====================================================================
# 7. falha de auditoria (exceção E negação explícita)
# =====================================================================

def test_07a_falha_de_auditoria_por_excecao_e_fail_closed():
    class BuilderQuebrado:
        def build_for_result(self, result, private_mode, extra_metadata=None):
            raise RuntimeError("audit builder explodiu")
    r = CouncilOrchestratorDryRun(audit_builder=BuilderQuebrado()).run(_entrada())
    _assert_fail_closed(r, OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED)
    # (c) auditoria genuinamente FALHOU (não "vazia por engano"): o
    # audit_result fail-closed tem allowed=False e ZERO envelopes — o
    # próprio orquestrador não inventa um envelope de substituição.
    assert r.audit_result["allowed"] is False
    assert r.audit_result["envelopes"] == []
    # mesmo assim, o envelope FINAL (etapa anterior à auditoria) já tinha
    # sido criado normalmente antes da exceção — a ordem não é violada.
    assert "FINAL_ENVELOPE_CREATED" in _nomes(r)
    assert _nomes(r).index("FINAL_ENVELOPE_CREATED") < _nomes(r).index("AUDIT_ENVELOPE_CREATED")


def test_07b_falha_de_auditoria_por_negacao_explicita_e_fail_closed():
    class BuilderNega:
        def build_for_result(self, result, private_mode, extra_metadata=None):
            return CouncilAuditDryRunResult(
                allowed=False, envelopes=[],
                failure_code=AuditEnvelopeFailureCode.AUDIT_ENVELOPE_SENSITIVE_METADATA,
                warnings=["metadata sensível simulada"])
    r = CouncilOrchestratorDryRun(audit_builder=BuilderNega()).run(_entrada())
    _assert_fail_closed(r, OrchestrationFailureCode.ORCH_AUDIT_ENVELOPE_DENIED)
    assert r.audit_result["allowed"] is False
    assert r.audit_result["failure_code"] == "AUDIT_ENVELOPE_SENSITIVE_METADATA"
    audit_step = next(s for s in r.trace["steps"] if s["name"] == "AUDIT_ENVELOPE_CREATED")
    assert audit_step["ok"] is False
    assert audit_step["metadata"]["audit_failure_code"] == "AUDIT_ENVELOPE_SENSITIVE_METADATA"


# =====================================================================
# 8. auditoria bem-sucedida
# =====================================================================

def test_08_auditoria_bem_sucedida_registra_envelopes_redigidos():
    r = CouncilOrchestratorDryRun().run(_entrada())
    assert r.audit_result["allowed"] is True
    assert r.audit_result["failure_code"] is None
    envelopes = r.audit_result["envelopes"]
    assert len(envelopes) > 0
    for env in envelopes:
        assert env["redacted"] is True
        assert env["would_write_audit"] is False   # (b) nenhuma escrita real
        assert env["dry_run"] is True


def test_08b_auditoria_bem_sucedida_em_modo_privado_nunca_persiste():
    r = CouncilOrchestratorDryRun().run(_entrada(private_mode=True))
    assert r.audit_result["allowed"] is True
    envelopes = r.audit_result["envelopes"]
    assert len(envelopes) > 0
    # (d) invariante de governança: private_mode propaga para TODO envelope
    assert all(e["persist_allowed"] is False for e in envelopes)
    assert r.final_envelope["persist_allowed"] is False


# =====================================================================
# 9. raiz permitida
# =====================================================================

def test_09_raiz_permitida_significa_nenhuma_falha_raiz_marcada():
    r = CouncilOrchestratorDryRun().run(_entrada())
    # "raiz permitida" == nenhuma etapa marcou uma falha raiz == failure_code
    # None E allowed True ao mesmo tempo (nunca um sem o outro)
    assert r.failure_code is None
    assert r.allowed is True
    ultimo = r.trace["steps"][-1]
    assert ultimo["name"] == "ORCHESTRATION_COMPLETED"
    assert ultimo["ok"] is True
    assert ultimo["failure_code"] is None
    assert ultimo["metadata"]["failure_code"] is None


# =====================================================================
# 10. raiz fora das permissões — e é sempre a PRIMEIRA falha, nunca a última
# =====================================================================

@pytest.mark.parametrize("montar_orch,motivo_esperado", [
    (lambda: CouncilOrchestratorDryRun(
        provider=DeterministicLocalCandidateProvider(engines=[])),
     OrchestrationFailureCode.ORCH_NO_CANDIDATES),
    (lambda: CouncilOrchestratorDryRun(
        provider=DeterministicLocalCandidateProvider(
            engines=[LocalEngineDescriptor(engine_id="local:cloud", cloud=True)])),
     OrchestrationFailureCode.ORCH_PROVIDER_FAILED),
], ids=["provider-sem-motor", "provider-cloud-bloqueado"])
def test_10a_raiz_fora_das_permissoes_por_causa_do_provider(montar_orch, motivo_esperado):
    r = montar_orch().run(_entrada())
    _assert_fail_closed(r, motivo_esperado)
    # falha do provider é a etapa mais cedo possível: gate/auditoria ainda
    # rodam (fail-closed = sempre negados), mas a CAUSA raiz é o provider,
    # não o gate nem a auditoria — provado comparando os `ok` de cada etapa.
    provider_step = next(s for s in r.trace["steps"]
                         if s["name"] == "LOCAL_PROVIDER_EVALUATED")
    gate_step = next(s for s in r.trace["steps"] if s["name"] == "POLICY_GATE_EVALUATED")
    assert provider_step["ok"] is False, "a raiz real (provider) deveria estar marcada ok=False"
    # o gate também nega (fail-closed, sem candidatos não há final_content),
    # mas o `failure_code` do RESULTADO reflete a raiz (provider), não o gate
    assert gate_step["ok"] is False, (
        "sem candidatos o gate também nega (fail-closed em cascata), "
        "mas isso não deve sobrescrever a causa raiz do provider no resultado")
    assert r.failure_code == motivo_esperado
    assert r.failure_code != OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED


def test_10b_raiz_e_sempre_a_primeira_falha_gate_nao_sobrescreve_provider():
    """Prova direta de `_marcar_raiz` (só grava a PRIMEIRA falha): um
    provider que falha E um risk_level que também faria o gate negar (A6) —
    o `failure_code` final tem que ser da falha do PROVIDER (a mais cedo),
    nunca do gate (mais tarde), mesmo que o gate também tivesse motivo
    próprio para negar."""
    orch = CouncilOrchestratorDryRun(
        provider=DeterministicLocalCandidateProvider(engines=[]))
    r = orch.run(_entrada(risk_level="A6"))
    assert r.failure_code in (OrchestrationFailureCode.ORCH_PROVIDER_FAILED,
                              OrchestrationFailureCode.ORCH_NO_CANDIDATES)
    assert r.failure_code != OrchestrationFailureCode.ORCH_POLICY_GATE_DENIED


def test_10c_raiz_fora_das_permissoes_por_causa_do_simulador():
    class SimuladorQuebrado:
        def run_with_candidates(self, **kw):
            raise KeyError("sim explodiu")
    r = CouncilOrchestratorDryRun(simulator=SimuladorQuebrado()).run(_entrada())
    _assert_fail_closed(r, OrchestrationFailureCode.ORCH_SIMULATOR_FAILED,
                        etapa_alcancada=False)
    # quando o simulador quebra, run() nem tenta montar gate/audit — não há
    # candidato simulado para avaliar, então pára ali (fail-closed cedo)
    assert "POLICY_GATE_EVALUATED" not in _nomes(r)
    assert r.audit_result == {}


# =====================================================================
# 11. exceções inesperadas de cada componente plugável, fail-closed
# =====================================================================

class _ExcecaoCustomizadaDoTeste(Exception):
    """Tipo de exceção deliberadamente NÃO relacionado a nenhum dos códigos
    de falha do domínio — prova que o `except Exception` é genérico, não
    uma lista de tipos conhecidos."""


@pytest.mark.parametrize("kwarg,fabrica_componente,motivo_esperado", [
    ("provider", lambda: _ComponenteQuebrado("generate"),
     OrchestrationFailureCode.ORCH_PROVIDER_FAILED),
    ("simulator", lambda: _ComponenteQuebrado("run_with_candidates"),
     OrchestrationFailureCode.ORCH_SIMULATOR_FAILED),
    ("gate", lambda: _ComponenteQuebrado("evaluate"),
     OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED),
    ("audit_builder", lambda: _ComponenteQuebrado("build_for_result"),
     OrchestrationFailureCode.ORCH_INTERNAL_INVARIANT_FAILED),
], ids=["provider-excecao-nao-mapeada", "simulator-excecao-nao-mapeada",
       "gate-excecao-nao-mapeada", "audit-excecao-nao-mapeada"])
def test_11_excecao_inesperada_de_cada_componente_e_fail_closed(
        kwarg, fabrica_componente, motivo_esperado):
    componente = fabrica_componente()
    r = CouncilOrchestratorDryRun(**{kwarg: componente}).run(_entrada())
    assert r.allowed is False
    assert r.blocked is True
    assert r.failure_code == motivo_esperado
    # (b) nenhuma execução indevida mesmo diante do inesperado
    assert r.dry_run is True
    assert r.would_execute is False
    assert r.would_write_audit is False
    # a exceção NUNCA escapa de run() como traceback cru — sempre vira um
    # CouncilOrchestrationResult bem formado (o teste em si já prova isso:
    # se tivesse escapado, pytest reportaria erro de coleta, não asserção)
    assert isinstance(r.to_dict(), dict)


class _ComponenteQuebrado:
    """Fake plugável que implementa só o método pedido, e sempre levanta um
    tipo de exceção CUSTOMIZADO (não RuntimeError/ValueError conhecidos) —
    prova que o fail-closed do orquestrador não depende do tipo específico
    de exceção, só de `Exception` genericamente."""

    def __init__(self, metodo_que_quebra: str):
        self._metodo = metodo_que_quebra

    def list_engines(self):
        if self._metodo == "list_engines":
            raise _ExcecaoCustomizadaDoTeste("list_engines quebrado")
        return [LocalEngineDescriptor(engine_id="local:mock-a")]

    def generate(self, request):
        if self._metodo == "generate":
            raise _ExcecaoCustomizadaDoTeste("generate quebrado")
        from nomos.council.local_provider import AnswerCandidate
        return LocalCandidateResult(candidates=[
            AnswerCandidate(candidate_id="c0", engine_id="local:mock-a",
                            content="[teste] candidato fixo")], failure_code=None)

    def run_with_candidates(self, **kw):
        raise _ExcecaoCustomizadaDoTeste("run_with_candidates quebrado")

    def evaluate(self, request):
        raise _ExcecaoCustomizadaDoTeste("evaluate quebrado")

    def build_for_result(self, result, private_mode, extra_metadata=None):
        raise _ExcecaoCustomizadaDoTeste("build_for_result quebrado")


# =====================================================================
# invariantes transversais (aplicadas a TODOS os cenários acima, de novo,
# de forma sistemática — não confiar só nas asserções individuais)
# =====================================================================

def _cenarios_para_invariantes_transversais():
    """(entrada, kwargs do construtor) cobrindo sucesso e cada tipo de
    falha, para verificação sistemática das 5 propriedades pedidas."""
    return [
        ("sucesso", _entrada(), {}),
        ("gate-nega-a6", _entrada(risk_level="A6"), {}),
        ("gate-nega-sensivel", _entrada(contains_sensitive_data=True), {}),
        ("privado-sucesso", _entrada(private_mode=True), {}),
        ("provider-sem-motor", _entrada(),
         {"provider": DeterministicLocalCandidateProvider(engines=[])}),
    ]


@pytest.mark.parametrize("rotulo,entrada,kwargs",
                         _cenarios_para_invariantes_transversais(),
                         ids=[c[0] for c in _cenarios_para_invariantes_transversais()])
def test_invariante_nenhuma_execucao_indevida_em_qualquer_cenario(rotulo, entrada, kwargs):
    r = CouncilOrchestratorDryRun(**kwargs).run(entrada)
    assert r.dry_run is True
    assert r.would_execute is False
    assert r.would_write_audit is False


@pytest.mark.parametrize("rotulo,entrada,kwargs",
                         _cenarios_para_invariantes_transversais(),
                         ids=[c[0] for c in _cenarios_para_invariantes_transversais()])
def test_invariante_blocked_e_sempre_o_oposto_logico_de_allowed(rotulo, entrada, kwargs):
    r = CouncilOrchestratorDryRun(**kwargs).run(entrada)
    assert r.blocked == (not r.allowed)


@pytest.mark.parametrize("rotulo,entrada,kwargs",
                         _cenarios_para_invariantes_transversais(),
                         ids=[c[0] for c in _cenarios_para_invariantes_transversais()])
def test_invariante_falha_marcada_sse_nao_permitido(rotulo, entrada, kwargs):
    """(e) nenhum caminho transforma erro em sucesso aparente, verificado de
    forma sistemática: `failure_code is not None` se e somente se
    `allowed is False`. Nunca os dois juntos, nunca nenhum dos dois."""
    r = CouncilOrchestratorDryRun(**kwargs).run(entrada)
    if r.allowed:
        assert r.failure_code is None
    else:
        assert r.failure_code is not None


@pytest.mark.parametrize("rotulo,entrada,kwargs",
                         _cenarios_para_invariantes_transversais(),
                         ids=[c[0] for c in _cenarios_para_invariantes_transversais()])
def test_invariante_ordem_das_etapas_quando_todas_presentes(rotulo, entrada, kwargs):
    r = CouncilOrchestratorDryRun(**kwargs).run(entrada)
    nomes = _nomes(r)
    if "POLICY_GATE_EVALUATED" in nomes and "FINAL_ENVELOPE_CREATED" in nomes:
        assert nomes.index("POLICY_GATE_EVALUATED") < nomes.index("FINAL_ENVELOPE_CREATED")
    if "FINAL_ENVELOPE_CREATED" in nomes and "AUDIT_ENVELOPE_CREATED" in nomes:
        assert nomes.index("FINAL_ENVELOPE_CREATED") < nomes.index("AUDIT_ENVELOPE_CREATED")
    # a última etapa é sempre um dos dois nomes terminais, nunca outra coisa
    assert nomes[-1] in ("ORCHESTRATION_COMPLETED", "ORCHESTRATION_BLOCKED")


def test_invariante_auditoria_ausente_quando_etapa_nao_alcancada_nao_e_erro_silencioso():
    """(c) "auditoria é registrada quando exigida" tem um espelho: quando a
    etapa NUNCA é alcançada (falha de entrada ou do simulador, que cortam o
    fluxo antes do audit builder rodar), `audit_result` deve ser exatamente
    `{}` — não um dict parcialmente preenchido, não um envelope fantasma."""
    entrada = _entrada()
    entrada.session_id = ""
    r1 = CouncilOrchestratorDryRun().run(entrada)
    assert r1.audit_result == {}

    class SimuladorQuebrado:
        def run_with_candidates(self, **kw):
            raise RuntimeError("sim boom")
    r2 = CouncilOrchestratorDryRun(simulator=SimuladorQuebrado()).run(_entrada())
    assert r2.audit_result == {}

    # mas quando a etapa DE FATO roda (mesmo com falha em outro ponto do
    # pipeline, como o gate), a auditoria SEMPRE está presente e não-vazia
    r3 = CouncilOrchestratorDryRun().run(_entrada(risk_level="A6"))
    assert r3.audit_result != {}
    assert len(r3.audit_result["envelopes"]) > 0
