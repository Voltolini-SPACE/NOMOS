"""C2c — o que a redução de perfil TIROU, provado com controle positivo.

Uma linha diferente no perfil não é uma redução; é uma linha diferente. Cada
teste aqui mede a autoridade que sumiu, e o faz comparando com o perfil ANTIGO
no mesmo cenário — sem esse par, "o filtro não conseguiu" pode significar
apenas que o filtro não tentou.

As duas reduções desta fase:

    file-write   repositório INTEIRO  ->  DIRETÓRIO GIT (working tree sai)
    mach-lookup  irrestrito           ->  um único global-name

E uma diferenciação por capacidade: as operações object-only (`git-log`,
`git-show`, `git-diff`) passam a rodar SEM nenhuma autoridade de escrita — não
prometem não escrever, não conseguem.
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
pytestmark = pytest.mark.skipif(
    not (Path(supervisor.SANDBOX).exists() and Path(GIT).exists()),
    reason="sandbox-exec ou git ausentes (fora do macOS)")


def _git(repo, *args, **kw):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run([GIT, "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, **kw)


def _sob(conf, *argv, cwd=None):
    fd, sb = tempfile.mkstemp(suffix=".sb")
    with os.fdopen(fd, "w") as fh:
        fh.write(supervisor.perfil(conf))
    try:
        return subprocess.run([supervisor.SANDBOX, "-f", sb, *argv],
                              capture_output=True, text=True, timeout=60,
                              cwd=cwd, stdin=subprocess.DEVNULL)
    finally:
        os.unlink(sb)


def _marca():
    m = supervisor.criar_marca()
    m.conferir()
    return m


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main", check=True)
    (r / "FONTE.txt").write_text("intacto")
    _git(r, "add", "FONTE.txt", check=True)
    _git(r, "commit", "-qm", "p0", check=True)
    return r


# ═══════════ file-write: a working tree saiu da autoridade de escrita ═══════

def test_perfil_antigo_PERMITIA_sobrescrever_a_working_tree(repo):
    """CONTROLE POSITIVO. Sem ele o teste seguinte não prova redução nenhuma.

    Era esta a principal autoridade que sobrava a um `filter.clean` hostil:
    reescrever o código-fonte do projeto durante um `git add` legítimo, com
    rc=0 e sem nenhum sinal.
    """
    m = _marca()
    try:
        antigo = supervisor.Confinamento(
            escrita=(supervisor.existente(repo),), marca=m)
        _sob(antigo, "/bin/sh", "-c", f"echo OWNED > {repo}/FONTE.txt")
        assert (repo / "FONTE.txt").read_text().strip() == "OWNED", (
            "o perfil ANTIGO já negava — então não há redução a provar aqui")
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)


def test_perfil_reduzido_NEGA_escrita_na_working_tree(repo):
    m = _marca()
    try:
        conf = supervisor.Confinamento(
            escrita=mod_git.confinamento_de_repo(repo).escrita, marca=m)
        _sob(conf, "/bin/sh", "-c", f"echo OWNED > {repo}/FONTE.txt")
        assert (repo / "FONTE.txt").read_text() == "intacto"
        # E um arquivo NOVO na working tree também não nasce.
        _sob(conf, "/bin/sh", "-c", f"echo x > {repo}/PLANTADO.txt")
        assert not (repo / "PLANTADO.txt").exists()
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)


def test_git_dir_continua_gravavel_e_add_commit_funcionam(repo, tmp_path):
    """A redução não vale nada se quebrar a operação autorizada."""
    from nomos.adapters import git_tree
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.wiring import registrar_git_tree
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades

    reg = RegistroCapacidades(policy=PolicyEngine(tmp_path / "p.json"),
                              approver=lambda *a, **k: True)
    registrar_git_tree(reg, raizes=(str(tmp_path),))
    ad = git_tree.GitTreeAdapter()

    def ctx(cap):
        return CapabilityContext.de_registro(reg, cap, "runtime-governado",
                                             raizes=(str(tmp_path),))

    (repo / "novo.txt").write_text("conteudo\n")
    ad.executar(CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": ["novo.txt"]}),
                ctx("git-add"))
    ad.executar(CapabilityRequest(capacidade="git-commit", alvo=str(repo),
                                  argumentos={"mensagem": "sob perfil reduzido"}),
                ctx("git-commit"))
    assert "sob perfil reduzido" in _git(repo, "log", "--oneline", "-1").stdout


@pytest.mark.parametrize("onde", ["pai", "irmao", "fora"])
def test_escrita_fora_do_git_dir_continua_negada(repo, tmp_path, onde):
    alvos = {"pai": tmp_path / "no-pai.txt",
             "irmao": tmp_path / "irmao.txt",
             "fora": tmp_path.parent / f"fora-{os.getpid()}.txt"}
    alvo = alvos[onde]
    m = _marca()
    try:
        conf = supervisor.Confinamento(
            escrita=mod_git.confinamento_de_repo(repo).escrita, marca=m)
        _sob(conf, "/bin/sh", "-c", f"echo X > {alvo}")
        assert not alvo.exists(), f"escrita alcançou {onde}"
    finally:
        alvo.unlink(missing_ok=True)
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)


def test_filtro_hostil_NAO_EXECUTA_no_caminho_padrao(repo, tmp_path):
    """CONTRATO NOVO (A5). Substitui o teste de "não reescreve o projeto".

    O contrato antigo media contenção DEPOIS da execução: o filtro rodava e a
    escrita fora do git dir era negada. Depois de A5 o contrato é anterior e
    mais forte — o filtro escolhido pelo repositório não executa.

    A defesa antiga (escrita limitada ao git dir, A3) continua no perfil como
    profundidade: se um dia uma capability futura reabrir exec, a fronteira de
    escrita ainda está lá.
    """
    import subprocess as _sp
    fonte = repo / "FONTE.txt"
    fonte.write_text("intacto")
    filtro = repo / "hostil.sh"
    filtro.write_text("#!/bin/sh\necho OWNED > %s\ncat\n" % fonte)
    filtro.chmod(0o755)
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    _sp.run([GIT, "-C", str(repo), "config", "filter.hostil.clean",
             str(filtro)], check=True, capture_output=True, env=env)
    (repo / ".gitattributes").write_text("*.dat filter=hostil\n")
    _sp.run([GIT, "-C", str(repo), "add", "--", ".gitattributes"],
            check=True, capture_output=True, env=env)
    _sp.run([GIT, "-C", str(repo), "commit", "-q", "-m", "attrs"],
            check=True, capture_output=True, env=env)
    (repo / "dados.dat").write_text("conteudo\n")

    from nomos.adapters import git_tree
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.wiring import registrar_git_tree
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades
    registro = RegistroCapacidades(policy=PolicyEngine(tmp_path / "p.json"),
                                   approver=lambda *a, **k: True)
    registrar_git_tree(registro, raizes=(str(tmp_path),))
    with pytest.raises(supervisor.ErroSeguranca) as exc:
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-add", alvo=str(repo),
                              argumentos={"caminhos": ["dados.dat"]}),
            CapabilityContext.de_registro(registro, "git-add",
                                          "runtime-governado",
                                          raizes=(str(tmp_path),)))
    assert "cannot exec" in str(exc.value), str(exc.value)[:300]
    assert fonte.read_text() == "intacto", "o filtro executou e reescreveu"


# ═══════════ capacidades de leitura: sem autoridade de escrita ══════════════

def test_leitura_nao_recebe_nenhuma_escrita_no_repo(repo):
    conf = mod_git.confinamento_de_leitura(repo)
    assert conf.escrita == ()
    assert conf.declara_sem_escrita is True
    perfil = supervisor.perfil(conf)
    assert f'(allow file-write* (subpath "{os.path.realpath(repo)}")' not in (
        perfil), "a capacidade de leitura recebeu autoridade de ESCRITA"
    assert '(literal "/dev/null")' in perfil, (
        "GIT_CONFIG_GLOBAL=/dev/null é aberto em leitura E escrita; sem esta "
        "linha o git morre com rc=128")


def test_leitura_perdeu_o_file_read_irrestrito(repo):
    """A2: a capacidade de leitura declara raízes, então o piso medido entra.

    O `(allow file-read*)` global some, e o repo passa a ser alcançável por
    uma raiz explícita em vez de por autoridade sobre o disco inteiro.
    """
    perfil = supervisor.perfil(mod_git.confinamento_de_leitura(repo))
    assert "\n(allow file-read*)\n" not in f"\n{perfil}", (
        "leitura irrestrita voltou ao perfil da capacidade de leitura")
    assert f'(allow file-read* (subpath "{os.path.realpath(repo)}"))' in perfil
    assert '(allow file-read* (literal "/"))' in perfil, (
        "sem o literal '/' o dyld aborta TUDO com rc=134 e sem mensagem")


def test_capacidade_sem_raizes_declaradas_mantem_leitura_ampla():
    """CONTROLE NEGATIVO da adesão explícita.

    A redução entra capacidade a capacidade. Quem ainda não declarou raízes
    tem de continuar com o comportamento histórico — senão A2 viraria uma
    troca global, que é exatamente o que quebraria tudo de uma vez.
    """
    perfil = supervisor.perfil(supervisor.Confinamento(escrita=("/private/tmp",)))
    assert "(allow file-read*)" in perfil


def test_git_log_e_show_funcionam_sem_autoridade_de_escrita(repo):
    conf = supervisor.Confinamento(escrita=(), declara_sem_escrita=True,
                                   marca=_marca())
    try:
        for sub in (["log", "--oneline", "-1"], ["show", "--stat", "HEAD"]):
            r = _sob(conf, GIT, "-C", str(os.path.realpath(repo)),
                     "--no-pager", *sub)
            assert r.returncode == 0, (sub, r.stderr[:300])
        # E a fronteira fecha: nem o git dir é gravável.
        _sob(conf, "/bin/sh", "-c", f"echo X > {repo}/.git/INTRUSO")
        assert not (repo / ".git" / "INTRUSO").exists()
    finally:
        import shutil
        shutil.rmtree(conf.marca.execdir, ignore_errors=True)


def test_confinamento_vazio_sem_declaracao_continua_recusado(tmp_path):
    """A declaração é explícita, não um efeito colateral de esquecer a lista."""
    with pytest.raises(supervisor.ErroSeguranca, match="raiz de escrita"):
        supervisor.executar([GIT, "--version"], cwd=tmp_path,
                            env=mod_git.ambiente_minimo(), prazo=10,
                            confinamento=supervisor.Confinamento())


# ═════════════════════ mach-lookup deixou de ser irrestrito ═════════════════

def test_perfil_nao_concede_mach_lookup_irrestrito():
    p = supervisor.perfil(supervisor.Confinamento(escrita=("/private/tmp",)))
    assert "(allow mach-lookup)" not in p, "mach-lookup voltou a ser irrestrito"
    assert 'global-name "com.apple.bsd.dirhelper"' in p


def test_servico_mach_nao_relacionado_fica_inalcancavel(repo):
    """MACH_UNRELATED_SERVICE=DENIED, com controle positivo.

    `pbpaste` fala com o pasteboard, um serviço que a operação Git não usa.
    Sob o perfil antigo (mach-lookup irrestrito) ele responde; sob o reduzido,
    não. A diferença é comportamental — não inspeção do texto do perfil.
    """
    m = _marca()
    try:
        raizes = mod_git.confinamento_de_repo(repo).escrita
        amplo = supervisor.perfil(
            supervisor.Confinamento(escrita=raizes, marca=m)
        ).replace(supervisor.MACH, "(allow mach-lookup)")
        fd, sb = tempfile.mkstemp(suffix=".sb")
        with os.fdopen(fd, "w") as fh:
            fh.write(amplo)
        try:
            largo = subprocess.run(
                [supervisor.SANDBOX, "-f", sb, "/usr/bin/pbpaste"],
                capture_output=True, text=True, timeout=30,
                stdin=subprocess.DEVNULL)
        finally:
            os.unlink(sb)
        if largo.returncode != 0:
            pytest.skip("pbpaste não funciona nem com mach-lookup amplo neste "
                        "host — sem controle positivo o teste seria vácuo")

        estreito = _sob(supervisor.Confinamento(escrita=raizes, marca=m),
                        "/usr/bin/pbpaste")
        assert estreito.returncode != 0, (
            "serviço Mach não relacionado continua alcançável com o perfil "
            "reduzido")
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)


def test_git_add_e_commit_ainda_funcionam_com_mach_restrito(repo):
    """O par obrigatório: MACH_REQUIRED_SERVICE=ALLOWED."""
    m = _marca()
    try:
        conf = supervisor.Confinamento(
            escrita=mod_git.confinamento_de_repo(repo).escrita, marca=m)
        (repo / "m.txt").write_text("com mach restrito\n")
        real = os.path.realpath(repo)
        env = mod_git.ambiente_minimo()
        base = [GIT, "-C", real, "--no-pager"]
        r1 = _sob(conf, *base, "add", "--", "m.txt")
        assert r1.returncode == 0, r1.stderr[:400]
        assert "m.txt" in _git(repo, "diff", "--cached", "--name-only").stdout
        assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)
