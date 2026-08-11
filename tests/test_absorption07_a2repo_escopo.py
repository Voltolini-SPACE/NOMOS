"""A2-REPO — o repositório é o PRINCIPAL adversarial, não o dado de entrada.

A propriedade que esta bateria persegue:

    REPOSITORY_CANNOT_EXPAND_NOMOS_AUTHORITY = TRUE

Ela foi medida FALSA, e por uma porta que nenhuma das defesas anteriores olhava.
`resolver()` valida o DIRETÓRIO DE TRABALHO contra as raízes aprovadas — e mais
nada. `diretorio_git()` então segue duas indireções que o REPOSITÓRIO escreve:

    .git como ARQUIVO      ->  "gitdir: <caminho>"
    <git_dir>/commondir    ->  "<caminho>"

e devolve o destino sem ninguém conferir onde ele foi parar. Como
`confinamento_de_repo()` usa esse git dir como RAIZ DE ESCRITA do sandbox, o
resultado é direto: **o repositório escolhe onde o NOMOS grava**.

Reproduzido ponta a ponta antes do conserto: `git-add` devolveu
`efeito_aplicado=True` e escreveu o índice fora de toda raiz aprovada.

## O controle que impede esta bateria de virar "negue tudo"

`.git` como arquivo é o mecanismo NORMAL de worktree ligada e de submódulo — o
próprio repositório onde esta missão roda usa isso. Uma bateria que só provasse
recusa passaria igual num sistema que quebrou a funcionalidade inteira. Por isso
`test_a2repo_05` exige que a indireção LEGÍTIMA, dentro das raízes, continue
funcionando; sem ele, os quatro testes de recusa não distinguem contenção de
quebra.

## Segunda família: leitura do processo PAI

O caminho governado de A5.7 lia o alvo com `Path.read_bytes()` — no processo do
supervisor, fora do sandbox, seguindo symlink. Todo o confinamento de A5.5 é
irrelevante quando quem lê é o pai. Medido: um repositório com
`vaza.txt -> /etc/passwd` fez o NOMOS indexar o conteúdo de `/etc/passwd`, com
modo `100644` — o link virava arquivo regular, mudando a semântica do Git sem
ninguém pedir.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git, git_tree, supervisor
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
def campo(tmp_path):
    """Duas áreas: `raizes/` é o escopo aprovado, `fora/` nunca foi aprovado."""
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()

    class Campo:
        def __init__(self):
            self.raiz, self.fora, self.tmp = raiz, fora, tmp_path

        def ctx(self, cap="git-add"):
            rc = RegistroCapacidades(
                policy=PolicyEngine(tmp_path / "pol.json"),
                approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            return CapabilityContext.de_registro(rc, cap, "runtime-governado",
                                                 raizes=(str(raiz),))

        def add(self, repo: Path, *caminhos, registro=None):
            return git_tree.GitTreeAdapter(registro=registro).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx())

    return Campo()


def _repo_com_gitdir_separado(trabalho: Path, gitdir: Path) -> None:
    trabalho.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", "--separate-git-dir", str(gitdir),
                    str(trabalho)], check=True, capture_output=True)


# ════════════ 01-04 — o repositório NÃO escolhe onde o NOMOS grava ══════════

def test_a2repo_01_gitdir_ABSOLUTO_fora_das_raizes_e_recusado(campo):
    """CONTROLE POSITIVO junto: sem o conserto, isto gravava o índice em `fora`."""
    trabalho = campo.raiz / "repo"
    gitdir = campo.fora / "gitdir-da-vitima"
    _repo_com_gitdir_separado(trabalho, gitdir)
    assert (trabalho / ".git").is_file(), "o cenário não montou `.git` como arquivo"
    (trabalho / "x.txt").write_text("conteudo\n")

    with pytest.raises(supervisor.ErroSeguranca, match="FORA das raízes"):
        campo.add(trabalho, "x.txt")

    assert not (gitdir / "index").exists(), (
        "REPO_AUTHORITY_EXPANSION: o índice foi escrito fora das raízes")


def test_a2repo_02_gitdir_RELATIVO_com_traversal_e_recusado(campo):
    """`gitdir: ../../fora/x` — o mesmo escape sem caminho absoluto."""
    trabalho = campo.raiz / "repo"
    gitdir = campo.fora / "gd-rel"
    _repo_com_gitdir_separado(trabalho, gitdir)
    relativo = os.path.relpath(gitdir, trabalho)
    (trabalho / ".git").write_text(f"gitdir: {relativo}\n")
    assert ".." in relativo, "o cenário não gerou traversal"
    (trabalho / "x.txt").write_text("conteudo\n")

    with pytest.raises(supervisor.ErroSeguranca, match="FORA das raízes"):
        campo.add(trabalho, "x.txt")


def test_a2repo_03_commondir_fora_das_raizes_e_recusado(campo):
    """A segunda indireção: o git dir está dentro, o `commondir` aponta fora.

    É o salto duplo — e o mais traiçoeiro, porque a primeira validação passa.
    """
    trabalho = campo.raiz / "repo"
    subprocess.run([GIT, "init", "-q", str(trabalho)], check=True,
                   capture_output=True)
    alheio = campo.fora / "repo-alheio"
    subprocess.run([GIT, "init", "-q", str(alheio)], check=True,
                   capture_output=True)
    (trabalho / ".git" / "commondir").write_text(str(alheio / ".git") + "\n")
    (trabalho / "x.txt").write_text("conteudo\n")

    with pytest.raises(supervisor.ErroSeguranca, match="FORA das raízes"):
        campo.add(trabalho, "x.txt")


def test_a2repo_04_git_como_SYMLINK_para_fora_e_recusado(campo):
    """Terceira forma da mesma indireção, por link em vez de conteúdo."""
    trabalho = campo.raiz / "repo"
    trabalho.mkdir()
    alheio = campo.fora / "gd-link"
    subprocess.run([GIT, "init", "-q", "--bare", str(alheio)], check=True,
                   capture_output=True)
    (trabalho / ".git").symlink_to(alheio)
    (trabalho / "x.txt").write_text("conteudo\n")

    with pytest.raises(supervisor.ErroSeguranca, match="FORA das raízes"):
        campo.add(trabalho, "x.txt")


def test_a2repo_05_indirecao_LEGITIMA_dentro_das_raizes_CONTINUA_funcionando(campo):
    """O controle que separa contenção de quebra.

    `.git` como arquivo é o mecanismo normal de worktree ligada e submódulo — o
    próprio repositório desta missão usa isso. Sem este teste, os quatro
    anteriores passariam igual num sistema que simplesmente parou de aceitar
    worktree.
    """
    trabalho = campo.raiz / "repo"
    gitdir = campo.raiz / "gitdir-legitimo"          # DENTRO da raiz aprovada
    _repo_com_gitdir_separado(trabalho, gitdir)
    assert (trabalho / ".git").is_file()
    (trabalho / "x.txt").write_text("conteudo legitimo\n")

    r = campo.add(trabalho, "x.txt")
    assert r.efeito_aplicado, "a indireção legítima parou de funcionar"
    assert (gitdir / "index").exists(), "o índice não foi escrito no git dir"


def test_a2repo_06_a_conferencia_e_por_COMPONENTE_nao_por_prefixo(campo):
    """`/raiz-do-atacante` não está dentro de `/raiz`.

    Contenção por `startswith` aceitaria — e é o erro clássico. `commonpath`
    compara componente a componente, que é a pergunta que se quer fazer.
    """
    vizinho = campo.tmp / "raizes-do-atacante"
    vizinho.mkdir()
    trabalho = vizinho / "repo"
    subprocess.run([GIT, "init", "-q", str(trabalho)], check=True,
                   capture_output=True)
    assert str(vizinho).startswith(str(campo.raiz)), (
        "o cenário não montou o prefixo enganoso")
    with pytest.raises(supervisor.ErroSeguranca, match="FORA das raízes"):
        git.conferir_git_dir(trabalho, (str(campo.raiz),))


def test_a2repo_07_sem_raizes_declaradas_nao_ha_o_que_conferir(campo):
    """Contrato explícito: sem raízes, `conferir_git_dir` não inventa uma.

    O chamador que não delimita escopo tem de ser corrigido, não silenciosamente
    contido por um palpite deste módulo — um palpite errado seria pior que a
    ausência, porque pareceria contenção.
    """
    trabalho = campo.raiz / "repo"
    subprocess.run([GIT, "init", "-q", str(trabalho)], check=True,
                   capture_output=True)
    git_dir, common = git.conferir_git_dir(trabalho, ())
    assert Path(git_dir).is_dir() and Path(common).is_dir()


# ════════════ 12-14 — a WORKING TREE também é escolhida pelo repo ═══════════
#
# Escape INDEPENDENTE do git dir, e por isso `conferir_git_dir` não o alcança:
# ali o git dir está DENTRO das raízes; o que sai é a working tree.

def test_a2repo_12_core_worktree_para_fora_nao_alcanca_o_host(campo):
    """MEDIDO antes do conserto: `core.worktree=/etc` indexou `/etc/hosts`.

    O controle positivo é o próprio `/etc/hosts` — existe e é legível, então a
    ausência do conteúdo no índice não é acidente de arquivo ausente.
    """
    assert Path("/etc/hosts").is_file(), "sem alvo legível o teste seria vácuo"
    repo = campo.raiz / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", str(repo)], check=True,
                   capture_output=True)
    subprocess.run([GIT, "-C", str(repo), "config", "core.worktree", "/etc"],
                   check=True, capture_output=True)

    # `ErroInvalido` e não `ErroSeguranca`: com a working tree pinada, o Git
    # simplesmente não acha `hosts` — a recusa vem de o caminho não existir no
    # escopo real, que é a forma mais forte de negar (não há o que decidir).
    with pytest.raises(ErroInvalido, match="pathspec"):
        campo.add(repo, "hosts")

    saida = subprocess.run([GIT, "-C", str(repo), "cat-file",
                            "--batch-all-objects", "--batch"],
                           capture_output=True).stdout
    assert b"localhost" not in saida, (
        "REPO_FS_ESCAPE: `/etc/hosts` chegou ao store pelo `core.worktree`")


def test_a2repo_13_core_worktree_hostil_nao_quebra_o_arquivo_legitimo(campo):
    """Com a working tree pinada, o arquivo do PRÓPRIO repo continua entrando."""
    repo = campo.raiz / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", str(repo)], check=True,
                   capture_output=True)
    subprocess.run([GIT, "-C", str(repo), "config", "core.worktree", "/etc"],
                   check=True, capture_output=True)
    (repo / "bom.txt").write_text("conteudo bom\n")

    r = campo.add(repo, "bom.txt")
    assert r.efeito_aplicado
    corpo = subprocess.run([GIT, "-C", str(repo), "show", ":bom.txt"],
                           capture_output=True).stdout
    assert corpo == b"conteudo bom\n"


def test_a2repo_14_a_pinagem_e_por_GIT_WORK_TREE_e_nao_por_c(campo):
    """Documenta a medição que decidiu o mecanismo, e prende a regressão.

    `-c core.worktree=<repo>` NÃO vence a chave do `.git/config` — medido: o Git
    continua reportando `/private/etc`. Trocar `GIT_WORK_TREE` por `-c` aqui
    seria um no-op silencioso, que é o pior desfecho possível para uma defesa.
    """
    repo = campo.raiz / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", str(repo)], check=True,
                   capture_output=True)
    subprocess.run([GIT, "-C", str(repo), "config", "core.worktree", "/etc"],
                   check=True, capture_output=True)

    por_c = subprocess.run(
        [GIT, "-C", str(repo), "-c", f"core.worktree={repo}",
         "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout
    assert "/etc" in por_c, (
        "`-c core.worktree` passou a vencer neste host — a pinagem pode "
        "simplificar, mas a mudança tem de ser deliberada e medida")

    por_env = subprocess.run(
        [GIT, "-C", str(repo), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
        env={**os.environ, "GIT_WORK_TREE": str(repo)}).stdout
    assert "/etc" not in por_env, "GIT_WORK_TREE deixou de vencer"


# ═══════ 08-11 — a leitura do processo PAI, que o sandbox não alcança ═══════

@pytest.fixture
def governado(campo):
    """Repo governado com filtro aprovado, dentro das raízes."""
    repo = campo.raiz / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", str(repo)], check=True,
                   capture_output=True)
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)
    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(binario),
        managed_artifact=art, read_roots=(str(repo),), write_roots=(str(repo),)))
    (repo / ".gitattributes").write_text("*.txt filter=redator\n")
    return campo, repo, reg


def test_a2repo_08_filtro_governado_NAO_segue_symlink_para_segredo(governado):
    """Medido antes do conserto: `/etc/passwd` foi lido e indexado.

    A leitura acontece no processo do SUPERVISOR, fora do sandbox — todo o
    confinamento de A5.5 é irrelevante para ela. O controle positivo é o próprio
    `/etc/passwd`: ele existe e é legível, então "não vazou" não é acidente de
    arquivo ausente.
    """
    campo, repo, reg = governado
    assert Path("/etc/passwd").is_file(), "sem alvo legível o teste seria vácuo"
    (repo / "vaza.txt").symlink_to("/etc/passwd")

    with pytest.raises(supervisor.ErroSeguranca, match="symlink"):
        campo.add(repo, "vaza.txt", registro=reg)

    saida = subprocess.run([GIT, "-C", str(repo), "cat-file",
                            "--batch-all-objects", "--batch"],
                           capture_output=True).stdout
    assert b"root:" not in saida, (
        "LINK_BASED_ESCAPE: o conteúdo de /etc/passwd chegou ao store")


def test_a2repo_09_filtro_governado_recusa_FIFO(governado):
    """FIFO penduraria a leitura do supervisor sem prazo nenhum."""
    campo, repo, reg = governado
    fifo = repo / "trava.txt"
    os.mkfifo(fifo)
    with pytest.raises(supervisor.ErroSeguranca, match="não é arquivo regular"):
        campo.add(repo, "trava.txt", registro=reg)


def test_a2repo_10_o_caminho_governado_LEGITIMO_continua_funcionando(governado):
    """Controle: sem ele, 08 e 09 passariam num sistema que recusa tudo."""
    campo, repo, reg = governado
    (repo / "ok.txt").write_text("SENHA=hunter2\nnormal\n")
    r = campo.add(repo, "ok.txt", registro=reg)
    assert r.efeito_aplicado
    sha = subprocess.run([GIT, "-C", str(repo), "ls-files", "-s", "--", "ok.txt"],
                         capture_output=True, text=True).stdout.split()
    corpo = subprocess.run([GIT, "-C", str(repo), "cat-file", "-p", sha[1]],
                           capture_output=True).stdout
    assert corpo == b"SENHA=REDIGIDO\nnormal\n"
    assert sha[0] == "100644"


def test_a2repo_11_symlink_pelo_caminho_NORMAL_continua_sendo_link(governado):
    """Sem filtro pedido, o Git grava o LINK (120000) — e isso não muda.

    A recusa de 08 é do caminho GOVERNADO, não do Git. Confundir os dois faria a
    correção quebrar versionamento legítimo de symlink.
    """
    campo, repo, reg = governado
    (repo / "link.dat").symlink_to("alvo-inexistente")
    r = campo.add(repo, "link.dat", registro=reg)     # .dat não casa *.txt
    assert r.efeito_aplicado
    modo = subprocess.run([GIT, "-C", str(repo), "ls-files", "-s", "--",
                           "link.dat"], capture_output=True,
                          text=True).stdout.split()[0]
    assert modo == "120000", f"o link virou modo {modo}, deixou de ser link"
