"""A5.9 — os ataques COMBINADOS, não os controles isolados.

As baterias anteriores mediram cada fronteira sozinha: o registry decide (A5.2),
o artefato é a identidade (A5.3), o argv é da política (A5.4), o confinamento
limita (A5.5), o ciclo de vida encerra (A5.6), a transação desfaz (A5.8). Cada
uma passou.

Sistema seguro por peça e inseguro por composição é o padrão, não a exceção: o
atacante não escolhe UMA fronteira, escolhe a costura entre duas. Esta bateria
combina.

## O que muda em relação a A5.5

A5.5 provou que o filtro não alcança rede nem arquivo fora do escopo — com o
filtro VAZIO. Aqui o filtro está SEGURANDO O SEGREDO quando tenta vazar, que é
a única versão do teste que importa: contenção que só foi medida sem carga não
demonstrou nada sobre o caso com carga.

Todo alvo de exfiltração tem CONTROLE POSITIVO: o mesmo binário, a mesma
entrada, sem sandbox, tem de CONSEGUIR. Ausência de vazamento só prova
contenção depois de provado que o vazamento aconteceria.
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.git import diretorio_git
from nomos.adapters.supervisor import TipoDeProcesso as TP
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"
SEGREDO = b"hunter2"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cen(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([GIT, "-C", str(repo), "init", "-q", "-b", "main"],
                   check=True, capture_output=True)
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)
    (repo / "a.txt").write_text("SENHA=hunter2\n")
    (repo / ".gitattributes").write_text("*.txt filter=redator\n")

    class Cen:
        def __init__(self):
            self.repo, self.tmp, self.artefato = repo, tmp_path, art
            self.binario = binario
            self.escopo = tmp_path / "escopo"
            self.escopo.mkdir(exist_ok=True)

        def politica(self, *argv, fid="redator") -> fg.PoliticaDeFiltro:
            return fg.PoliticaDeFiltro(
                filter_id=fid, canonical_executable=str(binario),
                managed_artifact=art, argv_policy=tuple(argv),
                read_roots=(str(repo), str(self.escopo)),
                write_roots=(str(self.escopo),))

        def rodar(self, *argv, entrada=SEGREDO, prazo=20.0):
            pol = self.politica(*argv)
            return supervisor.executar(
                pol.comando(), cwd=self.tmp, env=pol.ambiente(), prazo=prazo,
                confinamento=pol.confinamento(), tipo=TP.FILTRO_GOVERNADO,
                entrada=entrada)

        def solto(self, *argv, entrada=SEGREDO):
            """CONTROLE POSITIVO: o MESMO binário, sem sandbox."""
            return subprocess.run([str(binario), *argv], input=entrada,
                                  capture_output=True)

        def registro(self, *argv) -> fg.RegistroDeFiltros:
            reg = fg.RegistroDeFiltros()
            reg.registrar("redator", self.politica(*argv))
            return reg

        def ctx(self, cap="git-add"):
            rc = RegistroCapacidades(
                policy=PolicyEngine(self.tmp / "pol.json"),
                approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(self.tmp),))
            return CapabilityContext.de_registro(
                rc, cap, "runtime-governado", raizes=(str(self.tmp),))

        def add(self, registro, *caminhos):
            return git_tree.GitTreeAdapter(registro=registro).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(self.repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx())

        def indice(self):
            alvo = Path(diretorio_git(self.repo)[0]) / "index"
            return alvo.read_bytes() if alvo.exists() else None

        def objetos_com_segredo(self) -> int:
            r = subprocess.run(
                [GIT, "-C", str(self.repo), "cat-file",
                 "--batch-all-objects", "--batch"], capture_output=True)
            return r.stdout.count(SEGREDO)

    return Cen()


# ═══════ 01-02 — o segredo NA MÃO do filtro, tentando sair ══════════════════

def test_a59_01_exfil_de_REDE_com_o_segredo_na_entrada(cen):
    """O filtro recebe o segredo por stdin e tenta mandá-lo para um listener.

    O destino é um listener REAL deste host: sem ele, "não conectou" não se
    distingue de "não havia ninguém ouvindo", e o teste mediria a ausência de
    servidor em vez da negação do sandbox.
    """
    import contextlib

    @contextlib.contextmanager
    def escuta():
        """Um listener novo por medição, com o que ele recebeu.

        Um por medição, e não um reaproveitado: a conexão do controle positivo
        já consumiu o `accept`, e reusar o socket faria a segunda medição
        observar o silêncio de um servidor esgotado em vez da negação do
        sandbox — o teste passaria pelo motivo errado.
        """
        recebido: list[bytes] = []
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)

        def aceitar():
            try:
                srv.settimeout(15)
                c, _ = srv.accept()
                recebido.append(c.recv(65536))
                c.close()
            except OSError:
                pass

        t = threading.Thread(target=aceitar, daemon=True)
        t.start()
        try:
            yield srv.getsockname()[1], recebido, t
        finally:
            srv.close()

    # CONTROLE POSITIVO: sem sandbox, o segredo CHEGA ao listener.
    with escuta() as (porta, recebido, t):
        livre = cen.solto("--sonda-exfil-rede", "127.0.0.1", str(porta))
        t.join(timeout=15)
        assert b"ALCANCEI" in livre.stdout, "a sonda de rede não funciona"
        assert recebido and SEGREDO in recebido[0], (
            "o controle positivo não entregou o segredo; o teste seria vácuo")

    # A MESMA tentativa, agora confinada.
    with escuta() as (porta, recebido, t):
        p = cen.rodar("--sonda-exfil-rede", "127.0.0.1", str(porta))
        t.join(timeout=10)
        assert b"NEGADO" in p.stdout, f"EXFIL_REDE alcançou: {p.stdout!r}"
        assert not recebido or SEGREDO not in recebido[0], (
            "NETWORK_EXFIL: o segredo saiu do filtro confinado")


def test_a59_02_exfil_de_ARQUIVO_com_o_segredo_na_entrada(cen):
    """O filtro tenta gravar o segredo FORA do escopo de escrita dele."""
    fora = cen.tmp / "vazou.txt"

    livre = cen.solto("--sonda-exfil-arquivo", str(fora))
    assert b"ALCANCEI" in livre.stdout and fora.exists(), (
        "o controle positivo não gravou; o teste seria vácuo")
    assert SEGREDO in fora.read_bytes()
    fora.unlink()

    p = cen.rodar("--sonda-exfil-arquivo", str(fora))
    assert b"NEGADO" in p.stdout, f"EXFIL_ARQUIVO alcançou: {p.stdout!r}"
    assert not fora.exists(), "FILESYSTEM_ESCAPE: o segredo foi gravado fora"


def test_a59_03_o_escopo_LEGITIMO_continua_gravavel_com_o_segredo(cen):
    """O controle que impede os dois anteriores de serem vácuo por excesso.

    Um sandbox que negasse TUDO passaria em 01 e 02 sem conter nada — estaria
    apenas quebrado. O filtro precisa continuar escrevendo onde a política
    mandou.
    """
    dentro = cen.escopo / "ok.txt"
    p = cen.rodar("--sonda-exfil-arquivo", str(dentro))
    assert b"ALCANCEI" in p.stdout, "o sandbox negou o escopo LEGÍTIMO"
    assert dentro.read_bytes() == SEGREDO


# ═══════ 04-06 — ataque de argv, artefato e config, COM a transação ═════════

def test_a59_04_argv_hostil_na_POLITICA_e_recusado_na_construcao(cen):
    """Quem escolhe argv é a política — mas nem a política pode pedir exec."""
    with pytest.raises(fg.ErroFiltro, match="execução de OUTRO programa"):
        cen.politica("--exec", "/bin/echo")


def test_a59_05_artefato_TROCADO_mais_git_add_nao_move_o_indice(cen):
    """A5.3 + A5.8 juntos: divergência recusa, e a transação não se move."""
    antes = cen.indice()
    reg = cen.registro()
    alvo = Path(cen.artefato.managed_path)
    alvo.chmod(0o700)
    alvo.write_bytes(b"trocado\n")
    alvo.chmod(0o500)

    with pytest.raises(fg.ErroFiltro, match="DIVERGE"):
        cen.add(reg, "a.txt")
    assert cen.indice() == antes
    assert cen.objetos_com_segredo() == 0


def test_a59_06_repo_hostil_pedindo_filtro_governado_nao_troca_o_binario(cen):
    """O repositório declara o `clean` E pede o id aprovado, ao mesmo tempo."""
    canario = cen.tmp / "CANARIO"
    hostil = cen.tmp / "h.sh"
    hostil.write_text(f"#!/bin/sh\necho HOSTIL > {canario}\ncat\n")
    hostil.chmod(0o755)
    subprocess.run([GIT, "-C", str(cen.repo), "config",
                    "filter.redator.clean", str(hostil)],
                   check=True, capture_output=True)

    assert cen.add(cen.registro(), "a.txt").efeito_aplicado
    assert not canario.exists(), "o `clean` do REPOSITÓRIO executou"
    assert cen.objetos_com_segredo() == 0


# ═══════ 07-08 — prazo e sinal na costura com a transação ═══════════════════

def test_a59_07_prazo_DURANTE_o_stdin_nao_deixa_orfao_nem_indice_sujo(cen):
    """Entrada grande + filtro que dorme: o prazo estoura com stdin em voo."""
    antes = cen.indice()
    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(cen.binario),
        managed_artifact=cen.artefato, argv_policy=("--sonda-dorme", "60"),
        read_roots=(str(cen.repo),), write_roots=(str(cen.escopo),),
        timeout=2.0))
    (cen.repo / "a.txt").write_bytes(b"SENHA=hunter2\n" + b"x" * (2 * 1024 * 1024))

    with pytest.raises(Exception, match="prazo|excedeu"):
        cen.add(reg, "a.txt")
    assert cen.indice() == antes
    assert cen.objetos_com_segredo() == 0
    r = subprocess.run(["/bin/ps", "-Ao", "command"], capture_output=True,
                       text=True)
    assert "nomos-sb-" not in r.stdout, "ORPHAN_PROCESS após prazo no stdin"


def test_a59_08_fork_do_filtro_DURANTE_a_transacao_nao_sobrevive(cen):
    """O filtro deixa descendentes e a operação é recusada pelo prazo.

    Duas pós-condições na mesma saída: a árvore morre (A5.6) e o índice volta
    (A5.8). Uma passar sem a outra seria contenção pela metade.
    """
    antes = cen.indice()
    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(cen.binario),
        managed_artifact=cen.artefato,
        argv_policy=("--sonda-forks", "4", "60", str(cen.escopo)),
        read_roots=(str(cen.repo),), write_roots=(str(cen.escopo),),
        timeout=3.0))

    with pytest.raises(Exception, match="prazo|excedeu"):
        cen.add(reg, "a.txt")

    marcados = [int(p.name.rsplit(".", 1)[1]) for p in cen.escopo.iterdir()
                if p.name.startswith(("cria.", "pai."))]
    assert len(marcados) >= 2, (
        "PROCESS_ACTUALLY_EXISTED=FALSE: o filtro nem chegou a forkar")
    vivos = []
    for pid in marcados:
        try:
            os.kill(pid, 0)
            vivos.append(pid)
        except OSError:
            pass
    assert vivos == [], f"ORPHAN_PROCESS: {vivos} sobreviveram à recusa"
    assert cen.indice() == antes
    assert cen.objetos_com_segredo() == 0


# ═══════ 09-10 — contenção e substituição sob concorrência ══════════════════

def test_a59_09_registry_sob_CONTENCAO_nunca_resolve_o_que_nao_registrou(cen):
    """12 threads pedindo ids aprovados e não aprovados ao mesmo tempo.

    O que não pode acontecer é um id NÃO registrado sair resolvido porque outra
    thread estava registrando algo ao lado.
    """
    reg = cen.registro()
    erros: list[str] = []
    pronto = threading.Barrier(12)

    def pedir(i):
        pronto.wait(timeout=30)
        fid = "redator" if i % 2 == 0 else f"nao-existe-{i}"
        try:
            pol = reg.resolver(fid)
            if fid != "redator":
                erros.append(f"resolveu {fid!r}, que nunca foi registrado")
            elif pol.filter_id != "redator":
                erros.append(f"resolveu {fid!r} como {pol.filter_id!r}")
        except fg.ErroFiltro:
            if fid == "redator":
                erros.append("recusou o id APROVADO sob contenção")

    ts = [threading.Thread(target=pedir, args=(i,)) for i in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=40)
    assert erros == [], erros[:3]


def test_a59_10_substituir_o_artefato_ENTRE_dois_adds_e_pego(cen):
    """O primeiro `add` aprova; o artefato é trocado; o segundo tem de recusar.

    Sem revalidação por uso, a aprovação viraria permanente — e trocar o binário
    passaria a exigir só paciência.
    """
    reg = cen.registro()
    assert cen.add(reg, "a.txt").efeito_aplicado

    alvo = Path(cen.artefato.managed_path)
    alvo.chmod(0o700)
    alvo.write_bytes(b"outro binario\n")
    alvo.chmod(0o500)

    antes = cen.indice()
    (cen.repo / "b.txt").write_text("SENHA=hunter2\n")
    with pytest.raises(fg.ErroFiltro, match="DIVERGE"):
        cen.add(reg, "b.txt")
    assert cen.indice() == antes
    assert cen.objetos_com_segredo() == 0
