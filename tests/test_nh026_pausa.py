"""NH-026 — pausa graciosa: a ocorrência atual termina, nenhuma nova começa.

O freio cobre as DUAS portas autônomas (Ticker e rotinas) e nada além delas.
Doutrina de fricção assimétrica: pausar não tem gate; retomar tem (A1).
Freio nunca é fail-open: pausa.json ilegível = PAUSADO; `pausado_fn` que
levanta exceção = PAUSADO.
"""
from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone

from nomos import cli
from nomos.adapters.scheduler import ArmazemJobs, Scheduler
from nomos.adapters.ticker import SEM_AUTORIZACAO, CatchUp, Ticker, SEM_TRAVA
from nomos.kernel import pausa
import pytest

T0 = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


class _AuditFake:
    def __init__(self):
        self.eventos = []

    def append(self, evento, **campos):
        self.eventos.append((evento, campos))


class _SchedulerEspiao:
    """Só o que o tick() usa; registra se `devidos()` foi consultado."""

    def __init__(self):
        self.consultas = 0

    def devidos(self, agora):
        self.consultas += 1
        return []


# ------------------------------------------------------------- kernel.pausa

def test_pausa_default_ativo(tmp_path):
    assert pausa.esta_pausado(tmp_path) is False
    est = pausa.estado(tmp_path)
    assert est["pausado"] is False and est["ilegivel"] is False


@pytest.mark.permissao_unix
def test_pausa_roundtrip_0600_atomico(tmp_path):
    est = pausa.pausar(tmp_path, motivo="manutenção")
    assert est["pausado"] is True and est["motivo"] == "manutenção"
    assert pausa.esta_pausado(tmp_path) is True
    arquivo = tmp_path / pausa.ARQUIVO
    modo = stat.S_IMODE(arquivo.stat().st_mode)
    assert modo == 0o600
    assert not arquivo.with_suffix(".tmp").exists(), "escrita não foi atômica"
    pausa.retomar(tmp_path)
    assert pausa.esta_pausado(tmp_path) is False


def test_pausa_motivo_truncado_em_200(tmp_path):
    est = pausa.pausar(tmp_path, motivo="x" * 999)
    assert len(est["motivo"]) == 200


def test_pausa_ilegivel_e_pausado(tmp_path):
    alvo = tmp_path / pausa.ARQUIVO
    for lixo in ("{corrompido", "[1,2,3]", "null", ""):
        alvo.write_text(lixo)
        assert pausa.esta_pausado(tmp_path) is True, repr(lixo)
        est = pausa.estado(tmp_path)
        assert est["pausado"] is True
    # lista JSON válida não é dict ⇒ ilegível para nós
    alvo.write_text(json.dumps([True]))
    assert pausa.estado(tmp_path)["ilegivel"] is True


def test_pausa_diretorio_no_lugar_do_arquivo_sem_crash(tmp_path):
    (tmp_path / pausa.ARQUIVO).mkdir()
    assert pausa.esta_pausado(tmp_path) is True
    assert pausa.estado(tmp_path)["ilegivel"] is True


# ------------------------------------------------------------------ Ticker

def test_ticker_pausado_nao_examina():
    espiao = _SchedulerEspiao()
    t = Ticker(espiao, SEM_AUTORIZACAO, agora_fn=lambda: T0,
               dormir=lambda _s: None, pausado_fn=lambda: True, trava=SEM_TRAVA)
    r = t.tick()
    assert espiao.consultas == 0, "pausado não pode nem consultar devidos()"
    assert (r.examinados, r.executadas) == (0, 0)


def test_ticker_default_none_intacto():
    espiao = _SchedulerEspiao()
    t = Ticker(espiao, SEM_AUTORIZACAO, agora_fn=lambda: T0,
               dormir=lambda _s: None, trava=SEM_TRAVA)
    t.tick()
    assert espiao.consultas == 1


def test_ticker_pausado_fn_excecao_e_pausado():
    espiao = _SchedulerEspiao()

    def quebrado():
        raise RuntimeError("freio quebrou")

    t = Ticker(espiao, SEM_AUTORIZACAO, agora_fn=lambda: T0,
               dormir=lambda _s: None, pausado_fn=quebrado, trava=SEM_TRAVA)
    t.tick()
    assert espiao.consultas == 0, "freio que quebra tem de quebrar FECHADO"


def test_ticker_audit_por_borda_nao_por_tick():
    audit = _AuditFake()
    pausado = {"v": True}
    t = Ticker(_SchedulerEspiao(), SEM_AUTORIZACAO, audit=audit,
               agora_fn=lambda: T0, dormir=lambda _s: None,
               pausado_fn=lambda: pausado["v"], trava=SEM_TRAVA)
    for _ in range(5):
        t.tick()
    entrou = [e for e, _c in audit.eventos if e == "ticker.pausa.entrou"]
    assert len(entrou) == 1, "5 ticks pausados = 1 evento, não 5 (DoS de trilha)"
    pausado["v"] = False
    t.tick()
    saiu = [e for e, _c in audit.eventos if e == "ticker.pausa.saiu"]
    assert len(saiu) == 1


