"""C2c — o rc=0 que mente: filtro do repositório falha e o índice fica cru.

Este arquivo existe por causa de um defeito MEDIDO no caminho governado, não
de uma hipótese. Duas sondas independentes do censo (FILE_READ e PROCESS_EXEC)
chegaram sozinhas ao mesmo ponto: os quatro adapters de Git decidiam sucesso
olhando SÓ `p.returncode`.

O Git, porém, só trata falha de filtro externo como fatal quando
`filter.<driver>.required` está ligado — e essa chave vive no REPOSITÓRIO,
isto é, do lado não confiável. Quem ataca escolhe se o erro é fatal.

O cenário não é acadêmico. Usar `filter.clean` como REDATOR de segredo é
padrão documentado do Git. Com o filtro quebrado, o efeito se inverte:

    antes desta checagem
      NOMOS retornou       : SUCESSO
      indexado             : 'SEGREDO.txt'
      CONTEUDO NO INDICE   : 'SENHA=hunter2\\n'      <- em claro

O invariante da missão diz isto em uma linha: segurança não pode depender
apenas de RC=0.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FILTRO_QUEBRADO = "/nao/existe/redator-de-segredo"


def _git(repo, *a):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run([GIT, "-C", str(repo), *a], capture_output=True,
                          text=True, env=env)


@pytest.fixture
def repo_com_redator(tmp_path):
    """Repositório que declara um `clean` redator — e o redator não existe."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "filter.redator.clean", FILTRO_QUEBRADO)
    (repo / ".gitattributes").write_text("SEGREDO.txt filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "SEGREDO.txt").write_text("SENHA=hunter2\n")
    return repo


def _ctx_e_registro(raiz, tmp_path):
    registro = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                   approver=lambda *a, **k: True)
    registrar_git_tree(registro, raizes=(str(raiz),))
    return registro


# ══════════════ PASSO 1 — CONTROLE POSITIVO: o Git realmente mente ══════════

@pytest.mark.git_governado
def test_controle_positivo_o_git_sai_com_rc0_e_indexa_o_conteudo_cru(
        repo_com_redator):
    """Sem isto o teste seguinte não prova nada.

    Se um dia o Git passar a devolver rc != 0 aqui, a proteção vira redundante
    e este teste avisa — em vez de continuar verde sem medir nada.
    """
    r = _git(repo_com_redator, "add", "--", "SEGREDO.txt")
    assert r.returncode == 0, (
        "o Git passou a falhar sozinho; a premissa do defeito mudou")
    assert "external filter" in r.stderr, r.stderr[:300]
    assert _git(repo_com_redator, "diff", "--cached",
                "--name-only").stdout.strip() == "SEGREDO.txt"
    assert _git(repo_com_redator, "show",
                ":SEGREDO.txt").stdout == "SENHA=hunter2\n", (
        "o conteúdo indexado não é o cru — o cenário do defeito não se armou")


# ═══════════ PASSO 2 — o caminho governado RECUSA em vez de mentir ══════════

@pytest.mark.git_governado
def test_nomos_recusa_em_vez_de_reportar_sucesso(repo_com_redator, tmp_path):
    """O que o defeito produzia: `efeito_aplicado=True` com segredo em claro."""
    registro = _ctx_e_registro(tmp_path, tmp_path)
    ctx = CapabilityContext.de_registro(
        registro, "git-add", "runtime-governado", raizes=(str(tmp_path),))

    with pytest.raises(supervisor.ErroSeguranca) as exc:
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-add",
                              alvo=str(repo_com_redator),
                              argumentos={"caminhos": ["SEGREDO.txt"]}), ctx)

    assert "degradação silenciosa" in str(exc.value)
    # A mensagem carrega a PRIMEIRA linha de erro do Git. Neste cenário é o
    # `fatal: cannot exec`, não o `error: external filter` que vem depois —
    # asserir o segundo faria o teste medir a ordem da saída do Git.
    assert "cannot exec" in str(exc.value)
    assert FILTRO_QUEBRADO in str(exc.value)


@pytest.mark.git_governado
def test_o_indice_NAO_fica_contaminado_apos_a_recusa(repo_com_redator,
                                                     tmp_path):
    """Antes existia aqui um teste que PASSAVA asserindo o índice sujo.

    Estava errado por método: teste verde que afirma a vulnerabilidade
    transforma o defeito em comportamento esperado e faz a correção parecer
    regressão. O contrato correto é o oposto, e está em
    `tests/test_absorption07_a0_indice_transacional.py` (A0).
    Aqui fica só a ponta: recusou, então nada ficou estagiado.
    """
    registro = _ctx_e_registro(tmp_path, tmp_path)
    ctx = CapabilityContext.de_registro(
        registro, "git-add", "runtime-governado", raizes=(str(tmp_path),))
    with pytest.raises(supervisor.ErroSeguranca):
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-add",
                              alvo=str(repo_com_redator),
                              argumentos={"caminhos": ["SEGREDO.txt"]}), ctx)

    assert _git(repo_com_redator, "diff", "--cached",
                "--name-only").stdout.strip() == "", (
        "a recusa deixou conteúdo estagiado — a cadeia até o commit segue viva")


