"""Uma instância só do ticker por NOMOS_HOME.

Medido em 23/08: `runtime/agendador.py` (300 linhas) e `adapters/scheduler.py`
(774) somavam ZERO `flock`/`LOCK_EX`. Dois `nomos scheduler rodar` no mesmo
home disparavam a MESMA ocorrência duas vezes. Job idempotente aguenta; job
que envia, cobra ou publica não tem desfazer.

A trava reusa `servico.TravaInstancia` (flock + anti-troca de inode) em vez de
duplicar, e segue a doutrina que já estava escrita lá: a autoridade é o LOCK
(morre com o processo; crash nunca deixa trava presa), o conteúdo do arquivo é
diagnóstico e NENHUMA decisão o lê.
"""
from __future__ import annotations

import threading
import time

import pytest

from nomos.adapters.ticker import (SEM_AUTORIZACAO, SEM_TRAVA, Ticker,
                                   TickerJaRodando)
from nomos.runtime.servico import TravaInstancia


class _SchedFake:
    def __init__(self):
        self.ticks = 0

    def devidos(self, agora=None):
        self.ticks += 1
        return []


def _ticker(home, sched=None, com_trava=True):
    return Ticker(sched or _SchedFake(), SEM_AUTORIZACAO, dormir=lambda s: None,
                  trava=TravaInstancia(home / "scheduler" / "ticker.lock")
                  if com_trava else SEM_TRAVA)


def test_segundo_ticker_no_mesmo_home_e_recusado(tmp_path):
    parar = [False]
    t1 = _ticker(tmp_path)
    th = threading.Thread(
        target=lambda: t1.rodar_ate(condicao=lambda: not parar[0]), daemon=True)
    th.start()
    try:
        for _ in range(50):          # espera o laço pegar a trava
            if (tmp_path / "scheduler" / "ticker.lock").exists():
                break
            time.sleep(0.02)
        with pytest.raises(TickerJaRodando):
            _ticker(tmp_path).rodar_ate(max_ticks=1)
    finally:
        parar[0] = True
        t1.parar()
        th.join(timeout=5)


def test_a_recusa_diz_quem_esta_segurando(tmp_path):
    """Mensagem sem o dono manda o operador matar processo às cegas."""
    trava = TravaInstancia(tmp_path / "scheduler" / "ticker.lock")
    assert trava.adquirir()
    try:
        with pytest.raises(TickerJaRodando) as exc:
            _ticker(tmp_path).rodar_ate(max_ticks=1)
        assert "pid" in str(exc.value)
    finally:
        trava.liberar()


def test_liberada_a_trava_um_novo_ticker_sobe(tmp_path):
    """Trava presa depois do fim seria pior que trava nenhuma: o agendamento
    morreria em silêncio até alguém apagar um arquivo."""
    assert len(_ticker(tmp_path).rodar_ate(max_ticks=1)) == 1
    assert len(_ticker(tmp_path).rodar_ate(max_ticks=1)) == 1


def test_homes_diferentes_nao_se_bloqueiam(tmp_path):
    """A exclusão é por NOMOS_HOME, não global — dois NOMOS distintos na mesma
    máquina são um caso legítimo."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    parar = [False]
    t1 = _ticker(a)
    th = threading.Thread(
        target=lambda: t1.rodar_ate(condicao=lambda: not parar[0]), daemon=True)
    th.start()
    try:
        for _ in range(50):
            if (a / "scheduler" / "ticker.lock").exists():
                break
            time.sleep(0.02)
        assert len(_ticker(b).rodar_ate(max_ticks=1)) == 1   # home B não trava
    finally:
        parar[0] = True
        t1.parar()
        th.join(timeout=5)


def test_trava_e_obrigatoria_no_construtor():
    """Default `None` deixava a porta encostada: um refator que esquecesse de
    passar a trava não quebraria nada. Mesma doutrina do `autorizador`, no
    mesmo arquivo — quem não quer exclusão diz `SEM_TRAVA` em voz alta."""
    with pytest.raises(TypeError):
        Ticker(_SchedFake(), SEM_AUTORIZACAO)          # sem `trava` nenhuma
    with pytest.raises(ValueError, match="SEM_TRAVA"):
        Ticker(_SchedFake(), SEM_AUTORIZACAO, trava=None)


def test_o_caminho_de_producao_nao_consegue_omitir_a_trava():
    """`agendador.ticker()` monta a trava sozinho.

    Mesma doutrina que tornou o `autorizador` obrigatório: invariante que se
    desliga por omissão não é invariante.
    """
    import inspect

    from nomos.runtime import agendador
    fonte = inspect.getsource(agendador.AgendadorGovernado.ticker)
    assert "TravaInstancia" in fonte and "trava=trava" in fonte


def test_sem_trava_haveria_execucao_em_dobro(tmp_path):
    """CONTROLE: é o comportamento que existia antes. Dois tickers sem trava
    tickam os dois — a prova de que a trava não é decorativa."""
    s1, s2 = _SchedFake(), _SchedFake()
    _ticker(tmp_path, s1, com_trava=False).rodar_ate(max_ticks=1)
    _ticker(tmp_path, s2, com_trava=False).rodar_ate(max_ticks=1)
    assert s1.ticks == 1 and s2.ticks == 1     # dois disparos, zero recusa
