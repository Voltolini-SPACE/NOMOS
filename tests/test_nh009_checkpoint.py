"""NH-009 — checkpoint durável + retomada de missão.

Uma missão longa morre no meio — crash, panic, kill -9 — e hoje a única opção
é rodar TUDO de novo. Para nós idempotentes isso é desperdício; para nós NÃO
idempotentes é efeito duplicado no mundo, que é exatamente o que a série
inteira considera pior que falhar.

As três propriedades que importam, em ordem de gravidade:

1. **Nó interrompido NO MEIO e não idempotente NUNCA reexecuta.** No crash,
   "o efeito aplicou?" não tem resposta — o checkpoint diz EXECUTANDO e o
   mundo não diz nada. Reexecutar apostaria no efeito duplicado; a retomada
   fail-closed marca FALHOU com o motivo e deixa a decisão com o operador.

2. **O checkpoint é amarrado ao GRAFO por digest.** Retomar com um plano
   DIFERENTE herdaria os status (e implicitamente as aprovações consumidas)
   de outro plano — um plano hostil "continuaria" a missão de um benigno.
   Digest divergente ⇒ ErroCheckpoint, nada executa.

3. **Nó já OK não reexecuta.** É o ponto do checkpoint — e a prova é por
   CONTAGEM de execuções, não por status final.
"""
from __future__ import annotations

import json
import threading

import pytest

from nomos.kernel.policy import Category, PolicyEngine
from nomos.orquestracao.checkpoint import CheckpointMissao, ErroCheckpoint
from nomos.orquestracao.grafo import GrafoTarefas, No, Orquestrador
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


class Contador:
    """Conta execuções por nó — a prova de retomada é contagem, não status."""

    def __init__(self):
        self._trava = threading.Lock()
        self.execucoes: dict[str, int] = {}
        self.falhar: set[str] = set()

    def executor(self, nome: str):
        def _exec(**_kw):
            with self._trava:
                self.execucoes[nome] = self.execucoes.get(nome, 0) + 1
            if nome in self.falhar:
                raise RuntimeError(f"falha injetada em {nome}")
            return f"ok:{nome}"
        return _exec


@pytest.fixture()
def policy(tmp_path):
    return PolicyEngine(tmp_path / "policy.json")


def _montar(policy, contador: Contador, *, idempotentes: set[str] = frozenset()):
    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    for nome in ("t-a", "t-b", "t-c"):
        reg.registrar(nome, Category.READ_LOCAL, contador.executor(nome),
                      "teste", idempotente=(nome in idempotentes))
    nos = [No("a", "t-a"), No("b", "t-b", depende_de=("a",)),
           No("c", "t-c", depende_de=("b",))]
    return reg, nos


def _orq(reg, policy, **kw):
    return Orquestrador(reg, policy, approver=lambda d: True,
                        audit=AuditFake(), **kw)


# --------------------------------------------------- retomada básica

def test_no_ja_ok_nao_reexecuta_na_retomada(policy, tmp_path):
    """1ª corrida: a OK, b FALHA, c bloqueia. 2ª corrida (b consertado):
    a NÃO roda de novo; b e c rodam. Prova por contagem.

    Este teste falha hoje: `orquestracao.checkpoint` não existe.
    """
    contador = Contador()
    contador.falhar.add("t-b")
    reg, nos = _montar(policy, contador)
    ck = CheckpointMissao(tmp_path / "missao.ckpt")

    r1 = _orq(reg, policy).executar(GrafoTarefas(nos, reg), checkpoint=ck)
    assert not r1.ok
    assert r1.nos["a"].status == "OK"
    assert r1.nos["b"].status == "FALHOU"
    assert r1.nos["c"].status == "BLOQUEADO"

    contador.falhar.discard("t-b")
    r2 = _orq(reg, policy).executar(GrafoTarefas(nos, reg), checkpoint=ck)
    assert r2.ok, {i: n.detalhe for i, n in r2.nos.items()}
    assert contador.execucoes["t-a"] == 1, "nó OK reexecutou na retomada"
    assert contador.execucoes["t-b"] == 2
    assert contador.execucoes["t-c"] == 1
    assert "checkpoint" in r2.nos["a"].detalhe.lower()


