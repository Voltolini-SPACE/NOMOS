"""`.7.14` / `N-A7-01` / `N-A7-02` — a autoridade era uma STRING de caminho.

`AutoridadeDeRepo` fechou o TOCTOU ENTRE CHAMADORES e deixou aberto tudo o que
vem DEPOIS dela. Quem age re-resolve o caminho na hora de agir:

    supervisor.perfil()    canonicaliza `conf.escrita` ao emitir o SBPL
    _gravar_atomico        mkstemp(dir=alvo.parent), por caminho
    _restaurar_refs        mkdir(parents=True) + gravação, por caminho
    _promover_quarentena   canonicaliza os DOIS lados pelo MESMO symlink

Trocar `<repo>/.git` — diretório próprio, DENTRO das raízes — por SYMLINK para
um git dir de FORA, depois da validação, bastava. MEDIDO na 4ª medição global:

    12/12   perfis do sandbox com `(allow file-write* (subpath "<fora>/gd"))`
    ok=True `git-tag` governado criando ref no repositório de FORA
    ok=True `git-log` devolvendo a história do repositório de FORA
    20/20   o SUPERVISOR (fora do sandbox) sobrescrevendo índice e reflog de
            TERCEIRO pelo DESFAZER — com o NOMOS relatando a operação como
            RECUSADA. A recusa vinha DEPOIS do dano.

## Por que `(st_dev, st_ino)` e não mais uma releitura

O caminho não carrega identidade; o inode carrega. Um symlink plantado no lugar
do diretório resolve para OUTRO inode, e a divergência é observável sem confiar
em releitura de conteúdo — que é justamente o canal que o repositório controla.

O que isto NÃO resolve, e está dito no código: entre `conferir_identidade()` e o
`perfil()` que re-resolve ainda restam microssegundos. O que a checagem elimina é
a janela de MILISSEGUNDOS que a medição explorou, não a de instruções. Fechar a
de instruções exigiria I/O relativo a descritor em toda a cadeia.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import git, supervisor

GIT = "/usr/bin/git"


def _git(*a):
    return subprocess.run([GIT, *a], capture_output=True, text=True)


def _init(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q", "-b", "main", str(p)], check=True,
                   capture_output=True)
    _git("-C", str(p), "config", "user.email", "t@t")
    _git("-C", str(p), "config", "user.name", "t")
    return p


@pytest.fixture
def cenario(tmp_path):
    """Hostil DENTRO das raízes; alvo FORA. O flip acontece após a validação."""
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    hostil = _init(raiz / "hostil")
    alvo = _init(fora / "alvo")
    (alvo / "DA_VITIMA.txt").write_text("da vitima\n")
    _git("-C", str(alvo), "add", "DA_VITIMA.txt")
    _git("-C", str(alvo), "commit", "-qm", "MENSAGEM_SO_DO_REPO_DE_FORA")

    class Cen:
        def __init__(self):
            self.raiz, self.fora, self.hostil, self.alvo = raiz, fora, hostil, alvo

        def ligar(self):
            gd, cm = git.conferir_git_dir(str(hostil), (str(raiz),))
            return git.autoridade_de(str(hostil), gd, cm)

        def flip(self):
            """O REPOSITÓRIO troca o próprio `.git` por symlink para fora."""
            shutil.rmtree(hostil / ".git")
            (hostil / ".git").symlink_to(alvo / ".git", target_is_directory=True)

    return Cen()


def test_r4_01_confinamento_de_ESCRITA_recusa_apos_a_troca(cenario):
    """O perfil do sandbox saía com raiz de escrita FORA das raízes, 12/12."""
    aut = cenario.ligar()
    cenario.flip()
    with pytest.raises(supervisor.ErroSeguranca, match="NÃO é mais o objeto validado"):
        git.confinamento_de_repo(str(cenario.hostil), autoridade=aut)


def test_r4_02_confinamento_de_LEITURA_recusa_apos_a_troca(cenario):
    """`git-log` governado devolvia a história do repositório de FORA (6/120)."""
    aut = cenario.ligar()
    cenario.flip()
    with pytest.raises(supervisor.ErroSeguranca, match="NÃO é mais o objeto validado"):
        git.confinamento_de_leitura(str(cenario.hostil), autoridade=aut)


def test_r4_03_o_caminho_de_FORA_nao_chega_ao_perfil(cenario):
    """O critério é o EFEITO: nenhum caminho de fora das raízes no SBPL.

    Sem este teste, `test_r4_01` passaria numa implementação que recusa por
    outro motivo qualquer e continuaria emitindo o perfil errado no caminho em
    que a recusa não dispara.
    """
    aut = cenario.ligar()
    cenario.flip()
    try:
        conf = git.confinamento_de_repo(str(cenario.hostil), autoridade=aut)
    except supervisor.ErroSeguranca:
        return
    pytest.fail(f"não recusou, e a escrita concedida foi {conf.escrita} — "
                f"`{cenario.fora}` está fora das raízes aprovadas")


def test_r4_04_CONTROLE_sem_a_troca_o_confinamento_continua_saindo(cenario):
    """Sem este controle os três acima passariam num sistema que recusa tudo.

    O MESMO repositório, a MESMA autoridade, sem o flip: tem de funcionar, e a
    escrita tem de ser o git dir dele — não a working tree, não o repo de fora.
    """
    aut = cenario.ligar()
    conf = git.confinamento_de_repo(str(cenario.hostil), autoridade=aut)
    assert conf.escrita == (str(cenario.hostil / ".git"),), conf.escrita
    leitura = git.confinamento_de_leitura(str(cenario.hostil), autoridade=aut)
    assert leitura.escrita == ()
    assert str(cenario.fora) not in " ".join(leitura.leitura)


def test_r4_05_a_identidade_e_do_INODE_nao_do_CAMINHO(cenario):
    """Estrutural: mover o git dir e apontar de volta NÃO é troca.

    Se a checagem fosse por texto do caminho ou por conteúdo relido, este caso
    legítimo viraria recusa. O que se liga é o objeto — e ele é o mesmo.
    """
    aut = cenario.ligar()
    gd = cenario.hostil / ".git"
    movido = cenario.hostil / ".git-movido"
    gd.rename(movido)
    gd.symlink_to(movido, target_is_directory=True)
    git.confinamento_de_repo(str(cenario.hostil), autoridade=aut)


def test_r4_06_DESFAZER_nao_grava_no_repositorio_de_terceiro(cenario, monkeypatch):
    """`N-A7-02`: o supervisor sobrescrevia índice e reflog alheios, 20/20.

    O desfazer roda no processo PAI, fora do sandbox, e gravava por CAMINHO
    derivado de `autoridade.git_dir` — caminho que o repositório re-apontou
    depois do instantâneo. O NOMOS relatava RECUSA e o dano já estava feito.
    """
    from nomos.adapters import git_tree
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.wiring import registrar_git_tree
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades
    from nomos.adapters import filtro_governado as fg

    (cenario.hostil / "s.txt").write_text("do hostil\n")
    antes = _git("--git-dir", str(cenario.alvo / ".git"), "ls-files").stdout
    reflog = (cenario.alvo / ".git" / "logs" / "HEAD")
    reflog_antes = reflog.read_bytes() if reflog.exists() else b""

    # O flip acontece DEPOIS do instantâneo e ANTES do desfazer — a janela exata.
    real = git_tree._instantaneo_das_refs

    def espiao(*a, **k):
        est = real(*a, **k)
        cenario.flip()
        return est
    monkeypatch.setattr(git_tree, "_instantaneo_das_refs", espiao)
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            RuntimeError("recusa pos-exec")))

    rc = RegistroCapacidades(policy=PolicyEngine(cenario.raiz.parent / "p.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(cenario.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-add", "runtime-governado",
                                        raizes=(str(cenario.raiz),))
    # O TIPO não é o critério aqui: a operação pode morrer pelo `_auditar`
    # injetado ou pela troca de identidade, e as duas são recusas legítimas.
    # O critério é o EFEITO no repositório de terceiro, medido logo abaixo.
    erro = ""
    try:
        git_tree.GitTreeAdapter(registro=fg.RegistroDeFiltros()).executar(
            CapabilityRequest(capacidade="git-add", alvo=str(cenario.hostil),
                              argumentos={"caminhos": ["s.txt"]}), ctx)
    except Exception as e:                                   # noqa: BLE001
        erro = str(e)
    assert erro, "a operação não foi recusada; o desfazer nunca rodou"

    depois = _git("--git-dir", str(cenario.alvo / ".git"), "ls-files").stdout
    assert depois == antes, (
        f"o DESFAZER reescreveu o índice do repositório de TERCEIRO: "
        f"{antes!r} -> {depois!r}")
    agora = reflog.read_bytes() if reflog.exists() else b""
    assert agora == reflog_antes, "o DESFAZER reescreveu o reflog de TERCEIRO"


def test_r4_07_autoridade_SEM_identidade_nao_quebra_o_caminho_legitimo():
    """Compatibilidade: quem constrói a autoridade à mão não passa a falhar.

    `conferir_identidade` degrada para no-op quando não há identidade ligada —
    e isso é DELIBERADO e limitado: `autoridade_de` (a única fábrica usada no
    caminho governado) sempre liga. Sem esta porta, todo teste e chamador que
    monta `AutoridadeDeRepo` diretamente viraria recusa, e a mudança seria uma
    quebra de contrato disfarçada de conserto.
    """
    a = git.AutoridadeDeRepo(repo="/x", git_dir="/x/.git", common="/x/.git")
    a.conferir_identidade("teste")
