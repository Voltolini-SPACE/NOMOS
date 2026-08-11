"""A5.6 — o ciclo de vida do processo do filtro governado, sob o supervisor.

A5.2 decidiu QUEM executa, A5.3 QUAL objeto, A5.4 COM QUE argumentos e A5.5 COM
QUE AUTORIDADE. Nada disso diz o que acontece com o processo DEPOIS de nascer —
e um filtro que sobrevive à operação que o invocou carrega para frente uma
autoridade que ninguém concedeu.

## Por que esta bateria não reaproveita o PASS parcial anterior

A tentativa anterior de A5.6 passou 6 de 12 e parou: os 6 verdes eram
estruturais (o filtro não tem caminho próprio de execução, o confinamento é o
do supervisor, o perfil tem UM literal de exec, `prazo<=0` recusa antes de
começar) e os 6 restantes dependiam de executar o filtro PELO supervisor — que
era justamente o que estava bloqueado. Herdar aquele PASS seria herdar a metade
que não media processo nenhum.

## O controle positivo, que é o que separa esta bateria de vácuo

"Não sobrou processo" é indistinguível de "nunca houve processo". Por isso todo
descendente GRAVA UM MARCADOR com o próprio pid antes de dormir, e cada teste
de kill exige:

    PROCESS_ACTUALLY_EXISTED = TRUE      (o marcador está no disco)
    ORPHAN_PROCESS           = 0         (e o pid não responde mais)

Descendente é sempre por `fork`: a allowlist de exec do filtro tem UM literal
(o próprio artefato), então o filtro não consegue lançar OUTRO programa — só
cópias de si mesmo. É a forma mais forte disponível sob A5.5, e a mais realista
para um filtro hostil.
"""
from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import supervisor
from nomos.adapters.supervisor import TipoDeProcesso as TP

FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cenario(tmp_path):
    """Artefato nativo importado + fábrica de políticas com argv governado."""
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)
    escopo = tmp_path / "escopo"
    escopo.mkdir()

    class Cen:
        def __init__(self):
            self.escopo = escopo
            self.tmp = tmp_path

        def politica(self, *argv: str) -> fg.PoliticaDeFiltro:
            return fg.PoliticaDeFiltro(
                filter_id="redator", canonical_executable=str(binario),
                managed_artifact=art, argv_policy=tuple(argv),
                read_roots=(str(escopo),), write_roots=(str(escopo),))

        def rodar(self, *argv, prazo=30.0, entrada=None):
            pol = self.politica(*argv)
            return supervisor.executar(
                pol.comando(), cwd=tmp_path, env=pol.ambiente(), prazo=prazo,
                confinamento=pol.confinamento(), tipo=TP.FILTRO_GOVERNADO,
                entrada=entrada)

        def pids_marcados(self, *papeis: str) -> list[int]:
            """Os pids que REALMENTE existiram, lidos do disco."""
            achados = []
            for p in escopo.iterdir():
                if p.name.split(".")[0] in papeis:
                    achados.append(int(p.name.rsplit(".", 1)[1]))
            return sorted(achados)

    return Cen()


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # existe, e é de outro dono
    return True


def _todos_mortos(pids: list[int], prazo=10.0) -> list[int]:
    """Espera curta antes de acusar: reaping do kernel não é instantâneo."""
    fim = time.monotonic() + prazo
    while time.monotonic() < fim:
        vivos = [p for p in pids if _vivo(p)]
        if not vivos:
            return []
        time.sleep(0.2)
    return [p for p in pids if _vivo(p)]


def _exige_que_existiram(pids: list[int], quantos: int) -> None:
    assert len(pids) >= quantos, (
        f"PROCESS_ACTUALLY_EXISTED=FALSE: só {len(pids)} marcador(es) no disco, "
        f"esperado >= {quantos}. Sem processo criado, 'nada sobrou' não prova "
        "contenção nenhuma e o teste seria vácuo")


# ══════════════════════════ 01 — saída normal ════════════════════════════════

def test_a56_01_saida_normal_nao_deixa_residuo(cenario):
    p = cenario.rodar(entrada=b"SENHA=x\n")
    assert p.returncode == 0 and p.classificacao == "EXIT_OK"
    assert p.stdout == b"SENHA=REDIGIDO\n"
    assert p.residuais_mortos == 0 and not p.grupo_resistiu


# ══════════════════════ 02-04 — prazo em cada geração ════════════════════════

def test_a56_02_prazo_mata_o_PAI(cenario):
    p = cenario.rodar("--sonda-dorme", "60", prazo=2.0, entrada=b"")
    assert p.morto_por_timeout and p.classificacao == "KILLED_BY_TIMEOUT"
    assert b"LI_TUDO" in p.stdout and b"ACORDEI" not in p.stdout
    assert not p.grupo_resistiu


