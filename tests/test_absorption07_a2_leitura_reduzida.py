"""A2 — leitura de filesystem reduzida ao piso medido.

`(allow file-read*)` dava LEITURA DO DISCO INTEIRO a qualquer processo sob o
perfil. Era a maior concessão que sobrava depois que a escrita parou no git
dir. Aqui ela sai das capacidades de LEITURA (`git-log`, `git-show`,
`git-diff`), que é onde a redução é segura hoje.

## Por que só as capacidades de leitura

Medido no censo do C2c e reconfirmado pela síntese: nesse caminho NENHUM
filtro do repositório roda — as três operações são object-only. Em
`git-add`/`git-commit` a mesma redução nega ao `filter.clean` as dependências
dele, o que faz filtro legítimo falhar. Isso hoje é CONTIDO (rc=0 mentiroso
vira `ErroSeguranca`, índice restaurado, objeto na quarentena), mas continua
sendo uma quebra funcional — entra em A2-REPO com a sua própria bateria.

## A adesão é explícita

`Confinamento.leitura` vazio mantém o comportamento histórico. Só quem declara
raízes recebe o piso. Uma troca global quebraria todas as capacidades de uma
vez, e a redução não vale o incidente.

## Landmines que a medição impôs

- `(allow file-read* (literal "/"))` é OBRIGATÓRIO: sem ele o dyld aborta tudo
  com rc=134 e SEM mensagem. Permite listar `/` e nada além.
- `/var` e `/etc` são SYMLINK: precisam de allow próprio para o componente
  resolver. `file-read-metadata` basta e não deixa ler conteúdo.
- Ancestrais de cada raiz precisam de `file-read-metadata`, senão o Git para
  com `Invalid path <X>` (rc=128).
- O developer dir vem de `realpath("/var/select/developer_dir")` em runtime:
  fixar o caminho quebraria tudo após um `xcode-select -s`.
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

GIT = "/usr/bin/git"          # preparo do repositório, FORA do sandbox
SANDBOX = supervisor.SANDBOX
pytestmark = pytest.mark.skipif(
    not (Path(GIT).exists() and Path(SANDBOX).exists()),
    reason="git ou sandbox-exec ausente")


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    def g(*a):
        return subprocess.run([GIT, "-C", str(r), *a], capture_output=True,
                              text=True, env=env)
    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (r / "a.txt").write_text("conteudo\n")
    g("add", "--", "a.txt")
    g("commit", "-q", "-m", "base")
    return r


def _sob(conf, *argv, env=None):
    """Roda `argv` sob o perfil de `conf`, sem passar pelo adapter.

    Para invocar o GIT é obrigatório passar `env=mod_git.ambiente_minimo()`:
    é o que o caminho real faz. Sem isso o Git herda `HOME` e vai atrás de
    `~/.gitconfig` — que o piso de A2 nega, corretamente, e o teste mediria a
    fixture em vez da política.
    """
    fd, caminho = tempfile.mkstemp(suffix=".sb")
    with os.fdopen(fd, "w") as fh:
        fh.write(supervisor.perfil(conf))
    try:
        return subprocess.run([SANDBOX, "-f", caminho, *argv],
                              capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, env=env)
    finally:
        os.unlink(caminho)


def _amplo():
    """Perfil de CONTROLE: leitura irrestrita (o estado anterior a A2)."""
    return supervisor.Confinamento(escrita=(), declara_sem_escrita=True,
                                   exec_permitido=_SONDA)


# Depois de A5 o `exec_permitido` é POR CAPACIDADE, e a capacidade de leitura
# só admite o Git. A sonda que usa `/bin/cat` precisa declarar o próprio
# executável — senão ela mede a allowlist de exec, não a fronteira de LEITURA
# que pretende medir.
# Só o que cada sonda precisa. A CAPACIDADE continua admitindo apenas o Git.
_SONDA = ("/bin/cat", "/bin/ls")


def _com_sonda(conf):
    """Mesmo confinamento, mais o binário da sonda. Nada além dele."""
    import dataclasses
    return dataclasses.replace(conf, exec_permitido=conf.exec_permitido + _SONDA)


# ════════ Cada DENY vem com o ALLOW gêmeo — senão o teste é vácuo ═══════════

@pytest.mark.parametrize("nome,rel", [
    ("home_arbitrario", ".zshrc"),
    ("ssh", ".ssh/known_hosts"),
])
def test_leitura_fora_da_raiz_e_negada_com_controle_positivo(nome, rel, repo):
    alvo = Path.home() / rel
    if not alvo.exists():
        pytest.skip(f"{alvo} não existe neste host — sem controle positivo")

    amplo = _sob(_amplo(), "/bin/cat", str(alvo))
    if amplo.returncode != 0:
        pytest.skip("nem o perfil amplo lê o alvo; a sonda seria vácuo")

    estreito = _sob(_com_sonda(mod_git.confinamento_de_leitura(repo)), "/bin/cat",
                    str(alvo))
    assert estreito.returncode != 0, f"{nome}: leitura fora da raiz permitida"
    assert "Operation not permitted" in estreito.stderr, estreito.stderr[:200]


def test_projeto_externo_e_negado(repo, tmp_path):
    fora = tmp_path / "outro-projeto"
    fora.mkdir()
    alvo = fora / "segredo.txt"
    alvo.write_text("conteudo de outro projeto\n")

    assert _sob(_amplo(), "/bin/cat", str(alvo)).returncode == 0, (
        "controle positivo falhou: o perfil amplo já negava")
    assert _sob(_com_sonda(mod_git.confinamento_de_leitura(repo)), "/bin/cat",
                str(alvo)).returncode != 0


def test_canario_controlado_fora_da_fronteira_e_negado(repo, tmp_path):
    canario = tmp_path / "CANARIO"
    canario.write_text("nao pode ser lido\n")
    assert _sob(_amplo(), "/bin/cat", str(canario)).returncode == 0
    assert _sob(_com_sonda(mod_git.confinamento_de_leitura(repo)), "/bin/cat",
                str(canario)).returncode != 0


def test_gitconfig_do_usuario_fica_inalcancavel(repo):
    """Ganho concreto de A2, descoberto pela própria bateria.

    Sob o perfil AMPLO o Git alcançava `~/.gitconfig` (a neutralização era só
    por ambiente — `GIT_CONFIG_GLOBAL=/dev/null`). Sob o piso ele nem chega ao
    arquivo: a defesa deixou de depender de UMA variável não ter sido
    esquecida, e passou a ser fronteira de filesystem.
    """
    alvo = Path.home() / ".gitconfig"
    if not alvo.exists():
        pytest.skip("~/.gitconfig não existe neste host")
    assert _sob(_amplo(), "/bin/cat", str(alvo)).returncode == 0
    assert _sob(_com_sonda(mod_git.confinamento_de_leitura(repo)), "/bin/cat",
                str(alvo)).returncode != 0


def test_o_proprio_repo_CONTINUA_legivel(repo):
    """ALLOW positivo. Sem ele a redução seria só quebra."""
    r = _sob(_com_sonda(mod_git.confinamento_de_leitura(repo)), "/bin/cat",
             str(repo / "a.txt"))
    assert r.returncode == 0, r.stderr[:300]
    assert r.stdout == "conteudo\n"


def test_ancestral_nao_permite_LISTAR(repo):
    """`file-read-metadata` no ancestral resolve o componente e só.

    Se ele permitisse listar, a fronteira vazaria o nome de todo projeto
    vizinho — e o teste acima ainda passaria.
    """
    pai = str(Path(repo).parent)
    r = _sob(_com_sonda(mod_git.confinamento_de_leitura(repo)), "/bin/ls", pai)
    assert r.returncode != 0, (
        "metadata do ancestral virou permissão de listagem")


# ═══════════════ A capacidade tem de CONTINUAR funcionando ══════════════════

@pytest.mark.parametrize("op", [
    ["log", "--oneline", "-1"],
    ["show", "--stat", "HEAD"],
    ["diff", "HEAD", "HEAD"],
])
def test_operacoes_object_only_funcionam_sob_o_piso(repo, op):
    real = os.path.realpath(repo)
    # `binario_de_git()` e não `GIT`: DENTRO do sandbox o produto executa o
    # binário resolvido. Usar o shim aqui media um caminho que o adapter não
    # percorre — e trazia junto o `rc=71` dependente do cache do xcrun.
    r = _sob(mod_git.confinamento_de_leitura(repo), mod_git.binario_de_git(),
             "-C", real, "--no-pager", *op, env=mod_git.ambiente_minimo())
    assert r.returncode == 0, f"{op}: rc={r.returncode} {r.stderr[:300]}"


def test_paridade_de_saida_com_o_perfil_amplo(repo):
    """A redução não pode MUDAR o resultado, só a autoridade."""
    real = os.path.realpath(repo)
    argv = (mod_git.binario_de_git(), "-C", real, "--no-pager", "log",
            "--oneline")
    amb = mod_git.ambiente_minimo()
    largo = _sob(supervisor.Confinamento(escrita=(), declara_sem_escrita=True,
                                         exec_permitido=mod_git.executaveis_de_git()),
                 *argv, env=amb)
    estreito = _sob(mod_git.confinamento_de_leitura(repo), *argv, env=amb)
    assert largo.returncode == estreito.returncode == 0
    assert largo.stdout == estreito.stdout, "a saída divergiu sob o piso"


def test_o_binario_executado_NAO_e_o_shim_do_xcrun():
    """Regressão do `rc=71` que dependia de CACHE, não de código.

    `/usr/bin/git` no macOS é o shim do `xcrun`: ele procura o Git consultando
    `$TMPDIR/xcrun_db` e, no miss, tenta `xcodebuild` — fora da allowlist. Isso
    fazia a MESMA suíte passar ou falhar conforme a ordem dos testes (medido:
    897/897 na família inteira, 8 falhas rodando só `c1_git`), e derrubava 222
    testes no runner macOS do CI.

    Voltar a `/usr/bin/git` reintroduz a procura. Este teste é o que impede.
    """
    escolhido = mod_git.binario_de_git()
    assert escolhido != GIT, (
        "o adapter voltou ao shim do xcrun — o rc=71 dependente de cache volta "
        "junto")
    assert os.path.exists(escolhido), f"binário resolvido não existe: {escolhido}"
    # Contraprova de que o resolvido é Git de verdade, e não um caminho qualquer
    # que só "não é o shim".
    r = subprocess.run([escolhido, "--version"], capture_output=True, text=True)
    assert r.returncode == 0 and "git version" in r.stdout


def test_o_binario_executado_esta_na_allowlist_de_exec():
    """Sem isto, resolver o binário certo e não o permitir daria `Operation not
    permitted` — trocaria um modo de falha por outro."""
    assert mod_git.binario_de_git() in mod_git.executaveis_de_git()


def test_adapter_real_de_leitura_funciona_ponta_a_ponta(repo, tmp_path):
    """Pelo caminho GOVERNADO, não por sandbox-exec direto."""
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.wiring import registrar_git
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades

    registro = RegistroCapacidades(policy=PolicyEngine(tmp_path / "p.json"),
                                   approver=lambda *a, **k: True)
    registrar_git(registro, raizes=(str(tmp_path),))
    r = mod_git.GitAdapter().executar(
        CapabilityRequest(capacidade="git-log", alvo=str(repo),
                          argumentos={"limite": 1}),
        CapabilityContext.de_registro(registro, "git-log",
                                      "runtime-governado",
                                      raizes=(str(tmp_path),)))
    assert r is not None


# ═════════════════════ Estrutura e fail-closed ══════════════════════════════

def test_developer_dir_e_derivado_em_runtime():
    fonte = Path(supervisor.__file__).read_text("utf-8")
    assert 'realpath("/var/select/developer_dir")' in fonte, (
        "caminho do Xcode fixado quebra após `xcode-select -s`")


def test_piso_recusa_em_vez_de_cair_para_leitura_ampla(monkeypatch):
    """FAIL-CLOSED: toolchain que não resolve é RECUSA, nunca degradação."""
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    with pytest.raises(supervisor.ErroSeguranca, match="developer dir"):
        supervisor.perfil(supervisor.Confinamento(
            escrita=(), declara_sem_escrita=True, leitura=("/private/tmp",)))


def test_symlinks_de_var_e_etc_tem_allow_proprio(repo):
    p = supervisor.perfil(mod_git.confinamento_de_leitura(repo))
    assert '(allow file-read-metadata (literal "/var"))' in p
    assert '(allow file-read-metadata (literal "/etc"))' in p


def test_worktree_ligada_inclui_git_dir_E_common_dir(repo):
    """Worktree ligada tem estado em DOIS lugares; faltar um dá rc=128."""
    conf = mod_git.confinamento_de_leitura(repo)
    git_dir, comum = mod_git.diretorio_git(repo)
    assert git_dir in conf.leitura
    if comum != git_dir:
        assert comum in conf.leitura


def test_raiz_alcancada_por_symlink_usa_o_caminho_REAL(tmp_path, repo):
    """Landmine do realpath: a autoridade acompanha o destino, não o nome."""
    link = tmp_path / "atalho"
    link.symlink_to(repo, target_is_directory=True)
    p = supervisor.perfil(mod_git.confinamento_de_leitura(link))
    assert f'(subpath "{os.path.realpath(repo)}")' in p
    assert f'(subpath "{link}")' not in p


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
