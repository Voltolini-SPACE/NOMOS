"""NH-002 — grafo de tarefas governado + resolvedor de dependências.

Invariantes cobertos:
- validação estrutural fail-closed: id duplicado, dependência desconhecida,
  ciclo, ferramenta fora do registro => ErroGrafo (nada executa);
- ordem topológica respeita dependências;
- CADA nó passa pelo policy.gate ANTES de executar; DENY não executa o nó
  e BLOQUEIA todos os dependentes transitivos;
- REQUIRE_APPROVAL sem aprovador => negado (mesma semântica do kernel);
- falha de executor => nó FALHOU e dependentes BLOQUEADOS;
- missão só é ok=True com TODOS os nós OK; tudo auditado.
"""
from __future__ import annotations

import pytest

from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.grafo import (
    ErroGrafo, GrafoTarefas, No, Orquestrador,
)
from nomos.orquestracao.registro import RegistroCapacidades


class AuditFake:
    def __init__(self):
        self.eventos: list[tuple[str, dict]] = []

    def append(self, evento: str, **campos) -> None:
        self.eventos.append((evento, campos))

    def nomes(self) -> list[str]:
        return [e for e, _ in self.eventos]


@pytest.fixture()
def policy(tmp_path):
    return PolicyEngine(tmp_path / "policy.json")


@pytest.fixture()
def registro(policy):
    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    reg.registrar("ler-a0", Category.READ_LOCAL, lambda **kw: "lido", "teste")
    reg.registrar("gravar-a1", Category.WRITE_LOCAL, lambda **kw: "gravado", "teste")
    reg.registrar("quebra-a0", Category.READ_LOCAL,
                  lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")), "teste")
    return reg


# ---------- validação estrutural (fail-closed, nada executa) ----------

def test_id_duplicado(registro):
    with pytest.raises(ErroGrafo):
        GrafoTarefas([No("n1", "ler-a0"), No("n1", "ler-a0")], registro)


def test_dependencia_desconhecida(registro):
    with pytest.raises(ErroGrafo):
        GrafoTarefas([No("n1", "ler-a0", depende_de=("fantasma",))], registro)


def test_ciclo_detectado(registro):
    with pytest.raises(ErroGrafo):
        GrafoTarefas([
            No("n1", "ler-a0", depende_de=("n2",)),
            No("n2", "ler-a0", depende_de=("n1",)),
        ], registro)


def test_ferramenta_fora_do_registro(registro):
    with pytest.raises(ErroGrafo):
        GrafoTarefas([No("n1", "tool-fantasma")], registro)


def test_autodependencia(registro):
    with pytest.raises(ErroGrafo):
        GrafoTarefas([No("n1", "ler-a0", depende_de=("n1",))], registro)


# ---------- ordem topológica ----------

def test_ordem_respeita_dependencias(registro):
    g = GrafoTarefas([
        No("c", "ler-a0", depende_de=("a", "b")),
        No("a", "ler-a0"),
        No("b", "ler-a0", depende_de=("a",)),
    ], registro)
    ordem = g.ordem_topologica()
    assert ordem.index("a") < ordem.index("b") < ordem.index("c")


# ---------- execução governada ----------

def test_execucao_a0_sem_aprovador_ok(policy, registro):
    """A0 é ALLOW por default: executa sem aprovador."""
    audit = AuditFake()
    orq = Orquestrador(registro, policy, approver=None, audit=audit)
    g = GrafoTarefas([No("n1", "ler-a0")], registro)
    r = orq.executar(g)
    assert r.ok
    assert r.nos["n1"].status == "OK"
    assert r.nos["n1"].resultado == "lido"
    assert "orquestracao.no.ok" in audit.nomes()


def test_a1_sem_aprovador_negado_e_dependente_bloqueado(policy, registro):
    """A1 exige aprovação; sem aprovador => nó NEGADO e dependente BLOQUEADO."""
    audit = AuditFake()
    orq = Orquestrador(registro, policy, approver=None, audit=audit)
    g = GrafoTarefas([
        No("escreve", "gravar-a1"),
        No("depois", "ler-a0", depende_de=("escreve",)),
    ], registro)
    r = orq.executar(g)
    assert not r.ok
    assert r.nos["escreve"].status == "NEGADO"
    assert r.nos["depois"].status == "BLOQUEADO"
    assert "orquestracao.no.negado" in audit.nomes()
    assert "orquestracao.no.bloqueado" in audit.nomes()


def test_a1_com_aprovador_executa(policy, registro):
    orq = Orquestrador(registro, policy, approver=lambda d: True)
    g = GrafoTarefas([No("escreve", "gravar-a1")], registro)
    r = orq.executar(g)
    assert r.ok
    assert r.nos["escreve"].status == "OK"


def test_falha_de_executor_bloqueia_dependentes(policy, registro):
    audit = AuditFake()
    orq = Orquestrador(registro, policy, approver=None, audit=audit)
    g = GrafoTarefas([
        No("explode", "quebra-a0"),
        No("filho", "ler-a0", depende_de=("explode",)),
        No("neto", "ler-a0", depende_de=("filho",)),
        No("livre", "ler-a0"),
    ], registro)
    r = orq.executar(g)
    assert not r.ok
    assert r.nos["explode"].status == "FALHOU"
    assert r.nos["filho"].status == "BLOQUEADO"
    assert r.nos["neto"].status == "BLOQUEADO"
    assert r.nos["livre"].status == "OK"          # ramo independente segue


def test_no_sem_executor_falha_fechado(policy, registro):
    """Nativa sem wiring de executor => nó falha (nunca inventa execução)."""
    orq = Orquestrador(registro, policy, approver=None)
    g = GrafoTarefas([No("n1", "arquivo_ler")], registro)
    r = orq.executar(g)
    assert not r.ok
    assert r.nos["n1"].status == "FALHOU"
    assert "sem executor" in r.nos["n1"].detalhe


def test_executores_explicitos_para_nativas(policy, registro):
    """Wiring explícito (como cli faria) habilita nativas no grafo."""
    orq = Orquestrador(registro, policy, approver=None,
                       executores={"arquivo_ler": lambda **kw: "conteudo"})
    g = GrafoTarefas([No("n1", "arquivo_ler")], registro)
    r = orq.executar(g)
    assert r.ok
    assert r.nos["n1"].resultado == "conteudo"


def test_params_chegam_ao_executor(policy, registro):
    recebido = {}

    def executor(**kw):
        recebido.update(kw)
        return "ok"
    orq = Orquestrador(registro, policy, approver=None,
                       executores={"arquivo_ler": executor})
    g = GrafoTarefas([No("n1", "arquivo_ler", params={"caminho": "/tmp/x"})], registro)
    r = orq.executar(g)
    assert r.ok
    assert recebido["caminho"] == "/tmp/x"


def test_aprovador_que_levanta_nega(policy, registro):
    def aprovador_quebrado(d):
        raise RuntimeError("boom")
    orq = Orquestrador(registro, policy, approver=aprovador_quebrado)
    g = GrafoTarefas([No("escreve", "gravar-a1")], registro)
    r = orq.executar(g)
    assert not r.ok
    assert r.nos["escreve"].status == "NEGADO"
