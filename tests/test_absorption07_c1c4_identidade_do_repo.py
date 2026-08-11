"""C1.10 + C4.02 — o repositório não escolhe ONDE o efeito cai nem O QUE se lê.

Duas propriedades, medidas separadamente:

    O_EFEITO_CAI_NO_REPO_QUE_O_OPERADOR_APROVOU = TRUE      (C1.10)
    O_STORE_DE_OBJETOS_ESTA_DENTRO_DAS_RAIZES   = TRUE      (C4.02)

## C1.10 — confusão cross-repo, e por que `conferir_git_dir` não bastava

O conserto de A2-REPO exige que git dir e common dir caiam DENTRO das raízes
aprovadas. Isso fecha o escape para fora — e deixa passar o caso em que os dois
repositórios estão DENTRO. MEDIDO: um repo `hostil` cujo `.git` é o arquivo
`gitdir: <vitima>/.git` fez `git-add` sobre `hostil` estagiar no índice de
`vitima`, com `ok=True`, `efeito_aplicado=True`, e a auditoria registrando
`alvo=hostil`. O operador aprovou operar num repositório; o efeito caiu em
outro, e a evidência aponta para o lugar errado.

## O risco desta bateria: virar deny-all

`.git` como ARQUIVO é o mecanismo NORMAL de worktree ligada, de submódulo e de
`--separate-git-dir` — o próprio repositório onde esta missão roda é uma
worktree ligada. Uma correção que recusasse `.git`-arquivo passaria em todos os
testes de recusa e quebraria o produto inteiro.

Por isso os QUATRO layouts legítimos têm teste próprio aqui. O discriminador é
medido, não inventado: no ataque o git dir alheio se chama `.git` e é a git dir
PRINCIPAL de outra working tree. Worktree ligada aponta para
`.git/worktrees/<n>`, submódulo para `.git/modules/<n>`, e `--separate-git-dir`
para um diretório de nome arbitrário que não é `.git` de ninguém — nenhum dos
três colide com a regra.
"""
from __future__ import annotations

import os
import subprocess
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


def _git(*args, cwd=None):
    r = subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} rc={r.returncode}: {r.stderr}"
    return r


@pytest.fixture
def campo(tmp_path):
    raiz = tmp_path / "raizes"
    raiz.mkdir()

    class Campo:
        def __init__(self):
            self.raiz, self.tmp = raiz, tmp_path

        def repo(self, onde: Path, arquivo="a.txt") -> Path:
            onde.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", "-b", "main", str(onde))
            _git("-C", str(onde), "config", "user.email", "a@b.c")
            _git("-C", str(onde), "config", "user.name", "T")
            if arquivo:
                (onde / arquivo).write_text("conteudo\n")
            return onde

        def add(self, repo: Path, *caminhos):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            ctx = CapabilityContext.de_registro(rc, "git-add",
                                                "runtime-governado",
                                                raizes=(str(raiz),))
            return git_tree.GitTreeAdapter().executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}), ctx)

        def indice(self, repo: Path) -> str:
            return subprocess.run([GIT, "-C", str(repo), "ls-files"],
                                  capture_output=True, text=True).stdout

    return Campo()


# ═════════════════ C1.10 — o ataque, e os QUATRO layouts legítimos ═══════════

def test_c1_10_cross_repo_confused_deputy_e_RECUSADO(campo):
    """Os dois repos DENTRO das raízes: `conferir_git_dir` sozinho não pega."""
    vitima = campo.repo(campo.raiz / "vitima", arquivo="importante.txt")
    _git("-C", str(vitima), "add", "importante.txt")

    hostil = campo.raiz / "hostil"
    hostil.mkdir()
    (hostil / ".git").write_text(f"gitdir: {vitima / '.git'}\n")
    (hostil / "backdoor.sh").write_text("#!/bin/sh\necho own\n")

    with pytest.raises(supervisor.ErroSeguranca, match="cross-repo"):
        campo.add(hostil, "backdoor.sh")

    assert "backdoor.sh" not in campo.indice(vitima), (
        "CROSS_REPO: o efeito caiu num repositório diferente do alvo aprovado")


