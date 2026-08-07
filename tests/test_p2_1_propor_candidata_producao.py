"""P2-1 (auditoria de 2026-07-17): propor_candidata() nunca chamado pelo
fluxo real de chat.

Achado: `Memory.propor_candidata()` — a fila de revisão humana de memória
(ISSUE-020: "você quer que eu lembre disso?"), com CLI (`nomos memoria
candidatas`/`revisar`) e badge no painel web já prontos e testados — nunca
era chamada por nenhum caminho de produção. Só aparecia em teste,
alimentando a fila manualmente. Em uso real, a fila ficava permanentemente
vazia: a feature existia de um lado (revisão) mas não do outro (proposta).

Causa raiz: a feature foi construída "de trás pra frente" — consumidor
implementado, produtor nunca implementado.

Correção (mínima, dois produtores reais — os dois fluxos de chat de
produção do NOMOS têm a mesma lacuna, não é exclusiva de um):
- `Memory.propor_candidatas_do_texto()` (novo): aplica a MESMA heurística
  local já usada por `consolidar()` (padrões compartilhados via
  `_PADROES_FATOS`) a uma fala isolada, em tempo real, propondo candidata
  em vez de gravar direto.
- `cli.py::one_turn()` (usado por `nomos chat`) chama essa função a cada
  turno bem-sucedido.
- `simple/amigavel.py::iniciar_chat()` (usado por `nomos start`, "modo
  simples") faz o mesmo no turno principal "conversa de verdade".
- `consolidar()` ganhou um dedup extra (contra `candidatas()` pendentes)
  para não duplicar um fato que já está na fila de revisão — interação
  nova que a correção principal tornou possível e que precisava ser
  fechada (ver `test_consolidar_nao_duplica_candidata_pendente`).

Fora de escopo, documentado (mesma filosofia de não expandir sem
justificar, mas também não confundir achados distintos):
- o sub-fluxo `/nuvem` dentro de `amigavel.py` — caminho de nuvem, tráfego
  bem menor, mantido idêntico;
- o modo demo de `amigavel.py` (`parece_lembrete()`) — heurística própria
  pré-existente, de auto-commit direto (design deliberadamente diferente,
  não é o achado);
- `consolidar()` continua auto-gravando direto (sem revisão) — contrato
  próprio e maduro, só recebeu o dedup mínimo necessário acima.
"""
from __future__ import annotations

import io

import pytest

from nomos import cli
from nomos.cognition.memory import Memory
from nomos.cognition.router import ChatOutcome
from nomos.kernel.policy import PolicyEngine