def test_ticker_borda_reseta_nos_dois_sentidos():
    """Mata o mutante que remove `self._estava_pausado = False` na saída
    (SOBREVIVEU à 1ª rodada: com 1 tick pós-pausa o total de 'saiu' ainda é
    1). Sem o reset, CADA tick ativo re-audita 'saiu' (DoS de trilha) e a
    pausa seguinte não audita 'entrou'. Aqui: N ticks ativos ⇒ 1 'saiu';
    re-pausar ⇒ 2º 'entrou' tem de aparecer."""
    audit = _AuditFake()
    pausado = {"v": True}
    t = Ticker(_SchedulerEspiao(), SEM_AUTORIZACAO, audit=audit,
               agora_fn=lambda: T0, dormir=lambda _s: None,
               pausado_fn=lambda: pausado["v"], trava=SEM_TRAVA)
    t.tick()                                   # entra pausado (1º 'entrou')
    pausado["v"] = False
    for _ in range(4):                         # 4 ticks ativos
        t.tick()
    saiu = [e for e, _c in audit.eventos if e == "ticker.pausa.saiu"]
    assert len(saiu) == 1, "4 ticks ativos = 1 'saiu', não 4"
    pausado["v"] = True
    t.tick()                                   # pausa DE NOVO
    entrou = [e for e, _c in audit.eventos if e == "ticker.pausa.entrou"]
    assert len(entrou) == 2, "re-pausar tem de auditar o 2º 'entrou'"


def test_ticker_pausa_no_meio_do_catchup(tmp_path):
    """3 ocorrências vencidas; o freio liga após a 1ª ⇒ a corrente termina,
    as outras 2 NÃO iniciam. Mata o mutante que remove o check do laço."""
    execucoes = []

    def efeito(d, i, credencial=None):
        execucoes.append(i.ocorrencia)
        return type("R", (), {"efeito_aplicado": True})()

    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=efeito,
                  agora_fn=lambda: T0)
    s.criar("j", "suj", "fs-listar", intervalo_s=60,
            primeiro_em=T0 - timedelta(seconds=120))
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: T0,
               dormir=lambda _s: None, catchup=CatchUp.RUN_ALL_BOUNDED,
               pausado_fn=lambda: len(execucoes) >= 1, trava=SEM_TRAVA)
    t.tick()
    assert len(execucoes) == 1, (
        f"pausa no meio do catch-up: esperava 1 execução, houve {len(execucoes)}")


def test_ticker_pausa_entre_jobs_do_mesmo_tick(tmp_path):
    """Dois jobs devidos no MESMO tick; freio liga após o 1º ⇒ o 2º não roda."""
    execucoes = []

    def efeito(d, i, credencial=None):
        execucoes.append(d.job_id)
        return type("R", (), {"efeito_aplicado": True})()

    s = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=efeito,
                  agora_fn=lambda: T0)
    s.criar("a", "suj", "fs-listar", primeiro_em=T0)
    s.criar("b", "suj", "fs-listar", primeiro_em=T0)
    t = Ticker(s, SEM_AUTORIZACAO, agora_fn=lambda: T0,
               dormir=lambda _s: None,
               pausado_fn=lambda: len(execucoes) >= 1, trava=SEM_TRAVA)
    t.tick()
    assert len(execucoes) == 1


# ------------------------------------------------------------------ rotinas

def test_rotinas_pausadas_nao_executam_nem_marcam(tmp_path, monkeypatch):
    from nomos.simple import rotinas as rot
    chamadas = {"acao": 0, "marcou": 0}
    monkeypatch.setattr(rot, "devidas",
                        lambda home, agora=None: [
                            {"id": "r1", "nome": "n", "acao": "a"}])
    monkeypatch.setattr(rot, "executar_acao",
                        lambda *a, **k: chamadas.__setitem__(
                            "acao", chamadas["acao"] + 1) or (True, ""))
    monkeypatch.setattr(rot, "_marcar_execucao",
                        lambda *a, **k: chamadas.__setitem__(
                            "marcou", chamadas["marcou"] + 1))
    audit = _AuditFake()
    ctx = {"home": tmp_path, "audit": audit}

    pausa.pausar(tmp_path, motivo="teste")
    assert rot.executar_devidas(ctx) == []
    assert chamadas == {"acao": 0, "marcou": 0}
    assert ("rotinas.pausadas" in [e for e, _c in audit.eventos])

    pausa.retomar(tmp_path)
    resultados = rot.executar_devidas(ctx)
    assert len(resultados) == 1 and chamadas["acao"] == 1, (
        "depois do retomar a rotina continua DEVIDA e roda")


# ---------------------------------------------------------------------- CLI

def _home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("NOMOS_HOME", str(h))
    return h


def test_cmd_pausar_sem_gate_e_status_mostra(tmp_path, monkeypatch, capsys):
    h = _home(tmp_path, monkeypatch)
    assert cli.main(["pausar", "--motivo", "janela de manutenção"]) == cli.EXIT_OK
    assert pausa.esta_pausado(h) is True
    capsys.readouterr()
    assert cli.main(["status"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "pausa: ATIVA" in out and "janela de manutenção" in out


def test_cmd_retomar_sem_tty_negado(tmp_path, monkeypatch, capsys):
    h = _home(tmp_path, monkeypatch)
    pausa.pausar(h, motivo="x")
    rc = cli.main(["retomar"])
    assert rc == cli.EXIT_DENIED, "sem TTY não há dono presente: fail-closed"
    assert pausa.esta_pausado(h) is True, "negado não pode ter retomado"


def test_cmd_retomar_ja_inativa_e_ok(tmp_path, monkeypatch, capsys):
    _home(tmp_path, monkeypatch)
    assert cli.main(["retomar"]) == cli.EXIT_OK


def test_panic_tambem_pausa(tmp_path, monkeypatch, capsys):
    h = _home(tmp_path, monkeypatch)
    assert cli.main(["panic"]) == cli.EXIT_OK
    est = pausa.estado(h)
    assert est["pausado"] is True and est["origem"] == "panic"
    out = capsys.readouterr().out
    assert "PAUSADA" in out
