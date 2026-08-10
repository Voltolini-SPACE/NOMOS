"""ABSORPTION-02 / FASE 1 — as rotas legadas atravessam o caminho governado.

Antes desta fase, `nomos agentes usar` e a conversa amigável chamavam o
`AgentToolBoundary` direto: gate A0–A6 sim, mas sem token assinado, escopo,
TTL, nonce ou anti-replay. Agora ambas passam por
`runtime.governado.usar_ferramenta_governada`, que é a MESMA cadeia do
runtime — nenhuma política paralela foi criada.

Ordem que estes testes fixam:

    identidade/manifesto (boundary) → PDP → PEP → boundary (gate) → adapter

O manifesto é checado ANTES do PDP de propósito: "essa ferramenta não é sua"
é pergunta de identidade, e a resposta precisa continuar sendo a do boundary,
com a mensagem e o evento `agente.ferramenta.negada` que já existiam.
"""
from __future__ import annotations

import json
from datetime import timedelta

from nomos.agents.manifest import AgentManifest
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.pdp import ArmazemNonce, Autorizacao, Chaveiro, Decisor
from nomos.pdp.autorizacao import agora_utc
from nomos.runtime.governado import (
    AUDIENCIA_RUNTIME, sessao_pdp, usar_ferramenta_governada,
)

CHAVE = b"0123456789abcdef0123456789abcdef"


