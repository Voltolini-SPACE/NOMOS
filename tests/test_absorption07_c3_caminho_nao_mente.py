"""C3 — o caminho aprovado tem de significar o que diz.

Três formas, todas medidas, de um caminho relativo "dentro do repositório"
alcançar outra coisa:

    sub -> /etc  +  add `sub/hosts`     componente do MEIO é link
    cano.txt (FIFO)                     `open` pendura o SUPERVISOR
    add `dir`                           expande para o que existir na hora

## Por que `O_NOFOLLOW` não bastava

`O_NOFOLLOW` protege apenas o ÚLTIMO componente. Com `sub` sendo symlink de
diretório, o `lstat`/`open` de `repo/sub/hosts` encontra um arquivo regular —
porque o kernel já atravessou o `sub`. A leitura acontece no processo do
supervisor, FORA do sandbox do filtro, então todo o confinamento de A5.5 é
irrelevante.

O que torna o achado material é o contraste: o `git add` CRU **recusa** este
caminho por conta própria (`fatal: pathspec ... is beyond a symbolic link`). O
caminho governado atravessava uma defesa que o Git já tinha — divergência a
MENOS de segurança, não a mais.

## Landmines registradas (as duas custaram uma rodada cada)

`O_DIRECTORY|O_NOFOLLOW` sobre symlink-para-diretório devolve **ENOTDIR** no
macOS, não ELOOP. Tratar só ELOOP contém igual, mas classifica o ataque como
erro de caminho do usuário — e é do registro que a auditoria vive.

`open` de FIFO sem escritor **bloqueia**. Ao trocar `lstat`-antes-de-`open` por
`open`-e-`fstat` (necessário para fechar a corrida), o pendura-tudo VOLTOU. Só
`O_NONBLOCK` no open final o fecha de verdade: o descritor retorna na hora e o
`fstat` recusa por não ser arquivo regular.
"""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, ErroInvalido,
)
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cen(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)],
                   check=True, capture_output=True)
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)

    class Cen:
        def __init__(self):
            self.repo, self.tmp = repo, tmp_path

        def registro(self):
            reg = fg.RegistroDeFiltros()
            reg.registrar("redator", fg.PoliticaDeFiltro(
                filter_id="redator", canonical_executable=str(binario),
                managed_artifact=art, read_roots=(str(repo),),
                write_roots=(str(repo),)))
            return reg

        def add(self, *caminhos, com_registro=True):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(tmp_path),))
            ctx = CapabilityContext.de_registro(rc, "git-add",
                                                "runtime-governado",
                                                raizes=(str(tmp_path),))
            adapter = git_tree.GitTreeAdapter(
                registro=self.registro() if com_registro else None)
            return adapter.executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}), ctx)

        def indice(self, rel: str) -> bytes:
            r = subprocess.run([GIT, "-C", str(repo), "show", f":{rel}"],
                               capture_output=True)
            return r.stdout if r.returncode == 0 else b"<AUSENTE>"

    return Cen()


def test_c3_00_controle_positivo_caminho_com_subdiretorio_REAL_funciona(cen):
    """Sem isto, os testes de recusa passariam num sistema que quebrou `sub/x`."""
    d = cen.repo / "sub"
    d.mkdir()
    (d / "arq.txt").write_text("SENHA=hunter2\n")
    (cen.repo / ".gitattributes").write_text("sub/arq.txt filter=redator\n")
    r = cen.add("sub/arq.txt")
    assert r.efeito_aplicado
    assert cen.indice("sub/arq.txt") == b"SENHA=REDIGIDO\n"


def test_c3_01_symlink_de_DIRETORIO_no_meio_do_caminho(cen, tmp_path):
    """O componente do meio é link — `O_NOFOLLOW` no último não vê isto."""
    fora = tmp_path / "dir_de_fora"
    fora.mkdir()
    (fora / "hosts").write_text("CONTEUDO_DE_FORA_DO_REPO\n")
    os.symlink(str(fora), str(cen.repo / "sub"))
    (cen.repo / ".gitattributes").write_text("sub/hosts filter=redator\n")

    with pytest.raises(supervisor.ErroSeguranca, match="symlink de diretório"):
        cen.add("sub/hosts")
    assert cen.indice("sub/hosts") == b"<AUSENTE>", (
        "conteúdo de FORA do repositório foi indexado pelo caminho governado")


