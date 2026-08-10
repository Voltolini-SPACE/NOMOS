"""ABSORPTION-03 / FASES 4 e 5 — registry race e timeout duro por nó.

**Registry race.** O ataque é temporal:

    plan(capability=A) → authorization(A) → registry muda → execute

A autorização vale para o mundo que ela VIU. Se o descritor de A mudou entre a
emissão e a execução — removida, risco alterado, idempotência alterada,
executor trocado — a decisão que foi tomada com os valores antigos não vale
mais. O PDP nega com `CAPACIDADE_MUDOU`.

**Timeout duro.** "Deu timeout" não é resposta: o que importa é se o mundo
mudou. Por isso o resultado é CLASSIFICADO, e `EFEITO_DESCONHECIDO` nunca
autoriza retry — nem mesmo para capacidade idempotente, porque idempotência
diz que repetir é seguro, não que o efeito parcial foi revertido.
"""
from __future__ import annotations

import time
from datetime import timedelta

import pytest

from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, EfeitoTimeout, ErroTimeout,
    versao_de_capacidade,
)
from nomos.adapters.filesystem import FilesystemAdapter
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.pdp import ArmazemNonce, Autorizacao, Chaveiro, Decisor, Efeito, Motivo, Pedido
from nomos.pdp.autorizacao import agora_utc
from nomos.runtime.governado import AUDIENCIA_RUNTIME, _versoes_de, sessao_pdp

CHAVE = b"0123456789abcdef0123456789abcdef"


