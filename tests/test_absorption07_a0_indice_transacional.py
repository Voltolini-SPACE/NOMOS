"""A0 — o índice é TRANSACIONAL: falha do filtro não deixa nada estagiado.

## Por que este arquivo substitui um teste anterior

Existia aqui `test_LIMITE_CONHECIDO_a_recusa_nao_desfaz_o_indice`, que passava
asserindo que o índice FICAVA sujo depois da recusa. Isso estava metodologicamente
errado e foi retirado: um teste verde que afirma a vulnerabilidade transforma o
defeito em comportamento esperado, e faz a CORREÇÃO aparecer como regressão.

O contrato de regressão tem de exigir o oposto, e é o que este arquivo faz:

    depois de QUALQUER falha da operação, o índice é EXATAMENTE o de antes.

## A cadeia que isto fecha

    git add executa
      → conteúdo sensível entra no índice
      → filtro falha
      → NOMOS detecta e recusa (ErroSeguranca)
      → índice CONTINUA contaminado          <- era aqui que parava
      → git commit posterior persiste o segredo

Detecção sem contenção atômica não fecha a cadeia. Por isso o rollback é
BLOCKER_A0: vem antes de reduzir FILE_READ ou PROCESS_EXEC.

## Por que restaurar bytes e nunca `git reset`

`reset` recalcula o índice a partir de HEAD. Isso destrói justamente os casos
que precisam sobreviver: caminho que já estava estagiado de propósito, e
estagiamento PARCIAL (conteúdo no índice diferente do da working tree).
Restaurar os bytes devolve o estado exato; `reset` devolveria um plausível.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.git import diretorio_git
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
pytestmark = pytest.mark.skipif(not Path(GIT).exists(), reason="git ausente")

FILTRO_INEXISTENTE = "/nao/existe/redator-de-segredo"


def _git(repo, *a):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run([GIT, "-C", str(repo), *a], capture_output=True,
                          text=True, env=env)


def _indice_bytes(repo) -> bytes | None:
    alvo = Path(diretorio_git(repo)[0]) / "index"
    return alvo.read_bytes() if alvo.exists() else None


def _novo_repo(base: Path, filtro: str | None = FILTRO_INEXISTENTE) -> Path:
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    if filtro is not None:
        _git(repo, "config", "filter.redator.clean", filtro)
        (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
        _git(repo, "add", "--", ".gitattributes")
        _git(repo, "commit", "-q", "-m", "attrs")
    return repo


def _executar(repo, caminhos, tmp_path, capacidade="git-add"):
    registro = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                   approver=lambda *a, **k: True)
    registrar_git_tree(registro, raizes=(str(tmp_path),))
    args = ({"caminhos": caminhos} if capacidade == "git-add"
            else {"mensagem": "m"})
    return git_tree.GitTreeAdapter().executar(
        CapabilityRequest(capacidade=capacidade, alvo=str(repo),
                          argumentos=args),
        CapabilityContext.de_registro(registro, capacidade,
                                      "runtime-governado",
                                      raizes=(str(tmp_path),)))


# ════════ CONTROLE POSITIVO — sem ele toda asserção abaixo é vácuo ══════════

def test_controle_positivo_o_filtro_quebrado_de_fato_contamina(tmp_path):
    """Prova que, SEM a transação, o `git add` cru suja o índice.

    Se este teste parar de valer, os demais deixam de medir contenção e passam
    a medir "nada aconteceu" — e passariam verdes por engano.
    """
    repo = _novo_repo(tmp_path)
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    r = _git(repo, "add", "--", "a.secreto")
    assert r.returncode == 0, "o Git deixou de sair 0; a premissa mudou"
    assert "external filter" in r.stderr
    assert _git(repo, "show", ":a.secreto").stdout == "SENHA=hunter2\n", (
        "o conteúdo cru não chegou ao índice — o cenário não se armou")


# ═══════════════ O CONTRATO: índice idêntico ao estado anterior ═════════════

def test_indice_volta_exatamente_ao_estado_anterior(tmp_path):
    """O invariante central de A0, em bytes."""
    repo = _novo_repo(tmp_path)
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes, "o índice não voltou ao byte anterior"
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == ""


def test_arquivo_antes_unstaged_continua_unstaged(tmp_path):
    repo = _novo_repo(tmp_path)
    (repo / "outro.txt").write_text("trabalho do usuário\n")
    (repo / "a.secreto").write_text("SENHA=hunter2\n")

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    estagiados = _git(repo, "diff", "--cached", "--name-only").stdout.split()
    assert "outro.txt" not in estagiados
    assert "a.secreto" not in estagiados


def test_arquivo_ja_estagiado_mantem_o_conteudo_estagiado_original(tmp_path):
    """O caso que `git reset` estragaria."""
    repo = _novo_repo(tmp_path)
    (repo / "importante.txt").write_text("VERSAO ESTAGIADA DE PROPOSITO\n")
    _git(repo, "add", "--", "importante.txt")
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes
    assert _git(repo, "show", ":importante.txt").stdout == (
        "VERSAO ESTAGIADA DE PROPOSITO\n"), (
        "o rollback destruiu estagiamento legítimo anterior")


def test_estagiamento_PARCIAL_e_preservado(tmp_path):
    """Índice != working tree: o caso em que `reset` mais claramente erraria."""
    repo = _novo_repo(tmp_path)
    alvo = repo / "parcial.txt"
    alvo.write_text("CONTEUDO ESTAGIADO\n")
    _git(repo, "add", "--", "parcial.txt")
    alvo.write_text("CONTEUDO NOVO NA WORKING TREE\n")   # divergem de propósito
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes
    assert _git(repo, "show", ":parcial.txt").stdout == "CONTEUDO ESTAGIADO\n"
    assert alvo.read_text() == "CONTEUDO NOVO NA WORKING TREE\n", (
        "o rollback tocou a working tree — ele só pode tocar o índice")


def test_remocao_estagiada_e_preservada(tmp_path):
    repo = _novo_repo(tmp_path)
    (repo / "vai_sumir.txt").write_text("x\n")
    _git(repo, "add", "--", "vai_sumir.txt")
    _git(repo, "commit", "-q", "-m", "add")
    _git(repo, "rm", "-q", "--", "vai_sumir.txt")        # remoção estagiada
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes
    assert "vai_sumir.txt" in _git(repo, "diff", "--cached",
                                   "--name-only").stdout


def test_renomeacao_estagiada_e_preservada(tmp_path):
    repo = _novo_repo(tmp_path)
    (repo / "velho.txt").write_text("conteudo\n")
    _git(repo, "add", "--", "velho.txt")
    _git(repo, "commit", "-q", "-m", "add")
    _git(repo, "mv", "velho.txt", "novo.txt")
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes
    # `--name-only` COLAPSA a renomeação no destino (a detecção de rename é
    # padrão no diff). Para ver os dois lados é preciso `--no-renames`, senão
    # o teste mediria a heurística do Git em vez do estado do índice.
    saida = _git(repo, "diff", "--cached", "--name-only", "--no-renames").stdout
    assert "novo.txt" in saida and "velho.txt" in saida


def test_multiplos_caminhos_nenhum_sobrevive_parcialmente(tmp_path):
    """O `add` processa vários caminhos; a falha de UM não pode deixar os
    outros estagiados pela metade."""
    repo = _novo_repo(tmp_path)
    for nome in ("um.txt", "dois.txt"):
        (repo / nome).write_text(f"conteudo de {nome}\n")
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["um.txt", "dois.txt", "a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == ""


def test_repositorio_sem_indice_volta_a_nao_ter_indice(tmp_path):
    """Borda: repo recém-criado. "Restaurar" é o arquivo deixar de existir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "filter.redator.clean", FILTRO_INEXISTENTE)
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    assert _indice_bytes(repo) is None, "o repo já tinha índice; borda perdida"

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) is None, "sobrou índice onde não havia nenhum"