def test_c1_10_legitimo_WORKTREE_LIGADA_continua_funcionando(campo):
    """CONTROLE 1/4 — é o layout do próprio repositório desta missão."""
    main = campo.repo(campo.raiz / "main")
    _git("-C", str(main), "add", "a.txt")
    _git("-C", str(main), "commit", "-qm", "i")
    wt = campo.raiz / "wt"
    _git("-C", str(main), "worktree", "add", "-q", str(wt), "-b", "b2")
    (wt / "novo.txt").write_text("novo\n")

    r = campo.add(wt, "novo.txt")
    assert r.efeito_aplicado
    assert "novo.txt" in campo.indice(wt)


def test_c1_10_legitimo_SUBMODULO_continua_funcionando(campo):
    """CONTROLE 2/4 — `.git`-arquivo apontando para `.git/modules/<n>`."""
    filho = campo.repo(campo.tmp / "filho", arquivo="c.txt")
    _git("-C", str(filho), "add", "c.txt")
    _git("-C", str(filho), "commit", "-qm", "c")

    super_ = campo.repo(campo.raiz / "super", arquivo=None)
    r = subprocess.run([GIT, "-C", str(super_), "-c",
                        "protocol.file.allow=always", "submodule", "add", "-q",
                        str(filho), "sub"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"submodule add indisponível neste host: {r.stderr[:160]}")
    assert (super_ / "sub" / ".git").is_file(), "o cenário não montou submódulo"

    (super_ / "sub" / "novo.txt").write_text("novo\n")
    res = campo.add(super_ / "sub", "novo.txt")
    assert res.efeito_aplicado
    assert "novo.txt" in campo.indice(super_ / "sub")


def test_c1_10_SEPARATE_GIT_DIR_sem_titularidade_e_RECUSADO(campo):
    """SECURITY_BREAKING_CHANGE — `UNPROVABLE_GITDIR_OWNERSHIP = REFUSE`.

    Este teste exigia o layout FUNCIONANDO. Mudou de lado porque
    `--separate-git-dir` não grava dono em lugar nenhum, e é a porta das duas
    formas P0 de confusão cross-repo (A2-REPO.7.12 / 9.05b).
    """
    trabalho = campo.raiz / "work"
    gitdir = campo.raiz / "realgit"
    trabalho.mkdir()
    _git("init", "-q", "-b", "main", "--separate-git-dir", str(gitdir),
         str(trabalho))
    _git("-C", str(trabalho), "config", "user.email", "a@b.c")
    _git("-C", str(trabalho), "config", "user.name", "T")
    (trabalho / "x.txt").write_text("x\n")

    with pytest.raises(supervisor.ErroSeguranca, match="não registra dono"):
        campo.add(trabalho, "x.txt")
    assert "x.txt" not in campo.indice(trabalho)


def test_c1_10_cross_repo_via_SEPARATE_GIT_DIR_e_RECUSADO(campo):
    """A forma que derrubou a primeira correção: basename != `.git`.

    `hostil/.git -> gitdir: <vitima-gd>`, com os DOIS repositórios dentro das
    raízes aprovadas. O discriminador antigo (`gd.name == '.git'`) não via.
    """
    vitima = campo.raiz / "vitima"
    gd = campo.raiz / "vitima-gd"
    vitima.mkdir()
    _git("init", "-q", "-b", "main", "--separate-git-dir", str(gd), str(vitima))
    _git("-C", str(vitima), "config", "user.email", "a@b.c")
    _git("-C", str(vitima), "config", "user.name", "T")
    (vitima / "seed.txt").write_text("seed\n")
    _git("-C", str(vitima), "add", "seed.txt")
    _git("-C", str(vitima), "commit", "-qm", "seed")
    antes = subprocess.run([GIT, f"--git-dir={gd}", "ls-files"],
                           capture_output=True, text=True).stdout

    hostil = campo.raiz / "hostil"
    hostil.mkdir()
    (hostil / ".git").write_text(f"gitdir: {gd}\n")
    (hostil / "s.txt").write_text("AWS_SECRET_ACCESS_KEY=DO_ATACANTE\n")

    with pytest.raises(supervisor.ErroSeguranca):
        campo.add(hostil, "s.txt")

    depois = subprocess.run([GIT, f"--git-dir={gd}", "ls-files"],
                            capture_output=True, text=True).stdout
    assert depois == antes, "INDEX_UNCHANGED=FALSE — o segredo entrou na vítima"


def test_c1_10_prova_de_titularidade_FORJADA_backpointer(campo):
    """A prova tem de casar com o que o Git HONRA, não só com o que existe.

    MEDIDO: plantar `<vitima>/.git/gitdir` = `<hostil>/.git` (85 bytes) imitava
    o backpointer de worktree ligada e o NOMOS aceitava. O Git IGNORA esse
    arquivo num git dir PRINCIPAL — então a adulteração era INERTE para o Git e
    AUTORITATIVA para o NOMOS, a pior combinação possível: a vítima seguia
    normal em toda inspeção (`rev-parse --show-toplevel` do hostil devolvia
    hostil) e o segredo entrava no índice, no store e na história dela.

    O backpointer só vale onde o Git realmente o lê: `<common>/worktrees/<n>`.
    """
    vitima = campo.repo(campo.raiz / "vitima", arquivo="ok.txt")
    _git("-C", str(vitima), "add", "ok.txt")
    _git("-C", str(vitima), "commit", "-qm", "inicial")

    hostil = campo.raiz / "hostil"
    hostil.mkdir()
    (hostil / ".git").write_text(f"gitdir: {vitima / '.git'}\n")
    (hostil / "segredo.txt").write_text("AWS_SECRET_ACCESS_KEY=hunter2\n")
    (vitima / ".git" / "gitdir").write_text(f"{hostil / '.git'}\n")

    with pytest.raises(supervisor.ErroSeguranca):
        campo.add(hostil, "segredo.txt")
    assert "segredo.txt" not in campo.indice(vitima)


def test_c1_10_prova_de_titularidade_FORJADA_secao_de_config(campo):
    """`worktree` fora de `[core]` é inerte para o Git — e era prova aqui.

    O parser não era sensível a seção: uma linha sob `[naoexiste]` valia como
    registro de submódulo. O Git só honra `[core] worktree`.
    """
    vitima = campo.repo(campo.raiz / "vitima", arquivo="ok.txt")
    _git("-C", str(vitima), "add", "ok.txt")
    _git("-C", str(vitima), "commit", "-qm", "inicial")

    hostil = campo.raiz / "hostil"
    hostil.mkdir()
    (hostil / ".git").write_text(f"gitdir: {vitima / '.git'}\n")
    (hostil / "segredo.txt").write_text("AWS_SECRET_ACCESS_KEY=hunter2\n")
    with open(vitima / ".git" / "config", "a") as f:
        f.write(f"[naoexiste]\n\tworktree = {hostil}\n")

    with pytest.raises(supervisor.ErroSeguranca):
        campo.add(hostil, "segredo.txt")
    assert "segredo.txt" not in campo.indice(vitima)


def test_c1_10_cross_repo_via_GIT_MODULES_e_RECUSADO(campo):
    """A segunda forma: apontar para `.git/modules/<n>` de outro superprojeto."""
    filho = campo.tmp / "filho"
    filho.mkdir()
    _git("init", "-q", "-b", "main", str(filho))
    _git("-C", str(filho), "config", "user.email", "a@b.c")
    _git("-C", str(filho), "config", "user.name", "T")
    (filho / "c.txt").write_text("c\n")
    _git("-C", str(filho), "add", "c.txt")
    _git("-C", str(filho), "commit", "-qm", "c")

    super_ = campo.raiz / "super2"
    super_.mkdir()
    _git("init", "-q", "-b", "main", str(super_))
    _git("-C", str(super_), "config", "user.email", "a@b.c")
    _git("-C", str(super_), "config", "user.name", "T")
    r = subprocess.run([GIT, "-C", str(super_), "-c",
                        "protocol.file.allow=always", "submodule", "add", "-q",
                        str(filho), "sub"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"submodule add indisponível: {r.stderr[:160]}")

    gd = super_ / ".git" / "modules" / "sub"
    hostil = campo.raiz / "hostil2"
    hostil.mkdir()
    (hostil / ".git").write_text(f"gitdir: {gd}\n")
    (hostil / "s.txt").write_text("SEGREDO\n")

    with pytest.raises(supervisor.ErroSeguranca, match="OUTRA working tree"):
        campo.add(hostil, "s.txt")


def test_c1_10_legitimo_REPO_COMUM_continua_funcionando(campo):
    """CONTROLE 4/4 — `.git` como DIRETÓRIO, o caso de longe mais comum."""
    repo = campo.repo(campo.raiz / "comum")
    r = campo.add(repo, "a.txt")
    assert r.efeito_aplicado
    assert "a.txt" in campo.indice(repo)


# ═══════════════════════ C4.02 — alternates fora das raízes ══════════════════

def test_c4_02_alternates_fora_das_raizes_e_RECUSADO(campo):
    """A propriedade medida é a RECUSA do NOMOS, não a alcançabilidade no git cru.

    O arquivo `objects/info/alternates` continua no disco depois da recusa, e o
    `git` cru fora do NOMOS segue honrando-o — isso é esperado e não é o
    critério. O que se mede aqui é a operação GOVERNADA ter sido recusada e o
    índice não ter avançado.
    """
    estrangeiro = campo.repo(campo.tmp / "estrangeiro", arquivo="e.txt")
    _git("-C", str(estrangeiro), "add", "e.txt")
    _git("-C", str(estrangeiro), "commit", "-qm", "e")

    repo = campo.repo(campo.raiz / "repo")
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(f"{estrangeiro / '.git' / 'objects'}\n")

    with pytest.raises(supervisor.ErroSeguranca, match="alternado"):
        campo.add(repo, "a.txt")
    assert "a.txt" not in campo.indice(repo)


def test_c4_02_alternates_DENTRO_das_raizes_continua_funcionando(campo):
    """CONTROLE — alternate é mecanismo legítimo (clone --reference)."""
    vizinho = campo.repo(campo.raiz / "vizinho", arquivo="v.txt")
    _git("-C", str(vizinho), "add", "v.txt")
    _git("-C", str(vizinho), "commit", "-qm", "v")

    repo = campo.repo(campo.raiz / "repo")
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(f"{vizinho / '.git' / 'objects'}\n")

    r = campo.add(repo, "a.txt")
    assert r.efeito_aplicado, "alternate legítimo dentro das raízes foi recusado"


def test_c4_02_alternates_RELATIVO_para_fora_e_RECUSADO(campo):
    """Caminho relativo resolve contra `<base>/objects` — traversal também sai."""
    estrangeiro = campo.repo(campo.tmp / "est2", arquivo="e.txt")
    repo = campo.repo(campo.raiz / "repo")
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    rel = os.path.relpath(estrangeiro / ".git" / "objects",
                          repo / ".git" / "objects")
    (info / "alternates").write_text(f"{rel}\n")

    with pytest.raises(supervisor.ErroSeguranca, match="alternado"):
        campo.add(repo, "a.txt")


# ══════════════ C4.01 — replace refs não falsificam a leitura ════════════════

def test_c4_01_GIT_NO_REPLACE_OBJECTS_esta_no_ambiente_de_todas(campo):
    """Estrutural: a defesa mora no AMBIENTE, não numa lista por adapter.

    `_NEUTRALIZAR` é por adapter; `ambiente_minimo` é herdado por git-log,
    git-show, git-diff, git-add, git-commit, git-tag e git-push. Pôr a defesa
    ali é o que impede o buraco por construção.
    """
    assert git.ambiente_minimo()["GIT_NO_REPLACE_OBJECTS"] == "1"


def test_c4_01_replace_ref_nao_falsifica_git_show(campo):
    """MEDIDO antes: `git-show <sha real>` devolvia a mensagem de OUTRO commit."""
    repo = campo.repo(campo.raiz / "repo")
    _git("-C", str(repo), "add", "a.txt")
    _git("-C", str(repo), "commit", "-qm", "MENSAGEM_REAL_AUDITAVEL")
    real = _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip()
    (repo / "b.txt").write_text("b\n")
    _git("-C", str(repo), "add", "b.txt")
    _git("-C", str(repo), "commit", "-qm", "MENSAGEM_FORJADA_PELO_REPO")
    falso = _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip()
    _git("-C", str(repo), "replace", real, falso)

    rc = RegistroCapacidades(policy=PolicyEngine(campo.tmp / "p2.json"),
                             approver=lambda *a, **k: True)
    from nomos.adapters.wiring import registrar_git
    registrar_git(rc, raizes=(str(campo.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-show", "runtime-governado",
                                        raizes=(str(campo.raiz),))
    r = git.GitAdapter().executar(
        CapabilityRequest(capacidade="git-show", alvo=str(repo),
                          argumentos={"ref": real}), ctx)

    assert "MENSAGEM_REAL_AUDITAVEL" in r.valor
    assert "FORJADA" not in r.valor, (
        "o repositório falsificou a saída de uma capacidade de LEITURA — a "
        "evidência que o NOMOS usa para auditar a si mesmo")


# ═════════════════ HEAD escolhido pelo repositório (C4.03/C4.04) ═════════════

def test_c4_03_HEAD_para_refs_tags_nao_muta_a_tag(campo):
    repo = campo.repo(campo.raiz / "repo")
    _git("-C", str(repo), "add", "a.txt")
    _git("-C", str(repo), "commit", "-qm", "i")
    _git("-C", str(repo), "tag", "v1.0", "HEAD")
    antes = _git("-C", str(repo), "rev-parse", "v1.0").stdout.strip()
    (repo / ".git" / "HEAD").write_text("ref: refs/tags/v1.0\n")

    rc = RegistroCapacidades(policy=PolicyEngine(campo.tmp / "p3.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(campo.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-commit", "runtime-governado",
                                        raizes=(str(campo.raiz),))
    with pytest.raises(supervisor.ErroSeguranca, match="refs/heads"):
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-commit", alvo=str(repo),
                              argumentos={"mensagem": "cp"}), ctx)

    assert _git("-C", str(repo), "rev-parse", "v1.0").stdout.strip() == antes


def test_c4_04_HEAD_para_refs_replace_nao_instala_substituicao(campo):
    """O pior dos dois: o commit governado PLANTA a arma que falsifica leituras."""
    repo = campo.repo(campo.raiz / "repo")
    _git("-C", str(repo), "add", "a.txt")
    _git("-C", str(repo), "commit", "-qm", "i")
    sha = _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip()
    (repo / ".git" / "refs" / "replace").mkdir(parents=True, exist_ok=True)
    (repo / ".git" / "HEAD").write_text(f"ref: refs/replace/{sha}\n")

    rc = RegistroCapacidades(policy=PolicyEngine(campo.tmp / "p4.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(campo.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-commit", "runtime-governado",
                                        raizes=(str(campo.raiz),))
    with pytest.raises(supervisor.ErroSeguranca, match="refs/heads"):
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-commit", alvo=str(repo),
                              argumentos={"mensagem": "cp"}), ctx)

    assert not (repo / ".git" / "refs" / "replace" / sha).exists()


def test_c4_03_CONTROLE_commit_em_branch_normal_continua_funcionando(campo):
    """Sem isto, os dois testes acima passariam com `git-commit` morto."""
    repo = campo.repo(campo.raiz / "repo")
    _git("-C", str(repo), "add", "a.txt")

    rc = RegistroCapacidades(policy=PolicyEngine(campo.tmp / "p5.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(campo.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-commit", "runtime-governado",
                                        raizes=(str(campo.raiz),))
    r = git_tree.GitTreeAdapter().executar(
        CapabilityRequest(capacidade="git-commit", alvo=str(repo),
                          argumentos={"mensagem": "commit legitimo"}), ctx)
    assert r.efeito_aplicado
    assert _git("-C", str(repo), "log", "--oneline").stdout.strip()
