"""Contenção de HOOK do repositório — e qual defesa realmente a sustenta.

Um hook é o mecanismo mais direto que o repositório tem para executar código
durante uma operação governada: basta um arquivo executável em `.git/hooks/`.
A propriedade é `REPO_HOOK_EXEC=0`.

## Por que este arquivo existe separado de C2a/C2b

A evidência anterior de contenção de hook era VÁCUA, por duas razões medidas:

    canário em `tmp_path`   fora da raiz de escrita do sandbox: o hook podia
                            ter executado e mesmo assim não gravar
    espião `#!/bin/sh`      não executa sob a allowlist de exec — `/bin/sh`
                            reexecuta `/bin/bash` como variante

Com as duas juntas, `not canario.exists()` era verdade POR CONSTRUÇÃO. Aqui o
hook é BINÁRIO NATIVO e o canário mora no GIT DIR, que é a raiz de escrita
concedida — e há controle positivo provando que, sem NOMOS, ele grava.

## O que a medição revelou sobre QUAL defesa segura

Não é a que o nome sugere. Medido, por capacidade:

    git-add / git-commit / git-tag
        exec allowlist = só os dois literais do Git
        -> o hook não consegue nem ser exec'ed
        -> `-c core.hooksPath=/dev/null` é REDUNDANTE aqui (defesa em
           profundidade), e removê-lo NÃO muda o comportamento

    git-push
        exec allowlist = `(allow process-exec process-fork)` AMPLO
        -> a contenção vem do par `--no-verify` + `core.hooksPath=/dev/null`

E o par se MASCARA mutuamente. Tabela medida, hook nativo, canário gravável:

    hooksPath   --no-verify   HOOK EXECUTOU
    SIM         SIM           não
    NÃO         SIM           não
    SIM         NÃO           não
    NÃO         NÃO           SIM      <- a célula que prova que nenhum dos
                                          dois é decorativo

Isso é MASCARAMENTO (A8): nenhum dos dois flags, sozinho, tem teste
comportamental capaz de matá-lo, porque o outro segura. A consequência honesta
é que a regressão de cada flag só pode ser presa ESTRUTURALMENTE — e é o que
`test_hooks_09` e `test_hooks_10` fazem, dizendo por quê.

Registrar isso importa mais que escondê-lo: o dia em que a allowlist de exec do
push for reduzida (achado C13), o `--no-verify` deixa de ser mascarado e passa a
ter prova comportamental própria.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import git, git_push, git_tree, git_write, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import (
    registrar_git_push, registrar_git_tree, registrar_git_write,
)
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")

HOOKS = ("pre-commit", "post-commit", "prepare-commit-msg", "commit-msg",
         "pre-push", "post-checkout", "reference-transaction")


@pytest.fixture
def bancada(tmp_path, espiao_nativo):
    """Repo com hook NATIVO em todos os pontos e canário no GIT DIR."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    for k, v in (("user.email", "x@x"), ("user.name", "x")):
        subprocess.run([GIT, "-C", str(repo), "config", k, v], check=True,
                       capture_output=True)
    (repo / "a.txt").write_text("conteudo\n")
    subprocess.run([GIT, "-C", str(repo), "add", "a.txt"], check=True,
                   capture_output=True)
    subprocess.run([GIT, "-C", str(repo), "commit", "-qm", "inicial"],
                   check=True, capture_output=True)

    canario = repo / ".git" / "CANARIO"
    espiao = espiao_nativo(tmp_path, canario)
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    for h in HOOKS:
        shutil.copy2(espiao, hooks / h)
        (hooks / h).chmod(0o755)
    canario.unlink(missing_ok=True)

    class B:
        def __init__(self):
            self.repo, self.tmp, self.canario = repo, tmp_path, canario
            self.espiao = espiao

        def ctx(self, cap, registrar, **kw):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar(rc, raizes=(str(tmp_path),), **kw)
            return CapabilityContext.de_registro(rc, cap, "runtime-governado",
                                                 raizes=(str(tmp_path),))

    return B()


# ═══════════════ 01 — CONTROLE POSITIVO: o hook FUNCIONA ════════════════════

def test_hooks_01_CONTROLE_POSITIVO_o_hook_executa_sem_nomos(bancada):
    """Sem isto, TODA asserção de ausência neste arquivo é vácuo.

    Prova as duas metades que faltavam: o hook é executável de verdade (binário
    nativo) e o canário é gravável onde mora (git dir, a raiz de escrita).
    """
    (bancada.repo / "b.txt").write_text("b\n")
    subprocess.run([GIT, "-C", str(bancada.repo), "add", "b.txt"],
                   capture_output=True)
    r = subprocess.run([GIT, "-C", str(bancada.repo), "commit", "-qm", "cru"],
                       capture_output=True)
    assert r.returncode == 0
    assert bancada.canario.exists(), (
        "HOOK_EXECUTION_ATTEMPT_PROVEN=FALSE: o hook não executa nem com git "
        "cru, ou o canário não é gravável onde mora — de um jeito ou de outro, "
        "as asserções de ausência não mediriam contenção")


