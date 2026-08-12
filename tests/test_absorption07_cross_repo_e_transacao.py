"""CROSS_REPO + transação de REFS — quatro achados, três formas de confusão.

    .5.04   `commondir` -> git dir de OUTRO repo, com `.git` DIRETÓRIO
    .9.07   `.git` como SYMLINK -> git dir de OUTRO repo
    .11.08  filtro com `write_roots=(<git dir>,)` grava refs/objects/HEAD
    .11.06  commit RECUSADO deixava o repositório CORROMPIDO

## O gate que não disparava

`_conferir_titularidade` existe exatamente contra confusão cross-repo, e em dois
layouts ela nunca era chamada:

    `.git` SYMLINK      o gate era `if not ponto.is_dir()`, e `is_dir()` SEGUE
                        link — devolvia True e o gate não disparava
    `commondir`         o gate (corretamente) não dispara com `.git` DIRETÓRIO,
                        e ninguém conferia a SEGUNDA indireção

Nos dois, `git-add` estagiou no índice da VÍTIMA e `git-commit` AVANÇOU
`refs/heads/main` dela para um commit com `AWS_SECRET_ACCESS_KEY` — com a
auditoria registrando o repositório do ATACANTE como alvo.

## Por que `rc != 0` não é o critério aqui

Uma recusa que já mexeu no repositório da vítima não é recusa. Cada teste de
negação prova `INDEX_UNCHANGED`, `REFS_UNCHANGED` e store intacto.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


def _git(*args):
    return subprocess.run([GIT, *args], capture_output=True, text=True)


@pytest.fixture
def campo(tmp_path):
    raiz = tmp_path / "raizes"
    raiz.mkdir()

    class Campo:
        def __init__(self):
            self.raiz, self.tmp = raiz, tmp_path

        def repo(self, onde: Path, nome="ok.txt") -> Path:
            onde.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", "-b", "main", str(onde))
            _git("-C", str(onde), "config", "user.email", "a@b.c")
            _git("-C", str(onde), "config", "user.name", "T")
            (onde / nome).write_text("ok\n")
            _git("-C", str(onde), "add", nome)
            _git("-C", str(onde), "commit", "-qm", "inicial")
            return onde

        def ctx(self, cap="git-add"):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            return CapabilityContext.de_registro(rc, cap, "runtime-governado",
                                                 raizes=(str(raiz),))

        def add(self, repo, *caminhos, registro=None):
            return git_tree.GitTreeAdapter(registro=registro).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx("git-add"))

        def commit(self, repo, msg="m", registro=None):
            return git_tree.GitTreeAdapter(registro=registro).executar(
                CapabilityRequest(capacidade="git-commit", alvo=str(repo),
                                  argumentos={"mensagem": msg}),
                self.ctx("git-commit"))

        def estado(self, repo: Path) -> tuple[str, str]:
            """O par que uma recusa não pode ter mexido."""
            return (_git("-C", str(repo), "rev-parse", "refs/heads/main").stdout,
                    _git("-C", str(repo), "ls-files").stdout)

    return Campo()


# ═══════════════ .5.04 e .9.07 — as duas formas de cross-repo ════════════════

def test_cross_repo_COMMONDIR_para_outro_repo_e_RECUSADO(campo):
    """A SEGUNDA indireção também tem dono, e ninguém a conferia."""
    vitima = campo.repo(campo.raiz / "vitima")
    hostil = campo.repo(campo.raiz / "hostil", nome="seed.txt")
    antes = campo.estado(vitima)

    (hostil / ".git" / "commondir").write_text(f"{vitima / '.git'}\n")
    (hostil / "segredo.txt").write_text("AWS_SECRET_ACCESS_KEY=vazou\n")

    with pytest.raises(supervisor.ErroSeguranca, match="commondir"):
        campo.add(hostil, "segredo.txt")
    assert campo.estado(vitima) == antes, "REFS/INDEX da vítima mudaram"


def test_cross_repo_DOTGIT_SYMLINK_e_RECUSADO(campo):
    """`is_dir()` SEGUE link — o gate da titularidade nunca disparava."""
    vitima = campo.repo(campo.raiz / "vitima")
    hostil = campo.raiz / "hostil"
    hostil.mkdir()
    os.symlink(str(vitima / ".git"), str(hostil / ".git"))
    (hostil / "segredo.txt").write_text("AWS_SECRET_ACCESS_KEY=abc123\n")
    antes = campo.estado(vitima)

    with pytest.raises(supervisor.ErroSeguranca):
        campo.add(hostil, "segredo.txt")
    assert campo.estado(vitima) == antes, "REFS/INDEX da vítima mudaram"


def test_cross_repo_CONTROLE_worktree_ligada_continua_funcionando(campo):
    """Sem isto, os dois acima passariam num sistema que parou de aceitar
    `commondir` — que é o mecanismo NORMAL de worktree ligada."""
    principal = campo.repo(campo.raiz / "principal", nome="a.txt")
    wt = campo.raiz / "wt"
    _git("-C", str(principal), "worktree", "add", "-q", str(wt), "-b", "b2")
    (wt / "novo.txt").write_text("novo\n")

    r = campo.add(wt, "novo.txt")
    assert r.efeito_aplicado
    assert "novo.txt" in _git("-C", str(wt), "ls-files").stdout


# ═════════════ .11.06 — commit RECUSADO não pode corromper o repo ════════════

def test_commit_recusado_nao_deixa_o_repositorio_CORROMPIDO(campo):
    """A configuração NORMAL de quem usa clean filter (git-lfs, git-crypt).

    `git commit` avança `refs/heads/<b>` e escreve o reflog ANTES de
    `conferir_saida` recusar; os objetos do commit estão na QUARENTENA, que o
    `finally` destrói. Sem as refs na transação, sobrava `HEAD` apontando para
    objeto INEXISTENTE — `git log` e `git status` parando de funcionar num
    repositório cuja operação foi RECUSADA.
    """
    repo = campo.repo(campo.raiz / "repo")
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)
    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(binario),
        managed_artifact=art, read_roots=(str(repo),), write_roots=(str(repo),)))

    (repo / "segredo.txt").write_text("SENHA=hunter2\n")
    (repo / ".gitattributes").write_text("segredo.txt filter=redator\n")
    _git("-C", str(repo), "config", "filter.redator.clean", str(binario))

    # O `add` governado FUNCIONA — o filtro do repo não executa, o governado
    # sim. Quem quebra é o `commit`, e é esse o ponto do achado.
    campo.add(repo, "segredo.txt", registro=reg)
    head_antes = _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(supervisor.ErroSeguranca):
        campo.commit(repo, registro=reg)

    assert _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip() == head_antes, (
        "a ref avançou numa operação RECUSADA")
    assert _git("-C", str(repo), "log", "--oneline").returncode == 0, (
        "`git log` parou de funcionar — o repositório ficou inutilizável")
    fsck = _git("-C", str(repo), "fsck")
    assert fsck.returncode == 0, f"fsck acusou corrupção: {fsck.stderr[:200]}"


def test_commit_CONTROLE_commit_legitimo_ainda_avanca_a_ref(campo):
    """A transação de refs não pode ter desfeito o caminho que FUNCIONA."""
    repo = campo.repo(campo.raiz / "repo")
    (repo / "novo.txt").write_text("novo\n")
    campo.add(repo, "novo.txt")
    antes = _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip()

    r = campo.commit(repo, "commit legitimo")
    assert r.efeito_aplicado
    assert _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip() != antes
    assert _git("-C", str(repo), "fsck").returncode == 0


# ═══════════ .11.08 — filtro com o GIT DIR como raiz de escrita ══════════════

@pytest.mark.parametrize("rel", [
    "refs/heads/plantado", "packed-refs", "objects/plantado", "HEAD", "logs/x",
])
def test_filtro_com_gitdir_como_raiz_nao_escreve_estado_do_git(campo, rel):
    """A forma de política que o código dizia estar coberta — e não estava.

    Com `write_roots=(<git dir>,)`, o termo `<raiz>/.git` aponta para um caminho
    que NÃO EXISTE, então sobravam graváveis `refs/`, `HEAD`, `packed-refs` e
    `objects/` — onde o filtro planta OBJETO e REF, não só configuração.
    """
    repo = campo.repo(campo.raiz / "repo")
    gd = repo / ".git"
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)

    alvo = gd / rel
    alvo.parent.mkdir(parents=True, exist_ok=True)
    pol = fg.PoliticaDeFiltro(
        filter_id="f", canonical_executable=str(binario), managed_artifact=art,
        argv_policy=("--sonda-escrita", str(alvo)),
        read_roots=(str(gd),), write_roots=(str(gd),))
    supervisor.executar(pol.comando(), cwd=repo, env=pol.ambiente(), prazo=10.0,
                        confinamento=pol.confinamento(),
                        tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO,
                        entrada=b"")

    escreveu = alvo.exists() and alvo.read_bytes() == b"PLANTADO\n"
    assert not escreveu, f"o filtro plantou estado do Git em {rel}"


def test_filtro_com_gitdir_como_raiz_CONTROLE_area_concedida(campo):
    """Controle: a sonda escreve onde a política REALMENTE concede."""
    repo = campo.repo(campo.raiz / "repo")
    gd = repo / ".git"
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)

    alvo = gd / "saida-do-filtro.txt"
    pol = fg.PoliticaDeFiltro(
        filter_id="f", canonical_executable=str(binario), managed_artifact=art,
        argv_policy=("--sonda-escrita", str(alvo)),
        read_roots=(str(gd),), write_roots=(str(gd),))
    supervisor.executar(pol.comando(), cwd=repo, env=pol.ambiente(), prazo=10.0,
                        confinamento=pol.confinamento(),
                        tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO,
                        entrada=b"")
    assert alvo.exists() and alvo.read_bytes() == b"PLANTADO\n", (
        "a sonda não escreve nem na área concedida — os testes de recusa acima "
        "não distinguem contenção de sonda morta")


# ═══════════ .7.13 — a auditoria nomeia a autoridade CONSUMIDA ═══════════════

def test_auditoria_registra_o_git_dir_EFETIVO_nao_so_o_alvo(campo):
    """O operador nomeia a working tree; o efeito cai no git dir/common.

    MEDIDO: o registro trazia só `alvo`. Numa worktree ligada LEGÍTIMA o objeto
    foi para o COMMON DIR, e quem lê a auditoria via `alvo=<raizes>/wt` sem ter
    como saber onde o efeito caiu. Combinado com confusão cross-repo, o registro
    apontava para o repositório do ATACANTE — errado exatamente no caso em que
    ele mais importa.
    """
    principal = campo.repo(campo.raiz / "principal", nome="a.txt")
    wt = campo.raiz / "wt"
    _git("-C", str(principal), "worktree", "add", "-q", str(wt), "-b", "b2")
    (wt / "novo.txt").write_text("novo\n")

    registros = []

    class Espia:
        def append(self, evento, **campos):
            registros.append((evento, campos))

    rc = RegistroCapacidades(policy=PolicyEngine(campo.tmp / "aud.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(campo.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-add", "runtime-governado",
                                        raizes=(str(campo.raiz),),
                                        audit=Espia())
    git_tree.GitTreeAdapter().executar(
        CapabilityRequest(capacidade="git-add", alvo=str(wt),
                          argumentos={"caminhos": ["novo.txt"]}), ctx)

    assert registros, "nenhum evento de auditoria foi emitido"
    _evento, campos = registros[-1]
    gd = _git("-C", str(wt), "rev-parse", "--absolute-git-dir").stdout.strip()
    comum = _git("-C", str(wt), "rev-parse", "--git-common-dir").stdout.strip()
    valores = " ".join(str(v) for v in campos.values())
    assert gd in valores, (
        f"a auditoria não nomeia o git dir EFETIVO ({gd}); campos={sorted(campos)}")
    assert Path(comum).name and str(Path(comum).resolve()) in valores or comum in valores, (
        f"a auditoria não nomeia o common dir EFETIVO ({comum})")