@pytest.fixture(autouse=True)
def _iso(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ------------------------------------------------------- Memory (unidade)

def test_detecta_preferencia_e_propoe_candidata(nomos_home):
    mem = Memory(nomos_home / "m.db")
    ids = mem.propor_candidatas_do_texto("eu prefiro respostas curtas, sem enrolação")
    assert len(ids) == 1
    fila = mem.candidatas()
    assert len(fila) == 1
    assert fila[0]["tipo"] == "preferencia"
    assert fila[0]["text"].startswith("preferência:")
    assert "respostas curtas" in fila[0]["text"]
    assert fila[0]["fonte"] == "chat"


def test_detecta_fato_de_nome(nomos_home):
    mem = Memory(nomos_home / "m.db")
    ids = mem.propor_candidatas_do_texto("meu nome é Fulano de Tal")
    assert len(ids) == 1
    assert mem.candidatas()[0]["tipo"] == "fato"


def test_nao_propoe_quando_fala_nao_bate_nenhum_padrao(nomos_home):
    mem = Memory(nomos_home / "m.db")
    assert mem.propor_candidatas_do_texto("qual a capital da França?") == []
    assert mem.candidatas() == []


def test_dedup_nao_repete_candidata_ja_pendente(nomos_home):
    mem = Memory(nomos_home / "m.db")
    primeira = mem.propor_candidatas_do_texto("eu prefiro respostas curtas")
    segunda = mem.propor_candidatas_do_texto("eu prefiro respostas curtas")
    assert len(primeira) == 1
    assert segunda == []                      # não duplica
    assert len(mem.candidatas()) == 1          # fila continua com só 1


def test_nao_repropoe_fato_ja_aprovado(nomos_home):
    mem = Memory(nomos_home / "m.db")
    cid = mem.propor_candidatas_do_texto("eu prefiro respostas curtas")[0]
    mid = mem.aprovar_candidata(cid)
    assert mid is not None
    assert mem.candidatas() == []
    # a mesma fala de novo: já virou memória de verdade, não deve reentrar na fila
    assert mem.propor_candidatas_do_texto("eu prefiro respostas curtas") == []
    assert mem.candidatas() == []


def test_todo_tipo_proposto_e_valido_para_aprovar_depois(nomos_home):
    """Cada padrão de _PADROES_FATOS usa um `tipo` que precisa bater com o
    enum validado por remember_typed() — senão aprovar_candidata() explode
    em produção. Testa isso disparando todos os 5 padrões."""
    mem = Memory(nomos_home / "m.db")
    falas = [
        "eu prefiro trabalhar de manhã",
        "meu aniversário é dia 10 de março",
        "meu email é fulano@example.com",
        "minha cor favorita é azul",
        "eu preciso renovar o passaporte",
    ]
    ids = []
    for f in falas:
        ids += mem.propor_candidatas_do_texto(f)
    assert len(ids) == 5
    for cid in ids:
        mid = mem.aprovar_candidata(cid)     # não pode levantar ValueError (tipo inválido)
        assert mid is not None


def test_descarte_tambem_funciona_normalmente(nomos_home):
    mem = Memory(nomos_home / "m.db")
    cid = mem.propor_candidatas_do_texto("eu prefiro café sem açúcar")[0]
    assert mem.descartar_candidata(cid) is True
    assert mem.candidatas() == []
    assert not any("café" in i.text for i in mem.recent(50))


# --------------------------------------------- consolidar(): interação nova

def test_consolidar_continua_com_contrato_antigo_intacto(nomos_home):
    """Regressão literal do teste pré-existente (test_memoria_v014.py) —
    prova que extrair _PADROES_FATOS não mudou nada do comportamento."""
    mem = Memory(nomos_home / "m.db")
    mem.remember("user", "eu prefiro respostas curtas, sem enrolação")
    mem.remember("user", "não posso esquecer de renovar o passaporte")
    mem.remember("assistant", "anotado!")
    mem.remember("user", "qual a capital da França?")
    criadas = mem.consolidar()
    tudo = " | ".join(criadas)
    assert "preferência: respostas curtas" in tudo
    assert "tarefa:" in tudo and "passaporte" in tudo
    assert "capital da França" not in tudo
    assert mem.consolidar() == []


def test_consolidar_nao_duplica_candidata_pendente(nomos_home):
    """P2-1: interação nova, possível só depois da correção principal — uma
    fala capturada ao vivo (propor_candidatas_do_texto, ainda pendente de
    revisão) não pode ser gravada de novo, direto e sem revisão, por
    consolidar() rodando sobre o mesmo histórico."""
    mem = Memory(nomos_home / "m.db")
    texto = "eu prefiro respostas curtas"
    mem.remember("user", texto)                      # como one_turn() grava
    ids = mem.propor_candidatas_do_texto(texto)       # como one_turn() propõe
    assert len(ids) == 1
    assert len(mem.candidatas()) == 1

    criadas = mem.consolidar()                        # rotina/manual, depois
    assert criadas == [], "consolidar() não deveria bypassar a fila de revisão pendente"
    assert len(mem.candidatas()) == 1                  # continua intacta, aguardando revisão
    assert not any("preferência: respostas curtas" in i.text
                   for i in mem.recent(50) if i.role == "note")


def test_consolidar_grava_normal_depois_que_candidata_e_descartada(nomos_home):
    """Se a candidata foi descartada (usuário disse "não, não guarde"),
    consolidar() volta a poder gravar aquele padrão normalmente depois."""
    mem = Memory(nomos_home / "m.db")
    texto = "eu prefiro respostas curtas"
    mem.remember("user", texto)
    cid = mem.propor_candidatas_do_texto(texto)[0]
    mem.descartar_candidata(cid)
    criadas = mem.consolidar()
    assert any("preferência: respostas curtas" in c for c in criadas)


# ------------------------------------------- cli.py::one_turn() (produção)

class _RouterFakeOk:
    def __init__(self, texto="combinado, vou lembrar!"):
        self.texto = texto

    def chat(self, messages, prefer_cloud=False, passphrase=None):
        return ChatOutcome(True, "local", self.texto, "fake", "fake-mini")


def test_cli_chat_produz_candidata_de_verdade(monkeypatch, nomos_home, capsys):
    """Prova objetiva de produção real: `nomos chat` (cli.main real, sem
    mock de propor_candidata) passa a alimentar a fila de revisão."""
    assert cli.main(["init"]) == 0
    monkeypatch.setattr(cli, "_router", lambda ctx: _RouterFakeOk())
    rc = cli.main(["chat", "eu", "prefiro", "respostas", "curtas"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "revise com: nomos memoria revisar" in err

    mem = Memory(nomos_home / "memory.db")
    fila = mem.candidatas()
    assert len(fila) == 1
    assert fila[0]["tipo"] == "preferencia"
    assert "respostas curtas" in fila[0]["text"]


def test_cli_chat_nao_propoe_quando_fala_nao_bate_padrao(monkeypatch, nomos_home, capsys):
    assert cli.main(["init"]) == 0
    monkeypatch.setattr(cli, "_router", lambda ctx: _RouterFakeOk("a capital é Paris"))
    rc = cli.main(["chat", "qual", "a", "capital", "da", "frança"])
    assert rc == 0
    assert "revise com" not in capsys.readouterr().err
    assert Memory(nomos_home / "memory.db").candidatas() == []


def test_cli_chat_repetir_a_mesma_fala_nao_duplica_candidata(monkeypatch, nomos_home):
    assert cli.main(["init"]) == 0
    monkeypatch.setattr(cli, "_router", lambda ctx: _RouterFakeOk())
    assert cli.main(["chat", "eu", "prefiro", "respostas", "curtas"]) == 0
    assert cli.main(["chat", "eu", "prefiro", "respostas", "curtas"]) == 0
    assert len(Memory(nomos_home / "memory.db").candidatas()) == 1


def test_cli_memoria_revisar_consegue_processar_candidata_vinda_do_chat(
        monkeypatch, nomos_home):
    """Fecha o ciclo ponta-a-ponta: chat produz -> `nomos memoria revisar`
    (a UI que já existia) consegue aprovar sem erro."""
    assert cli.main(["init"]) == 0
    monkeypatch.setattr(cli, "_router", lambda ctx: _RouterFakeOk())
    assert cli.main(["chat", "meu", "nome", "é", "Fulano"]) == 0
    assert len(Memory(nomos_home / "memory.db").candidatas()) == 1

    monkeypatch.setattr("sys.stdin", io.StringIO("s\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert cli.main(["memoria", "revisar"]) == 0
    mem = Memory(nomos_home / "memory.db")
    assert mem.candidatas() == []
    assert any("Fulano" in i.text for i in mem.recent(50) if i.role == "note")


# --------------------------------------- simple/amigavel.py::iniciar_chat()

class _RouterChatFakeOk:
    """Router fake com stream — mesmo padrão de test_v11_conversa.py."""
    def __init__(self, texto="combinado!"):
        self.texto = texto

    def chat_stream(self, messages, on_token):
        for palavra in self.texto.split(" "):
            on_token(palavra + " ")
        return ChatOutcome(True, "local", self.texto, "embutido", "fake-mini")


def _rodar_amigavel(home, entradas):
    from nomos.simple.amigavel import iniciar_chat
    feed = iter(entradas)
    tela: list[str] = []
    ctx = {"home": home, "policy": PolicyEngine(home / "p.json")}
    rc = iniciar_chat(ctx, {"agent_name": "Luna"}, router=_RouterChatFakeOk(),
                      ask=lambda _: next(feed), say=tela.append,
                      colorido=False, aprovador=lambda d: True,
                      say_token=lambda t: None)
    return rc, "\n".join(str(x) for x in tela)


def test_amigavel_tambem_produz_candidata_de_verdade(nomos_home):
    """O outro fluxo real de chat (`nomos start`, modo simples) tinha a
    MESMA lacuna — este teste prova que também foi fechada."""
    rc, tela = _rodar_amigavel(nomos_home, ["eu prefiro respostas curtas", "/sair"])
    assert rc == 0
    assert "reveja com: nomos memoria revisar" in tela
    fila = Memory(nomos_home / "memory.db").candidatas()
    assert len(fila) == 1
    assert fila[0]["tipo"] == "preferencia"


def test_amigavel_nao_propoe_quando_fala_nao_bate_padrao(nomos_home):
    rc, tela = _rodar_amigavel(nomos_home, ["oi, tudo bem?", "/sair"])
    assert rc == 0
    assert "reveja com" not in tela
    assert Memory(nomos_home / "memory.db").candidatas() == []