def test_a56_03_prazo_mata_o_FILHO(cenario):
    p = cenario.rodar("--sonda-forks", "1", "60", str(cenario.escopo), prazo=3.0)
    pids = cenario.pids_marcados("cria", "pai")
    _exige_que_existiram(pids, 2)
    assert p.morto_por_timeout
    assert _todos_mortos(pids) == [], "ORPHAN_PROCESS: filho sobreviveu"


def test_a56_04_prazo_mata_o_NETO(cenario):
    p = cenario.rodar("--sonda-neto", "60", str(cenario.escopo), prazo=3.0)
    pids = cenario.pids_marcados("pai", "filho", "neto")
    _exige_que_existiram(pids, 3)
    assert p.morto_por_timeout
    assert _todos_mortos(pids) == [], "ORPHAN_PROCESS: neto sobreviveu"


# ═════════════════ 05 — descendente que TROCA DE GRUPO ═══════════════════════

def test_a56_05_descendente_SOLTO_do_grupo_tambem_morre(cenario):
    """`setsid()` esvazia o grupo original — e grupo vazio é o que `killpg` lê
    como "nada sobreviveu". Quem prova ausência é a marca de sandbox."""
    p = cenario.rodar("--sonda-solta", "60", str(cenario.escopo), prazo=3.0)
    pids = cenario.pids_marcados("pai", "solto")
    _exige_que_existiram(pids, 2)
    assert p.morto_por_timeout
    assert _todos_mortos(pids) == [], "ORPHAN_PROCESS: o solto escapou"
    assert p.residuais_mortos >= 1, (
        "o solto morreu, mas não pela pós-condição — se `killpg` bastasse, a "
        "marca de sandbox não estaria sendo o discriminante que A5 exige")


# ══════════════════ 06-07 — sinais educados são ignorados ════════════════════

@pytest.mark.parametrize("sinal", [signal.SIGTERM, signal.SIGINT])
def test_a56_06e07_processo_que_IGNORA_sinal_educado_morre_assim_mesmo(
        cenario, sinal):
    """O supervisor manda SIGTERM e depois SIGKILL. Um filtro que instala
    SIG_IGN sobrevive ao primeiro — e não pode sobreviver ao segundo."""
    inicio = time.monotonic()
    p = cenario.rodar("--sonda-teimosa", "60", prazo=2.0)
    assert p.morto_por_timeout, "a teimosa venceu o prazo"
    assert b"TEIMOSA_VIVA" in p.stdout, "a sonda nem chegou a instalar SIG_IGN"
    assert b"TEIMOSA_ACORDOU" not in p.stdout
    assert time.monotonic() - inicio < 20
    assert not p.grupo_resistiu


# ═══════════ 08-10, 15 — cancelamento (exceção atravessando o supervisor) ════
#
# `executar()` NÃO tem cancelamento como API: o único mecanismo de parada é o
# `prazo`. Inventar um token de cancelamento para satisfazer a lista seria
# implementar produto para passar em teste. O que EXISTE e precisa valer é:
# qualquer exceção que atravesse o supervisor deixa o mesmo estado que uma
# saída normal — sem descendente vivo e sem lixo em disco.

class _PopenQueCancela(subprocess.Popen):
    """Popen real — o processo NASCE — cujo primeiro `wait` é interrompido.

    É a injeção mais fiel de "o operador cancelou": o processo existe, está
    confinado, e a espera dele morre no meio.

    O `pronto` não é conveniência de teste: a primeira versão levantava o
    KeyboardInterrupt na hora, ANTES de os filhos existirem, e o guard de vácuo
    desta bateria reprovou o teste com `PROCESS_ACTUALLY_EXISTED=FALSE`. Estava
    certo — cancelar antes de haver descendente não prova nada sobre limpeza de
    descendente. Agora a espera só é interrompida depois que os processos que o
    teste quer ver mortos ESTÃO no disco.
    """
    pronto = staticmethod(lambda: True)
    _ja = False

    def wait(self, timeout=None):
        if not _PopenQueCancela._ja:
            _PopenQueCancela._ja = True
            fim = time.monotonic() + 15
            while time.monotonic() < fim and not _PopenQueCancela.pronto():
                time.sleep(0.05)
            raise KeyboardInterrupt("cancelado")
        return super().wait(timeout=timeout)


@pytest.fixture
def cancelar_na_espera(monkeypatch):
    """Devolve um armador: o teste diz QUANDO o cancelamento é significativo."""
    def armar(pronto=lambda: True):
        _PopenQueCancela.pronto = staticmethod(pronto)
        _PopenQueCancela._ja = False
        monkeypatch.setattr(supervisor.subprocess, "Popen", _PopenQueCancela)
    yield armar
    _PopenQueCancela._ja = False
    _PopenQueCancela.pronto = staticmethod(lambda: True)


