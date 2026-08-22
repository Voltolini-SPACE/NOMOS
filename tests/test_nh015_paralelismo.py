"""NH-015 — nós independentes do grafo executam em PARALELO, com teto.

O grafo já sabia quem depende de quem: `ordem_topologica()` existe desde o
NH-002. O que faltava era usar essa informação para o que ela serve — dois nós
sem relação entre si esperavam um pelo outro sem motivo.

## A decisão que molda tudo aqui: o GATE não paralelize

`Orquestrador.executar` chama `gate(decisao, approver)`, e o approver pode ser
o humano no terminal. Paralelizar o gate colocaria duas perguntas disputando o
mesmo stdin — o operador aprovaria sem saber o quê, e a aprovação deixaria de
ser aprovação. Então a execução é por ONDAS:

    prontos → [fase SERIAL: política + gate, em ordem topológica]
            → [fase PARALELA: só o que já foi aprovado, com teto]
            → junta, bloqueia dependentes, repete

O recálculo do digest (`consumir`) segue imediatamente antes do efeito DE CADA
NÓ, dentro do worker: a propriedade é por nó e não se perde ao paralelizar.

`max_paralelo=1` é o padrão e tem de reproduzir a execução de hoje. É o teste
de anti-regressão mais importante do arquivo — paralelismo que muda o
comportamento do caso serial não é otimização, é defeito novo.
"""
from __future__ import annotations

import threading
import time

import pytest

from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.grafo import GrafoTarefas, No, Orquestrador
from nomos.orquestracao.registro import RegistroCapacidades


class AuditFake:
    """Trilha de teste com trava — o AuditLog real tem `_lock` + flock, e um
    dublê sem trava inventaria corrida que o produto não tem."""

    def __init__(self):
        self._trava = threading.Lock()
        self.eventos: list[tuple[str, dict]] = []

    def append(self, evento: str, **campos) -> None:
        with self._trava:
            self.eventos.append((evento, campos))

    def nomes(self) -> list[str]:
        return [e for e, _ in self.eventos]


class Cronometro:
    """Registra (inicio, fim) por nó para medir SOBREPOSIÇÃO real.

    Medir tempo total ("com paralelismo demora menos") seria frágil e mediria a
    máquina. Sobreposição de intervalos é a propriedade de verdade: dois nós
    estiveram vivos ao mesmo tempo, ou não estiveram.
    """

    def __init__(self, duracao=0.15):
        self.duracao = duracao
        self._trava = threading.Lock()
        self.janelas: dict[str, tuple[float, float]] = {}

    def executor(self, nome: str):
        def _exec(**_kw):
            ini = time.monotonic()
            time.sleep(self.duracao)
            fim = time.monotonic()
            with self._trava:
                self.janelas[nome] = (ini, fim)
            return f"ok:{nome}"
        return _exec

    def houve_sobreposicao(self) -> bool:
        js = sorted(self.janelas.values())
        return any(js[i][1] > js[i + 1][0] for i in range(len(js) - 1))

    def concorrencia_maxima(self) -> int:
        eventos = []
        for ini, fim in self.janelas.values():
            eventos.append((ini, 1))
            eventos.append((fim, -1))
        eventos.sort()
        atual = pico = 0
        for _t, delta in eventos:
            atual += delta
            pico = max(pico, atual)
        return pico


@pytest.fixture()
def policy(tmp_path):
    return PolicyEngine(tmp_path / "policy.json")


def _registro(policy, cron: Cronometro, quantos: int) -> RegistroCapacidades:
    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    for i in range(quantos):
        reg.registrar(f"tarefa-{i}", Category.READ_LOCAL,
                      cron.executor(f"tarefa-{i}"), "teste")
    return reg


def _independentes(quantos: int) -> list[No]:
    return [No(f"n{i}", f"tarefa-{i}") for i in range(quantos)]


# --------------------------------------------- o paralelismo existe de fato

def test_nos_independentes_rodam_concorrentemente(policy):
    """A prova é SOBREPOSIÇÃO de janelas, não tempo total.

    Este é o teste que falha hoje: `Orquestrador` não aceita `max_paralelo`.
    """
    cron = Cronometro()
    reg = _registro(policy, cron, 4)
    orq = Orquestrador(reg, policy, approver=lambda d: True,
                       audit=AuditFake(), max_paralelo=4)
    r = orq.executar(GrafoTarefas(_independentes(4), reg))

    assert r.ok, {i: n.detalhe for i, n in r.nos.items()}
    assert cron.houve_sobreposicao(), (
        f"nenhuma sobreposição — rodou serial: {cron.janelas}")
    assert cron.concorrencia_maxima() >= 2, (
        f"pico de concorrência {cron.concorrencia_maxima()}, esperado >= 2")