def test_retomada_e_auditada(policy, tmp_path):
    contador = Contador()
    contador.falhar.add("t-b")
    reg, nos = _montar(policy, contador)
    ck = CheckpointMissao(tmp_path / "m.ckpt")
    _orq(reg, policy).executar(GrafoTarefas(nos, reg), checkpoint=ck)
    contador.falhar.discard("t-b")
    audit = AuditFake()
    Orquestrador(reg, policy, approver=lambda d: True, audit=audit).executar(
        GrafoTarefas(nos, reg), checkpoint=ck)
    assert "orquestracao.missao.retomada" in audit.nomes(), audit.nomes()


# ------------------------------------ interrupção no meio (a propriedade nº1)

def _forjar_executando(ck_path, reg, nos, no_id):
    """Simula o crash: grava um checkpoint válido com `no_id` EXECUTANDO.

    Forjado pela API do próprio CheckpointMissao (não à mão) para o teste não
    depender do formato interno do arquivo.
    """
    ck = CheckpointMissao(ck_path)
    grafo = GrafoTarefas(nos, reg)
    ck.iniciar(grafo)
    ck.marcar(no_id, "EXECUTANDO")
    return ck


def test_interrompido_nao_idempotente_NAO_reexecuta(policy, tmp_path):
    """EXECUTANDO + não idempotente ⇒ FALHOU na retomada, zero execuções.

    É a propriedade mais importante do NH-009: na dúvida sobre o efeito,
    não aposta. Dependentes bloqueiam, como qualquer falha.
    """
    contador = Contador()
    reg, nos = _montar(policy, contador)      # nada idempotente
    ck = _forjar_executando(tmp_path / "m.ckpt", reg, nos, "a")

    r = _orq(reg, policy).executar(GrafoTarefas(nos, reg), checkpoint=ck)
    assert r.nos["a"].status == "FALHOU"
    assert "idempotente" in r.nos["a"].detalhe.lower()
    assert contador.execucoes.get("t-a", 0) == 0, (
        "nó não idempotente interrompido REEXECUTOU — efeito duplicado")
    assert r.nos["b"].status == "BLOQUEADO"
    assert not r.ok


def test_interrompido_idempotente_reexecuta(policy, tmp_path):
    """EXECUTANDO + idempotente ⇒ reexecutar é seguro por definição."""
    contador = Contador()
    reg, nos = _montar(policy, contador, idempotentes={"t-a"})
    ck = _forjar_executando(tmp_path / "m.ckpt", reg, nos, "a")

    r = _orq(reg, policy).executar(GrafoTarefas(nos, reg), checkpoint=ck)
    assert r.ok, {i: n.detalhe for i, n in r.nos.items()}
    assert contador.execucoes["t-a"] == 1


# ----------------------------------------- amarração ao grafo (digest)

def test_grafo_diferente_e_recusado(policy, tmp_path):
    """Plano modificado não herda estado do plano antigo. Nada executa."""
    contador = Contador()
    reg, nos = _montar(policy, contador)
    ck = CheckpointMissao(tmp_path / "m.ckpt")
    _orq(reg, policy).executar(GrafoTarefas(nos, reg), checkpoint=ck)

    outros = [No("a", "t-a", params={"alvo": "OUTRO"}),
              No("b", "t-b", depende_de=("a",)),
              No("c", "t-c", depende_de=("b",))]
    with pytest.raises(ErroCheckpoint, match="grafo"):
        _orq(reg, policy).executar(GrafoTarefas(outros, reg), checkpoint=ck)
    assert contador.execucoes.get("t-a", 0) == 1, "algo executou após a recusa"


def test_checkpoint_corrompido_e_recusa_nao_recomeco_silencioso(policy, tmp_path):
    """Arquivo ilegível ⇒ ErroCheckpoint. Recomeçar do zero em silêncio
    reexecutaria tudo — inclusive o que não pode ser reexecutado."""
    contador = Contador()
    reg, nos = _montar(policy, contador)
    caminho = tmp_path / "m.ckpt"
    ck = CheckpointMissao(caminho)
    _orq(reg, policy).executar(GrafoTarefas(nos, reg), checkpoint=ck)
    caminho.write_text("isto não é um checkpoint", encoding="utf-8")

    with pytest.raises(ErroCheckpoint):
        _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                                   checkpoint=CheckpointMissao(caminho))


