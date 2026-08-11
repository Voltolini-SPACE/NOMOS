"""A5.5 — aprovado NÃO é ilimitado. Bateria completa com filtro NATIVO.

A5.2/A5.3/A5.4 decidiram QUEM executa, QUAL objeto e COM QUE argumentos. Nada
disso limita o que o processo faz DEPOIS de nascer.

    APPROVED_MANAGED_NATIVE_FILTER != UNLIMITED_EXECUTION_AUTHORITY

## Por que o filtro é um BINÁRIO NATIVO e as sondas são COMPILADAS

A5.5 mediu que as outras rotas estão fechadas neste host: script exige o
interpretador na allowlist (reabre shell), e binário do SO copiado morre com
SIGKILL em arm64 mesmo fora do sandbox. Sobra binário purpose-built.

As sondas vivem DENTRO dele porque um filtro que chamasse `sh`/`python` para
testar uma fronteira estaria executando o próprio escape que A5.5 proíbe. Quem
escolhe a sonda é a POLÍTICA (argv governado por A5.4), nunca o repositório.

## Regra anti-vácuo

Nenhum DENIED vale sem o ALLOW gêmeo. Cada teste de contenção roda o MESMO
probe fora do confinamento primeiro. `FILTER_ACTUALLY_EXECUTED` é asserido em
todo cenário que depende de execução — os 17 resultados da rodada anterior
foram descartados justamente porque o artefato não executava.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from nomos.adapters import supervisor
from nomos.adapters.filtro_governado import (
    ArmazemDeExecutaveis,
    ErroFiltro,
    PoliticaDeFiltro,
)

SANDBOX = supervisor.SANDBOX
FONTE = Path(__file__).parent / "fixtures_nativas" / "redator.c"
pytestmark = pytest.mark.skipif(
    not (Path(SANDBOX).exists() and FONTE.exists()),
    reason="sandbox-exec ou fonte do filtro nativo ausente")


@pytest.fixture(scope="module")
def binario_nativo(tmp_path_factory):
    """Compila o filtro DO FONTE VERSIONADO. O binário nunca é versionado:
    versionar Mach-O tornaria o artefato não auditável, e A5.3 inteiro é sobre
    saber exatamente que bytes executam."""
    saida = tmp_path_factory.mktemp("build") / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(saida), str(FONTE)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        pytest.skip(f"cc indisponível: {r.stderr[:200]}")
    return saida


@pytest.fixture
def cen(tmp_path, binario_nativo):
    """Filtro governado + vizinhos que ele NÃO pode alcançar."""
    art = ArmazemDeExecutaveis(tmp_path / "store").importar(binario_nativo)
    trabalho = tmp_path / "trabalho"
    trabalho.mkdir()
    (trabalho / "entrada.txt").write_text("SENHA=hunter2\n")

    vizinho = tmp_path / "repo-vizinho"
    (vizinho / ".git").mkdir(parents=True)
    (vizinho / "segredo.txt").write_text("SEGREDO_DO_VIZINHO\n")
    (vizinho / ".git" / "config").write_text("[remote]\n")

    def pol(argv):
        return PoliticaDeFiltro(
            filter_id="synthetic-redactor",
            canonical_executable=str(binario_nativo), argv_policy=argv,
            managed_artifact=art, read_roots=(str(trabalho),),
            write_roots=(str(trabalho),))
    return pol, trabalho, vizinho, art


def _livre(art, argv, entrada=None):
    """CONTROLE POSITIVO: o MESMO probe, sem confinamento."""
    return subprocess.run([art.managed_path, *argv], capture_output=True,
                          text=True, timeout=30, input=entrada,
                          env=dict(os.environ))


def _preso(pol, entrada=None):
    fd, sb = tempfile.mkstemp(suffix=".sb")
    with os.fdopen(fd, "w") as fh:
        fh.write(supervisor.perfil(pol.confinamento()))
    try:
        return subprocess.run([SANDBOX, "-f", sb, *pol.comando()],
                              capture_output=True, text=True, timeout=30,
                              input=entrada, env=pol.ambiente(),
                              stdin=None if entrada else subprocess.DEVNULL)
    finally:
        os.unlink(sb)


def _par(cen_, argv, marca="ALCANCEI"):
    """(alcancou_livre, alcancou_preso, resultado_preso)."""
    pol, _t, _v, art = cen_
    lv = _livre(art, list(argv))
    pr = _preso(pol(tuple(argv)))
    return marca in lv.stdout, marca in pr.stdout, pr


# ═══════ 01-02 · FILTER_ACTUALLY_EXECUTED + LEGIT_NATIVE_FILTER_FUNCTIONAL ══

def test_01_filtro_nativo_EXECUTA_de_fato_sob_o_sandbox(cen):
    pol, *_ = cen
    r = _preso(pol(()), entrada="SENHA=hunter2\n")
    assert r.returncode == 0, f"não executou: {r.stderr[:300]}"
    assert r.stdout.strip() == "SENHA=REDIGIDO", (
        f"FILTER_ACTUALLY_EXECUTED=FALSE — saída {r.stdout!r}")


def test_02_transformacao_legitima_redige_o_segredo(cen):
    pol, *_ = cen
    r = _preso(pol(()), entrada="SENHA=hunter2\nlinha normal\n")
    assert "hunter2" not in r.stdout, "o segredo passou intacto"
    assert "SENHA=REDIGIDO" in r.stdout
    assert "linha normal" in r.stdout, "o filtro corrompeu conteúdo inocente"


# ═══════════════ 03-09 · READ / WRITE BOUNDARY ══════════════════════════════

@pytest.mark.parametrize("rel", [".ssh/known_hosts", ".gitconfig", ".zshrc"])
def test_03a05_segredo_do_host_NEGADO(cen, rel):
    alvo = Path.home() / rel
    if not alvo.exists():
        pytest.skip(f"{alvo} ausente — sem controle positivo")
    lv, pr, _ = _par(cen, ["--sonda-leitura", str(alvo)])
    assert lv, f"probe não lê {rel} nem solto — sonda inválida"
    assert not pr, f"HOST_SECRET_ACCESS: {rel}"


def test_06_repo_vizinho_leitura_NEGADA(cen):
    _p, _t, viz, _a = cen
    lv, pr, _ = _par(cen, ["--sonda-leitura", str(viz / "segredo.txt")])
    assert lv and not pr, "SIBLING_REPO_ACCESS (leitura)"


def test_07_repo_vizinho_escrita_NEGADA(cen):
    _p, _t, viz, _a = cen
    alvo = viz / "plantado.txt"
    lv, pr, _ = _par(cen, ["--sonda-escrita", str(alvo)])
    assert lv, "probe não escreve no vizinho nem solto"
    assert not pr, "SIBLING_REPO_ACCESS (escrita)"
    alvo.unlink(missing_ok=True)


def test_08_git_alheio_NEGADO(cen):
    _p, _t, viz, _a = cen
    lv, pr, _ = _par(cen, ["--sonda-leitura", str(viz / ".git" / "config")])
    assert lv and not pr, "FOREIGN_GIT_ACCESS"


def test_09_escopo_proprio_CONTINUA_acessivel(cen):
    """WRITE/READ_BOUNDARY não pode virar 'bloqueia tudo'."""
    _p, trab, _v, _a = cen
    lv, pr, r = _par(cen, ["--sonda-leitura", str(trab / "entrada.txt")])
    assert lv and pr, f"o filtro não lê o próprio escopo: {r.stderr[:200]}"
    lv, pr, r = _par(cen, ["--sonda-escrita", str(trab / "saida.txt")])
    assert lv and pr, f"o filtro não escreve no próprio escopo: {r.stderr[:200]}"


@pytest.mark.parametrize("truque", ["traversal", "symlink"])
def test_10_11_traversal_e_symlink_NEGADOS(cen, truque):
    """A fronteira é o caminho REAL, não o texto."""
    _p, trab, viz, _a = cen
    if truque == "traversal":
        alvo = f"{trab}/../repo-vizinho/segredo.txt"
    else:
        atalho = trab / "atalho"
        if not atalho.exists():
            atalho.symlink_to(viz)
        alvo = f"{atalho}/segredo.txt"
    lv, pr, _ = _par(cen, ["--sonda-leitura", alvo])
    assert lv, f"{truque}: probe não alcança nem solto"
    assert not pr, f"FS_ESCAPE por {truque}"


def test_12_home_arbitrario_NEGADO(cen, tmp_path):
    alvo = tmp_path / "fora.txt"
    alvo.write_text("x\n")
    lv, pr, _ = _par(cen, ["--sonda-leitura", str(alvo)])
    assert lv and not pr, "FS_ESCAPE (HOME arbitrário)"


# ═══════════════ 13-14 · NETWORK BOUNDARY ══════════════════════════════════

def test_13_rede_NEGADA_com_listener_proprio(cen):
    """CONTROL_POSITIVE_NETWORK usa listener DO TESTE, nunca endpoint externo:
    endpoint externo indisponível faria o DENIED parecer contenção."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    porta = srv.getsockname()[1]
    threading.Thread(target=lambda: srv.accept(), daemon=True).start()
    try:
        lv, pr, _ = _par(cen, ["--sonda-rede", "127.0.0.1", str(porta)])
        assert lv, "CONTROL_POSITIVE_NETWORK falhou — bateria seria vácuo"
        assert not pr, "NETWORK_ESCAPE"
    finally:
        srv.close()


