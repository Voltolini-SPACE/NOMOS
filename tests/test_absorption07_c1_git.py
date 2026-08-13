"""C1 — Git de leitura: processo externo sem autoridade no plano.

Esta é a primeira capacidade a executar processo depois que `script-rodar`
genérico foi retirado. A tese que ela precisa provar não é "o NOMOS sabe rodar
git" — é que **a autoridade sobre o processo fica inteira no runtime**.

    script-rodar (removido)      git-status (aqui)
    plano escolhe argv[0]        runtime resolve o binário
    plano escolhe argv[1:]       runtime monta o argv INTEIRO
    plano escolhe cwd            cwd = repo validado contra o escopo
    ambiente herdado             ambiente mínimo, construído

O bloco mais importante é o do **repositório hostil**: um repo cuja própria
configuração tenta ligar pager, diff externo e alias. Configuração de repo é
dado que vem de fora — um `git clone` traz o `.git/config` de quem o produziu —
e o Git executa vários desses valores. Provar que o adapter não os executa é
provar que ler um repositório desconhecido não é executar código dele.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters.contrato import ErroInvalido
from nomos.adapters.git import ambiente_minimo, ref_valida
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.runtime.governado import RuntimeGovernado

GIT = "/usr/bin/git"
pytestmark = pytest.mark.skipif(not Path(GIT).exists(),
                                reason="git do sistema ausente")


def _sim(_d):
    return True


def _git(repo: Path, *args):
    env = dict(os.environ,
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    return subprocess.run([GIT, "-C", str(repo), *args], capture_output=True,
                          text=True, env=env, check=True)


@pytest.fixture()
def amb(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    repo = ws / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("linha 1\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "primeiro")
    (repo / "b.txt").write_text("nao rastreado\n")
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True, git=True)
    return rt, ws, repo, ctx


def _plano(rt, ferramenta, **params):
    return rt.rodar("c1", passos=[{"id": "p", "ferramenta": ferramenta,
                                   "params": params}])


# ============================================ execução REAL

def test_c1_status_e_diff_worktree_estao_AUSENTES(amb):
    """git-status=ABSENT, git-diff-worktree=ABSENT.

    Removidos depois que o repo hostil provou que ambos executam código do
    próprio repositório: o Git roda `filter.<driver>.clean` para decidir se um
    arquivo do working tree está modificado, e esse filtro É o mecanismo de
    comparação — desligá-lo mudaria o resultado, não protegeria.
    """
    rt, _ws, repo, _ = amb
    assert not rt.registro.conhecida("git-status")
    assert not _plano(rt, "git-status", alvo=str(repo)).ok
    # e `git-diff` sem as duas refs não pode cair no working tree
    assert not _plano(rt, "git-diff", alvo=str(repo)).ok
    assert not _plano(rt, "git-diff", alvo=str(repo), ref_a="HEAD").ok


def test_c1_log_e_show_leem_o_commit_real(amb):
    rt, _ws, repo, _ = amb
    log = _plano(rt, "git-log", alvo=str(repo), limite=5)
    assert log.ok and "primeiro" in log.missao.nos["p"].resultado
    show = _plano(rt, "git-show", alvo=str(repo), ref="HEAD")
    assert show.ok and "primeiro" in show.missao.nos["p"].resultado


def test_c1_diff_entre_refs_reais(amb):
    rt, _ws, repo, _ = amb
    (repo / "a.txt").write_text("linha 1\nlinha 2\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "segundo")
    res = _plano(rt, "git-diff", alvo=str(repo), ref_a="HEAD~1", ref_b="HEAD")
    assert res.ok, res.motivo
    assert "linha 2" in res.missao.nos["p"].resultado


# ============================================ o plano não tem autoridade

def test_c1_plano_nao_escolhe_executavel(amb):
    """PLAN_CAN_SELECT_EXECUTABLE=FALSE — o binário vive no adapter."""
    rt, _ws, repo, _ = amb
    from nomos.adapters.git import GitAdapter
    assert not hasattr(GitAdapter(), "binario")
    res = _plano(rt, "git-log", alvo=str(repo), limite=1, executavel="/bin/sh",
                 binario="/bin/sh", git="/bin/sh")
    if res.ok:
        assert "primeiro" in res.missao.nos["p"].resultado, (
            "campo do plano trocou o executável")


def test_c1_plano_nao_injeta_argv(amb):
    """PLAN_CAN_INJECT_ARGV=FALSE — o argv é montado inteiro pelo adapter."""
    rt, _ws, repo, _ = amb
    for campo in ("argv", "args", "opcoes", "flags"):
        res = _plano(rt, "git-log", alvo=str(repo), limite=1,
                     **{campo: ["--upload-pack=/bin/sh"]})
        if res.ok:
            assert "primeiro" in res.missao.nos["p"].resultado, campo


@pytest.mark.parametrize("hostil", [
    "--upload-pack=/bin/sh",
    "-c core.pager=/bin/sh",
    "--output=/tmp/x",
    "-c diff.external=/bin/sh",
    "--exec-path=/tmp",
    "-n",
    "--all",
])
def test_c1_ref_que_comeca_com_hifen_e_recusada(amb, hostil):
    """A defesa central: ref que começa com `-` é OPÇÃO para o Git, e opções
    do Git executam programa."""
    rt, _ws, repo, _ = amb
    for cap, campo in (("git-log", "ref"), ("git-show", "ref"),
                       ("git-diff", "ref_a")):
        res = _plano(rt, cap, alvo=str(repo), **{campo: hostil})
        assert not res.ok, f"{cap} aceitou ref hostil {hostil!r}"


@pytest.mark.parametrize("ruim", [
    "main;rm -rf /", "main`id`", "main$(id)", "main|cat", "main&echo",
    "main ", " main", "main\nHEAD", "main\x00", "..main", "main...HEAD",
    "main@{u}", "", "a" * 300, "-x", "<main>",
])
def test_c1_gramatica_de_ref_recusa_o_resto(ruim):
    with pytest.raises(ErroInvalido):
        ref_valida(ruim, "ref")


@pytest.mark.parametrize("boa", ["main", "HEAD", "HEAD~3", "v1.0.0",
                                 "feature/x", "abc123def", "release-1.2"])
def test_c1_gramatica_aceita_ref_legitima(boa):
    assert ref_valida(boa, "ref") == boa


def test_c1_shell_nunca_e_usado():
    """PLAN_CAN_ENABLE_SHELL=FALSE, verificado na AST do adapter."""
    import ast

    import nomos.adapters.git as mod
    fonte = Path(mod.__file__).read_text()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Call) and getattr(no.func, "attr", "") == "run":
            kw = {k.arg: k.value for k in no.keywords}
            assert "shell" in kw, "subprocess.run sem `shell=` explícito"
            assert isinstance(kw["shell"], ast.Constant) and kw["shell"] is not True
            assert kw["shell"].value is False


# ============================================ ambiente construído

def test_c1_ambiente_nao_herda_nada_do_host(monkeypatch):
    """HOST_ENV_CAN_CHANGE_GIT_EXECUTION=FALSE."""
    for var in ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "PAGER", "GIT_SSH_COMMAND",
                "GIT_CONFIG_GLOBAL", "GIT_EXEC_PATH", "GIT_EDITOR",
                "GIT_ASKPASS", "HOME", "GIT_CONFIG_COUNT"):
        monkeypatch.setenv(var, "/tmp/HOSTIL")
    env = ambiente_minimo()
    assert "HOME" not in env, "HOME traria ~/.gitconfig do usuário"
    assert "GIT_EXEC_PATH" not in env
    assert "GIT_SSH_COMMAND" not in env
    assert "GIT_CONFIG_COUNT" not in env
    assert env["GIT_EXTERNAL_DIFF"] == ""
    assert env["GIT_PAGER"] == "cat" and env["PAGER"] == "cat"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"


def test_c1_env_hostil_do_host_nao_muda_a_execucao(amb, monkeypatch, tmp_path,
                                                   espiao_nativo):
    """A prova pela execução — e o que ela pode e NÃO pode provar aqui.

    MEDIDO (`.3.05`): a versão anterior era VÁCUA nas duas metades que P0.1 já
    tinha corrigido em c2a/c2b — espião `#!/bin/sh` (que não executa sob a
    allowlist de exec: o kernel precisa do interpretador) e canário em
    `tmp_path`. Pior que no caso original: as capacidades de LEITURA rodam com
    `escrita=()` e `declara_sem_escrita=True`, então NÃO EXISTE caminho gravável
    de dentro do confinamento — nem o git dir, nem a working tree. O
    `not canario.exists()` era verdade POR CONSTRUÇÃO.

    Como não há onde gravar, a asserção comportamental não consegue distinguir
    contenção de impossibilidade. O que este teste passa a provar são as duas
    coisas que de fato distinguem:

        CONTROLE POSITIVO   o cenário é REAL — o git CRU, com as mesmas
                            variáveis, EXECUTA o espião e grava o canário
        ESTRUTURAL          o confinamento da leitura não concede escrita
                            nenhuma, então execução de código não persiste nada

    Espião BINÁRIO NATIVO tira o interpretador da equação.
    """
    rt, _ws, repo, _ = amb
    canario = tmp_path / "CANARIO-ENV"
    espiao = espiao_nativo(tmp_path, canario)

    # CONTROLE POSITIVO, e ele mudou de CAPACIDADE por medição. `git show` NÃO
    # invoca `GIT_EXTERNAL_DIFF` nem os pagers (sem TTY, `GIT_PAGER` nem é
    # consultado): medido, nenhuma das quatro variáveis dispara ali. A versão
    # anterior deste teste apontava para `git-show` e por isso era vácua também
    # nessa dimensão — não havia como o vetor ocorrer, com ou sem NOMOS.
    # `git diff <a> <b>` é onde `GIT_EXTERNAL_DIFF` de fato executa.
    # Duas revisões: sem diferença não há diff, e sem diff o `GIT_EXTERNAL_DIFF`
    # não é invocado nem pelo git cru — o controle mediria a ausência de
    # conteúdo, não a de execução.
    (repo / "delta.txt").write_text("mudou\n")
    _git(repo, "add", "delta.txt")
    _git(repo, "commit", "-qm", "delta")

    env_hostil = {**os.environ, "GIT_EXTERNAL_DIFF": str(espiao)}
    subprocess.run([GIT, "-C", str(repo), "diff", "HEAD~1", "HEAD"],
                   capture_output=True, env=env_hostil)
    assert canario.exists(), (
        "CONTROLE POSITIVO FALHOU: nem o git cru executou o espião — a "
        "asserção de ausência abaixo não mediria contenção nenhuma")
    canario.unlink()

    for var in ("GIT_EXTERNAL_DIFF", "GIT_PAGER", "PAGER", "GIT_EDITOR"):
        monkeypatch.setenv(var, str(espiao))
    assert _plano(rt, "git-diff", alvo=str(repo), ref_a="HEAD~1",
                  ref_b="HEAD").ok
    assert not canario.exists(), "variável do HOST executou programa no git"

    # ESTRUTURAL: a ausência acima é garantida, não sorteada.
    from nomos.adapters.git import confinamento_de_leitura
    conf = confinamento_de_leitura(repo)
    assert conf.escrita == () and conf.declara_sem_escrita, (
        "a capacidade de leitura passou a conceder escrita — a partir daí a "
        "asserção de canário volta a ser comportamental, e este teste tem de "
        "ser reescrito para medir de novo")


# ============================================ o repositório HOSTIL

def espiao_do_repo(repo) -> str:
    """O caminho que a config hostil do repositório declara como executável."""
    r = subprocess.run([GIT, "-C", str(repo), "config", "--get", "core.pager"],
                       capture_output=True, text=True)
    return r.stdout.strip()


@pytest.fixture()
def repo_hostil(amb, tmp_path):
    """Repo cuja PRÓPRIA configuração tenta executar programa.

    Configuração de repo vem de fora — um `git clone` traz o `.git/config` de
    quem o produziu. O Git executa vários desses valores.
    """
    rt, ws, repo, ctx = amb
    canario = tmp_path / "CANARIO-REPO"
    espiao = tmp_path / "hostil.sh"
    espiao.write_text(f"#!/bin/sh\ntouch {canario}\nexit 0\n")
    espiao.chmod(0o755)
    _git(repo, "config", "core.pager", str(espiao))
    _git(repo, "config", "diff.external", str(espiao))
    _git(repo, "config", "core.editor", str(espiao))
    _git(repo, "config", "alias.st", f"!{espiao}")
    _git(repo, "config", "core.fsmonitor", str(espiao))
    _git(repo, "config", "diff.textconv.command", str(espiao))
    _git(repo, "config", "filter.hostil.clean", str(espiao))
    _git(repo, "config", "filter.hostil.smudge", str(espiao))
    (repo / ".gitattributes").write_text("* diff=hostil filter=hostil\n")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-qm", "attrs")
    # O SETUP acima roda com o ambiente do host e a config hostil já ativa —
    # `core.fsmonitor` dispara ali e criaria o canário antes de o adapter
    # existir. Zerar aqui é o que faz o teste medir o ADAPTER, e não a própria
    # fixture. (A primeira versão não zerava e "provava" um furo inexistente.)
    canario.unlink(missing_ok=True)
    return rt, repo, canario


@pytest.mark.parametrize("cap,extra", [
    ("git-log", {"limite": 5}),
    ("git-show", {"ref": "HEAD"}),
    ("git-diff", {"ref_a": "HEAD~1", "ref_b": "HEAD"}),
])
def test_c1_config_do_repo_nao_executa_programa(repo_hostil, cap, extra):
    """EXTERNAL_DIFF_EXECUTION=FALSE, PAGER_EXECUTION=FALSE.

    Ler um repositório desconhecido não pode ser executar código dele.
    """
    rt, repo, canario = repo_hostil

    # CONTROLE POSITIVO (`.3.05`): sem ele, `not canario.exists()` é verdade
    # POR CONSTRUÇÃO — `confinamento_de_leitura` não concede escrita NENHUMA,
    # então o canário não teria onde ser gravado mesmo que o espião rodasse.
    # A escada de mutação mediu: o teste ficava VERDE com todas as defesas
    # removidas. O git CRU, com a MESMA config hostil, tem de executar.
    subprocess.run([GIT, "-C", str(repo), "diff", "HEAD~1", "HEAD"],
                   capture_output=True)
    assert canario.exists(), (
        "CONTROLE POSITIVO FALHOU: nem o git CRU executou o espião com esta "
        "config hostil — a asserção de ausência abaixo não mediria contenção")
    canario.unlink()

    rt.rodar("c1", passos=[{"id": "p", "ferramenta": cap,
                            "params": {"alvo": str(repo), **extra}}])
    assert not canario.exists(), (
        f"{cap} executou programa vindo da configuração do REPOSITÓRIO")

    # ESTRUTURAL, e é ele que MORDE (`.3.05`). MEDIDO com ablação: a asserção
    # comportamental acima fica VERDE mesmo com `_NEUTRALIZAR = []`, porque
    # `confinamento_de_leitura` não concede escrita NENHUMA — o canário não
    # teria onde ser gravado nem se o espião rodasse. Ela não distingue "não
    # executou" de "executou e não pôde gravar". Por construção.
    #
    # As duas afirmações que de fato distinguem são o CONTROLE POSITIVO acima
    # (o cenário é real: o git cru executa e grava) e esta. É o mesmo par que
    # `test_c1_variavel_do_host_nao_executa` já usava — o padrão existia no
    # arquivo e não tinha sido aplicado a ESTE vetor.
    from nomos.adapters import git as _g
    conf = _g.confinamento_de_leitura(repo)
    assert conf.escrita == () and conf.declara_sem_escrita, (
        "a leitura passou a conceder escrita: o canário volta a poder ser "
        f"gravado e a asserção acima deixa de ser conservadora. {conf.escrita}")
    assert espiao_do_repo(repo) not in conf.exec_permitido, (
        "o espião declarado na config do REPOSITÓRIO entrou na allowlist de "
        "exec — o repositório escolheria o que executa")


def test_c1_alias_hostil_nao_e_alcancavel(repo_hostil):
    """Alias `!cmd` do repo executa shell — e o plano não escolhe subcomando."""
    rt, repo, canario = repo_hostil
    for tentativa in ("st", "!sh", "alias.st"):
        rt.rodar("c1", passos=[{"id": "p", "ferramenta": "git-log",
                                "params": {"alvo": str(repo),
                                           "ref": tentativa}}])
    assert not canario.exists()


# ============================================ escopo e governança

def test_c1_repo_fora_do_escopo_e_negado(amb, tmp_path):
    rt, _ws, _repo, _ = amb
    fora = tmp_path / "fora"
    fora.mkdir()
    _git(fora, "init", "-q")
    assert not _plano(rt, "git-status", alvo=str(fora)).ok


def test_c1_nao_e_repositorio_falha_tipado(amb):
    rt, ws, _repo, _ = amb
    simples = ws / "sem-git"
    simples.mkdir()
    res = _plano(rt, "git-log", alvo=str(simples), limite=1)
    assert not res.ok
    assert "repositório git" in (res.missao.nos["p"].detalhe or "")


def test_c1_capacidades_sao_A0_e_nao_registram_escrita(amb):
    """Leitura e escrita são missões separadas: `git-push` não existe."""
    rt, _ws, _repo, _ = amb
    for nome in ("git-diff", "git-log", "git-show"):
        assert rt.registro.categoria_de(nome) is Category.READ_LOCAL
    for proibida in ("git-push", "git-commit", "git-add", "git-fetch",
                     "git-reset-hard", "git-clean", "git-rebase", "git",
                     "git-status"):
        assert not rt.registro.conhecida(proibida), f"{proibida} existe no C1"


def test_c1_nao_registra_sem_opt_in(amb, tmp_path):
    """Como todo executor de processo: opt-in explícito."""
    home = tmp_path / "h2"
    home.mkdir()
    ws = tmp_path / "ws2"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True)
    assert not any(n.startswith("git-") for n in rt.capacidades_adapter)


def test_c1_registrar_sem_raizes_falha_fechado():
    from nomos.adapters.wiring import registrar_git
    with pytest.raises(ValueError, match="raizes"):
        registrar_git(object(), raizes=())


def test_c1_passa_por_pdp_e_pep(amb):
    import json
    rt, _ws, repo, ctx = amb
    assert _plano(rt, "git-show", alvo=str(repo), ref="HEAD").ok
    ev = [json.loads(x).get("event") for x in
          (ctx["home"] / "logs" / "audit.jsonl").read_text().splitlines()
          if x.strip()]
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao") < ev.index("git.show")


def test_c1_nao_toca_a_rede(amb):
    """NETWORK_SIDE_EFFECT_FROM_C1=FALSE — nenhum subcomando de rede existe."""
    import ast

    import nomos.adapters.git as mod
    fonte = Path(mod.__file__).read_text()
    literais = {n.value for n in ast.walk(ast.parse(fonte))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for rede in ("fetch", "push", "pull", "clone", "remote", "ls-remote"):
        assert rede not in literais, f"subcomando de rede no adapter: {rede}"


# ============================================ object-only, provado por mtime

def _impressao(repo: Path) -> dict:
    """mtime+tamanho de working tree e índice — o que mudaria se fossem tocados."""
    alvo = {}
    for p in sorted(repo.rglob("*")):
        if ".git" in p.parts[len(repo.parts):] and p.name != "index":
            continue
        if p.is_file():
            st = p.stat()
            alvo[str(p)] = (st.st_mtime_ns, st.st_size)
    return alvo


@pytest.mark.parametrize("cap,extra", [
    ("git-log", {"limite": 5}),
    ("git-show", {"ref": "HEAD"}),
    ("git-diff", {"ref_a": "HEAD~1", "ref_b": "HEAD"}),
])
def test_c1_operacoes_nao_tocam_worktree_nem_indice(repo_hostil, cap, extra):
    """WORKTREE_TOUCHED=FALSE, INDEX_TOUCHED=FALSE.

    `GIT_OPTIONAL_LOCKS=0` já evita que a leitura reescreva o índice, mas a
    propriedade precisa ser medida, não assumida: um `git status` (removido do
    C1) reescreveria o índice em condições normais.
    """
    rt, repo, _canario = repo_hostil
    antes = _impressao(repo)
    rt.rodar("c1", passos=[{"id": "p", "ferramenta": cap,
                            "params": {"alvo": str(repo), **extra}}])
    depois = _impressao(repo)
    mudou = {k for k in set(antes) | set(depois) if antes.get(k) != depois.get(k)}
    assert not mudou, f"{cap} tocou: {sorted(mudou)}"


def test_c1_nenhum_subcomando_toca_rede(amb):
    """NETWORK_TOUCHED=FALSE — nem por config do repo.

    O `protocol.ext.allow=never` e a ausência de subcomando de rede cobrem os
    dois lados: nem o adapter pede rede, nem o repositório consegue provocá-la.
    """
    rt, _ws, repo, _ = amb
    _git(repo, "remote", "add", "origem", "ext::/bin/sh -c touch /tmp/NET")
    _git(repo, "config", "url.ext::.insteadOf", "https://")
    for cap, extra in (("git-log", {"limite": 3}),
                       ("git-show", {"ref": "HEAD"})):
        assert _plano(rt, cap, alvo=str(repo), **extra).ok
    assert not Path("/tmp/NET").exists()


def test_c1_GIT_EXEC_PATH_do_host_nao_redireciona_subcomando(amb, monkeypatch,
                                                              tmp_path):
    """O caso que mata o mutante "ambiente herdado".

    `GIT_EXEC_PATH` diz ao Git onde achar os PRÓPRIOS subcomandos: com ele
    apontando para um diretório do atacante, `git log` executa
    `$GIT_EXEC_PATH/git-log`. É herdado do ambiente e não é coberto por
    `--no-ext-diff` nem por `--no-pager` — só por não herdar o ambiente.
    """
    falso = tmp_path / "execpath"
    falso.mkdir()
    canario = tmp_path / "CANARIO-EXECPATH"
    for sub in ("git-log", "git-show", "git-diff"):
        f = falso / sub
        f.write_text(f"#!/bin/sh\ntouch {canario}\nexit 0\n")
        f.chmod(0o755)
    monkeypatch.setenv("GIT_EXEC_PATH", str(falso))
    rt, _ws, repo, _ = amb
    assert _plano(rt, "git-log", alvo=str(repo), limite=3).ok
    assert not canario.exists(), (
        "GIT_EXEC_PATH do HOST redirecionou o subcomando do git")


def test_c1_resolver_confina_o_repo_por_si_mesmo(tmp_path):
    """Mata o mutante "escopo desligado", que o PDP mascarava.

    A cadeia nega por escopo antes de o adapter agir — defesa em profundidade
    real, e por isso mesmo cada camada precisa da própria prova. É a terceira
    vez nesta série que um mutante sobrevive por estar atrás de outra defesa.
    """
    from nomos.adapters.caminho import ErroEscopo, resolver
    ws = tmp_path / "ws"
    ws.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    assert resolver(str(ws / "repo"), (str(ws),))
    with pytest.raises(ErroEscopo):
        resolver(str(fora), (str(ws),))


# ============================================ M3 — o adapter, sem o PDP

def _ctx_direto(tmp_path, ws, capacidade):
    """Contexto montado direto, SEM passar pelo PDP.

    É assim que o mutante "escopo do repo desligado" tem de morrer: o PDP nega
    antes e mascara a ausência da checagem no adapter. Defesa em profundidade
    só é defesa se cada camada segurar sozinha.
    """
    from nomos.adapters.contrato import CapabilityContext
    from nomos.adapters.wiring import registrar_git
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades
    home = tmp_path / "hd"
    home.mkdir(exist_ok=True)
    registro = RegistroCapacidades(policy=PolicyEngine(home / "policy.json"),
                                   approver=_sim)
    registrar_git(registro, raizes=(str(ws),))
    return CapabilityContext.de_registro(registro, capacidade,
                                         "runtime-governado", raizes=(str(ws),))


@pytest.mark.parametrize("cap,extra", [
    ("git-log", {"limite": 3}),
    ("git-show", {"ref": "HEAD"}),
    ("git-diff", {"ref_a": "HEAD~1", "ref_b": "HEAD"}),
])
def test_m3_adapter_recusa_repo_fora_do_escopo_sem_o_pdp(amb, tmp_path, cap, extra):
    """ADAPTER_SCOPE_ENFORCEMENT=DENY, exercitado no nível de `_repo`."""
    from nomos.adapters.caminho import ErroEscopo
    from nomos.adapters.contrato import CapabilityRequest
    from nomos.adapters.git import GitAdapter
    _rt, ws, _repo, _ = amb
    fora = tmp_path / "repo-fora"
    fora.mkdir()
    _git(fora, "init", "-q", "-b", "main")
    (fora / "x.txt").write_text("segredo\n")
    _git(fora, "add", "x.txt")
    _git(fora, "commit", "-qm", "um")
    _git(fora, "commit", "-qm", "dois", "--allow-empty")

    ctx = _ctx_direto(tmp_path, ws, cap)
    pedido = CapabilityRequest(capacidade=cap, alvo=str(fora), argumentos=extra)
    with pytest.raises(ErroEscopo):
        GitAdapter().executar(pedido, ctx)


def test_m3_adapter_aceita_repo_dentro_do_escopo_sem_o_pdp(amb, tmp_path):
    """Contraparte: sem ela, um adapter que recusa TUDO passaria."""
    from nomos.adapters.contrato import CapabilityRequest
    from nomos.adapters.git import GitAdapter
    _rt, ws, repo, _ = amb
    ctx = _ctx_direto(tmp_path, ws, "git-log")
    pedido = CapabilityRequest(capacidade="git-log", alvo=str(repo),
                               argumentos={"limite": 3})
    r = GitAdapter().executar(pedido, ctx)
    assert "primeiro" in (r.valor or "")


# ============================================ M1 — ambiente herdado é real

def test_m1_GIT_DIR_do_host_nao_redireciona_o_repositorio(amb, monkeypatch,
                                                           tmp_path):
    """O vetor que mata o mutante "ambiente herdado".

    `GIT_DIR` e `GIT_WORK_TREE` dizem ao Git QUAL repositório usar, e vencem o
    `-C`. Herdados do host, fariam o adapter ler um repositório que o plano não
    pediu e que o escopo não autorizou — escape de escopo por variável de
    ambiente, sem tocar em nenhum parâmetro do plano.

    Foi medido: com ambiente herdado + hostil, as três operações mudam de
    comportamento (rc e saída). Não é equivalente; é defeito.
    """
    rt, _ws, repo, _ = amb
    outro = tmp_path / "outro"
    outro.mkdir()
    _git(outro, "init", "-q", "-b", "main")
    (outro / "SEGREDO.txt").write_text("conteudo do OUTRO repo\n")
    _git(outro, "add", "SEGREDO.txt")
    _git(outro, "commit", "-qm", "commit-do-outro-repo")

    monkeypatch.setenv("GIT_DIR", str(outro / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outro))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(outro / ".git" / "objects"))

    res = _plano(rt, "git-log", alvo=str(repo), limite=5)
    assert res.ok, res.motivo
    saida = res.missao.nos["p"].resultado
    assert "primeiro" in saida, saida
    assert "commit-do-outro-repo" not in saida, (
        "GIT_DIR do HOST redirecionou o repositório lido — escape de escopo "
        "por ambiente")
