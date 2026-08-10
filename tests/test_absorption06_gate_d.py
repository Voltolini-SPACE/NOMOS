"""ABSORPTION-06 / GATE D — os achados do censo adversarial, virados em teste.

Escritos ANTES da correção, de propósito: um teste que nasce verde não prova
que pega o defeito, prova só que o defeito não estava onde ele olha. Estes
nascem VERMELHOS sobre o código atual e viram verdes com a correção — é a única
ordem em que a cor significa alguma coisa.

Todos vieram de um censo INDEPENDENTE. Vale registrar por quê: os mesmos
arquivos passaram por suíte verde e por mutação com zero sobreviventes nas
etapas anteriores desta missão. Mutação prova que o código faz o que os testes
dizem; não prova que os testes perguntam a coisa certa. O censo perguntou outras
coisas e achou nove defeitos.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from nomos.adapters.scheduler import (ArmazemJobs, JobInstance, JobState,
                                      Scheduler)
from nomos.adapters.ticker import CatchUp, Ticker
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _sim(_d):
    return True


class Relogio:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def avanca(self, **kw):
        self.t += timedelta(**kw)


def _monta(tmp_path, intervalo_s=60):
    """Scheduler com executor que CONTA efeitos reais, não o que o ticker relata."""
    efeitos = []

    def executor(d, inst, credencial=None):
        efeitos.append(inst.ocorrencia)
        return type("R", (), {"efeito_aplicado": True})()

    relogio = Relogio()
    s = Scheduler(ArmazemJobs(tmp_path / "jobs.db"), executor=executor,
                  agora_fn=relogio)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=intervalo_s)
    return s, efeitos, relogio


# ==================================================== D1 — SKIP não pula nada

@pytest.mark.parametrize("minutos,rotulo", [
    (5, "downtime curto"), (25, "downtime médio"), (45, "downtime longo"),
    (300, "downtime de 5h"),
])
def test_d1_skip_executa_exatamente_uma_ocorrencia(tmp_path, minutos, rotulo):
    """SKIP significa: rode SÓ a mais recente. Sempre. Não às vezes.

    O defeito estava numa guarda escrita ao contrário — a lista só era reduzida
    quando `recente != atrasadas[-1]`, condição falsa justamente quando o
    downtime é curto e a lista não bateu no teto. Os dois testes que existiam
    usavam 5h, o único regime em que o código acertava por acidente. Por isso
    este teste varre quatro durações: um teste que só olha um regime não
    descobre que o outro está quebrado.
    """
    s, efeitos, relogio = _monta(tmp_path, intervalo_s=60)
    relogio.avanca(minutes=minutos)
    t = Ticker(s, lambda d, i: object(), catchup=CatchUp.SKIP,
               catchup_max=10, agora_fn=relogio, dormir=lambda _s: None)
    t.rodar_ate(max_ticks=1)
    assert len(efeitos) == 1, (
        f"{rotulo} ({minutos}min): SKIP executou {len(efeitos)} ocorrências — "
        "deveria executar só a mais recente")


def test_d1_nao_existe_ramo_morto_no_catchup(tmp_path):
    """Ramo `if False and …` é código que finge existir.

    Não é estilo: é uma defesa que o leitor conta como presente e que nunca
    roda. Foi assim que o SKIP passou a não pular nada sem ninguém notar.
    """
    import ast
    import inspect

    from nomos.adapters import ticker as mod
    arvore = ast.parse(inspect.getsource(mod))
    mortos = [n.lineno for n in ast.walk(arvore)
              if isinstance(n, ast.If)
              and isinstance(n.test, ast.BoolOp)
              and any(isinstance(v, ast.Constant) and v.value is False
                      for v in n.test.values)]
    mortos += [n.lineno for n in ast.walk(arvore)
               if isinstance(n, ast.If) and isinstance(n.test, ast.Constant)
               and n.test.value is False]
    assert not mortos, f"ramo(s) inalcançável(is) em ticker.py, linha(s) {mortos}"


# ============================== D2 — crash entre reserva e efeito trava o job

def test_d2_ocorrencia_orfa_nao_congela_o_job_para_sempre(tmp_path):
    """Reserva órfã = processo morreu entre reservar e concluir.

    Ao voltar, o dedup faz a coisa certa (não reexecuta o efeito) e a coisa
    errada (retorna antes de reagendar). O job fica preso naquele instante:
    a cada tick o PDP é chamado, `executadas=1` é reportado, e NADA acontece.
    Livelock que se anuncia como sucesso — a pior combinação possível, porque
    a métrica que o operador olha diz que está tudo bem.
    """
    s, efeitos, relogio = _monta(tmp_path, intervalo_s=60)
    d = s.armazem.obter("j")
    inst = JobInstance(job_id="j", ocorrencia=d.proximo_em.isoformat())
    assert s.armazem.reservar(inst), "não reservou — teste inócuo"
    # o processo morreu aqui: reservado, nunca concluído

    antes = s.armazem.obter("j").proximo_em
    for _ in range(5):
        relogio.avanca(minutes=1)
        for dd in s.devidos():
            s.executar_ocorrencia(dd, JobInstance(
                job_id=dd.job_id, ocorrencia=dd.proximo_em.isoformat()),
                relogio.t)
    depois = s.armazem.obter("j").proximo_em
    assert depois > antes, (
        f"proximo_em não saiu de {antes} após 5 ticks — job congelado pela "
        "ocorrência órfã")


def test_d2_ocorrencia_orfa_nao_conta_como_executada(tmp_path):
    """Dedup não é sucesso. Relatar `executadas` para algo que não rodou faz a
    métrica mentir exatamente onde ela precisaria alertar."""
    s, efeitos, relogio = _monta(tmp_path, intervalo_s=60)
    d = s.armazem.obter("j")
    inst = JobInstance(job_id="j", ocorrencia=d.proximo_em.isoformat())
    s.armazem.reservar(inst)
    execucao = s.executar_ocorrencia(d, inst, relogio.t)
    assert not efeitos, "o efeito rodou apesar do dedup — teste inócuo"
    assert not execucao.efeito_aplicado, (
        "ocorrência deduplicada reportou efeito aplicado")


# ================== D3 — operação concorrente do operador derruba o processo

@pytest.mark.parametrize("operacao", ["cancelar", "apagar"])
def test_d3_operacao_do_operador_durante_o_tick_nao_derruba_o_ticker(tmp_path,
                                                                     operacao):
    """O operador cancelando um job não pode matar o daemon.

    `sched-cancelar` e `sched-apagar` são operações NORMAIS, expostas na CLI.
    Se elas caírem entre `devidos()` e a execução, a exceção sobe até
    `rodar_ate` e o processo morre — sem alerta, e com a ocorrência RUNNING
    órfã que o D2 descreve. Um daemon tem de sobreviver ao seu operador.
    """
    relogio = Relogio()
    efeitos = []

    def executor(d, inst, credencial=None):
        # o operador age EXATAMENTE aqui, com a execução em curso
        getattr(s, operacao)("j")
        efeitos.append(inst.ocorrencia)
        return type("R", (), {"efeito_aplicado": True})()

    s = Scheduler(ArmazemJobs(tmp_path / "jobs.db"), executor=executor,
                  agora_fn=relogio)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    t = Ticker(s, lambda d, i: object(), catchup=CatchUp.RUN_ONCE,
               agora_fn=relogio, dormir=lambda _s: None)
    try:
        t.rodar_ate(max_ticks=1)
    except Exception as exc:
        pytest.fail(f"`{operacao}` concorrente derrubou o ticker: "
                    f"{type(exc).__name__}: {exc}")


# ====================== D5 — efeito afirmado por quem não observou o efeito

def test_d5_capacidade_de_leitura_nao_grava_efeito_aplicado(tmp_path):
    """`fs-listar` é READ_LOCAL e idempotente: não muda nada.

    O agendador devolvia `efeito_aplicado=True` como literal fixo, então uma
    leitura era gravada como EXECUTED_EFFECT / EFFECT_APPLIED e saía com
    `autoriza_retry=False`. Isso contradiz a premissa da fonte única criada na
    ETAPA 3 — só se afirma efeito quando se SABE — e a informação necessária
    está disponível ali: a idempotência e a categoria vêm do REGISTRO, que é a
    autoridade sobre risco desde a ABSORPTION-03.
    """
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    ag = AgendadorGovernado(ctx, _sim, ConfigAgendador(raizes=(str(ws),)))
    ag.preparar()
    ok, _, motivo = ag.operar("sched-criar", job_id="leitura",
                              capacidade="fs-listar", alvo_job=str(ws))
    assert ok, motivo
    d = ag.armazem.obter("leitura")
    inst = JobInstance(job_id="leitura", ocorrencia=d.proximo_em.isoformat())
    rt = ag.autorizador(d, inst)
    assert rt is not None, "autorizador recusou — teste inócuo"
    execucao = ag.scheduler.executar_ocorrencia(d, inst, d.proximo_em,
                                                credencial=rt)
    assert execucao.estado_final is JobState.SUCCEEDED, execucao.detalhe
    assert not execucao.efeito_aplicado, (
        "capacidade de LEITURA idempotente gravou efeito aplicado")


# =========================== D6 — ocorrências descartadas somem sem rastro

def test_d6_ocorrencias_descartadas_pelo_teto_deixam_rastro(tmp_path):
    """60 vencidas, teto de 10: as outras 50 não podem sumir caladas.

    Descartar é uma decisão legítima — sem teto o daemon acorda e martela o
    mundo. O que não é legítimo é descartar em silêncio: o operador precisa
    conseguir responder "quantas execuções eu perdi na queda de ontem?".
    """
    home = tmp_path / "h"
    home.mkdir()
    ctx_audit = AuditLog(home / "audit.jsonl")
    relogio = Relogio()
    efeitos = []

    def executor(d, inst, credencial=None):
        efeitos.append(inst.ocorrencia)
        return type("R", (), {"efeito_aplicado": True})()

    s = Scheduler(ArmazemJobs(tmp_path / "jobs.db"), executor=executor,
                  audit=ctx_audit, agora_fn=relogio)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    relogio.avanca(minutes=60)                     # 60 ocorrências vencidas
    t = Ticker(s, lambda d, i: object(), catchup=CatchUp.RUN_ALL_BOUNDED,
               catchup_max=10, audit=ctx_audit, agora_fn=relogio,
               dormir=lambda _s: None)
    t.rodar_ate(max_ticks=1)

    assert len(efeitos) <= 10, f"teto furado: {len(efeitos)} execuções"
    eventos = [json.loads(linha) for linha in
               (home / "audit.jsonl").read_text().splitlines() if linha.strip()]
    rastro = [e for e in eventos
              if "descart" in e.get("event", "") or "pulou" in e.get("event", "")
              or "missed" in e.get("event", "").lower()]
    assert rastro, (
        f"{60 - len(efeitos)} ocorrências descartadas sem UM evento de "
        f"auditoria; eventos vistos: {sorted({e.get('event') for e in eventos})}")


def test_d6_estados_missed_e_recovered_tem_emissor(tmp_path):
    """Estado de taxonomia sem emissor é vocabulário, não observabilidade.

    Criei MISSED e RECOVERED na ETAPA 3 e não liguei nenhum dos dois. Um
    dicionário de estados que ninguém emite dá a impressão de que o sistema
    sabe distinguir casos que ele nunca chega a reportar.
    """
    import pathlib

    import nomos.adapters as pacote
    raiz = pathlib.Path(pacote.__file__).parent
    emissores = []
    for arq in raiz.glob("*.py"):
        if arq.name == "resultado.py":
            continue                       # a definição não conta como uso
        texto = arq.read_text()
        if "MISSED" in texto or "RECOVERED" in texto:
            emissores.append(arq.name)
    assert emissores, (
        "MISSED e RECOVERED existem só na definição — nenhum código os emite")
