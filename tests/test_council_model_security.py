"""MC1 — segurança dos modelos do Motor Council.

Provas por contrato: repr não vaza conteúdo, invariantes fail-closed, e o módulo
de modelos NÃO importa rede nem motor/LLM (é puro).
"""
import ast

from nomos.council import models
from nomos.council.models import (
    AnswerCandidate,
    BlindReview,
    CouncilAuditRecord,
    CouncilMode,
    CouncilPolicy,
    CouncilRiskLevel,
    CouncilSession,
)

SEGREDO = "CONTEUDO-SENSIVEL-DO-USUARIO-42"


# ---------------- repr não vaza conteúdo ----------------

def test_answer_candidate_repr_redacts_content():
    c = AnswerCandidate(candidate_id="c1", engine_id="e", content=SEGREDO)
    r = repr(c)
    assert SEGREDO not in r
    assert "chars" in r and "c1" in r


def test_council_audit_repr_redacts_metadata():
    a = CouncilAuditRecord(session_id="s", event_type="ev",
                           metadata={"texto": SEGREDO})
    r = repr(a)
    assert SEGREDO not in r
    assert "keys" in r


def test_arbiter_repr_redacts_final_content():
    from nomos.council.models import ArbiterDecision
    a = ArbiterDecision(decision_id="d", final_content=SEGREDO)
    assert SEGREDO not in repr(a)


# ---------------- invariantes fail-closed ----------------

def test_private_mode_forces_persist_false():
    s = CouncilSession(session_id="s", mode=CouncilMode.CRITICAL,
                       risk_level=CouncilRiskLevel.A2, private_mode=True)
    assert s.persist_allowed is False


def test_local_only_forces_cloud_false():
    s = CouncilSession(session_id="s", mode=CouncilMode.BALANCED,
                       risk_level=CouncilRiskLevel.A1, local_only=True,
                       cloud_allowed=True)
    assert s.cloud_allowed is False
    p = CouncilPolicy(mode=CouncilMode.BALANCED, local_only=True, cloud_allowed=True)
    assert p.cloud_allowed is False


def test_paranoid_forces_local_only():
    p = CouncilPolicy(mode=CouncilMode.PARANOID, local_only=False, cloud_allowed=True)
    assert p.local_only is True and p.cloud_allowed is False


def test_contains_sensitive_data_denies_cloud_in_model():
    from nomos.council.models import RiskAssessment
    r = RiskAssessment(risk_level=CouncilRiskLevel.A3, contains_sensitive_data=True)
    assert r.cloud_allowed is False


def test_blind_review_detects_self_judging():
    conflito = BlindReview(review_id="r", judge_engine_id="local:m1",
                           candidate_alias="A", candidate_engine_id="local:m1")
    assert conflito.is_self_judging is True
    ok = BlindReview(review_id="r", judge_engine_id="local:m2",
                     candidate_alias="A", candidate_engine_id="local:m1")
    assert ok.is_self_judging is False


# ---------------- pureza: sem I/O, sem rede, sem motor ----------------

def _imports_do_modulo():
    src = open(models.__file__, encoding="utf-8").read()
    arvore = ast.parse(src)
    nomes = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                nomes.add(node.module)
    return nomes


def test_models_do_not_import_network_modules():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib", "urllib.request",
                 "asyncio", "requests", "aiohttp", "httpx", "ftplib", "smtplib"}
    usados = _imports_do_modulo()
    assert not (usados & proibidos), f"import de rede proibido: {usados & proibidos}"


def test_models_do_not_import_engine_modules():
    usados = _imports_do_modulo()
    # nenhum import de motor/LLM/runtime/persistência/subprocesso
    proibidos_prefixo = ("nomos.cognition", "nomos.runtime", "nomos.ext",
                         "subprocess", "threading", "multiprocessing",
                         "sqlite3", "llama", "torch", "transformers")
    ruins = [m for m in usados
             if any(m == p or m.startswith(p + ".") for p in proibidos_prefixo)]
    assert not ruins, f"import de motor/persistência proibido: {ruins}"


def test_models_only_stdlib_top_level():
    """Todos os imports do módulo são stdlib puros."""
    usados = _imports_do_modulo()
    stdlib_ok = {"__future__", "json", "uuid", "dataclasses", "enum", "typing"}
    externos = {m.split(".")[0] for m in usados} - {s.split(".")[0] for s in stdlib_ok}
    assert not externos, f"imports não-stdlib inesperados: {externos}"