def _ctx(tmp_path):
    home = tmp_path / "h"
    home.mkdir(parents=True, exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


def _sim(_d):
    return True


def _registro(ctx):
    return RegistroCapacidades(policy=ctx["policy"], approver=_sim,
                               audit=ctx["audit"])


def _auth_com_versoes(registro, capacidades, versoes=None):
    chaveiro = Chaveiro({"k": CHAVE})
    agora = agora_utc()
    return chaveiro, chaveiro.assinar(Autorizacao(
        capacidades=tuple(capacidades), sujeito="suj",
        audiencia=AUDIENCIA_RUNTIME, emitida_em=agora,
        expira_em=agora + timedelta(hours=1), risco_max="A5",
        versoes=(versoes if versoes is not None
                 else _versoes_de(registro, capacidades))), "k")


def _decisor(chaveiro, registro, ctx):
    return Decisor(chaveiro, registro, audiencia=AUDIENCIA_RUNTIME,
                   armazem_nonce=ArmazemNonce(), audit=ctx["audit"])


# ============================================ FASE 4 — REGISTRY RACE

def test_versao_estavel_permite(tmp_path):
    ctx = _ctx(tmp_path)
    reg = _registro(ctx)
    ch, auth = _auth_com_versoes(reg, ("doutor",))
    d = _decisor(ch, reg, ctx).decidir(
        Pedido(capacidade="doutor", sujeito="suj", nonce="n1"), auth)
    assert d.efeito is Efeito.ALLOW


def test_capacidade_removida_apos_emissao_e_negada(tmp_path):
    """Capability removed after planning."""
    ctx = _ctx(tmp_path)
    reg = _registro(ctx)
    reg.registrar("temporaria", Category.READ_LOCAL, lambda **k: "x",
                  origem="teste", idempotente=True)
    ch, auth = _auth_com_versoes(reg, ("temporaria",))
    dec = _decisor(ch, reg, ctx)
    assert dec.decidir(Pedido(capacidade="temporaria", sujeito="suj",
                              nonce="a"), auth).efeito is Efeito.ALLOW

    reg.desregistrar("temporaria")                 # o mundo mudou
    d = dec.decidir(Pedido(capacidade="temporaria", sujeito="suj", nonce="b"), auth)
    assert d.efeito is Efeito.DENY
    # a capacidade some do registro: quem responde é o guard de desconhecida
    assert d.motivo in (Motivo.CAPACIDADE_DESCONHECIDA, Motivo.CAPACIDADE_MUDOU)


def test_idempotencia_alterada_apos_emissao_e_negada(tmp_path):
    """Metadata mutada: mesma capacidade, idempotência diferente ⇒ DENY."""
    ctx = _ctx(tmp_path)
    reg = _registro(ctx)
    reg.registrar("cap", Category.READ_LOCAL, lambda **k: "x",
                  origem="teste", idempotente=True)
    ch, auth = _auth_com_versoes(reg, ("cap",))
    dec = _decisor(ch, reg, ctx)
    assert dec.decidir(Pedido(capacidade="cap", sujeito="suj", nonce="a"),
                       auth).efeito is Efeito.ALLOW

    reg.desregistrar("cap")
    reg.registrar("cap", Category.READ_LOCAL, lambda **k: "x",
                  origem="teste", idempotente=False)      # mudou!
    d = dec.decidir(Pedido(capacidade="cap", sujeito="suj", nonce="b"), auth)
    assert d.efeito is Efeito.DENY
    assert d.motivo is Motivo.CAPACIDADE_MUDOU


def test_risco_alterado_apos_emissao_e_negado(tmp_path):
    ctx = _ctx(tmp_path)
    reg = _registro(ctx)
    reg.registrar("cap", Category.READ_LOCAL, lambda **k: "x", origem="t")
    ch, auth = _auth_com_versoes(reg, ("cap",))
    dec = _decisor(ch, reg, ctx)
    reg.desregistrar("cap")
    reg.registrar("cap", Category.WRITE_LOCAL, lambda **k: "x", origem="t")
    d = dec.decidir(Pedido(capacidade="cap", sujeito="suj", nonce="z"), auth)
    assert d.motivo is Motivo.CAPACIDADE_MUDOU


def test_executor_trocado_apos_emissao_e_negado(tmp_path):
    """Adapter trocado: mesmo nome, mesmo risco, executor diferente."""
    ctx = _ctx(tmp_path)
    reg = _registro(ctx)

    def original(**k):
        return "benigno"

    def substituto(**k):
        return "malicioso"

    reg.registrar("cap", Category.READ_LOCAL, original, origem="t", idempotente=True)
    ch, auth = _auth_com_versoes(reg, ("cap",))
    dec = _decisor(ch, reg, ctx)
    reg.desregistrar("cap")
    reg.registrar("cap", Category.READ_LOCAL, substituto, origem="t", idempotente=True)
    d = dec.decidir(Pedido(capacidade="cap", sujeito="suj", nonce="z"), auth)
    assert d.motivo is Motivo.CAPACIDADE_MUDOU


def test_versao_forjada_nao_passa(tmp_path):
    """Adulterar `versoes` quebra a assinatura — não é caminho de escape."""
    import dataclasses
    ctx = _ctx(tmp_path)
    reg = _registro(ctx)
    ch, auth = _auth_com_versoes(reg, ("doutor",))
    forjada = dataclasses.replace(auth, versoes=(("doutor", "0" * 16),))
    assert not ch.verificar(forjada)
    d = _decisor(ch, reg, ctx).decidir(
        Pedido(capacidade="doutor", sujeito="suj", nonce="n"), forjada)
    assert d.motivo is Motivo.ASSINATURA_INVALIDA


def test_sessao_pdp_carimba_versoes(tmp_path):
    ctx = _ctx(tmp_path)
    from nomos.runtime.governado import manifesto_do_runtime
    reg = _registro(ctx)
    _d, auth = sessao_pdp(reg, manifesto_do_runtime(("arquivo_ler", "doutor")),
                          audit=ctx["audit"])
    versoes = dict(auth.versoes)
    assert set(versoes) == {"arquivo_ler", "doutor"}
    assert versoes["arquivo_ler"] == versao_de_capacidade(reg, "arquivo_ler")


def test_autorizacao_sem_versoes_continua_valida(tmp_path):
    """Compatibilidade: autorização legada (sem versões) não é quebrada — o
    guard só age quando há versão para comparar."""
    ctx = _ctx(tmp_path)
    reg = _registro(ctx)
    ch, auth = _auth_com_versoes(reg, ("doutor",), versoes=())
    d = _decisor(ch, reg, ctx).decidir(
        Pedido(capacidade="doutor", sujeito="suj", nonce="n"), auth)
    assert d.efeito is Efeito.ALLOW


# ============================================ FASE 5 — TIMEOUT DURO

def test_deadline_estourado_impede_inicio(tmp_path):
    """O adapter nem começa — `exigir_prazo` roda antes de qualquer efeito."""
    raiz = tmp_path / "r"
    raiz.mkdir()
    alvo = raiz / "a.txt"
    alvo.write_text("x")

    class _Reg:
        def conhecida(self, n):
            return True

        def categoria_de(self, n):
            return Category.WRITE_LOCAL

        def risco_de(self, n):
            return "A1"

        def idempotente_de(self, n):
            return False

        def executor_de(self, n):
            return None

    ctx = CapabilityContext.de_registro(
        _Reg(), "fs_escrever", "suj", raizes=(str(raiz),),
        deadline_monotonic=time.monotonic() - 0.5)
    with pytest.raises(ErroTimeout):
        FilesystemAdapter().executar(
            CapabilityRequest(capacidade="fs_escrever", alvo=str(raiz / "novo.txt"),
                              argumentos={"conteudo": "y"}), ctx)
    assert not (raiz / "novo.txt").exists()          # nenhum efeito


def test_restante_reflete_o_prazo():
    class _Reg:
        conhecida = staticmethod(lambda n: True)
        categoria_de = staticmethod(lambda n: Category.READ_LOCAL)
        risco_de = staticmethod(lambda n: "A0")
        idempotente_de = staticmethod(lambda n: True)
        executor_de = staticmethod(lambda n: None)

    ctx = CapabilityContext.de_registro(_Reg(), "fs_ler", "s",
                                        deadline_monotonic=time.monotonic() + 5)
    r = ctx.restante()
    assert r is not None and 0 < r <= 5
    sem = CapabilityContext.de_registro(_Reg(), "fs_ler", "s")
    assert sem.restante() is None
    sem.exigir_prazo()                                # sem prazo não levanta


def test_classificacao_de_efeito_no_timeout_e_explicita():
    """`TIMED_OUT_EFFECT_UNKNOWN` existe justamente para não ser confundido
    com 'não aconteceu nada'."""
    assert EfeitoTimeout.SEM_EFEITO.value == "TIMED_OUT_NO_EFFECT"
    assert EfeitoTimeout.EFEITO_DESCONHECIDO.value == "TIMED_OUT_EFFECT_UNKNOWN"
    assert EfeitoTimeout.EFEITO_CONFIRMADO.value == "TIMED_OUT_EFFECT_CONFIRMED"
    assert len(set(EfeitoTimeout)) == 3


def test_retry_apos_timeout_nunca_vem_do_plano(tmp_path):
    """Regra herdada e reforçada: a decisão de repetir é do REGISTRO.

    Um nó que se declare idempotente para comprar retry após timeout é
    recusado na construção do grafo — a mesma defesa da ABSORPTION-01, aqui
    verificada no contexto de timeout.
    """
    from nomos.orquestracao.grafo import ErroGrafo, GrafoTarefas, No
    reg = RegistroCapacidades()
    with pytest.raises(ErroGrafo, match="não define o próprio risco"):
        GrafoTarefas([No("w", "arquivo_escrever", idempotente=True)], reg)


def test_efeito_desconhecido_nao_e_idempotente_por_definicao():
    """Documenta a regra em teste: idempotência autoriza REPETIR, não presume
    que um efeito parcial foi desfeito. As duas coisas não se confundem."""
    seguro = {EfeitoTimeout.SEM_EFEITO}
    assert EfeitoTimeout.EFEITO_DESCONHECIDO not in seguro
    assert EfeitoTimeout.EFEITO_CONFIRMADO not in seguro
