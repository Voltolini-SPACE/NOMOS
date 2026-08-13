"""ABSORPTION-06 / ETAPA 3 — 1 ocorrência ⇒ 1 estado canônico ⇒ 0 contradições.

O censo da 05 achou: a MESMA ocorrência gerava `UNKNOWN` pelo Scheduler e
`NO_EFFECT` pelo Ticker. Não era um dos dois estar errado — era os dois
interpretarem o mesmo fato independentemente.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nomos.adapters.alertas import SinkDeTeste
from nomos.adapters.resultado import (
    EstadoCanonico, ResultadoOcorrencia, Severidade, canonico, de_execucao,
)
from nomos.adapters.scheduler import ArmazemJobs, Scheduler
from nomos.adapters.ticker import SEM_AUTORIZACAO, Ticker

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


class _Efeito:
    def __init__(self, falhar=False):
        self.falhar = falhar

    def __call__(self, d, i, credencial=None):
        if self.falhar:
            raise RuntimeError("boom")
        return type("R", (), {"efeito_aplicado": True})()


# ------------------------------------------------ taxonomia

def test_taxonomia_tem_os_sete_estados():
    assert {r.value for r in ResultadoOcorrencia} == {
        "EXECUTED_EFFECT", "EXECUTED_NO_EFFECT", "DENIED", "FAILED",
        "UNKNOWN", "MISSED", "RECOVERED"}


def test_todo_resultado_tem_effect_state_severidade_e_mensagem():
    for r in ResultadoOcorrencia:
        e = canonico(r)
        assert isinstance(e, EstadoCanonico)
        assert e.effect_state in ("EFFECT_APPLIED", "NO_EFFECT", "UNKNOWN")
        assert isinstance(e.severidade, Severidade)
        assert e.mensagem


def test_denied_nao_e_failed():
    """Recusa é o sistema funcionando; falha é o sistema quebrando."""
    d = canonico(ResultadoOcorrencia.DENIED)
    f = canonico(ResultadoOcorrencia.FAILED)
    assert d.severidade is Severidade.AVISO
    assert f.severidade is Severidade.ERRO
    assert d.effect_state == "NO_EFFECT"       # negado antes de tocar nada
    assert f.effect_state == "UNKNOWN"         # pode ter mudado antes de cair


def test_failed_implica_efeito_desconhecido():
    assert canonico(ResultadoOcorrencia.FAILED).effect_state == "UNKNOWN"
    assert not canonico(ResultadoOcorrencia.FAILED).autoriza_retry
    assert not canonico(ResultadoOcorrencia.UNKNOWN).autoriza_retry


def test_sucesso_nao_alerta():
    """Alerta que dispara sempre é ruído, e ruído treina a ignorar."""
    for r in (ResultadoOcorrencia.EXECUTED_EFFECT,
              ResultadoOcorrencia.EXECUTED_NO_EFFECT,
              ResultadoOcorrencia.RECOVERED):
        assert not canonico(r).alerta
    for r in (ResultadoOcorrencia.DENIED, ResultadoOcorrencia.FAILED,
              ResultadoOcorrencia.UNKNOWN, ResultadoOcorrencia.MISSED):
        assert canonico(r).alerta


def test_de_execucao_classifica_na_ordem_certa():
    """Negação antes de falha; falha antes de sucesso."""
    assert de_execucao(houve_excecao=True, efeito_aplicado=False,
                       negado=True).resultado is ResultadoOcorrencia.DENIED
    assert de_execucao(houve_excecao=True,
                       efeito_aplicado=True).resultado is ResultadoOcorrencia.FAILED
    assert de_execucao(houve_excecao=False,
                       efeito_aplicado=True).resultado is ResultadoOcorrencia.EXECUTED_EFFECT
    assert de_execucao(houve_excecao=False,
                       efeito_aplicado=False).resultado is ResultadoOcorrencia.EXECUTED_NO_EFFECT
    assert de_execucao(houve_excecao=False, efeito_aplicado=True,
                       recuperada=True).resultado is ResultadoOcorrencia.RECOVERED


def test_resultado_nao_canonico_e_recusado():
    for ruim in ("FAILED", None, 42):
        with pytest.raises(ValueError):
            canonico(ruim)


# ------------------------------------------------ ANTI-CONTRADIÇÃO

def test_uma_ocorrencia_um_estado_zero_contradicoes(tmp_path):
    """O teste que a 05 não tinha: os DOIS emissores, a MESMA ocorrência."""
    sink = SinkDeTeste()
    armazem = ArmazemJobs(tmp_path / "j.db")
    s = Scheduler(armazem, executor=_Efeito(falhar=True), agora_fn=lambda: T0,
                  alert_sink=sink)
    s.criar("j", "suj", "fs-listar", primeiro_em=T0)
    t = Ticker(s, SEM_AUTORIZACAO, alert_sink=sink, agora_fn=lambda: T0,
               dormir=lambda _x: None)
    t.tick()

    # Ausência de contradição NÃO pode vir de um emissor calado: uma mutação
    # que silenciasse o ticker deixaria 1 estado e o teste passaria pelo motivo
    # errado. Por isso exijo que os DOIS tenham falado.
    assert len(sink.eventos) >= 2, (
        f"esperava alerta do Scheduler E do Ticker, vieram {len(sink.eventos)} "
        "— um emissor silencioso mascara a contradição em vez de resolvê-la")
    por_ocorrencia = {}
    for ev in sink.eventos:
        por_ocorrencia.setdefault(ev.occurrence_id, set()).add(ev.effect_state)
    assert len(por_ocorrencia) == 1, "esperava UMA ocorrência"
    for occ, estados in por_ocorrencia.items():
        assert len(estados) == 1, (
            f"ocorrência {occ} produziu estados CONTRADITÓRIOS: {estados}")
        assert estados == {"UNKNOWN"}, (
            f"execução que levantou tem efeito DESCONHECIDO, veio {estados}")


def test_falha_de_execucao_e_sempre_UNKNOWN_nos_dois_emissores(tmp_path):
    sink = SinkDeTeste()
    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=_Efeito(falhar=True),
                  agora_fn=lambda: T0, alert_sink=sink)
    d = s.criar("j", "suj", "fs-listar", primeiro_em=T0)
    s.executar_job(d, T0)                       # caminho SEM ticker
    assert sink.eventos
    assert all(e.effect_state == "UNKNOWN" for e in sink.eventos)


def test_negacao_de_autorizacao_e_NO_EFFECT(tmp_path):
    """Autorizador recusa ⇒ nada rodou ⇒ NO_EFFECT, não UNKNOWN."""
    sink = SinkDeTeste()
    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=_Efeito(),
                  agora_fn=lambda: T0)
    s.criar("j", "suj", "fs-listar", primeiro_em=T0)
    t = Ticker(s, lambda d, i: None, alert_sink=sink, agora_fn=lambda: T0,
               dormir=lambda _x: None)
    t.tick()
    assert sink.eventos
    assert all(e.effect_state == "NO_EFFECT" for e in sink.eventos)


def test_nenhum_emissor_decide_effect_state_por_conta_propria():
    """Estrutural, por AST — docstring que MENCIONA o literal não conta.

    (A primeira versão usava substring e reprovava a própria explicação de por
    que o literal não deve existir. Prosa não é código.)
    """
    import ast
    import inspect

    from nomos.adapters import scheduler as sched_mod
    from nomos.adapters import ticker as tick_mod
    for mod in (sched_mod, tick_mod):
        arvore = ast.parse(inspect.getsource(mod))
        for no in ast.walk(arvore):
            if isinstance(no, ast.keyword) and no.arg == "effect_state":
                assert not isinstance(no.value, ast.Constant), (
                    f"{mod.__name__} passa effect_state LITERAL — "
                    "deve vir de adapters.resultado")
        assert "from nomos.adapters.resultado import" in inspect.getsource(mod)
