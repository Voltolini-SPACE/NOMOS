"""NH-007 — integração do roteador de motores (já existente) ao orquestrador.

Não reimplementa roteamento (isso é cognition.engine_router); apenas adapta
um nó do grafo para uma Tarefa, roteia e devolve uma decisão auditável.
Invariantes:
- nó com motor="auto" recebe uma rota; nó sem motor não roteia;
- dados sensíveis NUNCA escolhem nuvem (local_only_preserved respeitado);
- a decisão de rota é DADO (não autoriza nada); a execução segue pelo gate;
- o orquestrador registra a rota no audit sem vazar o conteúdo da tarefa.
"""
from __future__ import annotations

import pytest

from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.grafo import GrafoTarefas, No, Orquestrador
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.orquestracao.roteamento import roteador_de_no


class AuditFake:
    def __init__(self):
        self.eventos: list[tuple[str, dict]] = []

    def append(self, evento: str, **campos) -> None:
        self.eventos.append((evento, campos))

    def eventos_de(self, nome: str) -> list[dict]:
        return [c for e, c in self.eventos if e == nome]


@pytest.fixture()
def ambiente(tmp_path):
    policy = PolicyEngine(tmp_path / "policy.json")
    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    reg.registrar("pensar", Category.READ_LOCAL, lambda **kw: kw.get("rota_motor"),
                  "teste")
    return policy, reg, tmp_path


def test_no_auto_recebe_rota(ambiente):
    policy, reg, home = ambiente
    rot = roteador_de_no(home=home)
    orq = Orquestrador(reg, policy, approver=None, rotear_motor=rot)
    g = GrafoTarefas([No("n1", "pensar", motor="auto",
                         params={"texto": "resuma isto"})], reg)
    r = orq.executar(g)
    assert r.ok
    rota = r.nos["n1"].resultado
    assert rota is not None
    assert hasattr(rota, "selected_engine")
    assert hasattr(rota, "local_only_preserved")


def test_no_sem_motor_nao_roteia(ambiente):
    policy, reg, home = ambiente
    rot = roteador_de_no(home=home)
    orq = Orquestrador(reg, policy, approver=None, rotear_motor=rot)
    g = GrafoTarefas([No("n1", "pensar", params={"texto": "oi"})], reg)
    r = orq.executar(g)
    assert r.ok
    assert r.nos["n1"].resultado is None       # sem rota injetada


def test_dados_sensiveis_nunca_nuvem(ambiente):
    """Texto sensível força privacidade: local preservado (nunca nuvem)."""
    policy, reg, home = ambiente
    rot = roteador_de_no(home=home)
    no = No("n1", "pensar", motor="auto",
            params={"texto": "minha senha e o token do banco"})
    rota = rot(no)
    assert rota.local_only_preserved is True
    assert rota.selected_engine != "nuvem" if rota.selected_engine else True


def test_rota_auditada_sem_vazar_conteudo(ambiente):
    policy, reg, home = ambiente
    audit = AuditFake()
    rot = roteador_de_no(home=home)
    orq = Orquestrador(reg, policy, approver=None, audit=audit, rotear_motor=rot)
    g = GrafoTarefas([No("n1", "pensar", motor="auto",
                         params={"texto": "segredo: cpf 123"})], reg)
    orq.executar(g)
    rotas = audit.eventos_de("orquestracao.no.rota_motor")
    assert len(rotas) == 1
    campos = rotas[0]
    assert "motor" in campos and "local_preservado" in campos
    # o conteúdo da tarefa nunca aparece no audit
    for v in campos.values():
        assert "cpf" not in str(v) and "segredo" not in str(v)


def test_roteador_infere_tipo_por_texto(ambiente):
    """Sanidade: usa o classificador existente (código vs conversa)."""
    _, _, home = ambiente
    rot = roteador_de_no(home=home)
    rota_codigo = rot(No("n1", "pensar", motor="auto",
                         params={"texto": "escreva uma função python"}))
    assert rota_codigo is not None      # roteou sem erro para tarefa de código