# ═══════════════ 02-04 — sob o NOMOS, o hook NÃO executa ════════════════════

def test_hooks_02_git_add_e_commit_nao_executam_hook(bancada):
    (bancada.repo / "b.txt").write_text("b\n")
    ad = git_tree.GitTreeAdapter()
    ad.executar(CapabilityRequest(capacidade="git-add", alvo=str(bancada.repo),
                                  argumentos={"caminhos": ["b.txt"]}),
                bancada.ctx("git-add", registrar_git_tree))
    r = ad.executar(
        CapabilityRequest(capacidade="git-commit", alvo=str(bancada.repo),
                          argumentos={"mensagem": "via nomos"}),
        bancada.ctx("git-commit", registrar_git_tree))
    assert r.efeito_aplicado, "a operação legítima falhou"
    assert not bancada.canario.exists(), "REPO_HOOK_EXEC != 0 em add/commit"


def test_hooks_03_git_tag_nao_executa_hook(bancada):
    r = git_write.GitTagAdapter().executar(
        CapabilityRequest(capacidade="git-tag", alvo=str(bancada.repo),
                          argumentos={"tag": "v1", "objeto": "HEAD"}),
        bancada.ctx("git-tag", registrar_git_write))
    assert r.efeito_aplicado
    assert not bancada.canario.exists(), "REPO_HOOK_EXEC != 0 em tag"


