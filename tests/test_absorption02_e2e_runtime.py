"""ABSORPTION-02 / FASE 5 — a cadeia inteira, ponta a ponta.

    prompt → planner → DAG → registry → PDP → PEP → boundary → adapter
           → effect → audit → result

Os casos determinísticos usam `ProvedorTeste` (sem rede) para o resultado não
depender do humor de um modelo. Há UM teste com o motor real (Ollama), que
pula sozinho se o backend não estiver de pé — o runtime governado nunca
dependeu de LLM, e a suíte não passa a depender agora.
"""
from __future__ import annotations

import json

import pytest

from nomos.agents.manifest import FERRAMENTAS
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.recuperacao import PoliticaRecuperacao
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.pdp import ArmazemNonce, Autorizacao, Chaveiro, Decisor
from nomos.pdp.autorizacao import agora_utc
from nomos.runtime.governado import AUDIENCIA_RUNTIME, RuntimeGovernado
from nomos.runtime.inferencia import (
    InferenciaIndisponivel, ProvedorLocal, ProvedorTeste, llm_para_planejador,
)

CHAVE = b"0123456789abcdef0123456789abcdef"


def _ctx(tmp_path):
    home = tmp_path / "h"
    home.mkdir(parents=True, exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


def _sim(_d):
    return True


def _nao(_d):
    return False


def _eventos(ctx):
    p = ctx["home"] / "logs" / "audit.jsonl"
    return [json.loads(x).get("event") for x in p.read_text().splitlines() if x.strip()] \
        if p.exists() else []


def _plano(passos):
    return llm_para_planejador(ProvedorTeste(json.dumps(passos)))


# ---------------------------------------------------------- 1. read allow

def test_e2e_read_allow(tmp_path):
    ctx = _ctx(tmp_path)
    alvo = tmp_path / "leitura.txt"
    alvo.write_text("conteudo real")
    rt = RuntimeGovernado(ctx, _sim)
    res = rt.rodar("ler", llm=_plano([
        {"id": "a", "ferramenta": "arquivo_ler", "params": {"alvo": str(alvo)}}]))
    assert res.ok
    assert res.missao.nos["a"].status == "OK"
    ev = _eventos(ctx)
    for esperado in ("pdp.decisao", "pep.aplicacao", "agente.ferramenta.usada",
                     "orquestracao.no.ok"):
        assert esperado in ev


# ------------------------------------------------- 2/3. write allow e deny

def test_e2e_write_allow_autorizado(tmp_path):
    """Escrita é confinada ao NOMOS_HOME/workspace — caminho relativo."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim)
    res = rt.rodar("escrever", llm=_plano([
        {"id": "w", "ferramenta": "arquivo_escrever",
         "params": {"alvo": "saida.txt", "conteudo": "efeito real"}}]))
    assert res.ok, res.resumo()
    escrito = ctx["home"] / "workspace" / "saida.txt"
    assert escrito.exists()
    assert "efeito real" in escrito.read_text()


def test_e2e_write_deny(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _nao)
    res = rt.rodar("escrever", llm=_plano([
        {"id": "w", "ferramenta": "arquivo_escrever",
         "params": {"alvo": "negado.txt", "conteudo": "x"}}]))
    assert not res.ok
    assert res.missao.nos["w"].status == "NEGADO"
    assert not (ctx["home"] / "workspace" / "negado.txt").exists()


def test_e2e_write_fora_do_workspace_e_recusado(tmp_path):
    """Path traversal: absoluto fora do workspace ⇒ recusa de segurança."""
    ctx = _ctx(tmp_path)
    fora = tmp_path / "fora.txt"
    rt = RuntimeGovernado(ctx, _sim)
    res = rt.rodar("escapar", llm=_plano([
        {"id": "w", "ferramenta": "arquivo_escrever",
         "params": {"alvo": str(fora), "conteudo": "x"}}]))
    assert not res.ok
    assert not fora.exists()
    assert "DestinoInseguro" in res.missao.nos["w"].detalhe


def test_e2e_traversal_relativo_e_recusado(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim)
    res = rt.rodar("traversal", llm=_plano([
        {"id": "w", "ferramenta": "arquivo_escrever",
         "params": {"alvo": "../../escapou.txt", "conteudo": "x"}}]))
    assert not res.ok
    assert not (tmp_path.parent / "escapou.txt").exists()


# ---------------------------------------------------- 4. unknown capability

def test_e2e_unknown_capability(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim)
    res = rt.rodar("shell", llm=_plano([
        {"id": "s", "ferramenta": "shell_exec", "params": {"alvo": "id"}}]))
    assert not res.ok
    assert res.missao is None


# ----------------------------------------------- 5/6. expired e replay

def _auth_custom(mf_caps, risco="A5", **kw):
    chaveiro = Chaveiro({"k": CHAVE})
    agora = agora_utc()
    base = dict(capacidades=tuple(mf_caps), sujeito="runtime-governado",
                audiencia=AUDIENCIA_RUNTIME, emitida_em=agora,
                expira_em=agora + __import__("datetime").timedelta(hours=1),
                risco_max=risco)
    base.update(kw)
    return chaveiro, chaveiro.assinar(Autorizacao(**base), "k")


def test_e2e_expired_authorization(tmp_path):
    from datetime import timedelta
    ctx = _ctx(tmp_path)
    agora = agora_utc()
    chaveiro, _ = _auth_custom(tuple(FERRAMENTAS))
    vencida = chaveiro.assinar(Autorizacao(
        capacidades=tuple(FERRAMENTAS), sujeito="runtime-governado",
        audiencia=AUDIENCIA_RUNTIME, emitida_em=agora - timedelta(hours=3),
        expira_em=agora - timedelta(hours=2), risco_max="A5"), "k")
    registro = RegistroCapacidades(policy=ctx["policy"], audit=ctx["audit"])
    decisor = Decisor(chaveiro, registro, audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce(), audit=ctx["audit"])
    rt = RuntimeGovernado(ctx, _sim, autorizacao=vencida, decisor=decisor)
    res = rt.rodar("ler", llm=_plano([{"id": "d", "ferramenta": "doutor"}]))
    assert not res.ok
    assert "expirada" in res.missao.nos["d"].detalhe


def test_e2e_replay(tmp_path):
    from nomos.pdp.decisor import Efeito, Motivo, Pedido
    ctx = _ctx(tmp_path)
    chaveiro, auth = _auth_custom(("doutor",), risco="A0", nonce="fixo")
    registro = RegistroCapacidades(policy=ctx["policy"], audit=ctx["audit"])
    decisor = Decisor(chaveiro, registro, audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce(), audit=ctx["audit"])
    p = Pedido(capacidade="doutor", sujeito="runtime-governado")
    assert decisor.decidir(p, auth).efeito is Efeito.ALLOW
    assert decisor.decidir(p, auth).motivo is Motivo.NONCE_REPETIDO


# ------------------------------------------------- 7/10. dependência e parcial

def test_e2e_dependency_failure_bloqueia_dependentes(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim)
    res = rt.rodar("dep", llm=_plano([
        {"id": "mau", "ferramenta": "arquivo_ler",
         "params": {"alvo": str(tmp_path / "nao-existe")}},
        {"id": "dep", "ferramenta": "doutor", "depende_de": ["mau"]}]))
    assert not res.ok
    assert res.missao.nos["mau"].status == "FALHOU"
    assert res.missao.nos["dep"].status == "BLOQUEADO"


def test_e2e_partial_dag(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim)
    res = rt.rodar("parcial", llm=_plano([
        {"id": "mau", "ferramenta": "arquivo_ler",
         "params": {"alvo": str(tmp_path / "sumiu")}},
        {"id": "dep", "ferramenta": "doutor", "depende_de": ["mau"]},
        {"id": "bom", "ferramenta": "doutor"}]))
    assert res.missao.nos["mau"].status == "FALHOU"
    assert res.missao.nos["dep"].status == "BLOQUEADO"
    assert res.missao.nos["bom"].status == "OK"


# ------------------------------------------------- 8/9. retry

def test_e2e_retry_idempotente(tmp_path):
    """arquivo_ler é A0 ⇒ idempotente no registro ⇒ pode repetir."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim,
                          politica_recuperacao=PoliticaRecuperacao(
                              max_tentativas=3, backoff_base=0.0))
    res = rt.rodar("retry", llm=_plano([
        {"id": "r", "ferramenta": "arquivo_ler",
         "params": {"alvo": str(tmp_path / "inexistente")}}]))
    assert not res.ok
    assert res.missao.nos["r"].tentativas == 3