def test_sem_checkpoint_nada_muda(policy, tmp_path):
    """`checkpoint=None` é o comportamento de sempre — anti-regressão."""
    contador = Contador()
    reg, nos = _montar(policy, contador)
    r = _orq(reg, policy).executar(GrafoTarefas(nos, reg))
    assert r.ok
    assert (tmp_path / "m.ckpt").exists() is False


# ------------------------------------------------------------ durabilidade

@pytest.mark.permissao_unix
def test_checkpoint_nasce_0600(policy, tmp_path):
    """O checkpoint carrega alvos e params do plano — é dado do dono."""
    import stat
    contador = Contador()
    reg, nos = _montar(policy, contador)
    caminho = tmp_path / "m.ckpt"
    _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                               checkpoint=CheckpointMissao(caminho))
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600


def test_estado_persiste_no_e_nao_em_memoria(policy, tmp_path):
    """Instância NOVA de CheckpointMissao lê o que a antiga gravou — o crash
    descarta o processo inteiro, não só o objeto."""
    contador = Contador()
    contador.falhar.add("t-c")
    reg, nos = _montar(policy, contador)
    caminho = tmp_path / "m.ckpt"
    _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                               checkpoint=CheckpointMissao(caminho))
    contador.falhar.discard("t-c")

    r = _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                                   checkpoint=CheckpointMissao(caminho))
    assert r.ok
    assert contador.execucoes["t-a"] == 1
    assert contador.execucoes["t-b"] == 1
    assert contador.execucoes["t-c"] == 2


def test_checkpoint_de_missao_concluida_nao_reexecuta_nada(policy, tmp_path):
    """Retomar missão já concluída é no-op: tudo OK, zero execuções novas."""
    contador = Contador()
    reg, nos = _montar(policy, contador)
    caminho = tmp_path / "m.ckpt"
    _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                               checkpoint=CheckpointMissao(caminho))
    r = _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                                   checkpoint=CheckpointMissao(caminho))
    assert r.ok
    assert all(v == 1 for v in contador.execucoes.values()), contador.execucoes


def test_params_nao_json_recusam_checkpoint(policy, tmp_path):
    """O digest exige params canonizáveis. Grafo com params exótico não pode
    usar checkpoint — recusa explícita, não digest 'mais ou menos'."""
    contador = Contador()
    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    reg.registrar("t-a", Category.READ_LOCAL, contador.executor("t-a"), "teste")
    nos = [No("a", "t-a", params={"alvo": object()})]
    with pytest.raises(ErroCheckpoint, match="canon"):
        _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                                   checkpoint=CheckpointMissao(tmp_path / "m.ckpt"))


def test_marca_EXECUTANDO_esta_no_disco_ANTES_do_efeito(policy, tmp_path):
    """O executor lê o próprio checkpoint DURANTE a execução e encontra
    EXECUTANDO. Se a marca fosse gravada depois, o crash no meio deixaria o
    nó como PENDENTE — e a retomada reexecutaria um não-idempotente sem
    saber que ele já tinha começado. A janela de detecção É a marca prévia.
    """
    caminho = tmp_path / "m.ckpt"
    visto: dict[str, str] = {}

    def executor_espiao(**_kw):
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        visto.update(dados["nos"])
        return "ok"

    reg = RegistroCapacidades(policy=policy, approver=lambda d: True)
    reg.registrar("t-a", Category.READ_LOCAL, executor_espiao, "teste")
    nos = [No("a", "t-a")]
    r = _orq(reg, policy).executar(GrafoTarefas(nos, reg),
                                   checkpoint=CheckpointMissao(caminho))
    assert r.ok
    assert visto.get("a") == "EXECUTANDO", (
        f"durante o efeito o disco dizia {visto.get('a')!r} — crash no meio "
        "seria indetectável na retomada")
