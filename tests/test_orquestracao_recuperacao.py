"""NH-004 — gerenciador de recuperação (retry/backoff/circuit-breaker).

Invariantes cobertos (hardening ETAPA 12 da missão NH):
- retry SÓ para nó idempotente; não-idempotente falha na 1ª (nunca repete
  efeito colateral às cegas);
- backoff exponencial com teto, via relógio injetável (teste não dorme);
- circuit-breaker por ferramenta: N falhas consecutivas abrem o circuito e
  chamadas seguintes falham imediatamente (fail-closed, sem tempestade);
- sucesso fecha o circuito (reset);
- orçamento global de tentativas por missão: esgotado ⇒ tudo falha fechado
  (anti retry-storm);
- tudo auditado; exceção do executor nunca escapa (vira falha).
"""
from __future__ import annotations

from nomos.orquestracao.grafo import No
from nomos.orquestracao.recuperacao import (
    GerenciadorRecuperacao, PoliticaRecuperacao,
)


class AuditFake:
    def __init__(self):
        self.eventos: list[tuple[str, dict]] = []

    def append(self, evento: str, **campos) -> None:
        self.eventos.append((evento, campos))

    def nomes(self) -> list[str]:
        return [e for e, _ in self.eventos]


class Dorminhoco:
    """Captura os sleeps pedidos em vez de dormir (teste rápido)."""

    def __init__(self):
        self.pausas: list[float] = []

    def __call__(self, segundos: float) -> None:
        self.pausas.append(segundos)


def _falha_n_vezes(n: int, depois: str = "ok"):
    estado = {"restantes": n}

    def executor(**kw):
        if estado["restantes"] > 0:
            estado["restantes"] -= 1
            raise RuntimeError("transiente")
        return depois
    return executor


def _ger(politica=None, audit=None, dormir=None):
    return GerenciadorRecuperacao(politica=politica or PoliticaRecuperacao(),
                                  audit=audit, dormir=dormir or Dorminhoco())


# ---------- idempotência governa retry ----------

def test_nao_idempotente_falha_na_primeira():
    audit = AuditFake()
    ger = _ger(audit=audit)
    no = No("n1", "tool", idempotente=False)
    ok, motivo, tentativas = ger.executar(no, _falha_n_vezes(1), {})
    assert not ok
    assert tentativas == 1
    assert "recuperacao.sem_retry" in audit.nomes()


def test_idempotente_recupera():
    ger = _ger(politica=PoliticaRecuperacao(max_tentativas=3))
    no = No("n1", "tool", idempotente=True)
    ok, resultado, tentativas = ger.executar(no, _falha_n_vezes(2), {})
    assert ok
    assert resultado == "ok"
    assert tentativas == 3


def test_idempotente_esgota_tentativas():
    ger = _ger(politica=PoliticaRecuperacao(max_tentativas=2))
    no = No("n1", "tool", idempotente=True)
    ok, motivo, tentativas = ger.executar(no, _falha_n_vezes(99), {})
    assert not ok
    assert tentativas == 2
    assert "esgotad" in str(motivo)


# ---------- backoff exponencial com teto ----------

def test_backoff_exponencial_com_teto():
    dormir = Dorminhoco()
    ger = _ger(politica=PoliticaRecuperacao(max_tentativas=5, backoff_base=1.0,
                                            backoff_teto=4.0, circuito_limite=99),
               dormir=dormir)
    no = No("n1", "tool", idempotente=True)
    ger.executar(no, _falha_n_vezes(99), {})
    assert dormir.pausas == [1.0, 2.0, 4.0, 4.0]     # 1,2,4,teto


# ---------- circuit-breaker ----------

def test_circuito_abre_apos_falhas_consecutivas():
    audit = AuditFake()
    ger = _ger(politica=PoliticaRecuperacao(max_tentativas=1, circuito_limite=3),
               audit=audit)
    no = No("n1", "tool-x", idempotente=True)
    for _ in range(3):
        ger.executar(no, _falha_n_vezes(99), {})
    ok, motivo, tentativas = ger.executar(no, lambda **kw: "nunca-roda", {})
    assert not ok
    assert tentativas == 0
    assert "circuito aberto" in str(motivo)
    assert "recuperacao.circuito.aberto" in audit.nomes()


def test_sucesso_fecha_circuito():
    ger = _ger(politica=PoliticaRecuperacao(max_tentativas=1, circuito_limite=3))
    no = No("n1", "tool-y", idempotente=True)
    ger.executar(no, _falha_n_vezes(99), {})
    ger.executar(no, _falha_n_vezes(99), {})
    ok, _, _ = ger.executar(no, lambda **kw: "ok", {})   # sucesso zera contagem
    assert ok
    for _ in range(2):
        ger.executar(no, _falha_n_vezes(99), {})
    ok2, _, _ = ger.executar(no, lambda **kw: "ok", {})  # ainda fechado (2<3)
    assert ok2


def test_circuito_por_ferramenta_isolado():
    ger = _ger(politica=PoliticaRecuperacao(max_tentativas=1, circuito_limite=1))
    ger.executar(No("a", "tool-a", idempotente=True), _falha_n_vezes(99), {})
    ok, _, _ = ger.executar(No("b", "tool-b", idempotente=True),
                            lambda **kw: "ok", {})
    assert ok                                            # tool-b não herda circuito de tool-a


# ---------- orçamento global (anti retry-storm) ----------

def test_orcamento_global_esgotado_falha_fechado():
    audit = AuditFake()
    ger = _ger(politica=PoliticaRecuperacao(max_tentativas=3, orcamento_missao=4),
               audit=audit)
    no1 = No("n1", "tool", idempotente=True)
    ger.executar(no1, _falha_n_vezes(99), {})            # consome 3
    ok, motivo, tentativas = ger.executar(
        No("n2", "tool2", idempotente=True), _falha_n_vezes(99), {})
    assert not ok
    assert tentativas <= 1                               # só restava 1 do orçamento
    ok3, motivo3, t3 = ger.executar(
        No("n3", "tool3", idempotente=True), lambda **kw: "ok", {})
    assert not ok3
    assert t3 == 0
    assert "orçamento" in str(motivo3)
    assert "recuperacao.orcamento.esgotado" in audit.nomes()


# ---------- exceção nunca escapa ----------

def test_excecao_vira_falha_com_tipo():
    ger = _ger()
    no = No("n1", "tool", idempotente=False)

    def executor(**kw):
        raise ValueError("dado ruim")
    ok, motivo, _ = ger.executar(no, executor, {})
    assert not ok
    assert "ValueError" in str(motivo)