def _ctx(tmp_path):
    home = tmp_path / "h"
    home.mkdir(parents=True, exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


def _mf(ferramentas=("arquivo_ler", "doutor"), risco="A0", nome="agente-teste"):
    return AgentManifest(name=nome, objetivo="teste", ferramentas=tuple(ferramentas),
                         risco_max=risco)


def _eventos(ctx):
    caminho = ctx["home"] / "logs" / "audit.jsonl"
    if not caminho.exists():
        return []
    return [json.loads(linha).get("event")
            for linha in caminho.read_text().splitlines() if linha.strip()]


def _sim(_decisao):
    return True


# ---------------------------------------------- a cadeia está no caminho

def test_rota_de_ferramenta_unica_passa_por_pdp_e_pep(tmp_path):
    ctx = _ctx(tmp_path)
    ok, _res = usar_ferramenta_governada(ctx, _mf(), "doutor", aprovador=_sim)
    assert ok
    ev = _eventos(ctx)
    assert "pdp.decisao" in ev
    assert "pep.aplicacao" in ev
    assert "agente.ferramenta.usada" in ev
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao")


def test_fora_do_manifesto_continua_sendo_o_boundary_que_nega(tmp_path):
    """Regressão: o caminho governado não pode piorar o diagnóstico."""
    ctx = _ctx(tmp_path)
    ok, msg = usar_ferramenta_governada(ctx, _mf(("arquivo_ler",)), "doutor",
                                        aprovador=_sim)
    assert not ok
    assert "não tem a ferramenta" in str(msg)
    assert "agente.ferramenta.negada" in _eventos(ctx)


# ---------------------------------------------- gates da FASE 1

def test_unknown_capability_default_deny(tmp_path):
    ctx = _ctx(tmp_path)
    ok, msg = usar_ferramenta_governada(ctx, _mf(), "shell_exec", aprovador=_sim)
    assert not ok
    assert "não tem a ferramenta" in str(msg)


def test_expired_auth_deny(tmp_path):
    ctx = _ctx(tmp_path)
    mf = _mf()
    chaveiro = Chaveiro({"k": CHAVE})
    registro = RegistroCapacidades(policy=ctx["policy"], approver=_sim,
                                   audit=ctx["audit"])
    agora = agora_utc()
    vencida = chaveiro.assinar(Autorizacao(
        capacidades=mf.ferramentas, sujeito=mf.name, audiencia=AUDIENCIA_RUNTIME,
        emitida_em=agora - timedelta(hours=3),
        expira_em=agora - timedelta(hours=2), risco_max="A0"), "k")
    decisor = Decisor(chaveiro, registro, audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce(), audit=ctx["audit"])
    ok, msg = usar_ferramenta_governada(ctx, mf, "doutor", aprovador=_sim,
                                        decisor=decisor, autorizacao=vencida)
    assert not ok
    assert "expirada" in str(msg)


def test_replay_deny(tmp_path):
    """Mesma autorização, mesmo nonce fixo ⇒ segunda vez é replay."""
    ctx = _ctx(tmp_path)
    mf = _mf()
    chaveiro = Chaveiro({"k": CHAVE})
    registro = RegistroCapacidades(policy=ctx["policy"], approver=_sim,
                                   audit=ctx["audit"])
    agora = agora_utc()
    auth = chaveiro.assinar(Autorizacao(
        capacidades=mf.ferramentas, sujeito=mf.name, audiencia=AUDIENCIA_RUNTIME,
        emitida_em=agora, expira_em=agora + timedelta(hours=1),
        risco_max="A0", nonce="nonce-fixo"), "k")
    decisor = Decisor(chaveiro, registro, audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce(), audit=ctx["audit"])

    from nomos.pdp.decisor import Efeito, Motivo, Pedido
    p = Pedido(capacidade="doutor", sujeito=mf.name)
    assert decisor.decidir(p, auth).efeito is Efeito.ALLOW
    assert decisor.decidir(p, auth).motivo is Motivo.NONCE_REPETIDO


def test_wrong_scope_deny(tmp_path):
    """Autorização com caminhos restritos nega recurso fora do escopo."""
    ctx = _ctx(tmp_path)
    mf = _mf(("arquivo_ler",))
    chaveiro = Chaveiro({"k": CHAVE})
    registro = RegistroCapacidades(policy=ctx["policy"], approver=_sim,
                                   audit=ctx["audit"])
    agora = agora_utc()
    auth = chaveiro.assinar(Autorizacao(
        capacidades=mf.ferramentas, sujeito=mf.name, audiencia=AUDIENCIA_RUNTIME,
        emitida_em=agora, expira_em=agora + timedelta(hours=1),
        risco_max="A0", caminhos=("/escopo/permitido",)), "k")
    decisor = Decisor(chaveiro, registro, audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce(), audit=ctx["audit"])
    ok, msg = usar_ferramenta_governada(ctx, mf, "arquivo_ler",
                                        alvo="/fora/do/escopo/segredo.txt",
                                        aprovador=_sim, decisor=decisor,
                                        autorizacao=auth)
    assert not ok
    assert "escopo" in str(msg)


def test_autorizacao_e_escopada_pelo_manifesto(tmp_path):
    """Um agente que declara menos recebe autorização menor — não a allowlist toda."""
    ctx = _ctx(tmp_path)
    mf = _mf(("arquivo_ler",))
    registro = RegistroCapacidades(policy=ctx["policy"], audit=ctx["audit"])
    _decisor, auth = sessao_pdp(registro, mf, audit=ctx["audit"])
    assert set(auth.capacidades) == {"arquivo_ler"}
    assert auth.risco_max == "A0"
    assert auth.audiencia == AUDIENCIA_RUNTIME


def test_risco_do_manifesto_limita_o_teto(tmp_path):
    """Manifesto A1 não autoriza capacidade A5."""
    ctx = _ctx(tmp_path)
    mf = AgentManifest(name="restrito", objetivo="t",
                       ferramentas=("skill_rodar",), risco_max="A5",
                       pode_executar_skill=True)
    registro = RegistroCapacidades(policy=ctx["policy"], audit=ctx["audit"])
    _d, auth = sessao_pdp(registro, mf, audit=ctx["audit"])
    assert auth.risco_max == "A5"          # coerente com o que o manifesto exige

    baixo = AgentManifest(name="baixo", objetivo="t",
                          ferramentas=("arquivo_ler",), risco_max="A0")
    _d2, auth2 = sessao_pdp(registro, baixo, audit=ctx["audit"])
    assert auth2.risco_max == "A0"
    assert "skill_rodar" not in auth2.capacidades


# ---------------------------------------------- sem política paralela

def test_nao_existe_pdp_paralelo_no_codigo():
    """Proíbe `legacy_pdp`, `simple_policy`, `agent_gate_v2` e afins.

    Procura o termo como IDENTIFICADOR (def/class/import/atribuição), não como
    substring: citar o nome numa docstring para dizer "isto não deve existir"
    é justamente o oposto de criá-lo.
    """
    import pathlib
    import re
    raiz = pathlib.Path(__file__).resolve().parents[1] / "src" / "nomos"
    proibidos = ("legacy_pdp", "simple_policy", "agent_gate_v2", "pdp_v2",
                 "policy_bypass", "skip_pdp")
    padrao = re.compile(
        r"^\s*(?:def|class)\s+(%s)\b|^\s*(?:from|import)\s+.*\b(%s)\b|^\s*(%s)\s*="
        % ("|".join(proibidos), "|".join(proibidos), "|".join(proibidos)),
        re.MULTILINE)
    achados = []
    for arq in raiz.rglob("*.py"):
        if padrao.search(arq.read_text(encoding="utf-8")):
            achados.append(arq.relative_to(raiz).as_posix())
    assert not achados, f"mecanismo de política paralelo detectado: {achados}"


def test_sessao_pdp_e_a_unica_fonte_de_autorizacao():
    """Só `sessao_pdp` emite autorização — ninguém assina por fora."""
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[1] / "src" / "nomos"
    assinantes = []
    for arq in raiz.rglob("*.py"):
        if arq.parts[-2:] == ("pdp", "autorizacao.py"):
            continue                      # é quem implementa assinar()
        txt = arq.read_text(encoding="utf-8")
        if ".assinar(" in txt:
            assinantes.append(arq.relative_to(raiz).as_posix())
    assert assinantes == ["runtime/governado.py"], (
        f"emissores de autorização fora de sessao_pdp: {assinantes}")
