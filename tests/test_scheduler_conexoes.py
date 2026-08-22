"""ArmazemJobs — toda conexão aberta FECHA, e a transação sobrevive à mudança.

O defeito (achado na Missão B, medido): os 13 pontos do armazém usavam
`with self._conn() as c:` acreditando fechar a conexão. Em `sqlite3`, `with
conexão` é gerenciador de TRANSAÇÃO — commit no sucesso, rollback na exceção
— e NÃO fecha nada. Toda conexão ficava para o coletor. No POSIX isso é
invisível; no Windows é `WinError 32` ("arquivo em uso") na primeira tentativa
de apagar o banco, e foi por isso que um teste do caos precisou de
`gc.collect()` para conseguir simular corrupção.

A correção tem uma pegadinha simétrica: trocar por `contextlib.closing()`
fecharia a conexão mas PERDERIA a transação — os writes deixariam de commitar
(isolation_level padrão) e o armazém passaria a perder dados em silêncio.
Por isso este arquivo prova as DUAS propriedades, não uma:

1. fecha SEMPRE (sucesso e exceção);
2. continua commitando no sucesso e revertendo na exceção.
"""
from __future__ import annotations

import sqlite3

import pytest

from nomos.adapters import scheduler as sched_mod
from nomos.adapters.scheduler import ArmazemJobs, Scheduler


class RastreadorDeConexoes:
    """Intercepta `sqlite3.connect` e lembra cada conexão criada."""

    def __init__(self):
        self.criadas: list[sqlite3.Connection] = []

    def instalar(self, monkeypatch):
        real = sqlite3.connect

        def espiao(*a, **kw):
            c = real(*a, **kw)
            self.criadas.append(c)
            return c

        monkeypatch.setattr(sched_mod.sqlite3, "connect", espiao)

    def abertas(self) -> list[int]:
        """Índices das conexões ainda abertas. Detecção pelo comportamento:
        conexão fechada levanta ProgrammingError ao executar."""
        vivas = []
        for i, c in enumerate(self.criadas):
            try:
                c.execute("SELECT 1")
                vivas.append(i)
            except sqlite3.ProgrammingError:
                pass
        return vivas


@pytest.fixture()
def rastreador(monkeypatch):
    r = RastreadorDeConexoes()
    r.instalar(monkeypatch)
    return r


# ------------------------------------------------------------- fecha sempre

def test_toda_operacao_fecha_a_conexao_que_abriu(tmp_path, rastreador):
    """Percorre o ciclo de vida inteiro do armazém; ao fim, ZERO conexões
    vivas. Este teste falha hoje: todas ficam para o coletor.
    """
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    s = Scheduler(armazem, executor=lambda *a, **k: None)
    s.criar("j1", "sujeito", "fs-listar", intervalo_s=60)
    armazem.obter("j1")
    armazem.listar()
    armazem.ilegiveis()
    armazem.nota_escrever("j1", "k", "v")
    armazem.nota_ler("j1", "k")
    armazem.notas_de("j1")
    armazem.notas_apagar("j1")
    armazem.apagar("j1")

    assert rastreador.criadas, "nenhuma conexão criada — teste inócuo"
    vivas = rastreador.abertas()
    assert vivas == [], (
        f"{len(vivas)} de {len(rastreador.criadas)} conexões ficaram ABERTAS "
        f"(índices {vivas}) — entregues ao coletor; no Windows isso é "
        f"WinError 32 ao apagar o banco")


def test_conexao_fecha_MESMO_quando_a_operacao_levanta(tmp_path, rastreador):
    """Exceção no meio da operação não pode vazar a conexão.

    `salvar` com job de tipo errado explode dentro da transação; a conexão
    daquela chamada tem de estar fechada mesmo assim.
    """
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    antes = len(rastreador.criadas)
    with pytest.raises(AttributeError):
        armazem.salvar(object())          # não é JobDefinition: explode dentro
    novas = rastreador.criadas[antes:]
    assert novas, "a operação nem abriu conexão — teste inócuo"
    assert rastreador.abertas() == [], (
        "conexão ficou aberta após exceção — vazamento no caminho de erro")


# ------------------------------------ a transação sobrevive à correção

def test_sucesso_continua_commitando(tmp_path):
    """O dado escrito numa conexão FECHADA persiste para a próxima.

    Mata a correção preguiçosa (`closing()` sem transação): com
    isolation_level padrão e sem commit, o INSERT evapora no close e o
    armazém perde jobs em silêncio — pior que o vazamento original.
    """
    caminho = tmp_path / "jobs.db"
    s = Scheduler(ArmazemJobs(caminho), executor=lambda *a, **k: None)
    s.criar("persistente", "sujeito", "fs-listar", intervalo_s=60)

    de_novo = ArmazemJobs(caminho)        # instância nova = conexões novas
    assert de_novo.obter("persistente") is not None, (
        "job sumiu — a correção fechou a conexão mas perdeu o COMMIT")


def test_excecao_continua_revertendo(tmp_path):
    """Falha no meio da transação não deixa metade do efeito no banco.

    A prova é contra o PRÓPRIO `_sessao`, com uma escrita real seguida de
    exceção dentro do bloco. Não dá para provar por um método público: as
    validações que levantam (quota de tamanho, tipo) acontecem ANTES de tocar
    o banco — a primeira versão deste teste usava `nota_escrever` com valor
    gigante e passava por VÁCUO, porque nada tinha sido escrito para reverter.
    """
    caminho = tmp_path / "jobs.db"
    armazem = ArmazemJobs(caminho)
    s = Scheduler(armazem, executor=lambda *a, **k: None)
    s.criar("j1", "sujeito", "fs-listar", intervalo_s=60)

    with pytest.raises(RuntimeError, match="no meio"):
        with armazem._sessao() as c:
            c.execute("INSERT INTO job_notas (job_id, chave, valor, "
                      "atualizado_em) VALUES ('j1', 'meio-escrita', 'x', 't')")
            raise RuntimeError("falha no meio da transação")

    assert ArmazemJobs(caminho).nota_ler("j1", "meio-escrita") is None, (
        "escrita interrompida PERSISTIU — o rollback da transação se perdeu")