def test_a56_08_cancelamento_ANTES_de_ler_nao_deixa_orfao(cenario,
                                                          cancelar_na_espera):
    cancelar_na_espera()
    with pytest.raises(KeyboardInterrupt):
        cenario.rodar("--sonda-dorme", "60", prazo=30.0, entrada=b"")
    assert _restos_do_sandbox() == [], "ORPHAN_PROCESS após cancelamento"


def test_a56_09_cancelamento_COM_stdin_em_voo_nao_deixa_orfao(
        cenario, cancelar_na_espera):
    cancelar_na_espera()
    with pytest.raises(KeyboardInterrupt):
        cenario.rodar("--sonda-dorme", "60", prazo=30.0,
                      entrada=os.urandom(4 * 1024 * 1024))
    assert _restos_do_sandbox() == [], "ORPHAN_PROCESS após cancelamento"


def test_a56_10_cancelamento_DEPOIS_de_forkar_nao_deixa_orfao(
        cenario, cancelar_na_espera):
    """Cancelar não pode ser um caminho MAIS PERMISSIVO que o prazo.

    O prazo mata a árvore e prova ausência pela marca. Se o cancelamento sair
    por cima disso, basta cancelar para deixar descendente vivo com a
    autoridade de uma operação que nem terminou.
    """
    cancelar_na_espera(lambda: len(cenario.pids_marcados("cria")) >= 3)
    with pytest.raises(KeyboardInterrupt):
        cenario.rodar("--sonda-forks", "3", "60", str(cenario.escopo),
                      prazo=30.0)
    pids = cenario.pids_marcados("cria", "pai")
    _exige_que_existiram(pids, 3)
    sobrando = _todos_mortos(pids)
    assert sobrando == [], (
        f"ORPHAN_PROCESS: {len(sobrando)} descendente(s) sobreviveram ao "
        "cancelamento. Cancelar não pode ser mais permissivo que o prazo")


def test_a56_15_cancelamento_e_prazo_juntos_nao_deixam_orfao(
        cenario, cancelar_na_espera):
    cancelar_na_espera(lambda: len(cenario.pids_marcados("neto")) >= 1)
    with pytest.raises(KeyboardInterrupt):
        cenario.rodar("--sonda-neto", "60", str(cenario.escopo), prazo=1.0)
    pids = cenario.pids_marcados("pai", "filho", "neto")
    _exige_que_existiram(pids, 3)
    assert _todos_mortos(pids) == [], "ORPHAN_PROCESS sob prazo + cancelamento"


# ═══════════════ 11 — pai sai, filho fica (o caso silencioso) ════════════════

def test_a56_11_pai_sai_com_SUCESSO_e_o_filho_NAO_fica(cenario):
    """O `wait` vê rc=0 imediato. Sem pós-condição, um `( sleep 60 ) &` do
    filtro sobreviveria a uma operação BEM-SUCEDIDA — que foi exatamente o
    defeito que a marca de sandbox existe para pegar."""
    p = cenario.rodar("--sonda-filho", "60", str(cenario.escopo), prazo=30.0)
    pids = cenario.pids_marcados("filho")
    _exige_que_existiram(pids, 1)
    assert p.returncode == 0, "o pai deveria ter saído com sucesso"
    assert not p.morto_por_timeout
    assert _todos_mortos(pids) == [], (
        "ORPHAN_PROCESS: o filho sobreviveu a uma operação BEM-SUCEDIDA")
    # Sem exigir POR QUAL mecanismo: um filho que não trocou de grupo é pego
    # pelo `killpg` (o caminho rápido), e nesse caso `exterminar` já não acha
    # ninguém para contar. Exigir `residuais_mortos >= 1` aqui reprovaria o
    # desfecho CORRETO — quem tem de morrer é o processo, não uma estatística.
    # A prova de que a marca de sandbox é o discriminante está no teste 05, com
    # o descendente que TROCA de grupo e some do `killpg`.


# ══════════════════════ 12 — muitos forks de uma vez ═════════════════════════

def test_a56_12_forks_REPETIDOS_todos_morrem(cenario):
    p = cenario.rodar("--sonda-forks", "8", "60", str(cenario.escopo), prazo=3.0)
    pids = cenario.pids_marcados("cria", "pai")
    _exige_que_existiram(pids, 9)
    assert p.morto_por_timeout
    assert _todos_mortos(pids) == [], "ORPHAN_PROCESS entre os 8 forks"


# ═══════════════════════ 13 — saída não-zero ═════════════════════════════════

