"""NH-021 — loop-guards: breaker de chamada idêntica + teto por turno.

O cenário que isto guarda: um planejador (humano apressado hoje, LLM amanhã)
gera plano que martela a MESMA chamada — mesmo `ferramenta` + mesmos `params`
— dezenas de vezes, ou um loop de replanejamento que reexecuta a mesma missão
falha para sempre. O orçamento de RETRY (NH-004) não cobre isso: ele só conta
tentativas de nós que FALHAM; um loop de chamadas idênticas bem-sucedidas
passa por ele sem gastar nada.

Duas defesas, ambas fail-closed e SEMPRE ligadas (configuráveis, não
desligáveis — guarda com interruptor não guarda):

1. BREAKER DE IDÊNTICAS: a partir da (N+1)-ésima chamada com a mesma
   identidade (ferramenta + params canônicos do PLANO), recusa. A identidade
   usa `no.params` — o dado do plano, JSON por construção — e NUNCA o params
   enriquecido da execução (que carrega `rota_motor`, um objeto).

2. TETO POR TURNO: total de execuções que um turno pode INTENTAR. Conta na
   reserva (fase serial), não no sucesso: um loop de chamadas negadas ainda é
   um loop, e queima o operador do mesmo jeito.

O escopo padrão é a missão (cada `Orquestrador` cria a própria guarda); o
chamador que roda VÁRIAS missões num turno — o loop de replanejamento — passa
a MESMA `GuardaDeLaco` para todas, e a contagem atravessa.
"""
from __future__ import annotations

import threading

import pytest

from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.grafo import GrafoTarefas, No, Orquestrador
from nomos.orquestracao.recuperacao import GuardaDeLaco, PoliticaGuarda
from nomos.orquestracao.registro import RegistroCapacidades


class AuditFake:
    def __init__(self):
        self._trava = threading.Lock()
        self.eventos: list[tuple[str, dict]] = []

    def append(self, evento: str, **campos) -> None:
        with self._trava:
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
    return reg


def _orq(registro, policy, **kw):
    return Orquestrador(registro, policy, approver=lambda d: True,
                        audit=AuditFake(), **kw)


# ------------------------------------------------- breaker de idênticas

def test_chamada_identica_alem_do_limite_e_recusada(registro, policy):
    """5 idênticas passam; a 6ª é NEGADA e os dependentes dela bloqueiam.

    Este teste falha hoje: `GuardaDeLaco` não existe.
    """
    guarda = GuardaDeLaco(PoliticaGuarda(identicas_limite=5))
    nos = [No(f"n{i}", "ler-a0", params={"alvo": "x.txt"}) for i in range(6)]
    nos.append(No("filho", "ler-a0", params={"alvo": "y.txt"},
                  depende_de=("n5",)))
    r = _orq(registro, policy, guarda=guarda).executar(GrafoTarefas(nos, registro))

    for i in range(5):
        assert r.nos[f"n{i}"].status == "OK", (i, r.nos[f"n{i}"].detalhe)
    assert r.nos["n5"].status == "NEGADO"
    assert "idêntic" in r.nos["n5"].detalhe.lower()
    assert r.nos["filho"].status == "BLOQUEADO"
    assert not r.ok


def test_params_diferentes_nao_disparam_o_breaker(registro, policy):
    """Idêntica é ferramenta + params. Variar o alvo não é loop."""
    guarda = GuardaDeLaco(PoliticaGuarda(identicas_limite=2))
    nos = [No(f"n{i}", "ler-a0", params={"alvo": f"{i}.txt"}) for i in range(6)]
    r = _orq(registro, policy, guarda=guarda).executar(GrafoTarefas(nos, registro))
    assert r.ok, {i: n.detalhe for i, n in r.nos.items() if n.status != "OK"}


def test_identidade_vem_do_plano_nao_da_execucao(registro, policy):
    """A identidade usa `no.params` (dado do plano), não o params enriquecido.

    `rota_motor` é um objeto injetado na execução; se entrasse na identidade,
    cada chamada ganharia identidade nova (repr com id()) e o breaker nunca
    dispararia — guarda silenciosamente desarmada.
    """
    guarda = GuardaDeLaco(PoliticaGuarda(identicas_limite=2))
    reg = registro
    nos = [No(f"n{i}", "ler-a0", params={"alvo": "mesmo.txt"}, motor="auto")
           for i in range(3)]
    r = _orq(reg, policy, guarda=guarda,
             rotear_motor=lambda no: object()).executar(GrafoTarefas(nos, reg))
    assert r.nos["n2"].status == "NEGADO", (
        "3ª idêntica passou — a identidade está vendo o params enriquecido")


# ------------------------------------------------------- teto por turno

def test_teto_por_turno_corta_o_excedente(registro, policy):
    """Acima do teto, tudo é NEGADO — inclusive chamadas inéditas."""
    guarda = GuardaDeLaco(PoliticaGuarda(chamadas_por_turno=4,
                                         identicas_limite=99))
    nos = [No(f"n{i}", "ler-a0", params={"alvo": f"{i}.txt"}) for i in range(6)]
    r = _orq(registro, policy, guarda=guarda).executar(GrafoTarefas(nos, registro))

    executados = [i for i, n in r.nos.items() if n.status == "OK"]
    negados = [i for i, n in r.nos.items() if n.status == "NEGADO"]
    assert len(executados) == 4, r.nos
    assert len(negados) == 2
    for i in negados:
        assert "turno" in r.nos[i].detalhe.lower()