def test_hooks_04_git_push_nao_executa_hook(bancada):
    bare = bancada.tmp / "bare.git"
    subprocess.run([GIT, "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    d = git_push.DestinoGovernado(remote_id="o", url=f"file://{bare}",
                                  branch_destino="main")
    r = git_push.GitPushAdapter(destinos={"o": d}).executar(
        CapabilityRequest(capacidade="git-push", alvo=str(bancada.repo),
                          argumentos={"remote_id": "o", "ref": "main",
                                      "source_branch": "main"}),
        bancada.ctx("git-push", registrar_git_push, destinos={"o": d}))
    assert r.efeito_aplicado
    assert not bancada.canario.exists(), "REPO_HOOK_EXEC != 0 em push"


def test_hooks_05_CONTROLE_POSITIVO_o_push_cru_DISPARA_o_pre_push(bancada):
    """O par do 04: prova que `pre-push` é alcançável neste cenário.

    Sem ele, o verde do 04 poderia significar apenas que `file://` não dispara
    hook nenhum — e o teste mediria a escolha do transporte, não a contenção.
    """
    bare = bancada.tmp / "bare2.git"
    subprocess.run([GIT, "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    subprocess.run([GIT, "-C", str(bancada.repo), "remote", "add", "cru",
                    f"file://{bare}"], check=True, capture_output=True)
    subprocess.run([GIT, "-C", str(bancada.repo), "push", "-q", "cru",
                    "main:refs/heads/cru"], capture_output=True)
    assert bancada.canario.exists(), "o pre-push não é alcançável nem sem NOMOS"


# ═══════════ 06-08 — QUAL defesa segura, por capacidade (medido) ════════════

def test_hooks_06_add_commit_tag_tem_exec_allowlist_restrita(bancada):
    """A defesa ATIVA aqui é a allowlist de exec, não a neutralização."""
    conf = git.confinamento_de_repo(bancada.repo)
    execs = [ln for ln in supervisor.perfil(conf).splitlines()
             if "process-exec" in ln]
    assert execs, "o perfil não declara exec — algo mudou de forma relevante"
    assert all("(literal " in ln for ln in execs), (
        f"exec deixou de ser por literal: {execs}")
    assert not any("hooks" in ln for ln in execs)


def test_hooks_07_push_tem_exec_POR_LITERAL_C13_corrigido(bancada):
    """C13 FECHADO — este teste mudou de lado, e era para mudar mesmo.

    A versão anterior prendia o DEFEITO: exigia
    `(allow process-exec process-fork)` e dizia "quando C13 for corrigido, este
    teste falha — e é assim que se descobre que a correção chegou". Chegou.

    O push agora declara allowlist por LITERAL. A allowlist inclui o shell, e
    isso é medição e não conveniência: o transporte local do Git executa
    `git-receive-pack '<destino>'` ATRAVÉS de um shell, e só com os dois
    binários de git o push legítimo morre em `cannot exec 'git-receive-pack …':
    Operation not permitted`.

    Incluir o shell parece devolver tudo, e não devolve — a allowlist vale para
    a árvore INTEIRA de processos, então o shell só executa o que também está
    nela. É o que `test_hooks_07b` mede.
    """
    bare = bancada.tmp / "bare.git"
    subprocess.run([GIT, "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    d = git_push.DestinoGovernado(remote_id="o", url=f"file://{bare}",
                                  branch_destino="main")
    conf = git_push.GitPushAdapter(destinos={"o": d}).confinamento(
        bancada.repo, d)
    execs = [ln for ln in supervisor.perfil(conf).splitlines()
             if "process-exec" in ln]
    assert execs, "o push ficou SEM allowlist de exec"
    assert "(allow process-exec process-fork)" not in execs, (
        "REGRESSÃO de C13: o push voltou ao exec AMPLO, e com ele a contenção "
        "de hook no push volta a depender só de --no-verify + core.hooksPath")
    assert all("literal" in ln for ln in execs), (
        f"exec do push deixou de ser por literal: {execs}")


def test_hooks_07b_a_allowlist_do_push_CONTEM_de_verdade(bancada):
    """O shell na allowlist não devolve a execução — medido, não argumentado.

    Sem este teste, `test_hooks_07` prova só que a lista existe; um `/bin/sh`
    ali dentro poderia significar contenção nenhuma. O que separa as duas
    hipóteses é rodar um binário que NÃO está na lista, a partir do shell que
    está.
    """
    bare = bancada.tmp / "bare.git"
    subprocess.run([GIT, "init", "-q", "--bare", str(bare)], check=True,
                   capture_output=True)
    d = git_push.DestinoGovernado(remote_id="o", url=f"file://{bare}",
                                  branch_destino="main")
    conf = git_push.GitPushAdapter(destinos={"o": d}).confinamento(
        bancada.repo, d)

    p = supervisor.executar(["/bin/sh", "-c", "/usr/bin/id"],
                            cwd=bancada.repo, env=git.ambiente_minimo(),
                            prazo=15.0, confinamento=conf)
    assert p.returncode != 0, (
        "o shell da allowlist executou /usr/bin/id — a allowlist não contém a "
        "ÁRVORE de processos, e o push voltou a poder rodar programa arbitrário")
    assert b"not permitted" in p.stderr.lower() or not p.stdout.strip()


def test_hooks_08_a_neutralizacao_sozinha_NAO_muda_add_commit(bancada,
                                                              monkeypatch):
    """Prova o MASCARAMENTO em vez de escondê-lo.

    Remover `-c core.hooksPath=/dev/null` de `add`/`commit` não faz o hook
    executar, porque a allowlist de exec já o impede. Um teste comportamental
    que dissesse provar essa neutralização estaria provando a allowlist.
    """
    sem = [x for x in git_tree._NEUTRALIZAR_TREE
           if x != "core.hooksPath=/dev/null"]
    sem = [x for i, x in enumerate(sem)
           if not (x == "-c" and i + 1 < len(sem) and sem[i + 1] == "-c")]
    monkeypatch.setattr(git_tree, "_NEUTRALIZAR_TREE", sem)

    (bancada.repo / "b.txt").write_text("b\n")
    ad = git_tree.GitTreeAdapter()
    ad.executar(CapabilityRequest(capacidade="git-add", alvo=str(bancada.repo),
                                  argumentos={"caminhos": ["b.txt"]}),
                bancada.ctx("git-add", registrar_git_tree))
    ad.executar(CapabilityRequest(capacidade="git-commit",
                                  alvo=str(bancada.repo),
                                  argumentos={"mensagem": "sem hooksPath"}),
                bancada.ctx("git-commit", registrar_git_tree))
    assert not bancada.canario.exists(), (
        "o hook executou sem a neutralização — então ela NÃO estava mascarada "
        "e o mascaramento documentado neste módulo precisa ser revisto")


# ═══════ 09-10 — a regressão de cada flag, presa ESTRUTURALMENTE ════════════

def test_hooks_09_neutralizacao_de_hooksPath_esta_presente(bancada):
    """Estrutural DE PROPÓSITO, e o docstring diz por quê.

    A prova comportamental é impossível enquanto a defesa estiver mascarada
    (ver 08). Prender a presença do flag é o que resta — e é honesto, desde que
    o teste não finja medir comportamento. Sem ele, apagar a neutralização não
    quebraria nada, e a defesa em profundidade sumiria em silêncio.
    """
    for lista, nome in ((git._NEUTRALIZAR, "git._NEUTRALIZAR"),
                        (git_tree._NEUTRALIZAR_TREE,
                         "git_tree._NEUTRALIZAR_TREE")):
        assert "core.hooksPath=/dev/null" in lista, (
            f"{nome} perdeu a neutralização de hooksPath")


def test_hooks_10_push_usa_no_verify(bancada):
    """A defesa que, no push, NÃO está mascarada pelo sandbox (exec é amplo).

    Estrutural pelo mesmo motivo do 09: `core.hooksPath` a mascara. A célula
    "ambos removidos" da tabela do módulo é o que prova que o par não é
    decorativo.
    """
    fonte = Path(git_push.__file__).read_text()
    assert '"--no-verify"' in fonte, (
        "git_push perdeu `--no-verify`: com exec AMPLO (C13) e sem ele, o "
        "hook do repositório passa a executar durante o push")