def test_e2e_no_retry_mutante(tmp_path):
    """arquivo_escrever é A1 ⇒ NÃO idempotente ⇒ uma tentativa só."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim,
                          politica_recuperacao=PoliticaRecuperacao(
                              max_tentativas=5, backoff_base=0.0))
    res = rt.rodar("sem retry", llm=_plano([
        {"id": "w", "ferramenta": "arquivo_escrever",
         "params": {"alvo": "../fora.txt", "conteudo": "x"}}]))
    assert not res.ok
    assert res.missao.nos["w"].tentativas == 1


# ------------------------------------------------- 11/12. provider e limites

def test_e2e_provider_failure_falha_fechado(tmp_path):
    class Quebrado:
        nome = "quebrado"

        def disponivel(self):
            return True

        def propor(self, objetivo):
            raise InferenciaIndisponivel("backend caiu")

    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim)
    plano = rt.planejar("x", llm=llm_para_planejador(Quebrado()))
    assert not plano.ok                      # provider morto ⇒ plano fail-closed
    assert rt.executar(plano).missao is None


def test_e2e_orcamento_limita_tentativas(tmp_path):
    """Não há timeout duro por nó (é do sandbox); o limite aqui é o ORÇAMENTO
    de tentativas da missão — anti retry-storm, verificado de verdade."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim,
                          politica_recuperacao=PoliticaRecuperacao(
                              max_tentativas=3, backoff_base=0.0,
                              orcamento_missao=4, circuito_limite=99))
    res = rt.rodar("orcamento", llm=_plano([
        {"id": "a", "ferramenta": "arquivo_ler",
         "params": {"alvo": str(tmp_path / "x1")}},
        {"id": "b", "ferramenta": "arquivo_ler",
         "params": {"alvo": str(tmp_path / "x2")}}]))
    assert not res.ok
    gastas = sum(n.tentativas for n in res.missao.nos.values())
    assert gastas <= 4, f"orçamento estourado: {gastas}"


