"""TOCTOU — a autoridade validada é LEVADA adiante, não revalidada.

    resolve -> validate -> BIND AUTHORITY -> effect      (o contrato)
    resolve -> validate -> discard -> resolve again -> effect   (o defeito)

`.git` é um arquivo que o REPOSITÓRIO escreve, e o fluxo o relia do disco de 4 a
6 vezes por operação. `conferir_git_dir` validava a PRIMEIRA leitura e devolvia a
tupla — e os quatro chamadores DESCARTAVAM o retorno. Cada etapa seguinte
resolvia de novo, e um escritor concorrente que trocasse `.git` entre a checagem
e o efeito movia o efeito para outro git dir.

MEDIDO, com corrida real e sem instrumentar o produto: em `git-push` o atacante
venceu 1/40 e 3/40, com o NOMOS reportando `ok=True` e PUBLICANDO um repositório
INTEIRAMENTE FORA das raízes, `AWS_SECRET_ACCESS_KEY` incluído. Janela medida:
115 ms no `add`, 90,5 ms no `push`.

## Por que "conferir de novo antes de cada uso" seria a correção errada

Revalidar em N pontos cria N janelas em vez de zero: entre a última checagem e o
uso ainda cabe uma troca. O que fecha é o efeito consumir a MESMA autoridade que
foi validada — um valor, não uma releitura.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from nomos.adapters import git, git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


def _git(*args):
    r = subprocess.run([GIT, *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r


@pytest.fixture
def campo(tmp_path):
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()

    class Campo:
        def __init__(self):
            self.raiz, self.fora, self.tmp = raiz, fora, tmp_path

        def repo(self, onde: Path, arquivo="a.txt"):
            onde.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", "-b", "main", str(onde))
            _git("-C", str(onde), "config", "user.email", "a@b.c")
            _git("-C", str(onde), "config", "user.name", "T")
            if arquivo:
                (onde / arquivo).write_text("conteudo\n")
            return onde

        def add(self, repo, *caminhos):
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


def test_toctou_01_a_autoridade_e_um_VALOR_nao_uma_releitura(campo):
    """Estrutural, e é o teste que impede a regressão de VOLTAR pelo desenho.

    Se `conferir_git_dir` voltar a ter o retorno descartado, o TOCTOU volta
    inteiro — e um teste de corrida é probabilístico demais para ser a única
    defesa. Aqui a exigência é sobre a FORMA: os quatro adapters ligam a
    autoridade.
    """
    from nomos.adapters import git_push, git_tree as gt, git_write

    # `nomos.adapters.git` (o adapter de LEITURA) estava FORA desta lista, e a
    # omissão custou um vazamento: 63 de 500 tentativas com escritor concorrente
    # devolveram `ok=True` contendo a história de um repositório INTEIRAMENTE
    # FORA das raízes. Divulgação vale tanto quanto mutação — uma lista de
    # adapters "que escrevem" é a fronteira errada.
    for modulo in (git, gt, git_write, git_push):
        fonte = Path(modulo.__file__).read_text("utf-8")
        assert "conferir_git_dir(repo, ctx.raizes)" in fonte
        assert "autoridade_de(repo" in fonte, (
            f"{modulo.__name__} valida a identidade e DESCARTA o resultado — "
            "o efeito vai reler `.git` do disco e o TOCTOU volta")


def test_toctou_01b_as_GUARDAS_tambem_consomem_a_autoridade(campo):
    """Não basta o EFEITO consumir: a guarda tem de olhar o mesmo repositório.

    MEDIDO: `conferir_alternates` relia `.git` por conta própria, então com um
    flip entre as duas leituras ela conferia um repositório DIFERENTE do que a
    autoridade ligou — 42/400 e 47/400 tentativas devolveram `ok=True` sobre um
    repo cujo store alcança um store FORA das raízes. E as 47 caíram TODAS no
    git dir da worktree, nenhuma no repo limpo: não foi acaso.
    """
    fonte = Path(git.__file__).read_text("utf-8")
    corpo = fonte.split("def conferir_alternates", 1)[1].split("\ndef ", 1)[0]
    assert "autoridade" in corpo, (
        "conferir_alternates resolve `.git` por conta própria — a guarda e o "
        "efeito podem acabar olhando repositórios diferentes")
    for modulo in (gt_mod(), git_write_mod(), git_push_mod()):
        fonte = Path(modulo.__file__).read_text("utf-8")
        assert "conferir_alternates(repo, ctx.raizes, autoridade)" in fonte, (
            f"{modulo.__name__} chama a guarda de alternates SEM a autoridade")


def gt_mod():
    from nomos.adapters import git_tree as m
    return m


def git_write_mod():
    from nomos.adapters import git_write as m
    return m


def git_push_mod():
    from nomos.adapters import git_push as m
    return m


def test_toctou_02_a_autoridade_carrega_git_dir_e_common(campo):
    """A autoridade tem de bastar para o efeito, senão alguém reresolve."""
    repo = campo.repo(campo.raiz / "repo")
    gd, comum = git.conferir_git_dir(repo, (str(campo.raiz),))
    a = git.autoridade_de(repo, gd, comum)
    assert a.git_dir == gd and a.common == comum
    assert a.raizes_de_escrita == ((gd,) if gd == comum else (gd, comum))
    conf = git.confinamento_de_repo(repo, autoridade=a)
    assert conf.escrita == a.raizes_de_escrita


def test_toctou_03_troca_de_git_dir_DURANTE_a_operacao_nao_move_o_efeito(campo):
    """Corrida real: um escritor concorrente reescreve `.git` sem parar.

    Não instrumenta o produto — só troca o arquivo de 49 bytes que o repositório
    controla, que é exatamente o que o atacante pode fazer. O critério não é
    "recusou": é que NENHUM efeito caia no git dir de fora das raízes.
    """
    # Worktree LIGADA: é o layout legítimo que tem `.git` como ARQUIVO — e a
    # forma-arquivo é o que o atacante precisa para poder trocar o ponteiro.
    principal = campo.repo(campo.raiz / "principal", arquivo="seed.txt")
    _git("-C", str(principal), "add", "seed.txt")
    _git("-C", str(principal), "commit", "-qm", "seed")
    trabalho = campo.raiz / "work"
    _git("-C", str(principal), "worktree", "add", "-q", str(trabalho), "-b", "b2")
    (trabalho / "s.txt").write_text("AWS_SECRET_ACCESS_KEY=NUNCA_SAIR\n")

    alheio = campo.fora / "alheio"
    _git("init", "-q", "-b", "main", str(alheio))
    ponto = trabalho / ".git"
    assert ponto.is_file(), "o cenário não montou `.git` como arquivo"
    bom = ponto.read_bytes()

    parar = threading.Event()

    def trocar():
        while not parar.is_set():
            try:
                ponto.write_text(f"gitdir: {alheio / '.git'}\n")
                ponto.write_bytes(bom)
            except OSError:
                pass
            time.sleep(0.001)

    t = threading.Thread(target=trocar, daemon=True)
    t.start()
    try:
        for _ in range(25):
            # A corrida faz a operação falhar de muitas formas; nenhuma delas é
            # o critério. O critério é o ESTADO do repositório de fora.
            with contextlib.suppress(Exception):
                campo.add(trabalho, "s.txt")
    finally:
        parar.set()
        t.join(timeout=5)
        ponto.write_bytes(bom)

    saida = subprocess.run([GIT, "-C", str(alheio), "ls-files"],
                           capture_output=True, text=True).stdout
    assert "s.txt" not in saida, (
        "BOUNDARY_ESCAPE: o efeito caiu no repositório de FORA das raízes — a "
        "autoridade validada não foi a que o efeito consumiu")
    objetos = list((alheio / ".git" / "objects").rglob("*"))
    assert not [p for p in objetos if p.is_file()
                and "info" not in str(p) and "pack" not in str(p)], (
        "objeto promovido para o store de fora das raízes")


def test_toctou_04_troca_de_FORMA_de_git_entre_as_duas_leituras(campo):
    """`.7.14`: o TOCTOU tinha MUDADO DE LUGAR, não fechado.

    `AutoridadeDeRepo` eliminou as releituras ENTRE chamadores. Sobrou uma
    DENTRO de `conferir_git_dir`: leitura #1 em `diretorio_git` resolvia o git
    dir, leitura #2 num `os.lstat` decidia se o gate de titularidade dispara.
    Trocando `.git` de ARQUIVO para DIRETÓRIO entre as duas, o git dir resolvido
    era o da VÍTIMA — dentro das raízes, então `_dentro` passa — enquanto o gate
    via `dentro_do_repo=True` e PULAVA a titularidade por completo. A raiz de
    escrita do sandbox virava `<vitima>/.git`.

    O conserto tem a MESMA forma do original: uma leitura alimenta as duas
    decisões (`_ler_ponto_git` devolve forma e conteúdo do MESMO descritor).
    """
    vitima = campo.repo(campo.raiz / "vitima", arquivo="ok.txt")
    _git("-C", str(vitima), "add", "ok.txt")
    _git("-C", str(vitima), "commit", "-qm", "seed")
    antes = subprocess.run([GIT, "-C", str(vitima), "ls-files"],
                           capture_output=True, text=True).stdout

    hostil = campo.raiz / "hostil"
    hostil.mkdir()
    ponto = hostil / ".git"
    ponto.write_text(f"gitdir: {vitima / '.git'}\n")
    (hostil / "segredo.txt").write_text("AWS_SECRET_ACCESS_KEY=NUNCA\n")

    parar = threading.Event()

    def alternar():
        real_dir = hostil / ".git-real"
        real_dir.mkdir(exist_ok=True)
        while not parar.is_set():
            try:
                ponto.unlink(missing_ok=True)
                os.symlink(str(real_dir), str(ponto))   # vira "diretório"
                ponto.unlink(missing_ok=True)
                ponto.write_text(f"gitdir: {vitima / '.git'}\n")
            except OSError:
                pass

    t = threading.Thread(target=alternar, daemon=True)
    t.start()
    try:
        for _ in range(40):
            with contextlib.suppress(Exception):
                campo.add(hostil, "segredo.txt")
    finally:
        parar.set()
        t.join(timeout=10)

    depois = subprocess.run([GIT, "-C", str(vitima), "ls-files"],
                            capture_output=True, text=True).stdout
    assert depois == antes, (
        "AUTHORITY_DRIFT: a troca de FORMA de `.git` pulou a titularidade e o "
        "efeito caiu no índice da vítima")


def test_toctou_05_a_FORMA_e_o_git_dir_vem_da_MESMA_leitura(campo):
    """Estrutural: prende o desenho, porque a corrida é probabilística.

    Se alguém voltar a decidir o gate com um `stat` próprio, o teste de corrida
    acima pode passar por sorte numa execução — este não passa.
    """
    fonte = Path(git.__file__).read_text("utf-8")
    corpo = fonte.split("def conferir_git_dir", 1)[1].split("\ndef ", 1)[0]
    assert "os.lstat" not in corpo, (
        "`conferir_git_dir` voltou a fazer um `stat` próprio de `.git` — a "
        "forma tem de vir da mesma leitura que resolveu o git dir")
    assert "_diretorio_git_com_forma" in corpo
