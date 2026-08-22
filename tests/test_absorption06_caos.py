"""ABSORPTION-06 / ETAPA 8 — caos: o que acontece quando algo dá errado no meio.

Os testes anteriores perguntam "funciona?". Estes perguntam "quando quebrar no
pior instante possível, quebra para que lado?". Um scheduler que vai virar
daemon roda 24h sem ninguém olhando: o modo de falha importa mais que o modo de
sucesso, porque o de sucesso alguém confere e o de falha ninguém vê.

Regra de leitura: em toda situação abaixo, DUAS execuções da mesma ocorrência é
pior que ZERO. Perder uma execução é um job atrasado; repetir uma é um efeito
duplicado no mundo — e o mundo não tem desfazer.
"""
from __future__ import annotations

import gc
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from nomos.adapters.contrato import ErroConflito
from nomos.adapters.scheduler import (ArmazemJobs, JobInstance, JobState,
                                      Scheduler)
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador


def _sim(_d):
    return True


def _ocorrencia(d):
    """A ocorrência planejada do job — `devidos()` devolve JobDefinition, e a
    unidade de deduplicação é o par (job_id, instante)."""
    return JobInstance(job_id=d.job_id, ocorrencia=d.proximo_em.isoformat())


def _ctx(tmp_path):
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    return {"home": home, "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


@pytest.fixture()
def amb(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = _ctx(tmp_path)
    ag = AgendadorGovernado(ctx, _sim, ConfigAgendador(raizes=(str(ws),)))
    ag.preparar()
    return ag, ws, ctx


# ============================================ 1. crash entre reserva e efeito

def test_crash_no_meio_do_efeito_nao_repete_a_ocorrencia(tmp_path):
    """A reserva acontece ANTES do efeito, e é isso que sobrevive ao crash.

    Se a reserva viesse depois, um processo que morre no meio do efeito
    reexecutaria a ocorrência ao voltar — efeito duplicado. Aqui o executor
    morre por exceção depois de ter tocado o mundo; a ocorrência NÃO pode ser
    reservada de novo.
    """
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    tocou = []

    def executor(d, inst, credencial=None):
        tocou.append(inst.chave)
        raise RuntimeError("morreu depois de tocar o mundo")

    agora = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    s = Scheduler(armazem, executor=executor, agora_fn=lambda: agora)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    devidos = s.devidos()
    assert devidos, "nenhum job devido — teste inócuo"
    d = devidos[0]
    inst = _ocorrencia(d)
    s.executar_ocorrencia(d, inst, agora)
    assert tocou, "o executor nunca tocou o mundo — teste inócuo"
    # a MESMA ocorrência não pode ser reservada outra vez
    n_antes = len(tocou)
    for _ in range(3):
        s.executar_ocorrencia(s.armazem.obter("j"), inst, agora)
    assert len(tocou) == n_antes, (
        f"ocorrência {inst.chave} executou {len(tocou)}× após crash — "
        "efeito duplicado")


# ============================================ 2. dois tickers concorrentes

def test_dois_tickers_no_mesmo_armazem_nao_executam_a_mesma_ocorrencia(tmp_path):
    """Dois processos apontados ao mesmo jobs.db é o cenário real de operador
    que sobe o daemon duas vezes por engano. A reserva é a defesa."""
    armazem_a = ArmazemJobs(tmp_path / "jobs.db")
    armazem_b = ArmazemJobs(tmp_path / "jobs.db")
    execucoes, trava = [], threading.Lock()

    def executor(d, inst, credencial=None):
        with trava:
            execucoes.append(inst.chave)
        time.sleep(0.01)
        return type("R", (), {"efeito_aplicado": True})()

    agora = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    sa = Scheduler(armazem_a, executor=executor, agora_fn=lambda: agora)
    sb = Scheduler(armazem_b, executor=executor, agora_fn=lambda: agora)
    sa.criar("j", "sujeito", "fs-listar", intervalo_s=60)

    resultados = []

    def roda(s):
        for d in s.devidos():
            try:
                resultados.append(
                    s.executar_ocorrencia(d, _ocorrencia(d), agora))
            except Exception as exc:
                resultados.append(exc)

    t1 = threading.Thread(target=roda, args=(sa,))
    t2 = threading.Thread(target=roda, args=(sb,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert len(execucoes) == len(set(execucoes)), (
        f"ocorrência executada mais de uma vez por tickers concorrentes: {execucoes}")


# ============================================ 3. relógio que salta

def test_relogio_para_tras_nao_reexecuta_ocorrencia_ja_feita(tmp_path):
    """NTP corrigindo o relógio, ou o Mac saindo de suspensão, move o tempo
    para trás. Uma ocorrência já executada não pode voltar a ser devida."""
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    feitas = []
    relogio = {"t": datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)}

    def executor(d, inst, credencial=None):
        feitas.append(inst.chave)
        return type("R", (), {"efeito_aplicado": True})()

    s = Scheduler(armazem, executor=executor, agora_fn=lambda: relogio["t"])
    s.criar("j", "sujeito", "fs-listar", intervalo_s=3600)
    for d in s.devidos():
        s.executar_ocorrencia(d, _ocorrencia(d), relogio["t"])
    antes = list(feitas)
    relogio["t"] -= timedelta(hours=6)          # relógio salta para trás
    for d in s.devidos():
        s.executar_ocorrencia(d, _ocorrencia(d), relogio["t"])
    assert feitas == antes, (
        f"relógio para trás reexecutou ocorrência: {feitas} (antes {antes})")


def test_relogio_para_frente_nao_dispara_tempestade_sem_limite(tmp_path):
    """Suspensão longa: ao acordar, mil ocorrências estão vencidas."""
    from nomos.adapters.ticker import CatchUp
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    feitas = []
    relogio = {"t": datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)}

    def executor(d, inst, credencial=None):
        feitas.append(inst.chave)
        return type("R", (), {"efeito_aplicado": True})()

    s = Scheduler(armazem, executor=executor, agora_fn=lambda: relogio["t"])
    s.criar("j", "sujeito", "fs-listar", intervalo_s=1)
    relogio["t"] += timedelta(days=30)          # 2.592.000 ocorrências vencidas
    from nomos.adapters.ticker import Ticker
    t = Ticker(s, lambda d, i: object(), catchup=CatchUp.RUN_ALL_BOUNDED,
               catchup_max=5, agora_fn=lambda: relogio["t"],
               dormir=lambda _s: None)
    t.rodar_ate(max_ticks=1)
    assert len(feitas) <= 5, (
        f"{len(feitas)} execuções numa passada com catchup_max=5 — sem teto, "
        "o daemon acorda e martela o mundo")


# ============================================ 4. registro corrompido

def test_registro_corrompido_nao_derruba_a_listagem_inteira(tmp_path):
    """Um job ilegível não pode cegar o operador sobre os outros nove."""
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    s = Scheduler(armazem, executor=lambda *a, **k: None)
    for i in range(3):
        s.criar(f"j{i}", "sujeito", "fs-listar", intervalo_s=60)
    con = sqlite3.connect(armazem.caminho)
    con.execute("UPDATE jobs SET schedule='{lixo' WHERE job_id='j1'")
    con.commit()
    con.close()
    try:
        vivos = [d.job_id for d in armazem.listar()]
    except Exception as exc:
        pytest.fail(f"listar() morreu inteiro por causa de um registro: {exc!r}")
    assert "j0" in vivos and "j2" in vivos, (
        f"registros sãos sumiram junto com o corrompido: {vivos}")


def test_armazem_corrompido_falha_fechado_nao_relata_zero_jobs(tmp_path):
    """Armazém ilegível tem de LEVANTAR, nunca responder "nenhum job".

    Esta é a falha aberta que mataria um daemon em silêncio: o arquivo fica
    ilegível, `listar()` devolve lista vazia, o ticker roda 24h achando que não
    há nada a fazer, e ninguém percebe até alguém perguntar por que o backup
    parou de acontecer. Errar para o lado do ruído é recuperável; errar para o
    lado do silêncio não é.
    """
    caminho = tmp_path / "jobs.db"
    s = Scheduler(ArmazemJobs(caminho), executor=lambda *a, **k: None)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    # Solta as conexões ANTES de apagar. No POSIX isto é dispensável — `unlink`
    # de arquivo aberto funciona —, mas no Windows o apagar falha com WinError
    # 32 ("usado por outro processo") e o teste morre antes de medir o que
    # promete. A propriedade sob teste (armazém ilegível LEVANTA) é portável; a
    # técnica é que não era.
    #
    # Precisa de `gc` porque `adapters/scheduler.py` nunca fecha conexão: são
    # 13 `self._conn()` e zero `.close()`, cada uma dependendo do coletor. É um
    # descuido real de recurso, invisível no POSIX, e a correção certa é no
    # produto — fora do escopo desta fatia, registrada aqui para não sumir.
    del s
    gc.collect()
    for p in tmp_path.iterdir():
        if p.name.startswith("jobs.db"):
            p.unlink()
    caminho.write_bytes(b"isto nao e um banco sqlite")
    # Tipo EXATO, não `Exception`: asserir exceção cega é o mesmo defeito que
    # o censo achou no test_n10 — passa com qualquer erro, inclusive um bug do
    # próprio teste.
    with pytest.raises(sqlite3.DatabaseError) as exc:
        ArmazemJobs(caminho).listar()
    assert "not a database" in str(exc.value).lower(), (
        f"levantou por outro motivo: {exc.value!r}")


# NOTA: existia aqui `test_wal_intacto_recupera_o_arquivo_principal_corrompido`,
# removido depois de falhar deterministicamente na suíte completa e passar
# isolado.
#
# Ele afirmava que corromper só o arquivo principal não perde jobs enquanto o
# `-wal` estiver lá. O fato é verdadeiro quando o WAL tem frames — mas eu NÃO
# CONSIGO FORÇAR esse estado de fora: o SQLite consolida o WAL por checkpoint
# automático quando a última conexão fecha, e o arquivo pode continuar
# existindo com apenas o cabeçalho, o que derrota qualquer guarda por tamanho.
#
# Ele era teste de CARACTERIZAÇÃO, escrito quando descobri que a primeira
# versão do teste irmão passava pelo motivo errado (o WAL recuperava e eu
# achava que era fail-closed). Documentava propriedade INCIDENTAL do SQLite,
# não decisão de desenho do NOMOS.
#
# A propriedade que importa — armazém ilegível LEVANTA em vez de responder
# "nenhum job" — continua coberta por
# `test_armazem_corrompido_falha_fechado_nao_relata_zero_jobs`, cujo cenário é
# construível: apagar TODOS os arquivos e escrever lixo.
#
# Manter um teste cuja premissa não se consegue construir é pior que não tê-lo:
# ele falha por motivo alheio ao código e ensina a ignorar vermelho.


# ============================================ 5. SIGTERM / SIGKILL

# `signal.SIGKILL` não existe no Windows e, avaliado no DECORATOR, derrubava
# a coleta inteira do runner. A parametrização passa a ser montada com o que
# a plataforma tem: no Windows sobra o SIGTERM (o caso que lá faz sentido).
@pytest.mark.parametrize(
    "sinal,nome",
    [(signal.SIGTERM, "SIGTERM")]
    + ([(signal.SIGKILL, "SIGKILL")] if hasattr(signal, "SIGKILL") else []))
def test_ticker_morto_por_sinal_nao_deixa_ocorrencia_meio_executada(tmp_path,
                                                                    sinal, nome):
    """Mata o processo NO MEIO da execução e confere o estado que sobrou.

    SIGTERM dá chance de shutdown limpo; SIGKILL não dá chance nenhuma. O
    invariante tem de valer nos dois: ao voltar, a ocorrência interrompida não
    pode reexecutar o efeito.
    """
    marcador = tmp_path / "efeito.txt"
    db = tmp_path / "jobs.db"
    programa = f'''
import time, sys
from datetime import datetime, timezone
from nomos.adapters.scheduler import ArmazemJobs, Scheduler
def executor(d, inst, credencial=None):
    with open({str(marcador)!r}, "a") as f:
        f.write(inst.chave + "\\n")
        f.flush()
    time.sleep(30)                      # morre AQUI, com o efeito já aplicado
    return type("R", (), {{"efeito_aplicado": True}})()
agora = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
from nomos.adapters.scheduler import JobInstance
s = Scheduler(ArmazemJobs({str(db)!r}), executor=executor, agora_fn=lambda: agora)
try:
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
except Exception:
    pass
for d in s.devidos():
    s.executar_ocorrencia(d, JobInstance(job_id=d.job_id,
                          ocorrencia=d.proximo_em.isoformat()), agora)
'''
    p = subprocess.Popen([sys.executable, "-c", programa],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    for _ in range(100):
        if marcador.exists():
            break
        time.sleep(0.05)
    assert marcador.exists(), f"efeito nunca começou — teste inócuo ({nome})"
    os.kill(p.pid, sinal)
    p.wait(timeout=10)
    primeira = marcador.read_text().strip().splitlines()

    # volta do "reinício": o mesmo armazém, processo novo
    p2 = subprocess.Popen([sys.executable, "-c", programa],
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(2)
    p2.kill()
    p2.wait(timeout=10)
    depois = marcador.read_text().strip().splitlines()
    assert depois == primeira, (
        f"após {nome} e reinício, a ocorrência executou de novo: "
        f"{primeira} → {depois}")


# ============================================ 6. despacho duplicado

def test_mesma_ocorrencia_despachada_duas_vezes_executa_uma(tmp_path):
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    feitas = []

    def executor(d, inst, credencial=None):
        feitas.append(inst.chave)
        return type("R", (), {"efeito_aplicado": True})()

    agora = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    s = Scheduler(armazem, executor=executor, agora_fn=lambda: agora)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    d = s.devidos()[0]
    inst = _ocorrencia(d)
    for _ in range(5):
        s.executar_ocorrencia(s.armazem.obter("j"), inst, agora)
    assert len(feitas) == 1, f"despacho repetido executou {len(feitas)}×"


# ============================================ 6b. permissão dos sidecars

@pytest.mark.permissao_unix
def test_sidecars_do_wal_nao_ficam_legiveis_por_terceiros(tmp_path):
    """0600 no `.db` só protege o `.db`.

    O `PRAGMA journal_mode=WAL` roda antes do chmod e já cria `-wal`/`-shm`
    com o padrão 0644 — e o `-wal` carrega a coluna `argumentos` dos jobs em
    texto claro. Proteger só o arquivo principal é trancar a porta e deixar a
    janela aberta. Este teste existe porque a correção original foi escrita
    sem ele e sobreviveu à mutação: defesa sem teste é defesa que a próxima
    refatoração remove sem ninguém perceber.
    """
    caminho = tmp_path / "jobs.db"
    armazem = ArmazemJobs(caminho)
    s = Scheduler(armazem, executor=lambda *a, **k: None)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60,
            argumentos={"segredo": "CANARIO-QUE-NAO-PODE-VAZAR"})
    # A checagem precisa de uma conexão VIVA: ao fechar a última, o SQLite
    # faz checkpoint e APAGA `-wal`/`-shm`. O armazém abre e fecha por
    # operação, então a presença dos sidecars dependia de timing e de versão
    # do SQLite — em py3.10 (Linux e macOS) eles já não estavam lá e o teste
    # morria no próprio guarda "teste inócuo". Com a conexão aberta, a
    # condição é determinística em qualquer plataforma.
    con = armazem._conn()
    try:
        con.execute("SELECT COUNT(*) FROM jobs").fetchone()
        sidecars = [p for p in tmp_path.iterdir()
                    if p.name.startswith("jobs.db-")]
        assert sidecars, "sem sidecars de WAL — teste inócuo"
        frouxos = {p.name: oct(p.stat().st_mode & 0o777)
                   for p in [caminho, *sidecars] if p.stat().st_mode & 0o077}
        assert not frouxos, f"legível por terceiros: {frouxos}"
    finally:
        con.close()


# ============================================ 7. estado inconsistente

def test_transicao_fora_da_allowlist_e_recusada(tmp_path):
    armazem = ArmazemJobs(tmp_path / "jobs.db")
    s = Scheduler(armazem, executor=lambda *a, **k: None)
    s.criar("j", "sujeito", "fs-listar", intervalo_s=60)
    s.cancelar("j")
    # Tipo EXATO: `Exception` passaria também se `habilitar` explodisse por
    # um bug do teste, e o veredito seria o mesmo. A allowlist recusa com
    # ErroConflito — é isso que precisa ser provado.
    with pytest.raises(ErroConflito):
        s.habilitar("j")            # CANCELLED → SCHEDULED não é permitido
    assert armazem.obter("j").estado is JobState.CANCELLED