def test_14_perfil_declara_deny_network(cen):
    pol, *_ = cen
    p = pol(())
    assert p.network_policy is False, "política nasceu com rede"
    assert "(deny network*)" in supervisor.perfil(p.confinamento())


# ═══════════════ 15-17 · EXEC BOUNDARY ══════════════════════════════════════

@pytest.mark.parametrize("alvo", ["/bin/sh", "/bin/bash", "/usr/bin/python3",
                                  "/bin/echo"])
def test_15_16_segundo_executavel_NEGADO(cen, alvo):
    """SECONDARY_EXEC_ESCAPE=0 e SHELL_ESCAPE=0."""
    if not Path(alvo).exists():
        pytest.skip(f"{alvo} ausente")
    # `execv` substitui a imagem: o sucesso é lido pela AUSÊNCIA de NEGADO,
    # nunca pela presença de uma marca que o código substituído não imprime.
    pol, _t, _v, art = cen
    livre = _livre(art, ["--sonda-exec", alvo])
    preso = _preso(pol(("--sonda-exec", alvo)))
    assert "TENTEI_EXEC" in livre.stdout, "a sonda nem chegou a tentar"
    assert "EXEC=NEGADO" not in livre.stdout, (
        f"{alvo} não executa nem SOLTO — sonda inválida, DENIED seria vácuo")
    assert "TENTEI_EXEC" in preso.stdout, "a sonda não rodou sob o sandbox"
    assert "EXEC=NEGADO" in preso.stdout, f"SECONDARY_EXEC_ESCAPE: {alvo}"