def test_c3_02_symlink_de_ARQUIVO_continua_recusado(cen, tmp_path):
    """Regressão do conserto de A2-REPO: o caso do último componente."""
    fora = tmp_path / "segredo_de_fora.txt"
    fora.write_text("CHAVE_PRIVADA\n")
    os.symlink(str(fora), str(cen.repo / "vaza.txt"))
    (cen.repo / ".gitattributes").write_text("vaza.txt filter=redator\n")

    with pytest.raises(supervisor.ErroSeguranca, match="symlink"):
        cen.add("vaza.txt")


def test_c3_03_FIFO_nao_pendura_o_supervisor(cen):
    """LANDMINE: `open` de FIFO sem escritor BLOQUEIA.

    Este teste tem alarme porque a falha que ele persegue não é uma asserção
    vermelha — é a suíte inteira parando para sempre. Sem `O_NONBLOCK` no open
    final, ele pendura.
    """
    os.mkfifo(cen.repo / "cano.txt")
    (cen.repo / ".gitattributes").write_text("cano.txt filter=redator\n")

    def estourou(*_):
        raise AssertionError(
            "PENDUROU: o open do FIFO bloqueou o processo do supervisor — "
            "`O_NONBLOCK` saiu do open final de `_abrir_sem_atravessar_link`")

    anterior = signal.signal(signal.SIGALRM, estourou)
    signal.alarm(20)
    try:
        with pytest.raises(supervisor.ErroSeguranca, match="arquivo regular"):
            cen.add("cano.txt")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, anterior)


def test_c3_04_DIRETORIO_na_lista_e_o_dash_A_disfarcado(cen):
    """`caminhos=['dir']` estagiava TUDO que estivesse dentro."""
    d = cen.repo / "dir"
    d.mkdir()
    (d / "aprovado.txt").write_text("ok\n")
    (d / "NAO_APROVADO_segredo.txt").write_text("AKIA-SEGREDO\n")

    with pytest.raises(ErroInvalido, match="DIRETÓRIO"):
        cen.add("dir", com_registro=False)
    assert cen.indice("dir/NAO_APROVADO_segredo.txt") == b"<AUSENTE>", (
        "ESCOPO_MAIOR_QUE_O_APROVADO: entrou arquivo que ninguém nomeou")


def test_c3_05_symlink_para_diretorio_e_gravado_como_LINK_e_nao_expandido(
        cen, tmp_path):
    """CONTROLE de que `_recusar_diretorio` não recusa DEMAIS.

    `lstat` e não `is_dir()`, e a diferença importa nos dois sentidos.
    `is_dir()` SEGUE o link: um link para diretório seria classificado como
    diretório e recusado — quebrando o caso legítimo de versionar um symlink.

    MEDIDO no git cru: `git add --no-all -- atalho` com `atalho -> <dir>`
    estagia `120000 … atalho`, o LINK, e nada de dentro do destino. Não há
    expansão, então não há o que recusar; o que importa é que continue sendo
    link e que nenhum arquivo de fora entre no índice.
    """
    fora = tmp_path / "alvo"
    fora.mkdir()
    (fora / "x.txt").write_text("de fora\n")
    os.symlink(str(fora), str(cen.repo / "atalho"))

    cen.add("atalho", com_registro=False)
    saida = subprocess.run([GIT, "-C", str(cen.repo), "ls-files", "-s"],
                           capture_output=True, text=True).stdout
    assert saida.startswith("120000 "), (
        f"o link virou outra coisa no índice: {saida!r}")
    assert "x.txt" not in saida, (
        "o conteúdo do diretório apontado entrou no índice")


def test_c3_06_o_git_cru_tambem_recusa_o_traversal(cen, tmp_path):
    """CONTROLE: prende a divergência que tornou o achado material.

    Se um dia o Git parar de recusar, este teste avisa — e a justificativa do
    conserto ("o caminho governado atravessava defesa que o Git já tinha")
    precisa ser reavaliada, não copiada.
    """
    fora = tmp_path / "d2"
    fora.mkdir()
    (fora / "hosts").write_text("x\n")
    os.symlink(str(fora), str(cen.repo / "sub2"))
    r = subprocess.run([GIT, "-C", str(cen.repo), "add", "--no-all", "--",
                        "sub2/hosts"], capture_output=True, text=True)
    assert r.returncode != 0
    assert "beyond a symbolic link" in r.stderr