def test_teto_de_paralelismo_e_respeitado(policy):
    """Teto é teto: com 6 nós e teto 2, nunca há 3 vivos ao mesmo tempo.

    Sem esta asserção, `max_paralelo` viraria enfeite — um pool sem limite
    passaria no teste anterior e estouraria a máquina num grafo grande.
    """
    cron = Cronometro()
    reg = _registro(policy, cron, 6)
    orq = Orquestrador(reg, policy, approver=lambda d: True,
                       audit=AuditFake(), max_paralelo=2)
    r = orq.executar(GrafoTarefas(_independentes(6), reg))

    assert r.ok
    assert cron.concorrencia_maxima() <= 2, (
        f"teto 2 violado: pico {cron.concorrencia_maxima()}")


# ------------------------------------- o caso serial não pode mudar de forma

def test_padrao_e_serial_e_identico_ao_comportamento_de_hoje(policy):
    """`max_paralelo` ausente ⇒ 1 ⇒ zero sobreposição.

    Anti-regressão principal: quem não pediu paralelismo não pode recebê-lo de
    surpresa, porque paralelismo muda ordem de efeito no mundo.
    """
    cron = Cronometro(duracao=0.05)
    reg = _registro(policy, cron, 3)
    orq = Orquestrador(reg, policy, approver=lambda d: True, audit=AuditFake())
    r = orq.executar(GrafoTarefas(_independentes(3), reg))

    assert r.ok
    assert not cron.houve_sobreposicao(), (
        f"padrão paralelizou sem ninguém pedir: {cron.janelas}")
    assert cron.concorrencia_maxima() == 1


def test_ordem_de_efeito_no_serial_segue_a_topologica(policy):
    """No serial, a ordem observável continua sendo a topológica.

    Guarda contra "otimizar" o caminho de teto 1 para um pool de 1 worker que
    consuma a fila em ordem de chegada.
    """
    ordem: list[str] = []
    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    for i in range(4):
        reg.registrar(f"t{i}", Category.READ_LOCAL,
                      (lambda n: lambda **kw: ordem.append(n))(f"t{i}"), "teste")
    nos = [No("a", "t0"), No("b", "t1", depende_de=("a",)),
           No("c", "t2", depende_de=("a",)), No("d", "t3", depende_de=("b", "c"))]
    grafo = GrafoTarefas(nos, reg)
    Orquestrador(reg, policy, approver=lambda d: True,
                 audit=AuditFake()).executar(grafo)
    assert ordem == ["t0", "t1", "t2", "t3"]


# ------------------------------------------- o gate NUNCA roda em paralelo

def test_gate_humano_nunca_ocorre_em_paralelo(policy, tmp_path):
    """Duas perguntas ao mesmo tempo no mesmo terminal = aprovação cega.

    O approver aqui detecta reentrância: se um segundo gate entrar enquanto o
    primeiro ainda não saiu, o teste morre. Um pool que envolvesse o gate
    passaria em todos os outros testes deste arquivo e falharia só aqui — que
    é exatamente o ponto.
    """
    dentro = {"n": 0}
    conflito = {"houve": False}
    trava = threading.Lock()

    def approver(_decisao) -> bool:
        with trava:
            dentro["n"] += 1
            if dentro["n"] > 1:
                conflito["houve"] = True
        time.sleep(0.05)
        with trava:
            dentro["n"] -= 1
        return True

    # A política vive em JSON no disco (não há setter): o padrão do kernel já é
    # read-only, então A1 escrita cai em REQUIRE_APPROVAL. Escrever o arquivo
    # explicitamente deixa o teste independente de mudança no default.
    import json

    caminho = tmp_path / "p2.json"
    politica = PolicyEngine(caminho)
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    dados["rules"][Category.WRITE_LOCAL.value] = "REQUIRE_APPROVAL"
    caminho.write_text(json.dumps(dados), encoding="utf-8")
    politica = PolicyEngine(caminho)
    reg = RegistroCapacidades(policy=politica, approver=approver)
    for i in range(4):
        reg.registrar(f"w{i}", Category.WRITE_LOCAL, lambda **kw: "ok", "teste")
    nos = [No(f"n{i}", f"w{i}") for i in range(4)]

    orq = Orquestrador(reg, politica, approver=approver, audit=AuditFake(),
                       max_paralelo=4)
    orq.executar(GrafoTarefas(nos, reg))
    assert not conflito["houve"], "dois gates humanos se sobrepuseram"


# ------------------------------ bloqueio de dependentes sob paralelismo

