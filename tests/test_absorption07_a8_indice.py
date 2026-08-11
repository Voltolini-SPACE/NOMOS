"""A2-REPO.8 — o ÍNDICE não é escolhido pelo repositório.

Dois vetores medidos, ambos no processo do SUPERVISOR — fora do sandbox, onde
todo o confinamento de A5.5 é irrelevante porque quem age é o pai.

    .git/index como SYMLINK    o instantâneo LÊ o destino escolhido pelo repo
    rollback sem index.lock    apaga `git add` concorrente que saiu com rc=0

## Por que "a operação falhou depois" não salvava o primeiro

Confidencialidade não precisa de escrita. Com
`.git/index -> /fora/das/raízes/chave.pem`, o `read_bytes()` do instantâneo
trazia a chave privada do host para dentro do processo do NOMOS; o `add` falhava
adiante, e o vazamento já tinha acontecido. Junto vinha uma mutação silenciosa:
`_restaurar_indice` faz `os.replace` sobre o caminho, então o LINK do
repositório era substituído por arquivo regular — num repositório cuja operação
foi RECUSADA.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


def _git(*args):
    return subprocess.run([GIT, *args], capture_output=True, text=True)


@pytest.fixture
def campo(tmp_path):
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    repo = raiz / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", str(repo))
    _git("-C", str(repo), "config", "user.email", "a@b.c")
    _git("-C", str(repo), "config", "user.name", "T")
    (repo / "a.txt").write_text("conteudo\n")

    class Campo:
        def __init__(self):
            self.raiz, self.fora, self.repo, self.tmp = raiz, fora, repo, tmp_path

        def add(self, *caminhos):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            ctx = CapabilityContext.de_registro(rc, "git-add",
                                                "runtime-governado",
                                                raizes=(str(raiz),))
            return git_tree.GitTreeAdapter().executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}), ctx)

    return Campo()


def test_a8_00_CONTROLE_add_normal_continua_funcionando(campo):
    """Sem isto, os testes de recusa passariam com `git add` morto."""
    r = campo.add("a.txt")
    assert r.efeito_aplicado
    assert "a.txt" in _git("-C", str(campo.repo), "ls-files").stdout


def test_a8_01_index_como_SYMLINK_nao_e_lido_pelo_supervisor(campo):
    """Confidencialidade não precisa de escrita para ser violada."""
    vitima = campo.fora / "chave_do_host.pem"
    vitima.write_text("-----BEGIN PRIVATE KEY-----\nSEGREDO\n")
    idx = campo.repo / ".git" / "index"
    if idx.exists():
        idx.unlink()
    os.symlink(str(vitima), str(idx))
    antes = vitima.read_text()

    with pytest.raises(supervisor.ErroSeguranca, match="symlink"):
        campo.add("a.txt")

    assert vitima.read_text() == antes, "a vítima foi sobrescrita"
    assert idx.is_symlink(), (
        "o rollback trocou o LINK do repositório por arquivo regular numa "
        "operação que foi RECUSADA — mutação silenciosa")


def test_a8_02_index_FIFO_nao_pendura_o_supervisor(campo):
    """Mesmo ponto do FIFO no caminho governado: o `read` roda no pai."""
    idx = campo.repo / ".git" / "index"
    if idx.exists():
        idx.unlink()
    os.mkfifo(idx)
    import signal

    def estourou(*_):
        raise AssertionError("PENDUROU: o instantâneo bloqueou no FIFO")

    anterior = signal.signal(signal.SIGALRM, estourou)
    signal.alarm(20)
    try:
        with pytest.raises(supervisor.ErroSeguranca, match="arquivo regular"):
            campo.add("a.txt")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, anterior)


def test_a8_03_rollback_toma_index_lock(campo):
    """`index.lock` é o único protocolo que um `git add` concorrente respeita.

    Estrutural porque a corrida é probabilística: sem o lock, o rollback
    sobrescrevia o índice de um `git add` concorrente que já tinha saído com
    rc=0 — trabalho aceito e depois APAGADO, sem sinal para ninguém.
    """
    fonte = Path(git_tree.__file__).read_text("utf-8")
    corpo = fonte.split("def _restaurar_indice", 1)[1].split("\ndef ", 1)[0]
    assert "index.lock" in corpo, (
        "o rollback escreve o índice por fora da serialização do Git")


def test_a8_04_rollback_nao_pendura_se_o_lock_esta_preso(campo):
    """O lock é BEST-EFFORT, e tem de ser.

    Um rollback que espera para sempre é PIOR que um rollback sem lock: deixa o
    índice sujo, com o conteúdo que a operação recusou já estagiado.
    """
    lock = campo.repo / ".git" / "index.lock"
    lock.write_text("preso por outro processo\n")
    inicio = time.monotonic()
    try:
        inst = git_tree._instantaneo_do_indice(campo.repo)
        git_tree._restaurar_indice(inst)
    finally:
        lock.unlink(missing_ok=True)
    assert time.monotonic() - inicio < 10, "o rollback pendurou esperando o lock"


def test_a8_05_add_concorrente_com_rc0_nao_e_apagado_pelo_rollback(campo):
    """A propriedade que o lock existe para garantir, medida de ponta a ponta."""
    _git("-C", str(campo.repo), "add", "a.txt")
    (campo.repo / "concorrente.txt").write_text("trabalho de outro\n")

    resultado = {}

    def concorrente():
        time.sleep(0.05)
        r = _git("-C", str(campo.repo), "add", "concorrente.txt")
        resultado["rc"] = r.returncode

    (campo.repo / "b.txt").write_text("x\n")
    t = threading.Thread(target=concorrente, daemon=True)
    t.start()
    # A operação pode falhar por causa da corrida; isso não é o critério.
    # O critério é o trabalho do concorrente sobreviver.
    with contextlib.suppress(Exception):
        campo.add("b.txt")
    t.join(timeout=10)

    if resultado.get("rc") == 0:
        assert "concorrente.txt" in _git("-C", str(campo.repo),
                                         "ls-files").stdout, (
            "o rollback apagou um `git add` concorrente que saiu com rc=0")