def test_a56_13_saida_NAO_ZERO_e_reportada_sem_virar_seguranca(cenario):
    """rc != 0 é falha da OPERAÇÃO, não incidente de contenção. Confundir os
    dois faria todo filtro que recusa entrada parecer ataque."""
    p = cenario.rodar("--sonda-rc", "3")
    assert p.returncode == 3
    assert p.classificacao == "EXIT_ERRO"
    assert not p.morto_por_timeout and not p.grupo_resistiu
    assert p.residuais_mortos == 0


# ═══════════════════ 14 — kill externo durante a execução ════════════════════

def test_a56_14_kill_EXTERNO_do_principal_nao_deixa_descendente(cenario):
    """Alguém de fora mata o processo principal. O supervisor não pode tratar
    isso como término limpo e ir embora deixando os descendentes."""
    import threading
    pol = cenario.politica("--sonda-forks", "3", "60", str(cenario.escopo))
    alvo = {}

    def matar_quando_aparecer():
        fim = time.monotonic() + 15
        while time.monotonic() < fim:
            pids = cenario.pids_marcados("pai")
            if pids:
                alvo["pai"] = pids[0]
                try:
                    os.kill(pids[0], signal.SIGKILL)
                except OSError:
                    pass
                return
            time.sleep(0.05)

    t = threading.Thread(target=matar_quando_aparecer, daemon=True)
    t.start()
    p = supervisor.executar(pol.comando(), cwd=cenario.tmp, env=pol.ambiente(),
                            prazo=20.0, confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO)
    t.join(timeout=20)
    pids = cenario.pids_marcados("cria", "pai")
    _exige_que_existiram(pids, 2)
    assert _todos_mortos(pids) == [], (
        "ORPHAN_PROCESS: matar o principal por fora deixou descendentes vivos")
    assert p.returncode != 0 or p.residuais_mortos >= 1


# ═════════════ 16 — exceção DENTRO do supervisor, depois do spawn ════════════

def test_a56_16_excecao_do_supervisor_limpa_processo_e_disco(cenario,
                                                             monkeypatch,
                                                             tmp_path):
    """Falha no caminho de reaping não pode virar vazamento.

    A pós-condição é a última coisa a rodar; se ELA quebrar, o processo já
    nasceu e o diretório-nonce já existe. Sair por aí sem limpar deixaria
    descendente vivo E lixo em /var/folders a cada incidente.
    """
    def explodir(*a, **k):
        raise RuntimeError("falha injetada no reaping")

    monkeypatch.setattr(supervisor.processos, "exterminar", explodir)

    # TMPDIR PRÓPRIO deste teste. `_nonces_em_disco()` varre um diretório
    # GLOBAL, e com outra atividade NOMOS no host ele contabiliza artefato de
    # vizinho como vazamento daqui — medido duas vezes nesta missão (13
    # diretórios-nonce vivos, criados por dez agentes de medição em paralelo).
    #
    # O escopo é de FUNÇÃO de propósito: trocar `TMPDIR` na sessão inteira foi
    # TENTADO e MEDIDO — 71 falhas, porque o `basetemp` do `tmp_path_factory` já
    # tinha sido escolhido sob o TMPDIR antigo e metade da suíte passa a montar
    # cenário sob uma raiz e comparar contra outra. Ver
    # `tests/test_isolamento_de_worker.py`.
    proprio = tmp_path / "tmpdir-do-teste"
    proprio.mkdir()
    monkeypatch.setenv("TMPDIR", str(proprio))
    monkeypatch.setattr(tempfile, "tempdir", None, raising=False)

    antes = _nonces_em_disco()
    with pytest.raises(RuntimeError, match="falha injetada"):
        cenario.rodar("--sonda-forks", "2", "60", str(cenario.escopo), prazo=2.0)
    pids = cenario.pids_marcados("cria", "pai")
    _exige_que_existiram(pids, 2)
    assert _todos_mortos(pids) == [], "ORPHAN_PROCESS após exceção interna"
    assert _nonces_em_disco() <= antes, (
        "o diretório-nonce vazou: cada incidente deixaria lixo em /var/folders")


# ═══════════════════════════ apoio ══════════════════════════════════════════

def _nonces_em_disco() -> set:
    raiz = Path(os.environ.get("TMPDIR", "/tmp"))
    return {p.name for p in raiz.glob("nomos-exec-*")}


def _restos_do_sandbox() -> list:
    """Processos `sandbox-exec` deste usuário que sobraram desta execução.

    Grosseiro de propósito: qualquer coisa que ainda esteja rodando sob o
    sandbox depois de o supervisor devolver o controle merece ser olhada.
    """
    r = subprocess.run(["/bin/ps", "-Ao", "pid,command"],
                       capture_output=True, text=True)
    return [ln for ln in r.stdout.splitlines()
            if "nomos-sb-" in ln and "grep" not in ln]