def test_falha_bloqueia_dependentes_mesmo_com_paralelismo(policy):
    """A garantia do NH-002 não pode evaporar quando o teto sobe."""
    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    reg.registrar("ok-a0", Category.READ_LOCAL, lambda **kw: "v", "teste")
    reg.registrar("quebra-a0", Category.READ_LOCAL,
                  lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")), "teste")
    nos = [No("livre", "ok-a0"), No("ruim", "quebra-a0"),
           No("filho", "ok-a0", depende_de=("ruim",)),
           No("neto", "ok-a0", depende_de=("filho",))]

    r = Orquestrador(reg, policy, approver=lambda d: True, audit=AuditFake(),
                     max_paralelo=4).executar(GrafoTarefas(nos, reg))

    assert r.nos["ruim"].status == "FALHOU"
    assert r.nos["filho"].status == "BLOQUEADO"
    assert r.nos["neto"].status == "BLOQUEADO", "bloqueio transitivo se perdeu"
    assert r.nos["livre"].status == "OK", "ramo independente foi punido junto"
    assert not r.ok


def test_teto_invalido_e_recusado_na_construcao(policy):
    """Fail-closed: teto 0 ou negativo pararia a missão em silêncio."""
    cron = Cronometro(duracao=0.01)
    reg = _registro(policy, cron, 1)
    for ruim in (0, -1):
        with pytest.raises(ValueError, match="max_paralelo"):
            Orquestrador(reg, policy, approver=lambda d: True, max_paralelo=ruim)


# ------------------------------------------- transcrição ao vivo por nó

def test_transcricao_ao_vivo_recebe_cada_transicao(policy):
    """O painel precisa ver a missão ACONTECENDO, não o resumo no fim.

    `ao_evento` recebe (evento, campos) a cada transição. A asserção é sobre a
    CHEGADA durante a corrida, não sobre a lista final: um callback chamado só
    no encerramento seria indistinguível de ler `ResultadoMissao`, e não seria
    transcrição de nada.
    """
    vistos: list[str] = []
    trava = threading.Lock()

    def ao_evento(evento, campos):
        with trava:
            vistos.append(evento)

    cron = Cronometro(duracao=0.02)
    reg = _registro(policy, cron, 2)
    orq = Orquestrador(reg, policy, approver=lambda d: True, audit=AuditFake(),
                       ao_evento=ao_evento)
    r = orq.executar(GrafoTarefas(_independentes(2), reg))

    assert r.ok
    assert "orquestracao.missao.inicio" in vistos
    assert vistos.count("orquestracao.no.ok") == 2, vistos
    assert "orquestracao.missao.fim" in vistos
    # o fim é o ÚLTIMO: se os eventos de nó chegassem depois, teriam sido
    # despejados no encerramento em vez de transmitidos durante a corrida
    assert vistos[-1] == "orquestracao.missao.fim"
    assert vistos.index("orquestracao.no.ok") < vistos.index("orquestracao.missao.fim")


def test_transcricao_quebrada_nao_derruba_a_missao(policy):
    """Renderizador com defeito é problema DELE.

    Sem esta guarda, um painel que levantasse exceção mataria a missão no meio
    — e pior, DEPOIS de o efeito já ter sido aplicado no mundo, deixando o nó
    sem desfecho registrado. Observação nunca pode mudar o observado.
    """
    def ao_evento(_evento, _campos):
        raise RuntimeError("painel quebrado")

    cron = Cronometro(duracao=0.01)
    reg = _registro(policy, cron, 2)
    r = Orquestrador(reg, policy, approver=lambda d: True, audit=AuditFake(),
                     ao_evento=ao_evento).executar(GrafoTarefas(_independentes(2), reg))

    assert r.ok, "callback quebrado derrubou a missão"
    assert all(n.status == "OK" for n in r.nos.values())


def test_transcricao_nao_ve_conteudo_alem_do_que_a_trilha_ve(policy):
    """O callback recebe os MESMOS campos do audit, nem um a mais.

    Se a transcrição pudesse carregar mais que a trilha, ela viraria um canal
    de vazamento paralelo — sem redação, sem hash-chain e sem revisão.
    """
    do_audit: list[tuple[str, dict]] = []
    do_vivo: list[tuple[str, dict]] = []

    class AuditEspiao(AuditFake):
        def append(self, evento, **campos):
            do_audit.append((evento, dict(campos)))
            super().append(evento, **campos)

    cron = Cronometro(duracao=0.01)
    reg = _registro(policy, cron, 2)
    Orquestrador(reg, policy, approver=lambda d: True, audit=AuditEspiao(),
                 ao_evento=lambda e, c: do_vivo.append((e, c))
                 ).executar(GrafoTarefas(_independentes(2), reg))

    assert do_vivo == do_audit, "transcrição divergiu da trilha"