def test_teto_conta_a_intencao_nao_o_sucesso(registro, policy):
    """Chamada negada pelo breaker também consome o teto do turno.

    Um loop de chamadas recusadas ainda é um loop: se recusa não contasse, o
    plano poderia martelar a mesma chamada para sempre "de graça".
    """
    guarda = GuardaDeLaco(PoliticaGuarda(identicas_limite=1,
                                         chamadas_por_turno=3))
    nos = [No(f"n{i}", "ler-a0", params={"alvo": "x.txt"}) for i in range(4)]
    r = _orq(registro, policy, guarda=guarda).executar(GrafoTarefas(nos, registro))
    # n0 executa (1ª idêntica); n1 e n2 caem no breaker mas CONSOMEM o turno;
    # n3 já encontra o turno esgotado — motivo diferente, mesma recusa.
    assert r.nos["n0"].status == "OK"
    assert r.nos["n1"].status == "NEGADO"
    assert r.nos["n2"].status == "NEGADO"
    assert r.nos["n3"].status == "NEGADO"
    assert "turno" in r.nos["n3"].detalhe.lower()


# ------------------------------------- a guarda atravessa missões do turno

def test_guarda_compartilhada_atravessa_missoes(registro, policy):
    """O loop de replanejamento roda N missões; a guarda é UMA por turno.

    Sem isto, cada replanejamento zeraria a contagem e o breaker só pegaria
    loops DENTRO de um plano — o caso mais raro. O caso real é o planejador
    gerando o mesmo plano de novo.
    """
    guarda = GuardaDeLaco(PoliticaGuarda(identicas_limite=3))
    plano = [No("n0", "ler-a0", params={"alvo": "x.txt"})]
    ultima = None
    for _ in range(4):
        ultima = _orq(registro, policy, guarda=guarda).executar(
            GrafoTarefas(plano, registro))
    assert ultima is not None
    assert ultima.nos["n0"].status == "NEGADO", (
        "4ª missão idêntica passou — a guarda não atravessa missões")


def test_sem_guarda_explicita_cada_missao_tem_a_sua(registro, policy):
    """Padrão: guarda própria por missão (sempre ligada, escopo missão).

    Duas missões idênticas SEM guarda compartilhada passam — o breaker
    default não pode punir o uso legítimo de rodar a mesma missão duas vezes.
    """
    plano = [No("n0", "ler-a0", params={"alvo": "x.txt"})]
    for _ in range(2):
        r = _orq(registro, policy).executar(GrafoTarefas(plano, registro))
        assert r.ok


def test_guarda_default_esta_sempre_ligada(registro, policy):
    """Não existe interruptor de desligar — só limites configuráveis.

    Um grafo que martela a mesma chamada acima do limite DEFAULT é recusado
    mesmo sem ninguém ter configurado guarda nenhuma.
    """
    limite = PoliticaGuarda().identicas_limite
    nos = [No(f"n{i}", "ler-a0", params={"alvo": "x.txt"})
           for i in range(limite + 1)]
    r = _orq(registro, policy).executar(GrafoTarefas(nos, registro))
    assert r.nos[f"n{limite}"].status == "NEGADO", (
        f"a {limite + 1}ª idêntica passou sem guarda explícita")


# ------------------------------------------------------------ fail-closed

def test_params_nao_canonizavel_e_recusado(registro, policy):
    """Identidade que não se computa é recusa, não isenção.

    Um grafo montado à mão pode carregar params não-JSON. Se isso isentasse o
    nó da guarda, params exóticos virariam o passe-livre do loop.
    """
    guarda = GuardaDeLaco(PoliticaGuarda(identicas_limite=5))
    nos = [No("n0", "ler-a0", params={"alvo": object()})]
    r = _orq(registro, policy, guarda=guarda).executar(GrafoTarefas(nos, registro))
    assert r.nos["n0"].status == "NEGADO"
    assert "canôn" in r.nos["n0"].detalhe.lower() or \
           "canon" in r.nos["n0"].detalhe.lower()


def test_limites_invalidos_sao_recusados_na_construcao():
    for ruim in (0, -1):
        with pytest.raises(ValueError):
            GuardaDeLaco(PoliticaGuarda(identicas_limite=ruim))
        with pytest.raises(ValueError):
            GuardaDeLaco(PoliticaGuarda(chamadas_por_turno=ruim))


# ----------------------------------------------------------------- trilha

def test_disparo_da_guarda_e_auditado(registro, policy):
    """Quem lê a trilha precisa ver que foi a GUARDA, não a política."""
    audit = AuditFake()
    guarda = GuardaDeLaco(PoliticaGuarda(identicas_limite=1))
    nos = [No(f"n{i}", "ler-a0", params={"alvo": "x.txt"}) for i in range(2)]
    Orquestrador(registro, policy, approver=lambda d: True, audit=audit,
                 guarda=guarda).executar(GrafoTarefas(nos, registro))
    assert "orquestracao.guarda.disparou" in audit.nomes(), audit.nomes()
