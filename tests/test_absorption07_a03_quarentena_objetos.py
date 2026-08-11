"""A0.3 — o segredo NUNCA chega ao object store permanente.

A0.1 fechou a cadeia até o commit restaurando o índice. Sobrava um resíduo
medido: o blob do `filter.clean` já estava gravado em `.git/objects` quando o
filtro falhava. Restaurar o índice tira a REFERÊNCIA, não o objeto — e o
segredo ficava legível por `git cat-file` até um `gc`:

    fsck: unreachable blob cdabdb02... conteúdo 'SENHA=hunter2'

A estratégia aqui NÃO é apagar depois de gravado. É não gravar:

    GIT_OBJECT_DIRECTORY          → escrita de objeto vai para a quarentena
    GIT_ALTERNATE_OBJECT_DIRECTORIES → leitura continua vendo o store real

É o mesmo mecanismo que o Git usa em `receive-pack` para não sujar o
repositório com um push ainda não aceito. Na falha, apaga-se um diretório que
só esta execução escreveu — nunca `git gc`, nunca `prune` amplo.

CONTRATO DESTE ARQUIVO, depois de QUALQUER falha:

    INDEX_BYTES_AFTER == INDEX_BYTES_BEFORE
    NEW_PERMANENT_SECRET_OBJECTS = 0
    REACHABLE_SECRET_OBJECTS     = 0
    UNREACHABLE_SECRET_OBJECTS   = 0

Segredos aqui são FIXTURES SINTÉTICAS (`SENHA=hunter2`), nunca material real.
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

SEGREDO = "SENHA=hunter2\n"          # fixture sintética
FILTRO_QUEBRADO = "/nao/existe/redator-de-segredo"


def _git(repo, *a):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run([GIT, "-C", str(repo), *a], capture_output=True,
                          text=True, env=env)


def _objetos(repo) -> set[str]:
    """Inventário do store PERMANENTE (o real, não a quarentena)."""
    raiz = Path(diretorio_git(repo)[1]) / "objects"
    return {str(p.relative_to(raiz)) for p in raiz.rglob("*") if p.is_file()}


def _indice(repo) -> bytes | None:
    alvo = Path(diretorio_git(repo)[0]) / "index"
    return alvo.read_bytes() if alvo.exists() else None


def _segredo_no_store(repo) -> list[str]:
    """SHAs cujo conteúdo bruto contém o segredo. A prova direta."""
    achados = []
    for rel in _objetos(repo):
        sha = rel.replace("/", "").replace("\\", "")
        if len(sha) < 40:
            continue          # pack/idx e afins não são objeto solto
        r = _git(repo, "cat-file", "-p", sha)
        if r.returncode == 0 and "hunter2" in r.stdout:
            achados.append(sha)
    return achados


def _repo(base: Path, filtro: str | None = FILTRO_QUEBRADO) -> Path:
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


def _exec(repo, caminhos, tmp_path, capacidade="git-add"):
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


def _falha_e_confere(repo, caminhos, tmp_path, excecao=Exception):
    """Roda esperando falha e asserta o contrato inteiro de A0.3."""
    antes_idx, antes_obj = _indice(repo), _objetos(repo)
    with pytest.raises(excecao):
        _exec(repo, caminhos, tmp_path)
    assert _indice(repo) == antes_idx, "o índice não voltou ao byte anterior"
    novos = _objetos(repo) - antes_obj
    assert novos == set(), f"objetos novos no store PERMANENTE: {novos}"
    assert _segredo_no_store(repo) == [], "o segredo ficou no object store"
    resto = _git(repo, "fsck", "--unreachable", "--no-progress")
    assert "unreachable blob" not in resto.stdout, resto.stdout[:300]


# ═════ CONTROLE POSITIVO — sem ele todo o resto poderia ser vácuo ═══════════

def test_controle_positivo_sem_quarentena_o_blob_ia_para_o_store(tmp_path):
    """Prova que o `git add` CRU grava o segredo no store permanente.

    Se isto parar de valer, os testes abaixo deixam de medir contenção.
    """
    repo = _repo(tmp_path)
    (repo / "x.secreto").write_text(SEGREDO)
    antes = _objetos(repo)
    r = _git(repo, "add", "--", "x.secreto")
    assert r.returncode == 0
    assert _objetos(repo) - antes, "nenhum objeto novo — cenário não se armou"
    assert _segredo_no_store(repo), (
        "o segredo NÃO foi para o store nem sem quarentena; premissa mudou")


# ═══════════════════ O CONTRATO, por modo de falha ══════════════════════════

def test_arquivo_novo_com_segredo(tmp_path):
    repo = _repo(tmp_path)
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path, supervisor.ErroSeguranca)


def test_arquivo_modificado(tmp_path):
    repo = _repo(tmp_path, filtro=None)
    (repo / "x.secreto").write_text("inocente\n")
    _git(repo, "add", "--", "x.secreto")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "config", "filter.redator.clean", FILTRO_QUEBRADO)
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path, supervisor.ErroSeguranca)


def test_multiplos_blobs(tmp_path):
    repo = _repo(tmp_path)
    for i in range(4):
        (repo / f"s{i}.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, [f"s{i}.secreto" for i in range(4)], tmp_path,
                     supervisor.ErroSeguranca)


def test_subdiretorio(tmp_path):
    repo = _repo(tmp_path)
    (repo / "sub" / "fundo").mkdir(parents=True)
    (repo / "sub" / "fundo" / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["sub/fundo/x.secreto"], tmp_path,
                     supervisor.ErroSeguranca)


def test_nome_unicode_e_RECUSADO_pela_gramatica_antes_de_executar(tmp_path):
    """Não é lacuna: a gramática de caminho exclui não-ASCII DE PROPÓSITO.

    A recusa acontece ANTES de qualquer execução, então nem quarentena nem
    índice chegam a ser tocados — a fronteira mais barata é a que nunca roda.
    Asserto a recusa, e também que nada foi escrito por causa dela.
    """
    from nomos.adapters.contrato import ErroInvalido
    repo = _repo(tmp_path)
    (repo / "acentuado-ção.secreto").write_text(SEGREDO)
    antes_idx, antes_obj = _indice(repo), _objetos(repo)

    with pytest.raises(ErroInvalido, match="gramática"):
        _exec(repo, ["acentuado-ção.secreto"], tmp_path)

    assert _indice(repo) == antes_idx
    assert _objetos(repo) - antes_obj == set()
    assert _segredo_no_store(repo) == []


def test_pre_staged_unrelated_file_sobrevive(tmp_path):
    repo = _repo(tmp_path)
    (repo / "importante.txt").write_text("ESTAGIADO DE PROPOSITO\n")
    _git(repo, "add", "--", "importante.txt")
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path, supervisor.ErroSeguranca)
    assert _git(repo, "show", ":importante.txt").stdout == (
        "ESTAGIADO DE PROPOSITO\n")


def test_partial_staging_preservado(tmp_path):
    repo = _repo(tmp_path)
    alvo = repo / "parcial.txt"
    alvo.write_text("VERSAO NO INDICE\n")
    _git(repo, "add", "--", "parcial.txt")
    alvo.write_text("VERSAO NA WORKING TREE\n")
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path, supervisor.ErroSeguranca)
    assert _git(repo, "show", ":parcial.txt").stdout == "VERSAO NO INDICE\n"
    assert alvo.read_text() == "VERSAO NA WORKING TREE\n"


def test_delete_e_add_na_mesma_operacao(tmp_path):
    repo = _repo(tmp_path)
    (repo / "some.txt").write_text("x\n")
    _git(repo, "add", "--", "some.txt")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "rm", "-q", "--", "some.txt")
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path, supervisor.ErroSeguranca)


def test_rename_estagiado_preservado(tmp_path):
    repo = _repo(tmp_path)
    (repo / "velho.txt").write_text("conteudo\n")
    _git(repo, "add", "--", "velho.txt")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "mv", "velho.txt", "novo.txt")
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path, supervisor.ErroSeguranca)


def test_rc0_silent_corruption(tmp_path):
    """Filtro que EXECUTA e falha: rc=0, `error:` só na 2ª linha do stderr."""
    repo = _repo(tmp_path, filtro=None)
    regras = tmp_path / "regras.sed"                     # não existe
    _git(repo, "config", "filter.redator.clean", f"/usr/bin/sed -f {regras}")
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path, supervisor.ErroSeguranca)


def test_filtro_com_required_rc_nao_zero(tmp_path):
    repo = _repo(tmp_path, filtro=None)
    _git(repo, "config", "filter.redator.clean", FILTRO_QUEBRADO)
    _git(repo, "config", "filter.redator.required", "true")
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "x.secreto").write_text(SEGREDO)
    _falha_e_confere(repo, ["x.secreto"], tmp_path)


def test_excecao_arbitraria_depois_do_efeito(monkeypatch, tmp_path):
    repo = _repo(tmp_path, filtro=None)
    (repo / "x.secreto").write_text(SEGREDO)
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            RuntimeError("injetada")))
    _falha_e_confere(repo, ["x.secreto"], tmp_path, RuntimeError)


def test_KeyboardInterrupt(monkeypatch, tmp_path):
    repo = _repo(tmp_path, filtro=None)
    (repo / "x.secreto").write_text(SEGREDO)
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            KeyboardInterrupt()))
    _falha_e_confere(repo, ["x.secreto"], tmp_path, KeyboardInterrupt)


def test_SystemExit(monkeypatch, tmp_path):
    repo = _repo(tmp_path, filtro=None)
    (repo / "x.secreto").write_text(SEGREDO)
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            SystemExit(1)))
    _falha_e_confere(repo, ["x.secreto"], tmp_path, SystemExit)


# ═════════ CONTROLES NEGATIVOS — a quarentena não pode quebrar o bom ════════

def test_sucesso_normal_promove_o_objeto(tmp_path):
    """Uma quarentena que descartasse sempre também "protegeria"."""
    repo = _repo(tmp_path, filtro=None)
    (repo / "bom.txt").write_text("conteudo legitimo\n")
    antes = _objetos(repo)

    r = _exec(repo, ["bom.txt"], tmp_path)
    assert r.efeito_aplicado is True
    assert _objetos(repo) - antes, "o objeto NÃO foi promovido ao store"
    assert _git(repo, "show", ":bom.txt").stdout == "conteudo legitimo\n"
    assert _git(repo, "fsck", "--no-progress").returncode == 0


def test_filtro_redator_legitimo_persiste_o_conteudo_redigido(tmp_path):
    repo = _repo(tmp_path, filtro=None)
    _git(repo, "config", "filter.redator.clean",
         "/usr/bin/sed -e s/SENHA=.*/REDIGIDO/")
    (repo / ".gitattributes").write_text("*.secreto filter=redator\n")
    _git(repo, "add", "--", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "attrs")
    (repo / "x.secreto").write_text(SEGREDO)

    r = _exec(repo, ["x.secreto"], tmp_path)
    assert r.efeito_aplicado is True
    assert _git(repo, "show", ":x.secreto").stdout.strip() == "REDIGIDO"
    assert _segredo_no_store(repo) == [], "o segredo cru vazou mesmo redigido"


def test_commit_apos_add_funciona_ponta_a_ponta(tmp_path):
    repo = _repo(tmp_path, filtro=None)
    (repo / "bom.txt").write_text("conteudo\n")
    _exec(repo, ["bom.txt"], tmp_path)
    r = _exec(repo, None, tmp_path, capacidade="git-commit")
    assert r.efeito_aplicado is True
    assert _git(repo, "fsck", "--no-progress").returncode == 0
    assert "bom.txt" in _git(repo, "show", "--stat", "HEAD").stdout


def test_dedup_objeto_que_ja_existe_no_store(tmp_path):
    """Colisão por conteúdo: mesmo SHA já presente. Promoção não pode quebrar."""
    repo = _repo(tmp_path, filtro=None)
    (repo / "a.txt").write_text("mesmo conteudo\n")
    _exec(repo, ["a.txt"], tmp_path)
    (repo / "b.txt").write_text("mesmo conteudo\n")      # blob idêntico
    r = _exec(repo, ["b.txt"], tmp_path)
    assert r.efeito_aplicado is True
    assert _git(repo, "show", ":b.txt").stdout == "mesmo conteudo\n"
    assert _git(repo, "fsck", "--no-progress").returncode == 0


# ═════════════════════ Invariantes estruturais ══════════════════════════════

def test_quarentena_nao_sobrevive_a_operacao(tmp_path):
    """Nem no sucesso nem na falha pode restar diretório de quarentena."""
    repo = _repo(tmp_path, filtro=None)
    (repo / "bom.txt").write_text("x\n")
    _exec(repo, ["bom.txt"], tmp_path)
    git_dir = Path(diretorio_git(repo)[0])
    assert list(git_dir.glob("nomos-quarentena-*")) == []

    (tmp_path / "outro").mkdir()
    repo2 = _repo(tmp_path / "outro", filtro=FILTRO_QUEBRADO)
    (repo2 / "x.secreto").write_text(SEGREDO)
    with pytest.raises(supervisor.ErroSeguranca):
        _exec(repo2, ["x.secreto"], tmp_path)
    assert list(Path(diretorio_git(repo2)[0]).glob("nomos-quarentena-*")) == []


def test_guard_de_ambiente_continua_recusando_as_variaveis_do_chamador():
    """A quarentena NÃO afrouxou o guard.

    As duas variáveis seguem proibidas quando vêm do CHAMADOR — o supervisor
    as injeta depois da conferência, por parâmetro tipado. Sem este teste, a
    mudança de A0.3 poderia virar uma porta de ambiente herdado.
    """
    for chave in ("GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        with pytest.raises(supervisor.ErroSeguranca):
            supervisor.conferir_ambiente({chave: "/tmp/qualquer"})


def test_nunca_usa_gc_ou_prune_como_mecanismo():
    fonte = Path(git_tree.__file__).read_text("utf-8")
    for proibido in ('"gc"', "'gc'", '"prune"', "'prune'", '"reset"',
                     "'reset'"):
        assert proibido not in fonte, (
            f"{proibido} como mecanismo de recuperação é indiscriminado")


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