# ═══════════ Modos de falha distintos, mesmo contrato de rollback ═══════════

def test_filtro_com_rc_nao_zero_tambem_desfaz(tmp_path):
    """Outro caminho de saída: `ErroInvalido` por rc != 0, não `ErroSeguranca`.

    `required=true` faz o Git tratar a falha como fatal. O rollback não pode
    depender de QUAL exceção saiu.
    """
    repo = _novo_repo(tmp_path, filtro=None)
    _git(repo, "config", "filter.redator.clean", FILTRO_INEXISTENTE)
    _git(repo, "config", "filter.redator.required", "true")
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(Exception) as exc:
        _executar(repo, ["a.secreto"], tmp_path)
    assert not isinstance(exc.value, AssertionError)

    assert _indice_bytes(repo) == antes
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == ""


def test_filtro_que_executa_e_falha_com_rc0_desfaz(tmp_path):
    """Binário existe e roda; quem falha é ele (regras fora do repo)."""
    repo = _novo_repo(tmp_path, filtro=None)
    regras = tmp_path / "regras.sed"                     # não existe
    _git(repo, "config", "filter.redator.clean", f"/usr/bin/sed -f {regras}")
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "a.secreto").write_text("SEGREDO=abc123\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes


@pytest.mark.git_governado
def test_excecao_arbitraria_no_meio_tambem_desfaz(monkeypatch, tmp_path):
    """Injeta falha DEPOIS do exec: prova que o rollback é do `finally`, não
    de um ramo específico de erro. Cobre timeout e interrupção por construção.
    """
    repo = _novo_repo(tmp_path, filtro=None)
    (repo / "normal.txt").write_text("conteudo\n")
    antes = _indice_bytes(repo)

    original = git_tree.GitTreeAdapter._auditar

    def explode(self, *a, **k):
        raise RuntimeError("falha injetada depois do efeito no índice")

    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", explode)
    with pytest.raises(RuntimeError):
        _executar(repo, ["normal.txt"], tmp_path)
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", original)

    assert _indice_bytes(repo) == antes, (
        "exceção fora do caminho de segurança deixou o índice mexido")


@pytest.mark.git_governado
def test_KeyboardInterrupt_tambem_desfaz(monkeypatch, tmp_path):
    """`BaseException`, não `Exception`: Ctrl-C não pode deixar segredo."""
    repo = _novo_repo(tmp_path, filtro=None)
    (repo / "normal.txt").write_text("conteudo\n")
    antes = _indice_bytes(repo)

    def interrompe(self, *a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", interrompe)
    with pytest.raises(KeyboardInterrupt):
        _executar(repo, ["normal.txt"], tmp_path)

    assert _indice_bytes(repo) == antes


# ═════════════ CONTROLE NEGATIVO — a transação não pode quebrar o bom ═══════

@pytest.mark.git_governado
def test_operacao_legitima_CONFIRMA_e_nao_sofre_rollback(tmp_path):
    """Uma transação que desfizesse sempre também "protegeria". Aqui o efeito
    TEM de persistir."""
    repo = _novo_repo(tmp_path, filtro=None)
    (repo / "bom.txt").write_text("conteudo legitimo\n")
    antes = _indice_bytes(repo)

    r = _executar(repo, ["bom.txt"], tmp_path)
    assert r.efeito_aplicado is True
    assert _indice_bytes(repo) != antes, "o efeito legítimo foi desfeito"
    assert _git(repo, "show", ":bom.txt").stdout == "conteudo legitimo\n"


@pytest.mark.git_governado
def test_commit_legitimo_continua_funcionando(tmp_path):
    repo = _novo_repo(tmp_path, filtro=None)
    (repo / "bom.txt").write_text("conteudo\n")
    _executar(repo, ["bom.txt"], tmp_path)
    r = _executar(repo, None, tmp_path, capacidade="git-commit")
    assert r.efeito_aplicado is True
    assert "bom.txt" in _git(repo, "show", "--stat", "HEAD").stdout


def test_filtro_LEGITIMO_e_negado_e_o_indice_fica_intacto(tmp_path):
    """CONTRATO NOVO (A5). Antes exigia que o redator FUNCIONASSE.

    O caminho padrão nega qualquer executável escolhido pelo REPOSITÓRIO —
    inclusive um `/usr/bin/sed` inofensivo. O critério não é a índole do
    binário: é quem escolhe. O caso legítimo migra para a capability governada
    (`git-add-governed-filter`), onde o executável vem do registry.

    O que este teste preserva de A0: a negação é transacional. Índice idêntico
    ao anterior, nada estagiado.
    """
    repo = _novo_repo(tmp_path, filtro=None)
    _git(repo, "config", "filter.redator.clean",
         "/usr/bin/sed -e s/SENHA=.*/REDIGIDO/")
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "a.secreto").write_text("SENHA=hunter2\n")
    antes = _indice_bytes(repo)

    with pytest.raises(supervisor.ErroSeguranca):
        _executar(repo, ["a.secreto"], tmp_path)

    assert _indice_bytes(repo) == antes
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == ""


# ═══════════════════════ Invariante estrutural do rollback ══════════════════

def test_rollback_nunca_usa_git_reset():
    """`reset` recalcula a partir de HEAD e destruiria estagiamento parcial."""
    fonte = Path(git_tree.__file__).read_text("utf-8")
    assert '"reset"' not in fonte and "'reset'" not in fonte, (
        "rollback por `git reset` é indiscriminado — restaure os bytes")


def test_instantaneo_e_tirado_ANTES_da_execucao():
    """Ordem importa: instantâneo depois do exec guardaria o índice já sujo."""
    fonte = Path(git_tree.__file__).read_text("utf-8")
    # Casa a CHAMADA, não a lista de argumentos: `_instantaneo_do_indice` passou
    # a receber a autoridade validada (bind authority, TOCTOU), e prender a
    # assinatura aqui faria este teste falhar por refatoração legítima em vez de
    # por inversão de ordem, que é o que ele mede.
    i_snap = fonte.index("_instantaneo_do_indice(repo", fonte.index("def executar"))
    i_exec = fonte.index("supervisor.executar", fonte.index("def executar"))
    assert i_snap < i_exec, "o instantâneo é tirado depois do exec"


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
