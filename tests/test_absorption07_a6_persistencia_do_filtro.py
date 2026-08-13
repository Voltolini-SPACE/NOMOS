"""A6 — o filtro contido não consegue instalar o próximo.

O censo mediu 12 vetores de subprocesso disparados por config do repositório.
Onze já estavam selados (`core.hooksPath=/dev/null` + `--no-verify`,
`credential.helper=`, `--no-ext-diff`, `--no-textconv`, pager/editor,
`core.sshCommand`, aliases `!`, `core.fsmonitor=false`). Sobrava UM que executa
por desenho: `filter.clean/smudge` — o filtro É o mecanismo do `git add`.

Esse é contido pelo sandbox. Mas contenção que vale UMA vez não é contenção:
o filtro rodava com escrita no git dir inteiro, e podia INSTALAR o próximo —
gravando `hooks/pre-commit`, reescrevendo `config` com outro `filter.*.clean`,
ou ligando arquivos a um filtro por `info/attributes`.

A6 fecha os três, e o custo medido foi zero: `git add` e `git commit` não
escrevem em nenhum deles (`quebras=[]` no censo).

    hooks/   programa que o Git executa em eventos futuros
    config   filter.*.clean, core.fsmonitor, aliases `!`
    info/    info/attributes liga arquivo a filtro, como .gitattributes

A ordem no perfil é o que faz funcionar: em SBPL a ÚLTIMA regra que casa vence,
então os `deny` são emitidos DEPOIS do `allow` da raiz que os contém.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from nomos.adapters import git as mod_git
from nomos.adapters import supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
SANDBOX = supervisor.SANDBOX
pytestmark = pytest.mark.skipif(
    not (Path(GIT).exists() and Path(SANDBOX).exists()),
    reason="git ou sandbox-exec ausente")

ALVOS = ("hooks/pre-commit", "config", "info/attributes")


def _git(repo, *a):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run([GIT, "-C", str(repo), *a], capture_output=True,
                          text=True, env=env)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("conteudo\n")
    _git(r, "add", "--", "a.txt")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _sob(conf, *argv):
    fd, caminho = tempfile.mkstemp(suffix=".sb")
    with os.fdopen(fd, "w") as fh:
        fh.write(supervisor.perfil(conf))
    try:
        return subprocess.run([SANDBOX, "-f", caminho, *argv],
                              capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)
    finally:
        os.unlink(caminho)


# Depois de A5 a capacidade só admite o Git. A sonda que escreve com `/bin/sh`
# precisa declarar o próprio executável — senão mede a allowlist de exec em vez
# da fronteira de ESCRITA que pretende medir.
# `/bin/sh` neste host RE-EXECUTA `/bin/bash` ("Failed to exec /bin/bash as
# variant for /bin/sh"). Declarar só o sh dá exec negado — landmine medido no
# censo. A sonda precisa dos dois; a CAPACIDADE continua sem nenhum.
_SONDA = ("/bin/sh", "/bin/bash")


def _sem_a6(repo):
    """Perfil ANTERIOR a A6: git dir gravável inteiro, sem as negações."""
    conf = mod_git.confinamento_de_repo(repo)
    return supervisor.Confinamento(escrita=conf.escrita, rede=conf.rede,
                                   exec_permitido=conf.exec_permitido + _SONDA)


def _com_sonda(repo):
    import dataclasses
    conf = mod_git.confinamento_de_repo(repo)
    return dataclasses.replace(conf,
                               exec_permitido=conf.exec_permitido + _SONDA)


# ═════ CONTROLE POSITIVO — a persistência FUNCIONAVA antes de A6 ════════════

@pytest.mark.parametrize("alvo", ALVOS)
def test_controle_positivo_sem_a6_o_filtro_instalava_o_proximo(repo, alvo):
    """Sem isto, os testes de negação abaixo não provam nada."""
    git_dir = Path(mod_git.diretorio_git(repo)[0])
    destino = git_dir / alvo
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.unlink(missing_ok=True)

    r = _sob(_sem_a6(repo), "/bin/sh", "-c", f"echo PLANTADO > {destino}")
    assert r.returncode == 0, r.stderr[:200]
    assert destino.exists() and "PLANTADO" in destino.read_text(), (
        f"o perfil anterior já negava {alvo}; não há redução a provar")


@pytest.mark.parametrize("alvo", ALVOS)
def test_a6_nega_a_instalacao(repo, alvo):
    git_dir = Path(mod_git.diretorio_git(repo)[0])
    destino = git_dir / alvo
    destino.parent.mkdir(parents=True, exist_ok=True)
    anterior = destino.read_text() if destino.exists() else None

    r = _sob(_com_sonda(repo), "/bin/sh", "-c",
             f"echo PLANTADO > {destino}")

    assert r.returncode != 0 or "PLANTADO" not in (
        destino.read_text() if destino.exists() else ""), (
        f"o filtro conseguiu instalar {alvo} — a contenção vale uma vez só")
    if anterior is not None:
        assert destino.read_text() == anterior, f"{alvo} foi alterado"


def test_o_resto_do_git_dir_CONTINUA_gravavel(repo):
    """A negação é cirúrgica. Negar o git dir inteiro quebraria o `add`."""
    git_dir = Path(mod_git.diretorio_git(repo)[0])
    r = _sob(_com_sonda(repo), "/bin/sh", "-c",
             f"echo ok > {git_dir}/NOMOS_CANARIO")
    assert r.returncode == 0, r.stderr[:200]
    assert (git_dir / "NOMOS_CANARIO").exists()


# ═══════════ A capacidade tem de continuar funcionando ══════════════════════

def _exec(repo, caminhos, tmp_path, capacidade="git-add"):
    registro = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                   approver=lambda *a, **k: True)
    registrar_git_tree(registro, raizes=(str(tmp_path),))
    args = ({"caminhos": caminhos} if capacidade == "git-add"
            else {"mensagem": "m"})
    from nomos.adapters import git_tree
    return git_tree.GitTreeAdapter().executar(
        CapabilityRequest(capacidade=capacidade, alvo=str(repo),
                          argumentos=args),
        CapabilityContext.de_registro(registro, capacidade,
                                      "runtime-governado",
                                      raizes=(str(tmp_path),)))


def test_add_e_commit_continuam_funcionando(repo, tmp_path):
    """`quebras=[]` do censo, verificado pelo caminho GOVERNADO."""
    (repo / "novo.txt").write_text("conteudo novo\n")
    assert _exec(repo, ["novo.txt"], tmp_path).efeito_aplicado is True
    assert _exec(repo, None, tmp_path,
                 capacidade="git-commit").efeito_aplicado is True
    assert "novo.txt" in _git(repo, "show", "--stat", "HEAD").stdout


def test_filtro_do_repo_NAO_EXECUTA_MAIS(repo, tmp_path):
    """CONTRATO NOVO (A5). Substitui `test_filtro_hostil_roda_mas_nao_persiste`.

    O teste antigo afirmava "o filtro roda e não persiste". Depois de A5 essa
    afirmação ficou FALSA por um motivo melhor: o filtro não roda. Mantê-lo
    verde exigiria readmitir a execução — foi exatamente o que a decisão de
    produto proibiu.

        REPOSITORY_MAY_DECLARE_REQUIREMENT     = TRUE
        REPOSITORY_MAY_GRANT_EXECUTION_AUTHORITY = FALSE
        NOMOS_POLICY_IS_SOLE_EXECUTION_AUTHORITY = TRUE

    O repositório declara `filter.hostil.clean` no `.git/config` e liga o
    arquivo por `.gitattributes` — isto é, PEDE execução. O NOMOS nega, e a
    negação é ALTA: `ErroSeguranca`, com o índice restaurado (A0.1) e o objeto
    descartado com a quarentena (A0.3).
    """
    git_dir = Path(mod_git.diretorio_git(repo)[0])
    filtro = repo / "filtro.sh"
    filtro.write_text(f"#!/bin/sh\necho RODOU > {git_dir}/CANARIO_A6\ncat\n")
    filtro.chmod(0o755)
    _git(repo, "config", "filter.hostil.clean", str(filtro))
    (repo / ".gitattributes").write_text("*.dat filter=hostil\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "dados.dat").write_text("conteudo\n")

    with pytest.raises(supervisor.ErroSeguranca) as exc:
        _exec(repo, ["dados.dat"], tmp_path)

    assert "cannot exec" in str(exc.value), str(exc.value)[:300]
    assert not (git_dir / "CANARIO_A6").exists(), (
        "o filtro do repositório EXECUTOU — NO_REPO_CONTROLLED_EXEC caiu")
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == "", (
        "a negação deixou conteúdo estagiado")


def test_filtro_LEGITIMO_tambem_e_negado_no_caminho_padrao(repo, tmp_path):
    """O custo da decisão, explícito em teste — não escondido.

    `/usr/bin/sed` é inofensivo, e mesmo assim é negado: o critério não é a
    índole do binário, é QUEM escolhe. Aqui quem escolheu foi o repositório.
    Preservar este caso é trabalho da capacidade governada (registry escolhe o
    executável), não de reabrir a porta no caminho padrão.
    """
    _git(repo, "config", "filter.redator.clean",
         "/usr/bin/sed -e s/SENHA=.*/REDIGIDO/")
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "x.secreto").write_text("SENHA=hunter2\n")

    with pytest.raises(supervisor.ErroSeguranca):
        _exec(repo, ["x.secreto"], tmp_path)
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == ""


# ═══════════════════════ Invariantes estruturais ════════════════════════════

def test_denies_vem_DEPOIS_dos_allows_no_perfil(repo):
    """Em SBPL a última regra que casa vence. Ordem invertida = deny inócuo."""
    p = supervisor.perfil(mod_git.confinamento_de_repo(repo))
    linhas = p.splitlines()
    ultimo_allow = max(i for i, linha in enumerate(linhas)
                       if linha.startswith("(allow file-write* (subpath"))
    primeiro_deny = min(i for i, linha in enumerate(linhas)
                        if linha.startswith("(deny file-write* (subpath"))
    assert primeiro_deny > ultimo_allow, (
        "deny emitido antes do allow — em SBPL isso o torna inócuo")


def test_os_tres_alvos_estao_negados_em_TODA_raiz(repo):
    conf = mod_git.confinamento_de_repo(repo)
    for raiz in conf.escrita:
        for nome in ("hooks", "info", "config"):
            assert any(n.endswith(f"{raiz}/{nome}") or n == f"{raiz}/{nome}"
                       for n in conf.negacao_de_escrita), (
                f"{nome} não negado na raiz {raiz}")


def test_capacidade_de_leitura_nao_precisa_de_negacao(repo):
    """Quem não escreve não precisa negar escrita — negação vazia é correta."""
    assert mod_git.confinamento_de_leitura(repo).negacao_de_escrita == ()


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