# ------------------------------------------------- motor REAL (opt-in)

def _ollama_vivo() -> bool:
    try:
        return ProvedorLocal(modelo="qwen2.5-7b-ptctx:latest").disponivel()
    except Exception:
        return False


@pytest.mark.skipif(not _ollama_vivo(), reason="Ollama local indisponível")
def test_e2e_com_motor_real(tmp_path):
    """Cadeia completa com inferência real. Se o modelo devolver algo
    inaproveitável, o plano falha FECHADO — que também é resultado correto."""
    ctx = _ctx(tmp_path)
    provedor = ProvedorLocal(modelo="qwen2.5-7b-ptctx:latest")
    rt = RuntimeGovernado(ctx, _sim)
    objetivo = ('Responda APENAS com JSON válido, sem texto em volta: '
                '[{"id":"a","ferramenta":"doutor"}]')
    plano = rt.planejar(objetivo, llm=llm_para_planejador(provedor))
    if not plano.ok:
        assert plano.motivo                  # fail-closed explicado
        return
    res = rt.executar(plano)
    ev = _eventos(ctx)
    assert "pdp.decisao" in ev and "pep.aplicacao" in ev
    for passo in plano.passos:               # nada veio do modelo
        assert passo.categoria is FERRAMENTAS[passo.ferramenta]
        assert passo.idempotente is (
            passo.categoria.value.startswith("A0"))
    assert isinstance(res.ok, bool)
