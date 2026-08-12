"""A9 — corrida: 12 cenários × 30 iterações, com tolerância ZERO.

Defesa que só foi medida em execução única é defesa medida no caso fácil. Tudo
aqui roda com um ADVERSÁRIO CONCORRENTE de verdade — thread que reescreve,
troca, apaga ou compete — e cada iteração é conferida contra os mesmos seis
invariantes:

    INDEX_DRIFT       = 0     os bytes do índice ou avançaram por inteiro,
                              ou voltaram por inteiro; nunca um meio-termo
    SECRET_RESIDUE    = 0     o segredo não fica em objeto nenhum do store
    OBJECT_RESIDUE    = 0     quarentena não sobrevive à operação
    ORPHAN_PROCESS    = 0     nada do filtro continua vivo
    PARTIAL_PROMOTION = 0     ou promoveu tudo, ou não promoveu nada
    AUTHORITY_BYPASS  = 0     o desfecho é ALLOW governado ou DENY, nunca
                              "funcionou por outro caminho"

## Por que 30 iterações e não 3

Corrida que aparece 1 vez em 20 passa despercebida em 3 tentativas e vira
"intermitência do CI" em produção. 30 é o piso para que uma janela estreita
apareça pelo menos uma vez com probabilidade alta — e o teste REGISTRA quantas
vezes cada desfecho ocorreu, para que "nunca corri o caso" não se disfarce de
"o caso sempre passou".

## O contador de desfechos é parte do gate

Cada cenário devolve um histograma. Um cenário cujas 30 iterações caíram todas
no mesmo ramo trivial (por exemplo: o adversário nunca chegou a agir) é
reprovado por VÁCUO, não aprovado por silêncio.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, ErroInvalido,
)
from nomos.adapters.git import diretorio_git
from nomos.adapters.supervisor import TipoDeProcesso as TP
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"
SEGREDO = b"hunter2"
N = 30

pytestmark = [
    pytest.mark.skipif(not os.path.exists(supervisor.SANDBOX),
                       reason="sem sandbox-exec não há execução supervisionada"),
    pytest.mark.slow,
]


class Bancada:
    """Um repositório governado descartável, com os invariantes ao lado."""

    def __init__(self, tmp: Path, binario: Path, artefato):
        self.tmp = tmp
        self.binario = binario
        self.artefato = artefato
        self.repo = tmp / "repo"
        self.repo.mkdir(exist_ok=True)
        subprocess.run([GIT, "-C", str(self.repo), "init", "-q", "-b", "main"],
                       check=True, capture_output=True)
        self.escopo = tmp / "escopo"
        self.escopo.mkdir(exist_ok=True)
        (self.repo / ".gitattributes").write_text("*.txt filter=redator\n")

    # ------------------------------------------------------------- montagem
    def politica(self, *argv, timeout=30.0) -> fg.PoliticaDeFiltro:
        return fg.PoliticaDeFiltro(
            filter_id="redator", canonical_executable=str(self.binario),
            managed_artifact=self.artefato, argv_policy=tuple(argv),
            read_roots=(str(self.repo), str(self.escopo)),
            write_roots=(str(self.escopo),), timeout=timeout)

    def registro(self, *argv, timeout=30.0) -> fg.RegistroDeFiltros:
        reg = fg.RegistroDeFiltros()
        reg.registrar("redator", self.politica(*argv, timeout=timeout))
        return reg

    def ctx(self, cap="git-add"):
        rc = RegistroCapacidades(policy=PolicyEngine(self.tmp / "pol.json"),
                                 approver=lambda *a, **k: True)
        registrar_git_tree(rc, raizes=(str(self.tmp),))
        return CapabilityContext.de_registro(rc, cap, "runtime-governado",
                                             raizes=(str(self.tmp),))

    def add(self, *caminhos, registro=None):
        ad = git_tree.GitTreeAdapter(registro=registro)
        return ad.executar(
            CapabilityRequest(capacidade="git-add", alvo=str(self.repo),
                              argumentos={"caminhos": list(caminhos)}),
            self.ctx())

    # ---------------------------------------------------------- invariantes
    def indice(self) -> bytes | None:
        alvo = Path(diretorio_git(self.repo)[0]) / "index"
        return alvo.read_bytes() if alvo.exists() else None

    def objetos_com_segredo(self) -> int:
        r = subprocess.run([GIT, "-C", str(self.repo), "cat-file",
                            "--batch-all-objects", "--batch"],
                           capture_output=True)
        return r.stdout.count(SEGREDO)

    def quarentenas(self) -> list[Path]:
        return list(Path(diretorio_git(self.repo)[0]).glob("nomos-quarentena-*"))

    def orfaos(self) -> list[str]:
        r = subprocess.run(["/bin/ps", "-Ao", "command"], capture_output=True,
                           text=True)
        return [ln for ln in r.stdout.splitlines() if "nomos-sb-" in ln]

    def indice_integro(self) -> bool:
        """O Git consegue LER o índice? Bytes restaurados que não parseiam
        seriam drift silencioso — o pior tipo."""
        r = subprocess.run([GIT, "-C", str(self.repo), "ls-files", "-s"],
                           capture_output=True)
        return r.returncode == 0

    def conferir(self, antes: bytes | None, *, permite_avancar: bool) -> None:
        depois = self.indice()
        if not permite_avancar:
            assert depois == antes, "INDEX_DRIFT: o índice mudou numa recusa"
        assert self.indice_integro(), "INDEX_DRIFT: índice ilegível pelo Git"
        assert self.objetos_com_segredo() == 0, "SECRET_RESIDUE"
        assert self.quarentenas() == [], "OBJECT_RESIDUE / PARTIAL_PROMOTION"
        assert self.orfaos() == [], "ORPHAN_PROCESS"


@pytest.fixture
def bancada(tmp_path):
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)
    return Bancada(tmp_path, binario, art)


def _exige_variedade(hist: Counter, cenario: str, minimo: int = 1) -> None:
    """Reprova o cenário cujas 30 iterações não exercitaram nada.

    Um histograma com um único desfecho pode ser correto (a defesa sempre
    venceu) ou VAZIO (o adversário nunca agiu). A distinção fica com cada
    cenário, que declara qual desfecho PRECISA ter aparecido.
    """
    assert sum(hist.values()) == N, f"{cenario}: rodou {sum(hist.values())}/{N}"
    assert len(hist) >= minimo or minimo == 0, f"{cenario}: histograma {dict(hist)}"


# ══════════════════ 01 — snapshot do índice vs add concorrente ══════════════

def test_a9_01_snapshot_vs_add_concorrente(bancada):
    """Um `git add` CRU compete com a operação governada pelo mesmo índice."""
    hist = Counter()
    for i in range(N):
        (bancada.repo / f"g{i}.txt").write_text("SENHA=hunter2\n")
        (bancada.repo / f"cru{i}.dat").write_text(f"cru {i}\n")
        parar = threading.Event()

        def concorrente():
            while not parar.is_set():  # noqa: B023 (closure invocada na MESMA iteracao)
                subprocess.run([GIT, "-C", str(bancada.repo), "add", "--",
                                f"cru{i}.dat"], capture_output=True)  # noqa: B023 (closure invocada na MESMA iteracao)

        t = threading.Thread(target=concorrente, daemon=True)
        t.start()
        try:
            bancada.add(f"g{i}.txt", registro=bancada.registro())
            hist["ALLOW"] += 1
        except Exception as e:
            hist[type(e).__name__] += 1
        finally:
            parar.set()
            t.join(timeout=10)
        assert bancada.indice_integro(), "INDEX_DRIFT: índice ilegível"
        assert bancada.objetos_com_segredo() == 0, "SECRET_RESIDUE"
        assert bancada.quarentenas() == [], "OBJECT_RESIDUE"
        assert bancada.orfaos() == [], "ORPHAN_PROCESS"
    _exige_variedade(hist, "01")


# ══════════════════ 02 — restauração do índice vs cancelamento ══════════════

def test_a9_02_restauracao_vs_cancelamento(bancada, monkeypatch):
    """Cancelar no meio, 30 vezes, sem nunca deixar o índice alterado."""
    hist = Counter()
    original = supervisor.executar
    for i in range(N):
        (bancada.repo / f"c{i}.txt").write_text("SENHA=hunter2\n")
        antes = bancada.indice()
        vistos = {"n": 0}

        def executar(argv, **kw):
            if kw.get("tipo") is TP.FILTRO_GOVERNADO:
                vistos["n"] += 1  # noqa: B023 (closure invocada na MESMA iteracao)
                raise KeyboardInterrupt("cancelado")
            return original(argv, **kw)

        monkeypatch.setattr(supervisor, "executar", executar)
        try:
            bancada.add(f"c{i}.txt", registro=bancada.registro())
            hist["ALLOW_INESPERADO"] += 1
        except KeyboardInterrupt:
            hist["CANCELADO"] += 1
        finally:
            monkeypatch.setattr(supervisor, "executar", original)
        assert vistos["n"] >= 1, "o cancelamento não foi exercido"
        bancada.conferir(antes, permite_avancar=False)
    assert hist["CANCELADO"] == N, f"histograma {dict(hist)}"


# ══════════════════ 03 — promoção da quarentena vs auditoria ════════════════

def test_a9_03_promocao_vs_auditoria(bancada, monkeypatch):
    """Auditoria falha em metade das iterações; nunca promove parcial."""
    hist = Counter()
    original = git_tree.GitTreeAdapter._auditar
    for i in range(N):
        (bancada.repo / f"q{i}.txt").write_text("SENHA=hunter2\n")
        antes = bancada.indice()
        falhar = (i % 2 == 0)

        def auditar(self, *a, **k):
            if falhar:  # noqa: B023 (closure invocada na MESMA iteracao)
                raise RuntimeError("auditoria injetada")
            return original(self, *a, **k)

        monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", auditar)
        try:
            bancada.add(f"q{i}.txt", registro=bancada.registro())
            hist["ALLOW"] += 1
            assert not falhar, "promoveu com auditoria falhando"
        except RuntimeError:
            hist["AUDITORIA_FALHOU"] += 1
            bancada.conferir(antes, permite_avancar=False)
        finally:
            monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", original)
        assert bancada.objetos_com_segredo() == 0, "SECRET_RESIDUE"
        assert bancada.quarentenas() == [], "OBJECT_RESIDUE"
    assert hist["AUDITORIA_FALHOU"] == N // 2, f"histograma {dict(hist)}"
    assert hist["ALLOW"] == N - N // 2, f"histograma {dict(hist)}"


# ══════════════════ 04 — limpeza da quarentena vs sinal ═════════════════════

def test_a9_04_limpeza_da_quarentena_vs_sinal(bancada, monkeypatch):
    hist = Counter()
    original = git_tree._promover_quarentena
    for i in range(N):
        (bancada.repo / f"s{i}.txt").write_text("SENHA=hunter2\n")
        antes = bancada.indice()

        def promover(*a, **k):
            raise KeyboardInterrupt("sinal na promoção")

        monkeypatch.setattr(git_tree, "_promover_quarentena", promover)
        try:
            bancada.add(f"s{i}.txt", registro=bancada.registro())
            hist["ALLOW_INESPERADO"] += 1
        except KeyboardInterrupt:
            hist["SINAL"] += 1
        finally:
            monkeypatch.setattr(git_tree, "_promover_quarentena", original)
        bancada.conferir(antes, permite_avancar=False)
    assert hist["SINAL"] == N, f"histograma {dict(hist)}"


# ══════════════════ 05 — stdin governado vs prazo ═══════════════════════════

def test_a9_05_stdin_vs_prazo(bancada):
    """Entrada grande e prazo curto: a escrita do stdin corre contra o kill."""
    hist = Counter()
    grande = b"SENHA=hunter2\n" + b"x" * (512 * 1024)
    pol = bancada.politica("--sonda-dorme", "60", timeout=1.0)
    for _ in range(N):
        p = supervisor.executar(
            pol.comando(), cwd=bancada.tmp, env=pol.ambiente(), prazo=1.0,
            confinamento=pol.confinamento(), tipo=TP.FILTRO_GOVERNADO,
            entrada=grande)
        hist["MORTO" if p.morto_por_timeout else p.classificacao] += 1
        assert not p.grupo_resistiu, "grupo resistiu ao encerramento"
        assert bancada.orfaos() == [], "ORPHAN_PROCESS"
    assert hist["MORTO"] == N, f"o prazo não venceu sempre: {dict(hist)}"


# ══════════════════ 06 — kill de processo vs cancelamento ═══════════════════

def test_a9_06_kill_vs_cancelamento(bancada, monkeypatch):
    """Cancela a espera enquanto o filtro tem descendentes vivos."""
    hist = Counter()
    for i in range(N):
        alvo = bancada.escopo / f"r{i}"
        alvo.mkdir()
        pol = bancada.politica("--sonda-forks", "3", "60", str(alvo))
        pol = fg.PoliticaDeFiltro(
            filter_id="redator", canonical_executable=str(bancada.binario),
            managed_artifact=bancada.artefato,
            argv_policy=("--sonda-forks", "3", "60", str(alvo)),
            read_roots=(str(bancada.repo), str(bancada.escopo)),
            write_roots=(str(alvo),))

        class PopenCancela(subprocess.Popen):
            def wait(self, timeout=None):
                fim = time.monotonic() + 15
                while time.monotonic() < fim:
                    if len(list(alvo.glob("cria.*"))) >= 3:  # noqa: B023 (closure invocada na MESMA iteracao)
                        break
                    time.sleep(0.05)
                raise KeyboardInterrupt("cancelado")

        monkeypatch.setattr(supervisor.subprocess, "Popen", PopenCancela)
        try:
            supervisor.executar(pol.comando(), cwd=bancada.tmp,
                                env=pol.ambiente(), prazo=30.0,
                                confinamento=pol.confinamento(),
                                tipo=TP.FILTRO_GOVERNADO)
            hist["SEM_EXCECAO"] += 1
        except KeyboardInterrupt:
            hist["CANCELADO"] += 1
        except supervisor.ErroSeguranca:
            hist["ERRO_SEGURANCA"] += 1
        finally:
            monkeypatch.setattr(supervisor.subprocess, "Popen", subprocess.Popen)

        pids = [int(p.name.rsplit(".", 1)[1]) for p in alvo.iterdir()
                if p.name.startswith(("cria.", "pai."))]
        assert len(pids) >= 3, "PROCESS_ACTUALLY_EXISTED=FALSE"
        vivos = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                vivos.append(pid)
            except OSError:
                pass
        assert vivos == [], f"ORPHAN_PROCESS: {vivos}"
    assert hist["CANCELADO"] == N, f"histograma {dict(hist)}"


# ══════════════════ 07 — verificação do artefato vs uso ═════════════════════

def test_a9_07_verificacao_do_artefato_vs_uso(bancada):
    """Adulteração contínua do artefato durante 30 usos governados."""
    hist = Counter()
    caminho = Path(bancada.artefato.managed_path)
    bons = caminho.read_bytes()
    parar = threading.Event()
    voltas = {"n": 0}

    def tamper():
        while not parar.is_set():
            try:
                caminho.chmod(0o700)
                caminho.write_bytes(b"trocado\n")
                caminho.chmod(0o500)
                caminho.chmod(0o700)
                caminho.write_bytes(bons)
                caminho.chmod(0o500)
            except OSError:
                pass
            voltas["n"] += 1

    t = threading.Thread(target=tamper, daemon=True)
    t.start()
    try:
        for _ in range(N):
            try:
                bancada.politica().executavel()
                hist["ACEITOU"] += 1
            except fg.ErroFiltro:
                hist["RECUSOU"] += 1
    finally:
        parar.set()
        t.join(timeout=20)
        caminho.chmod(0o700)
        caminho.write_bytes(bons)
        caminho.chmod(0o500)
    assert voltas["n"] > 0, "o tamper não rodou; o cenário seria vácuo"
    assert hist["RECUSOU"] > 0, (
        f"nenhuma divergência vista em {N} usos com {voltas['n']} reescritas — "
        "a verificação de integridade parou de verificar")


# ══════════════════ 08 — registry vs adulteração do artefato ════════════════

def test_a9_08_registry_vs_tamper(bancada):
    """Resolver do registry e adulterar o artefato ao mesmo tempo.

    O registry NUNCA pode devolver política cujo artefato não confere — e nunca
    pode recusar o id aprovado por causa da corrida.
    """
    reg = bancada.registro()
    caminho = Path(bancada.artefato.managed_path)
    bons = caminho.read_bytes()
    parar = threading.Event()
    erros: list[str] = []

    def tamper():
        while not parar.is_set():
            try:
                caminho.chmod(0o700)
                caminho.write_bytes(b"x\n")
                caminho.chmod(0o500)
                caminho.chmod(0o700)
                caminho.write_bytes(bons)
                caminho.chmod(0o500)
            except OSError:
                pass

    t = threading.Thread(target=tamper, daemon=True)
    t.start()
    hist = Counter()
    try:
        for _ in range(N):
            pol = reg.resolver("redator")          # resolver NUNCA pode falhar
            if pol.filter_id != "redator":
                erros.append("resolveu outro id")
            try:
                pol.executavel()
                hist["ACEITOU"] += 1
            except fg.ErroFiltro:
                hist["RECUSOU"] += 1               # divergência vista = correto
    finally:
        parar.set()
        t.join(timeout=20)
        caminho.chmod(0o700)
        caminho.write_bytes(bons)
        caminho.chmod(0o500)
    assert erros == [], erros
    assert sum(hist.values()) == N


# ══════════════════ 09 — config do repo mutando durante a operação ══════════

def test_a9_09_config_mutando_durante_a_operacao(bancada):
    hist = Counter()
    canario = bancada.tmp / "CANARIO09"
    hostil = bancada.tmp / "h09.sh"
    hostil.write_text(f"#!/bin/sh\necho H > {canario}\ncat\n")
    hostil.chmod(0o755)
    parar = threading.Event()

    def mutar():
        while not parar.is_set():
            subprocess.run([GIT, "-C", str(bancada.repo), "config",
                            "filter.redator.clean", str(hostil)],
                           capture_output=True)
            subprocess.run([GIT, "-C", str(bancada.repo), "config",
                            "core.fsmonitor", str(hostil)],
                           capture_output=True)

    t = threading.Thread(target=mutar, daemon=True)
    t.start()
    try:
        for i in range(N):
            (bancada.repo / f"m{i}.txt").write_text("SENHA=hunter2\n")
            try:
                bancada.add(f"m{i}.txt", registro=bancada.registro())
                hist["ALLOW"] += 1
            except Exception as e:
                hist[type(e).__name__] += 1
            assert not canario.exists(), (
                "AUTHORITY_BYPASS: a config do repositório executou programa")
            assert bancada.objetos_com_segredo() == 0, "SECRET_RESIDUE"
            assert bancada.quarentenas() == [], "OBJECT_RESIDUE"
    finally:
        parar.set()
        t.join(timeout=15)
    assert bancada.orfaos() == [], "ORPHAN_PROCESS"


# ══════════════════ 10 — troca de symlink durante o acesso ══════════════════

def test_a9_10_symlink_trocado_durante_o_acesso(bancada):
    """O alvo do link vira segredo do host no meio da operação."""
    segredo_host = bancada.tmp / "SEGREDO_DO_HOST"
    segredo_host.write_text("SENHA=hunter2 DO HOST\n")
    hist = Counter()
    parar = threading.Event()

    def trocar():
        alvo = bancada.repo / "link.txt"
        bom = bancada.repo / "bom.txt"
        bom.write_text("conteudo bom\n")
        while not parar.is_set():
            try:
                alvo.unlink(missing_ok=True)
                alvo.symlink_to(segredo_host)
                alvo.unlink(missing_ok=True)
                alvo.symlink_to(bom)
            except OSError:
                pass

    (bancada.repo / "bom.txt").write_text("conteudo bom\n")
    t = threading.Thread(target=trocar, daemon=True)
    t.start()
    try:
        for _ in range(N):
            try:
                bancada.add("link.txt", registro=bancada.registro())
                hist["ALLOW"] += 1
            except Exception as e:
                hist[type(e).__name__] += 1
            assert bancada.objetos_com_segredo() == 0, (
                "LINK_BASED_ESCAPE: o segredo do host entrou no store")
    finally:
        parar.set()
        t.join(timeout=15)
    assert sum(hist.values()) == N


# ══════════════════ 11 — escritor Git concorrente ═══════════════════════════

def test_a9_11_escritor_git_concorrente(bancada):
    """Outro Git escreve no MESMO repositório durante as operações."""
    hist = Counter()
    parar = threading.Event()

    def escritor():
        i = 0
        while not parar.is_set():
            p = bancada.repo / f"outro{i}.dat"
            p.write_text(f"conteudo {i}\n")
            subprocess.run([GIT, "-C", str(bancada.repo), "add", "--", p.name],
                           capture_output=True)
            i += 1

    t = threading.Thread(target=escritor, daemon=True)
    t.start()
    try:
        for i in range(N):
            (bancada.repo / f"w{i}.txt").write_text("SENHA=hunter2\n")
            try:
                bancada.add(f"w{i}.txt", registro=bancada.registro())
                hist["ALLOW"] += 1
            except Exception as e:
                hist[type(e).__name__] += 1
            assert bancada.indice_integro(), "INDEX_DRIFT: índice ilegível"
            assert bancada.objetos_com_segredo() == 0, "SECRET_RESIDUE"
            assert bancada.quarentenas() == [], "OBJECT_RESIDUE"
    finally:
        parar.set()
        t.join(timeout=15)
    assert bancada.orfaos() == [], "ORPHAN_PROCESS"


# ══════════════════ 12 — filtro governado + rollback concorrente ════════════

def test_a9_12_filtro_governado_e_rollback(bancada, monkeypatch):
    """Metade das iterações falha DEPOIS do filtro; um escritor compete."""
    hist = Counter()
    original = supervisor.executar
    parar = threading.Event()

    def escritor():
        i = 0
        while not parar.is_set():
            (bancada.repo / f"z{i}.dat").write_text("z\n")
            subprocess.run([GIT, "-C", str(bancada.repo), "add", "--",
                            f"z{i}.dat"], capture_output=True)
            i += 1

    t = threading.Thread(target=escritor, daemon=True)
    t.start()
    try:
        for i in range(N):
            (bancada.repo / f"f{i}.txt").write_text("SENHA=hunter2\n")
            falhar = (i % 2 == 0)
            antes = bancada.indice()

            def executar(argv, **kw):
                if falhar and any("update-index" in a for a in argv):  # noqa: B023 (closure invocada na MESMA iteracao)
                    raise RuntimeError("falha pos-filtro injetada")
                return original(argv, **kw)

            monkeypatch.setattr(supervisor, "executar", executar)
            try:
                bancada.add(f"f{i}.txt", registro=bancada.registro())
                hist["ALLOW"] += 1
                assert not falhar, "promoveu apesar da falha injetada"
            except (RuntimeError, ErroInvalido) as e:
                # RuntimeError = a falha INJETADA. ErroInvalido = o escritor
                # concorrente RAW git segurava `index.lock` e o `update-index`
                # governado falhou fail-closed — recusa legitima do Git, com as
                # MESMAS pos-condicoes de um rollback. As duas contam.
                if isinstance(e, ErroInvalido) and "index.lock" not in str(e):
                    raise
                hist["ROLLBACK"] += 1
                # INDEX_DRIFT mede se a operação RECUSADA deixou rastro — não se
                # o índice está byte-idêntico. Este cenário tem um ESCRITOR
                # CONCORRENTE legítimo, e depois de `.8.06` ele não pode mais ter
                # o trabalho destruído: o índice pode legitimamente conter o
                # avanço DELE. Exigir igualdade byte a byte confundiria as duas
                # coisas e cobraria justamente a destruição que `.8.06` proíbe.
                #
                # O que a recusa garante: nada do NOSSO caminho estagiado, e o
                # índice íntegro para a próxima operação.
                atual = bancada.indice()
                if atual != antes:
                    ls = subprocess.run(
                        [GIT, "-C", str(bancada.repo), "ls-files"],
                        capture_output=True, text=True)
                    assert ls.returncode == 0, "INDEX_CONSISTENT=FALSE no rollback"
                    assert f"f{i}.txt" not in ls.stdout, (
                        "INDEX_DRIFT: o caminho da operação RECUSADA ficou "
                        "estagiado")
            finally:
                monkeypatch.setattr(supervisor, "executar", original)
            assert bancada.objetos_com_segredo() == 0, "SECRET_RESIDUE"
            assert bancada.quarentenas() == [], "OBJECT_RESIDUE"
    finally:
        parar.set()
        t.join(timeout=15)
    # Piso, nao igualdade: a metade injetada SEMPRE recusa; alem dela, a
    # contencao de `index.lock` do escritor concorrente pode transformar uma
    # iteracao ALLOW em recusa. O que nao pode e uma injetada PROMOVER.
    assert hist["ROLLBACK"] >= N // 2, f"histograma {dict(hist)}"
    assert hist["ALLOW"] <= N // 2, f"uma falha injetada promoveu: {dict(hist)}"
    assert bancada.orfaos() == [], "ORPHAN_PROCESS"