# ══ PASSO 2b — o filtro que EXECUTA e falha (caminho distinto do não-exec) ══

@pytest.mark.filtro_posix
def test_filtro_que_executa_e_falha_tambem_e_recusado(tmp_path):
    """Cenário levantado pela sonda FILE_READ do censo, e ele é OUTRO caminho.

    Em `test_nomos_recusa_...` o filtro nem executa (`fatal: cannot exec`).
    Aqui o binário EXISTE e roda — quem falha é ele, por não alcançar o próprio
    arquivo de regras. É o caso realista de um `clean` redator legítimo cujas
    regras moram fora do repositório: exatamente o que a redução de file-read
    provoca ao negar ao filtro suas dependências.

    O detalhe que faz a proteção funcionar: a PRIMEIRA linha do stderr é
    `sed: ...: No such file or directory`, que NÃO casa com o marcador. Quem
    casa é a segunda (`error: external filter ... failed`). Sem a âncora
    MULTILINE, este caso passaria batido.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    regras = tmp_path / "regras.sed"           # de propósito: não existe
    _git(repo, "config", "filter.redator.clean", f"/usr/bin/sed -f {regras}")
    (repo / ".gitattributes").write_text("SEGREDO.txt filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "SEGREDO.txt").write_text("SEGREDO=abc123\n")

    # CONTROLE POSITIVO: o Git de fato sai com 0 e o marcador não é a 1ª linha.
    r = _git(repo, "add", "--", "SEGREDO.txt")
    assert r.returncode == 0
    assert not r.stderr.startswith("error:"), (
        "o marcador virou a primeira linha — este teste deixou de exercitar "
        "a âncora MULTILINE, que é o ponto dele")
    assert "error: external filter" in r.stderr
    _git(repo, "reset", "-q")

    registro = _ctx_e_registro(tmp_path, tmp_path)
    with pytest.raises(supervisor.ErroSeguranca):
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-add", alvo=str(repo),
                              argumentos={"caminhos": ["SEGREDO.txt"]}),
            CapabilityContext.de_registro(registro, "git-add",
                                          "runtime-governado",
                                          raizes=(str(tmp_path),)))


# ═════════════ PASSO 3 — a checagem não pode virar falso positivo ═══════════

@pytest.mark.git_governado
def test_operacao_limpa_continua_passando(tmp_path):
    """CONTROLE NEGATIVO. Uma checagem que recusa tudo também "protegeria"."""
    repo = tmp_path / "limpo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "ok.txt").write_text("sem filtro nenhum\n")

    registro = _ctx_e_registro(tmp_path, tmp_path)
    r = git_tree.GitTreeAdapter().executar(
        CapabilityRequest(capacidade="git-add", alvo=str(repo),
                          argumentos={"caminhos": ["ok.txt"]}),
        CapabilityContext.de_registro(registro, "git-add",
                                      "runtime-governado",
                                      raizes=(str(tmp_path),)))
    assert r.efeito_aplicado is True


@pytest.mark.parametrize("ruido", [
    b"",
    b"warning: LF will be replaced by CRLF in a.txt\n",
    b"Enumerating objects: 3, done.\nremote: Resolving deltas: 100%\n",
])
def test_stderr_benigno_nao_e_recusado(ruido):
    """`warning:` e progresso são rotina. Recusar neles quebraria operação boa."""
    supervisor.conferir_saida(ruido, "git")


@pytest.mark.parametrize("marcador", [b"error:", b"fatal:"])
def test_marcadores_de_erro_sao_recusados_em_qualquer_linha(marcador):
    """O marcador precisa valer no MEIO da saída, não só no começo — a linha
    de erro do Git costuma vir depois de progresso."""
    saida = b"Enumerating objects: 3, done.\n" + marcador + b" algo quebrou\n"
    with pytest.raises(supervisor.ErroSeguranca):
        supervisor.conferir_saida(saida, "git")


def test_marcador_no_meio_da_linha_nao_dispara():
    """`^` ancorado: a palavra "error:" dentro de um nome de arquivo ou de uma
    mensagem de commit não pode derrubar a operação."""
    supervisor.conferir_saida(b"add 'meu-error:-arquivo.txt'\n", "git")


# ═════════ PASSO 4 — a proteção existe nos QUATRO adapters, não em um ═══════

def test_os_quatro_adapters_conferem_a_saida():
    """Estrutural: se alguém acrescentar um adapter de Git sem a checagem, a
    lacuna aparece aqui e não num incidente."""
    import pathlib
    base = pathlib.Path(supervisor.__file__).parent
    faltando = [
        nome for nome in ("git.py", "git_tree.py", "git_write.py",
                          "git_push.py")
        if "conferir_saida" not in (base / nome).read_text("utf-8")
    ]
    assert faltando == [], f"adapters sem conferência de stderr: {faltando}"


def test_nenhum_adapter_decide_sucesso_so_pelo_returncode():
    """O defeito original em forma de invariante permanente."""
    import pathlib
    base = pathlib.Path(supervisor.__file__).parent
    for nome in ("git.py", "git_tree.py", "git_write.py", "git_push.py"):
        texto = (base / nome).read_text("utf-8")
        assert texto.count("conferir_saida") >= 1, nome


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
