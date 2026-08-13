"""C2c — as reduções que NÃO foram adotadas, e a medição que as barra.

Autoridade ampla preservada precisa de justificativa medida e registrada, não
de silêncio. Este arquivo é essa justificativa em forma executável: se alguém
tentar apertar `file-read*` ou `process-exec` no futuro, estes testes falham e
explicam por quê.

O achado que reorganizou a fase: reduzir `file-read*` ao piso medido produz
EXATAMENTE a corrupção silenciosa que se atribuía à restrição de `process-exec`.
Um `filter.clean` LEGÍTIMO — git-lfs, git-crypt, qualquer redator caseiro — lê
configuração fora do repositório. Sem essa leitura ele falha, e o Git indexa o
conteúdo NÃO filtrado com `rc=0`. O segredo entra em claro no objeto.

A primeira medição desta dimensão só testou filtro HOSTIL, onde ser bloqueado é
o objetivo. Um filtro que precisa funcionar nunca foi exercitado — e é ele que
decide.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from nomos.adapters import git as mod_git
from nomos.adapters import supervisor

GIT = "/usr/bin/git"
SED = "/usr/bin/sed"
pytestmark = pytest.mark.skipif(
    not (Path(supervisor.SANDBOX).exists() and Path(GIT).exists()),
    reason="sandbox-exec ou git ausentes (fora do macOS)")


def _git(repo, *args, **kw):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run([GIT, "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, **kw)


def _rodar(texto_perfil, *argv, cwd=None):
    fd, sb = tempfile.mkstemp(suffix=".sb")
    with os.fdopen(fd, "w") as fh:
        fh.write(texto_perfil)
    try:
        return subprocess.run(
            [supervisor.SANDBOX, "-f", sb, *argv], capture_output=True,
            text=True, timeout=60, cwd=cwd, stdin=subprocess.DEVNULL,
            env=dict(mod_git.ambiente_minimo(), GIT_AUTHOR_NAME="t",
                     GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                     GIT_COMMITTER_EMAIL="t@t"))
    finally:
        os.unlink(sb)


@pytest.fixture()
def repo_com_filtro_legitimo(tmp_path):
    """Repositório com um redator REAL: troca SEGREDO= por REDIGIDO=.

    A regra do `sed` vive FORA do repositório, como em qualquer redator de
    verdade — a configuração de redação não se versiona junto com o que ela
    redige. É exatamente essa leitura externa que o piso de `file-read` corta.
    """
    fora = tmp_path / "config"
    fora.mkdir()
    regras = fora / "regras.sed"
    regras.write_text("s/SEGREDO=/REDIGIDO=/\n")

    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main", check=True)
    _git(r, "config", "filter.redator.clean", f"{SED} -f {regras}", check=True)
    (r / ".gitattributes").write_text("*.txt filter=redator\n")
    (r / "seed").write_text("x")
    _git(r, "add", "seed", check=True)
    _git(r, "commit", "-qm", "seed", check=True)
    return r, regras


def _perfil(repo, leitura: str) -> str:
    """Perfil atual, trocando SÓ a linha de leitura. Uma variável por vez."""
    marca = supervisor.criar_marca()
    marca.conferir()
    conf = supervisor.Confinamento(
        escrita=mod_git.confinamento_de_repo(repo).escrita, marca=marca)
    return supervisor.perfil(conf).replace("(allow file-read*)", leitura), marca


def _indexar(repo, texto_perfil, arquivo="s.txt", binario=GIT):
    (repo / arquivo).write_text("SEGREDO=abc123\n")
    real = os.path.realpath(repo)
    add = _rodar(texto_perfil, binario, "-C", real, "--no-pager",
                 *mod_git._NEUTRALIZAR, "add", "--", arquivo)
    conteudo = _git(repo, "cat-file", "-p", f":{arquivo}").stdout
    return add, conteudo


def _git_real() -> str | None:
    """O git de verdade por trás do shim `/usr/bin/git`.

    O shim do xcrun resolve o developer dir por `/var/select/developer_dir`, e é
    essa resolução que o piso de leitura corta primeiro — antes de o filtro
    sequer rodar. Para medir a corrupção é preciso passar por cima dele.
    """
    p = subprocess.run(["/usr/bin/xcode-select", "-p"], capture_output=True,
                       text=True)
    if p.returncode != 0:
        return None
    alvo = Path(p.stdout.strip()) / "usr" / "bin" / "git"
    return str(alvo) if alvo.exists() else None


# ══════ file-read*: REQUIRED_MEASURED — reduzir corrompe em silêncio ════════

def test_perfil_atual_deixa_um_filtro_LEGITIMO_funcionar(repo_com_filtro_legitimo):
    """Controle positivo do limite: hoje o redator funciona e redige."""
    repo, _regras = repo_com_filtro_legitimo
    texto, marca = _perfil(repo, "(allow file-read*)")
    try:
        add, conteudo = _indexar(repo, texto)
        assert add.returncode == 0, add.stderr[:400]
        assert conteudo.strip() == "REDIGIDO=abc123", (
            f"o filtro legítimo não redigiu: {conteudo!r}")
    finally:
        import shutil
        shutil.rmtree(marca.execdir, ignore_errors=True)


def test_piso_de_leitura_quebra_o_binario_que_o_NOMOS_usa(
        repo_com_filtro_legitimo):
    """BLOQUEIO 1, com o `/usr/bin/git` que o NOMOS de fato invoca.

    O shim do xcrun resolve o developer dir lendo `/var/select/developer_dir`.
    O piso corta essa leitura e a operação morre antes de chegar ao Git, com
    uma mensagem que manda o operador reinstalar o Xcode — diagnóstico que
    aponta para o lugar errado.
    """
    repo, _regras = repo_com_filtro_legitimo
    piso = ('(allow file-read* (literal "/") (literal "/dev/null") '
            f'(subpath "{os.path.realpath(repo)}"))')
    texto, marca = _perfil(repo, piso)
    try:
        add, _conteudo = _indexar(repo, texto, "p.txt")
        assert add.returncode != 0
        assert "xcode-select" in add.stderr or "command line tools" in add.stderr
    finally:
        import shutil
        shutil.rmtree(marca.execdir, ignore_errors=True)


def test_piso_de_leitura_CORROMPE_EM_SILENCIO_com_o_git_real(
        repo_com_filtro_legitimo):
    """BLOQUEIO 2, o decisivo. A justificativa medida de manter `file-read*`.

    Este teste PRESERVA um defeito em vez de corrigi-lo, de propósito: ele
    documenta de forma executável por que a redução mais atraente da fase está
    barrada. Passando por cima do shim, o piso deixa de quebrar ruidosamente e
    passa a fazer coisa pior — o `add` devolve `rc=0`, o NOMOS reporta SUCESSO,
    e o objeto Git guarda o segredo EM CLARO, porque o filtro legítimo não
    conseguiu ler a própria regra.

    Trocar autoridade ampla por corrupção silenciosa é péssimo negócio: a
    autoridade é auditável, a corrupção não. A medição original desta dimensão
    só exercitou filtro HOSTIL, onde ser bloqueado é o objetivo; quem decide é
    o filtro que precisa FUNCIONAR.
    """
    real = _git_real()
    if real is None:
        pytest.skip("git real não resolvível por xcode-select neste host")
    repo, _regras = repo_com_filtro_legitimo
    piso = ('(allow file-read* (literal "/") (literal "/dev/null") '
            f'(subpath "{os.path.realpath(repo)}"))')
    texto, marca = _perfil(repo, piso)
    try:
        add, conteudo = _indexar(repo, texto, "p.txt", binario=real)
        assert add.returncode == 0, (
            "o piso passou a FALHAR ruidosamente — se isso mudou, a redução de "
            f"file-read volta à mesa e deve ser remedida. stderr={add.stderr[:300]}")
        assert conteudo.strip() == "SEGREDO=abc123", (
            f"o piso deixou de corromper ({conteudo!r}) — remeça a dimensão")
        assert "Operation not permitted" in add.stderr
    finally:
        import shutil
        shutil.rmtree(marca.execdir, ignore_errors=True)


# ═══════ git-tag: por que o git dir, e não `.git/refs/tags` ════════════════

def test_repo_hostil_nao_derruba_git_tag_com_uma_linha_de_config(tmp_path):
    """`core.logAllRefUpdates=always` faz o Git escrever reflog para tags.

    Com a autoridade limitada a `.git/refs/tags` — a redução "óbvia" para
    `git-tag` — qualquer repositório desliga a capacidade com uma linha de
    config: `rc=128`, "unable to create directory for '.git/logs/refs/tags'".
    Falha fechada, mas é negação de serviço governada pelo repositório hostil.
    `_NEUTRALIZAR_TAG` não cobre essa chave, e cobrir cada chave nova seria
    correr atrás. O git dir inteiro é o ponto estável.
    """
    from nomos.adapters.git_write import GitTagAdapter
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.wiring import registrar_git_write
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades

    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main", check=True)
    _git(r, "commit", "-qm", "p0", "--allow-empty", check=True)
    _git(r, "config", "core.logAllRefUpdates", "always", check=True)

    reg = RegistroCapacidades(policy=PolicyEngine(tmp_path / "p.json"),
                              approver=lambda *a, **k: True)
    registrar_git_write(reg, raizes=(str(tmp_path),))
    GitTagAdapter().executar(
        CapabilityRequest(capacidade="git-tag", alvo=str(r),
                          argumentos={"tag": "v1", "objeto": "HEAD"}),
        CapabilityContext.de_registro(reg, "git-tag", "runtime-governado",
                                      raizes=(str(tmp_path),)))
    assert "v1" in _git(r, "tag", "-l").stdout
    assert (r / ".git" / "logs" / "refs" / "tags" / "v1").exists(), (
        "o reflog de tag não foi criado — o cenário que derruba a redução "
        "`refs/tags` deixou de existir e este teste perdeu o sentido")


# ═════════ git-push: publica por URL, nunca por nome de remote ═════════════

def test_push_publica_por_URL_e_nao_por_nome_de_remote():
    """Estrutural, e o motivo NÃO é o TOCTOU do destino governado.

    Publicar por NOME de remote faz o Git tentar atualizar a ref de
    rastreamento local (`refs/remotes/<nome>/...`). Com a escrita reduzida ao
    git dir do destino isso vira `rc=0` com `update_ref failed` no stderr —
    falha PARCIAL silenciosa, porque o adapter só olha o código de retorno.

    A propriedade "push não escreve no repositório local" é consequência deste
    argv, não uma verdade estrutural do Git. Trocar por nome de remote a
    quebraria sem nenhum teste reclamar — daí esta trava.
    """
    fonte = Path("src/nomos/adapters/git_push.py").read_text()
    assert "destino.url, refspec]" in fonte, (
        "o argv de push mudou; se passou a usar nome de remote, a escrita "
        "local volta a ser necessária e a falha parcial fica invisível")
    assert 'f"refs/heads/{origem}:refs/heads/{alvo_branch}"' in fonte
