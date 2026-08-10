"""C2a — `git-tag`: escrita de referência sobre objeto já commitado.

O C2 original juntava `add`, `commit`, `tag` e `push`. A medição do `git add`
desfez o plano: com `filter.hostil.clean` do próprio repositório, ele executou
o programa do repo com `RC=0`, sem stderr, sem sinal. Sobrou a divisão por
fronteira de confiança — e `git-tag` é a única das quatro que não toca working
tree, nem índice, nem rede.

A primeira versão é LIGHTWEIGHT de propósito. Tag anotada exige mensagem, e
mensagem convida editor e assinatura — três caminhos de execução externa para
uma operação cujo efeito é escrever vinte bytes num arquivo de ref. Sem
mensagem não há o que editar nem o que assinar.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters.contrato import ErroInvalido
from nomos.adapters.git_write import tag_valida
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.runtime.governado import RuntimeGovernado

GIT = "/usr/bin/git"
pytestmark = pytest.mark.skipif(not Path(GIT).exists(), reason="git ausente")


def _sim(_d):
    return True


def _git(repo: Path, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
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
    (repo / "a.txt").write_text("x\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "primeiro")
    _git(repo, "commit", "-qm", "segundo", "--allow-empty")
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          git=True, git_write=True)
    return rt, ws, repo, ctx


def _plano(rt, **params):
    return rt.rodar("c2a", passos=[{"id": "p", "ferramenta": "git-tag",
                                    "params": params}])


def _tags(repo: Path) -> set[str]:
    return set(_git(repo, "tag", "-l").stdout.split())


# ============================================ execução real

def test_c2a_cria_tag_sobre_ref(amb):
    """REAL_GIT_WRITE_TEST: efeito real, verificado pelo próprio git."""
    rt, _ws, repo, _ = amb
    res = _plano(rt, alvo=str(repo), tag="v1.0.0", objeto="HEAD")
    assert res.ok, res.motivo
    assert "v1.0.0" in _tags(repo)


def test_c2a_cria_tag_sobre_SHA_real(amb):
    rt, _ws, repo, _ = amb
    sha = _git(repo, "rev-parse", "HEAD~1").stdout.strip()
    assert _plano(rt, alvo=str(repo), tag="marco", objeto=sha).ok
    assert _git(repo, "rev-parse", "marco").stdout.strip() == sha


def test_c2a_tag_e_leve_nao_anotada(amb):
    """Lightweight: o objeto apontado é o COMMIT, não um tag object.

    Se fosse anotada, haveria objeto de tag — e objeto de tag carrega mensagem,
    que é o que abre editor e assinatura.
    """
    rt, _ws, repo, _ = amb
    _plano(rt, alvo=str(repo), tag="leve", objeto="HEAD")
    tipo = _git(repo, "cat-file", "-t", "leve").stdout.strip()
    assert tipo == "commit", f"tag não é leve: objeto é {tipo}"


# ============================================ contrato sem defaults

def test_c2a_target_e_OBRIGATORIO(amb):
    """TAG_TARGET_REQUIRED=TRUE — ausência não vira HEAD.

    Um default que muda o objeto marcado transforma "marque este commit" em
    "marque o que estiver por aí", e o operador aprovou a primeira coisa.
    """
    rt, _ws, repo, _ = amb
    res = _plano(rt, alvo=str(repo), tag="sem-alvo")
    assert not res.ok
    assert "sem-alvo" not in _tags(repo)


def test_c2a_tag_e_obrigatoria(amb):
    rt, _ws, repo, _ = amb
    assert not _plano(rt, alvo=str(repo), objeto="HEAD").ok


@pytest.mark.parametrize("ruim", [
    "-d", "-f", "--delete", "--force", "-a", "-s", "-m", "--sign",
    "v1 ", " v1", "v1/x", "v1..v2", "v1@{0}", "v1;id", "v1`id`", "v1$(id)",
    "v1|x", "v1\nHEAD", "v1\x00", "", "a" * 200, "v1:x", "v1^", "v1~1",
])
def test_c2a_gramatica_de_tag_recusa(ruim):
    """TAG_STARTS_WITH_DASH=DENY e TAG_OPTION_INJECTION=DENY.

    `-d` apaga e `-f` sobrescreve: uma "tag" que começa com `-` não cria nada,
    destrói.
    """
    with pytest.raises(ErroInvalido):
        tag_valida(ruim)


@pytest.mark.parametrize("boa", ["v1.0.0", "release-2", "marco", "RC1", "a"])
def test_c2a_gramatica_aceita_tag_legitima(boa):
    assert tag_valida(boa) == boa


@pytest.mark.parametrize("ruim", ["-f", "--force", "-d HEAD", "HEAD;id", " HEAD"])
def test_c2a_target_com_opcao_e_recusado(amb, ruim):
    """TARGET_OPTION_INJECTION=DENY."""
    rt, _ws, repo, _ = amb
    res = _plano(rt, alvo=str(repo), tag="ok", objeto=ruim)
    assert not res.ok
    assert "ok" not in _tags(repo)


def test_c2a_target_inexistente_falha_tipado(amb):
    rt, _ws, repo, _ = amb
    res = _plano(rt, alvo=str(repo), tag="fantasma", objeto="naoexiste")
    assert not res.ok
    assert "fantasma" not in _tags(repo)


def test_c2a_repo_fora_do_escopo_e_negado(amb, tmp_path):
    rt, _ws, _repo, _ = amb
    fora = tmp_path / "fora"
    fora.mkdir()
    _git(fora, "init", "-q", "-b", "main")
    _git(fora, "commit", "-qm", "x", "--allow-empty")
    assert not _plano(rt, alvo=str(fora), tag="invasora", objeto="HEAD").ok
    assert "invasora" not in _tags(fora)


def test_c2a_adapter_recusa_repo_fora_do_escopo_sem_o_pdp(amb, tmp_path):
    """Cada camada segura sozinha — a lição que o M3 do C1 deixou."""
    from nomos.adapters.caminho import ErroEscopo
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.git_write import GitTagAdapter
    from nomos.adapters.wiring import registrar_git_write
    from nomos.orquestracao.registro import RegistroCapacidades
    _rt, ws, _repo, _ = amb
    fora = tmp_path / "fora2"
    fora.mkdir()
    _git(fora, "init", "-q", "-b", "main")
    _git(fora, "commit", "-qm", "x", "--allow-empty")
    home = tmp_path / "hd"
    home.mkdir()
    registro = RegistroCapacidades(policy=PolicyEngine(home / "p.json"),
                                   approver=_sim)
    registrar_git_write(registro, raizes=(str(ws),))
    ctx = CapabilityContext.de_registro(registro, "git-tag",
                                        "runtime-governado", raizes=(str(ws),))
    pedido = CapabilityRequest(capacidade="git-tag", alvo=str(fora),
                               argumentos={"tag": "x", "objeto": "HEAD"})
    with pytest.raises(ErroEscopo):
        GitTagAdapter().executar(pedido, ctx)


# ============================================ repositório hostil

@pytest.fixture()
def hostil(amb, tmp_path):
    rt, _ws, repo, _ = amb
    canario = tmp_path / "CANARIO"
    espiao = tmp_path / "espiao.sh"
    espiao.write_text(f"#!/bin/sh\ntouch {canario}\nexit 0\n")
    espiao.chmod(0o755)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for h in ("pre-push", "reference-transaction", "post-checkout", "pre-commit"):
        (hooks / h).write_text(f"#!/bin/sh\ntouch {canario}\n")
        (hooks / h).chmod(0o755)
    for k, v in (("core.hooksPath", str(hooks)), ("core.pager", str(espiao)),
                 ("core.editor", str(espiao)), ("gpg.program", str(espiao)),
                 ("tag.gpgSign", "true"), ("filter.h.clean", str(espiao)),
                 ("filter.h.smudge", str(espiao)), ("diff.external", str(espiao)),
                 ("core.fsmonitor", str(espiao)),
                 ("include.path", str(tmp_path / "extra.cfg"))):
        _git(repo, "config", k, v)
    (tmp_path / "extra.cfg").write_text(
        f"[core]\n\tpager = {espiao}\n[gpg]\n\tprogram = {espiao}\n")
    _git(repo, "config", "alias.zz", f"!{espiao}")
    canario.unlink(missing_ok=True)
    return rt, repo, canario


def test_c2a_repo_hostil_nao_executa_nada(hostil):
    """HOSTILE_REPO_CODE_EXECUTION=FALSE, GPG_EXECUTION=FALSE,
    EDITOR_EXECUTION=FALSE, HOOK_EXECUTION=FALSE."""
    rt, repo, canario = hostil
    res = _plano(rt, alvo=str(repo), tag="v9", objeto="HEAD")
    assert res.ok, res.motivo
    assert "v9" in _tags(repo)
    assert not canario.exists(), "config do repositório executou programa"


def test_c2a_tag_gpgsign_do_repo_nao_assina(hostil):
    """SIGNED_TAG_REACHABLE=FALSE — `tag.gpgSign=true` está no repo hostil."""
    rt, repo, canario = hostil
    assert _plano(rt, alvo=str(repo), tag="v10", objeto="HEAD").ok
    assert _git(repo, "cat-file", "-t", "v10").stdout.strip() == "commit"
    assert not canario.exists()


def test_c2a_nao_toca_worktree_nem_indice(hostil):
    """WORKTREE_TOUCHED=FALSE, INDEX_TOUCHED=FALSE."""
    rt, repo, _c = hostil
    alvos = [repo / "a.txt", repo / ".git" / "index"]
    antes = {p: (p.stat().st_mtime_ns, p.stat().st_size)
             for p in alvos if p.exists()}
    assert _plano(rt, alvo=str(repo), tag="v11", objeto="HEAD").ok
    for p, marca in antes.items():
        assert (p.stat().st_mtime_ns, p.stat().st_size) == marca, f"tocou {p}"


def test_c2a_GIT_DIR_do_host_nao_redireciona(amb, monkeypatch, tmp_path):
    """A lição do M1 do C1, aplicada à escrita — aqui o dano seria criar a tag
    no repositório ERRADO."""
    rt, _ws, repo, _ = amb
    outro = tmp_path / "outro"
    outro.mkdir()
    _git(outro, "init", "-q", "-b", "main")
    _git(outro, "commit", "-qm", "outro", "--allow-empty")
    monkeypatch.setenv("GIT_DIR", str(outro / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outro))
    assert _plano(rt, alvo=str(repo), tag="v12", objeto="HEAD").ok
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_WORK_TREE")
    # A MEDIÇÃO também precisa sair do ambiente contaminado: `_tags()` usa o
    # ambiente do host e, com GIT_DIR ainda apontando para `outro`, leria as
    # tags do lugar errado — o teste falharia por causa do próprio harness,
    # não do adapter. Terceira vez nesta série que o instrumento é que estava
    # medindo a coisa errada.
    assert "v12" in _tags(repo), "tag não foi criada no repositório pedido"
    assert "v12" not in _tags(outro), "tag criada no repositório ERRADO"


# ============================================ governança

def test_c2a_categoria_e_write_local_e_nao_idempotente(amb):
    rt, _ws, _repo, _ = amb
    assert rt.registro.categoria_de("git-tag") is Category.WRITE_LOCAL
    from nomos.adapters.retry import pode_repetir_sozinho
    assert not pode_repetir_sozinho("git-tag")


def test_c2a_add_commit_push_estao_AUSENTES(amb):
    """git-add e git-commit em C2c; git-push em C2b."""
    rt, _ws, _repo, _ = amb
    for ausente in ("git-add", "git-commit", "git-push", "git-write"):
        assert not rt.registro.conhecida(ausente), ausente


def test_c2a_nao_registra_sem_opt_in(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True, git=True)
    assert not rt.registro.conhecida("git-tag")


def test_c2a_passa_por_pdp_e_pep(amb):
    import json
    rt, _ws, repo, ctx = amb
    assert _plano(rt, alvo=str(repo), tag="v13", objeto="HEAD").ok
    ev = [json.loads(x).get("event") for x in
          (ctx["home"] / "logs" / "audit.jsonl").read_text().splitlines()
          if x.strip()]
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao") < ev.index("git.tag")


def test_c2a_registrar_sem_raizes_falha_fechado():
    """Sem escopo, `alvo` seria qualquer repositório do disco.

    Lacuna encontrada por mutação: eu tinha o teste equivalente para
    `registrar_git` (leitura) e simplesmente não escrevi o de escrita. O
    mutante que remove a checagem sobrevivia porque nada a exercitava.
    """
    from nomos.adapters.wiring import registrar_git_write
    with pytest.raises(ValueError, match="raizes"):
        registrar_git_write(object(), raizes=())


def test_c2a_gramatica_positiva_recusa_hifen_SOZINHA():
    """Prova de EQUIVALÊNCIA do mutante "tag aceita hífen".

    O mutante remove `(^-)` de `_TAG_PROIBIDO`. Ele sobrevive porque
    `_TAG_OK` — que exige `[A-Za-z0-9]` no primeiro caractere — já recusa
    tudo que começa com `-`. As duas checagens se sobrepõem nesse ponto de
    propósito: a primeira dá a MENSAGEM que explica o perigo, a segunda é o
    piso. Nenhuma entrada com `-` inicial atravessa só uma delas.

    Este teste congela a sobreposição, para que remover uma das duas não passe
    despercebido caso a outra também mude.
    """

    from nomos.adapters.git_write import _TAG_OK
    for hostil in ("-d", "-f", "--delete", "--force", "-a", "-s", "-m",
                   "--sign", "-", "-x", "--", "-HEAD"):
        assert not _TAG_OK.match(hostil), (
            f"{hostil!r} passaria pela gramática positiva sozinha — a "
            "sobreposição que torna o mutante equivalente deixou de existir")
    assert _TAG_OK.pattern.startswith("^[A-Za-z0-9]"), (
        "a gramática positiva deixou de ancorar no primeiro caractere; o "
        "mutante do hífen passa a ser REAL e precisa morrer por teste próprio")
