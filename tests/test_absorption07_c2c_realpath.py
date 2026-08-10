"""C2c / seção 1 — LANDMINE PERMANENTE: política de sandbox usa `realpath`.

Este landmine já apareceu DUAS vezes nesta série, com sintomas opostos e causa
idêntica — confiar no pathname lógico em vez do real:

- **GATE C**: o guard de symlink caminhava até `/`, e como `/tmp` e `/var` são
  symlinks no macOS, uma raiz sob eles tornava TODA mutação impossível. Falsa
  negação da operação legítima.
- **C2c**: o perfil `sandbox-exec` com `(subpath "/tmp/...")` nunca casava com
  o caminho real que o Git usa (`/private/tmp/...`), e `git add` falhava com
  "Operation not permitted" em `.git/index.lock`. Mesma falsa negação, outro
  mecanismo.

O teste cobre as DUAS direções que a missão exige: a operação autorizada
precisa funcionar, e a fronteira não pode ter sido ampliada para conseguir
isso. Um perfil que funcionasse liberando o pai do repositório passaria no
primeiro critério e falharia no segundo — que é exatamente o erro tentador.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

SANDBOX = "/usr/bin/sandbox-exec"
GIT = "/usr/bin/git"
pytestmark = pytest.mark.skipif(
    not (Path(SANDBOX).exists() and Path(GIT).exists()),
    reason="sandbox-exec ou git ausentes (fora do macOS)")

_PERFIL = """(version 1)
(deny default)
(deny network*)
(allow process-exec process-fork)
(allow file-read*)
(allow sysctl-read)
(allow mach-lookup)
(allow file-write* (literal "/dev/null"))
(allow file-write* (subpath "{raiz}"))
"""


def perfil_para(caminho: str) -> str:
    """A política SEMPRE canonicaliza. É a linha que este arquivo protege."""
    return _PERFIL.format(raiz=os.path.realpath(caminho))


def _git(repo, *args, **kw):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run([GIT, "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, **kw)


def _sob_sandbox(perfil: Path, *argv, timeout=30):
    return subprocess.run([SANDBOX, "-f", str(perfil), *argv],
                          capture_output=True, text=True, timeout=timeout,
                          stdin=subprocess.DEVNULL)


@pytest.fixture()
def repo_sob_tmp():
    """Repo sob `/tmp` DE PROPÓSITO — `tmp_path` do pytest já vem resolvido e
    esconderia o cenário, como escondeu no GATE C."""
    base = Path(tempfile.mkdtemp(dir="/tmp"))
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main", check=True)
    (repo / "a.txt").write_text("l1\n")
    _git(repo, "add", "a.txt", check=True)
    _git(repo, "commit", "-qm", "p1", check=True)
    fora = base / "FORA.txt"
    fora.write_text("protegido")
    yield base, repo, fora
    subprocess.run(["/bin/rm", "-rf", str(base)], check=False)


def test_c2c_cenario_existe_o_caminho_logico_difere_do_real(repo_sob_tmp):
    """Sem esta diferença o teste inteiro é inócuo."""
    base, repo, _fora = repo_sob_tmp
    assert str(repo).startswith("/tmp/")
    assert os.path.realpath(repo) != str(repo), (
        "/tmp deixou de ser symlink neste host — o cenário do landmine sumiu "
        "e este teste precisa de outro caminho para continuar significando algo")


def test_c2c_perfil_do_caminho_LOGICO_quebra_a_operacao(repo_sob_tmp, tmp_path):
    """A falsa negação, congelada.

    É o sintoma que custou três medições para eu diagnosticar: o erro aponta
    para `.git/index.lock`, sugerindo permissão faltante, quando a causa é o
    caminho não bater.
    """
    _base, repo, _fora = repo_sob_tmp
    p = tmp_path / "logico.sb"
    p.write_text(_PERFIL.format(raiz=str(repo)))     # SEM realpath, de propósito
    (repo / "b.txt").write_text("novo\n")
    r = _sob_sandbox(p, GIT, "-C", str(repo), "add", "--", "b.txt")
    assert r.returncode != 0, (
        "o perfil do caminho lógico funcionou — ou /tmp deixou de ser symlink, "
        "ou o sandbox mudou de semântica; revise antes de confiar")
    assert not _git(repo, "diff", "--cached", "--name-only").stdout.strip()


def test_c2c_perfil_canonicalizado_permite_a_operacao(repo_sob_tmp, tmp_path):
    """Direção 1: a operação autorizada FUNCIONA."""
    _base, repo, _fora = repo_sob_tmp
    p = tmp_path / "real.sb"
    p.write_text(perfil_para(str(repo)))
    (repo / "b.txt").write_text("novo\n")
    real = os.path.realpath(repo)
    r = _sob_sandbox(p, GIT, "-C", real, "add", "--", "b.txt")
    assert r.returncode == 0, r.stderr
    assert "b.txt" in _git(repo, "diff", "--cached", "--name-only").stdout
    c = _sob_sandbox(p, GIT, "-C", real, "commit", "-qm", "dentro-do-sandbox")
    assert c.returncode == 0, c.stderr
    assert "dentro-do-sandbox" in _git(repo, "log", "--oneline", "-1").stdout


def test_c2c_perfil_canonicalizado_NAO_amplia_a_fronteira(repo_sob_tmp, tmp_path):
    """Direção 2: e a fronteira não foi alargada para conseguir isso.

    Sem este teste, "faça a operação funcionar" tem uma solução trivial e
    errada — liberar o diretório PAI. Ela passaria no teste anterior.
    """
    base, repo, fora = repo_sob_tmp
    p = tmp_path / "real.sb"
    p.write_text(perfil_para(str(repo)))
    _sob_sandbox(p, "/bin/sh", "-c", f"echo INVADIDO > {fora}")
    assert fora.read_text() == "protegido", "escrita FORA do repo passou"
    alvo_pai = base / "no-pai.txt"
    _sob_sandbox(p, "/bin/sh", "-c", f"echo X > {alvo_pai}")
    assert not alvo_pai.exists(), "o perfil liberou o diretório PAI do repo"


def test_c2c_perfil_canonicalizado_mantem_rede_negada(repo_sob_tmp, tmp_path):
    """A canonicalização não pode ter afrouxado `deny network*`."""
    _base, repo, _fora = repo_sob_tmp
    p = tmp_path / "real.sb"
    p.write_text(perfil_para(str(repo)))
    r = _sob_sandbox(p, "/usr/bin/python3", "-c",
                     "import socket;s=socket.socket();s.settimeout(2)\n"
                     "try:\n s.connect(('127.0.0.1',9)); print('CONECTOU')\n"
                     "except PermissionError: print('NEGADA')\n"
                     "except Exception as e: print(type(e).__name__)")
    assert "NEGADA" in r.stdout, r.stdout + r.stderr


def test_c2c_gerador_de_perfil_canonicaliza_sempre(tmp_path):
    """Estrutural: `perfil_para` não pode deixar de resolver.

    Prende a FUNÇÃO, não o efeito — se alguém trocar `os.path.realpath` por
    `str()` numa refatoração, isto falha mesmo que o ambiente do teste esconda
    o sintoma.
    """
    d = tmp_path / "x"
    d.mkdir()
    link = tmp_path / "atalho"
    link.symlink_to(d, target_is_directory=True)
    perfil = perfil_para(str(link))
    assert str(d.resolve()) in perfil
    assert f'(subpath "{link}")' not in perfil, (
        "o gerador usou o pathname lógico — o landmine do realpath voltou")