def test_17_exec_allowlist_tem_APENAS_o_artefato(cen):
    _p, _t, _v, art = cen
    pol, *_ = cen
    conf = pol(()).confinamento()
    assert conf.exec_permitido == (art.managed_path,)
    perfil = supervisor.perfil(conf)
    for proibido in ("/bin/sh", "/bin/bash", "/usr/bin/python3"):
        assert f'(literal "{proibido}")' not in perfil


# ═══════════════ 18-20 · ENV BOUNDARY ═══════════════════════════════════════

@pytest.mark.parametrize("chave", ["HOME", "PATH", "SSH_AUTH_SOCK",
                                   "AWS_SECRET_ACCESS_KEY", "GIT_DIR"])
def test_18_19_variavel_sensivel_NAO_chega_ao_filtro(cen, monkeypatch, chave):
    """ENV_SECRET_LEAK=0, por ALLOWLIST — blocklist erra por omissão."""
    monkeypatch.setenv(chave, "VALOR_DO_HOST")
    pol, *_ = cen
    assert chave not in pol(()).ambiente()
    r = _preso(pol(("--sonda-env", chave)))
    assert "VALOR_DO_HOST" not in r.stdout, f"ENV_SECRET_LEAK: {chave}"


def test_20_ambiente_e_minimo_e_allowlist_explicita_funciona(cen, monkeypatch):
    monkeypatch.setenv("PERMITIDA", "ok")
    monkeypatch.setenv("NAO_PERMITIDA", "segredo")
    pol, trab, _v, art = cen
    assert set(pol(()).ambiente()) == {"LANG", "LC_ALL"}
    com = PoliticaDeFiltro(
        filter_id="r", canonical_executable="/usr/bin/true", argv_policy=(),
        managed_artifact=art, read_roots=(str(trab),),
        environment_allowlist=("PERMITIDA",))
    amb = com.ambiente()
    assert amb.get("PERMITIDA") == "ok" and "NAO_PERMITIDA" not in amb


# ═══════════════ 21-22 · estrutura e fail-closed ════════════════════════════

def test_21_confinamento_sem_artefato_e_RECUSADO():
    pol = PoliticaDeFiltro(filter_id="r", canonical_executable="/usr/bin/true")
    with pytest.raises(ErroFiltro, match="sem artefato"):
        pol.confinamento()


def test_22_sondas_sao_COMPILADAS_nao_delegadas():
    """Um filtro que chamasse sh/python para testar fronteira executaria o
    próprio escape que A5.5 proíbe."""
    fonte = FONTE.read_text("utf-8")
    for proibido in ("system(", "popen(", "/bin/sh", "execlp"):
        assert proibido not in fonte, f"{proibido} no filtro nativo"
    for sonda in ("--sonda-leitura", "--sonda-escrita", "--sonda-rede",
                  "--sonda-env", "--sonda-exec"):
        assert sonda in fonte, f"sonda {sonda} ausente"


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
