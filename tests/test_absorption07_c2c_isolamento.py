"""C2c — duas execuções simultâneas não se exterminam.

`ZERO resíduo` tem uma leitura preguiçosa e perigosa: matar mais do que se deve
também zera o resíduo. Um mecanismo de identificação amplo demais passaria em
toda a bateria anterior — as operações terminam, nada sobra — e estaria
destruindo trabalho legítimo de outra execução no mesmo host.

O sintoma é indistinguível de sucesso. Por isso a pós-condição precisa ser
declarada nos dois sentidos:

    cleanup de A   →  PODE matar descendente de A
                   →  NÃO PODE matar descendente de B

O caso adversarial decisivo é A terminando enquanto B mantém, de propósito, um
descendente vivo dentro da própria sandbox.

Os testes daqui montam o perfil e lançam o processo à mão, sem passar por
`supervisor.executar()`. É deliberado: `executar()` extermina ao final, então o
descendente de B morreria pelo cleanup do PRÓPRIO B e o teste mediria outra
coisa.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from nomos.adapters import processos, supervisor

pytestmark = pytest.mark.skipif(
    not (Path(supervisor.SANDBOX).exists() and processos.DISPONIVEL),
    reason="sandbox-exec / libproc ausentes (fora do macOS)")

_DESTACADO = '''\
import os, sys, time
marca = sys.argv[1]
if os.fork(): os._exit(0)
os.setsid()                      # sai do process group: só a marca o alcança
if os.fork(): os._exit(0)
d = os.open(os.devnull, os.O_RDWR)
os.dup2(d, 0); os.dup2(d, 1); os.dup2(d, 2)
while True:
    with open(marca, "w") as fh:
        fh.write(str(os.getpid()))
    time.sleep(0.05)
'''


class Execucao:
    """Uma execução com marca própria, e um descendente destacado vivo."""

    def __init__(self, raiz: Path, nome: str):
        self.nome = nome
        self.area = raiz / nome
        self.area.mkdir(parents=True)
        self.marca = supervisor.criar_marca()
        self.marcador = self.area / "vivo.mark"
        self.pid: int | None = None

    def lancar(self) -> int:
        helper = self.area / "d.py"
        helper.write_text(_DESTACADO)
        conf = supervisor.Confinamento(
            escrita=(supervisor.existente(self.area),), marca=self.marca)
        fd, sb = tempfile.mkstemp(suffix=".sb")
        with os.fdopen(fd, "w") as fh:
            fh.write(supervisor.perfil(conf))
        try:
            subprocess.run(
                [supervisor.SANDBOX, "-f", sb, "/usr/bin/python3",
                 str(helper), str(self.marcador)],
                capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
            limite = time.monotonic() + 10
            conteudo = ""
            while time.monotonic() < limite:
                # Esperar CONTEÚDO, não existência: o marcador aparece antes do
                # write terminar e `int('')` explodia sob carga concorrente
                # (TOCTOU do arnês, visto com duas suítes em paralelo).
                if self.marcador.exists():
                    conteudo = self.marcador.read_text().strip()
                    if conteudo:
                        break
                time.sleep(0.05)
        finally:
            os.unlink(sb)
        assert conteudo, f"{self.nome} não chegou ao regime permanente"
        self.pid = int(conteudo)
        return self.pid

    def vivo(self, espera: float = 0.6) -> bool:
        """Reaparece o marcador depois de apagado? Só isso prova vida."""
        self.marcador.unlink(missing_ok=True)
        time.sleep(espera)
        return self.marcador.exists()

    def encerrar(self) -> None:
        if self.pid:
            with contextlib.suppress(OSError):
                os.kill(self.pid, signal.SIGKILL)
        shutil.rmtree(self.marca.execdir, ignore_errors=True)


@pytest.fixture()
def a_e_b(tmp_path):
    a, b = Execucao(tmp_path, "A"), Execucao(tmp_path, "B")
    a.marca.conferir()
    b.marca.conferir()
    try:
        yield a, b
    finally:
        a.encerrar()
        b.encerrar()


def test_marcas_de_execucoes_distintas_nao_colidem(a_e_b):
    a, b = a_e_b
    assert a.marca.nonce != b.marca.nonce
    assert a.marca.execdir != b.marca.execdir
    assert not Path(b.marca.execdir).is_relative_to(a.marca.execdir)


def test_A_nao_classifica_descendente_de_B_como_residual(a_e_b):
    """CROSS_EXECUTION_CLASSIFICATION=0 — antes de matar, nem sequer selecionar."""
    a, b = a_e_b
    a.lancar()
    b.lancar()
    assert a.pid != b.pid

    de_a = {d[0] for d in processos.residuais(a.marca)}
    de_b = {d[0] for d in processos.residuais(b.marca)}
    assert a.pid in de_a, "A não reconheceu o próprio descendente"
    assert b.pid in de_b, "B não reconheceu o próprio descendente"
    assert b.pid not in de_a, "A classificou o descendente de B como residual seu"
    assert a.pid not in de_b, "B classificou o descendente de A como residual seu"
    assert de_a.isdisjoint(de_b), (
        f"conjuntos de identidade se intersectam: {de_a & de_b}")


def test_cleanup_de_A_nao_mata_descendente_de_B(a_e_b):
    """O caso adversarial decisivo.

    Se a identificação fosse ampla, este teste passaria despercebido como
    sucesso: as duas operações terminam e nada sobra. O que denuncia é B
    continuar vivo.
    """
    a, b = a_e_b
    a.lancar()
    b.lancar()
    assert a.vivo() and b.vivo(), "os dois precisam estar vivos ANTES do cleanup"

    mortos, sobrando = processos.exterminar(a.marca)
    assert sobrando == [], f"A não conseguiu limpar o próprio resíduo: {sobrando}"
    assert a.pid in {d[0] for d in mortos}

    assert not a.vivo(), "descendente de A sobreviveu ao próprio cleanup"
    assert b.vivo(), (
        "CROSS_EXECUTION_KILL: o cleanup de A matou o descendente de B — a "
        "identificação está ampla demais, e o sintoma seria indistinguível de "
        "sucesso")


def test_cleanup_de_B_depois_limpa_apenas_B(a_e_b):
    """A simetria importa: não basta A ser educado com B."""
    a, b = a_e_b
    a.lancar()
    b.lancar()
    processos.exterminar(b.marca)
    assert not b.vivo()
    assert a.vivo(), "CROSS_EXECUTION_KILL na direção B→A"


def test_marca_removida_do_disco_nao_vira_licenca_para_matar(a_e_b):
    """Execução encerrada não pode virar coringa.

    Com o diretório-nonce apagado, os caminhos da marca deixam de existir — e o
    `sandbox_check` com caminho ausente devolve resposta errada SEM erro, o que
    faria processo alheio casar. `conferir()` é o que impede isso, e aqui ele
    precisa recusar em vez de deixar varrer.
    """
    a, b = a_e_b
    b.lancar()
    shutil.rmtree(a.marca.execdir, ignore_errors=True)
    with pytest.raises(processos.ErroProcessos, match="não existe"):
        a.marca.conferir()
    assert b.vivo(), "B morreu por causa de uma marca de A já removida"
