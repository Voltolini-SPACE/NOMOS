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

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import git, supervisor
from nomos.adapters import git_tree as git_tree_mod

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


# ═══ `.2` da 4ª medição — o cancelamento de filtro, por TOKEN e com TETO ═════

_FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"


@pytest.fixture
def governado(tmp_path):
    """Redator APROVADO. Sem filtro real não há `hunter2` vs `REDIGIDO`."""
    if not os.path.exists(supervisor.SANDBOX):
        pytest.skip("sem sandbox-exec não há execução supervisionada")
    from nomos.adapters import filtro_governado as fg
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    repo = _init(raiz / "repo")
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(_FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)
    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(binario),
        managed_artifact=art, read_roots=(str(repo),), write_roots=(str(repo),)))
    # A regra que LIGA `*.txt` ao filtro na working tree. Sem ela, check-attr
    # responde `unspecified` e nada redige — os testes de controle mediriam a
    # ausência da regra, não a defesa.
    (repo / ".gitattributes").write_text("*.txt filter=redator\n")

    class Cen:
        def __init__(self):
            self.raiz, self.repo, self.reg, self.tmp = raiz, repo, reg, tmp_path

        def add(self, *caminhos):
            from nomos.adapters import git_tree
            from nomos.adapters.contrato import (CapabilityContext,
                                                 CapabilityRequest)
            from nomos.adapters.wiring import registrar_git_tree
            from nomos.kernel.policy import PolicyEngine
            from nomos.orquestracao.registro import RegistroCapacidades
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "p.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            ctx = CapabilityContext.de_registro(rc, "git-add",
                                                "runtime-governado",
                                                raizes=(str(raiz),))
            return git_tree.GitTreeAdapter(registro=reg).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}), ctx)

        def cru_no_store(self) -> bool:
            saida = subprocess.run(
                [GIT, "-C", str(self.repo), "cat-file",
                 "--batch-all-objects", "--batch"], capture_output=True).stdout
            return b"hunter2" in saida

    return Cen()


@pytest.mark.parametrize("separador,token", [
    ("\t", "!filter"), ("\t", "-filter"),
    (" ", "!filter"), (" ", "-filter"),
    ("  \t ", "!filter"),
])
def test_r4_10_cancelamento_por_QUALQUER_espaco_e_recusa(governado, separador,
                                                          token):
    """`.2.N1-TAB-BANG-FILTER` (P0): o Git separa por QUALQUER `isspace()`.

    O conserto da rodada anterior buscava a substring `" !filter"` — espaço mais
    token. MEDIDO 8/8: `SEGREDO.txt\\t!filter` cancela a redação exatamente
    igual e a substring não vê. A varredura passa a ser por TOKEN, que é a
    mesma regra do Git.
    """
    cen = governado
    (cen.repo / ".gitattributes").write_text(
        f"*.txt filter=redator\nsegredo.txt{separador}{token}\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    with pytest.raises(supervisor.ErroSeguranca):
        cen.add("segredo.txt")
    assert not cen.cru_no_store(), (
        f"`{token}` separado por {separador!r} desligou a redação e o conteúdo "
        "cru chegou ao store")


@pytest.mark.parametrize("atributo", ["-filterset", "-filtered", "-filtro"])
def test_r4_11_atributo_PARECIDO_nao_e_cancelamento(governado, atributo):
    """`.2.N6` (P2, direção oposta): a substring não tinha fim de token.

    `-filterset` desliga um atributo CHAMADO `filterset`, sem nenhuma relação
    com `filter`, e a operação inteira era recusada. Recusa falsa treina quem
    lê a suíte a contornar a guarda.
    """
    cen = governado
    (cen.repo / ".gitattributes").write_text(
        f"*.txt filter=redator\nsegredo.txt {atributo}\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    r = cen.add("segredo.txt")
    assert r.efeito_aplicado, f"recusa FALSA por causa de {atributo!r}"
    assert not cen.cru_no_store(), "o filtro deixou de rodar"


def test_r4_12_fonte_de_atributo_acima_do_teto_do_GIT_e_recusa(governado):
    """`.2.N9` (P0): acima de 100 MiB o Git IGNORA a fonte, com rc=0.

    MEDIDO no 2.50.1: `warning: ignoring overly large gitattributes file` —
    mensagem que o guard de `.2.15` não casa (exige "unable to access") e que
    `conferir_saida` não vê (casa `^(error|fatal):`). Discriminante medido:
    99 MiB REDIGE, 101 MiB entra EM CLARO. O repositório escolhia o TAMANHO, e
    com ele escolhia se a redação acontecia.

    O teste usa `truncate` (arquivo esparso) para não gastar 100 MiB de disco
    real: o que a guarda lê é `st_size`, que é o mesmo que o Git lê.
    """
    from nomos.adapters import git_tree
    cen = governado
    attrs = cen.repo / ".gitattributes"
    attrs.write_text("*.txt filter=redator\n")
    with open(attrs, "r+b") as fh:
        fh.truncate(git_tree.ATTR_MAX_GIT + 1)
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    with pytest.raises(supervisor.ErroSeguranca, match="teto do próprio Git"):
        cen.add("segredo.txt")
    assert not cen.cru_no_store()


def test_r4_13_CONTROLE_fonte_grande_mas_ABAIXO_do_teto_continua_valendo(
        governado):
    """Sem este controle, o de cima passaria num sistema que recusa por tamanho.

    Logo abaixo do teto o Git HONRA a fonte, então o NOMOS também tem de honrar
    — e a redação tem de acontecer.
    """
    from nomos.adapters import git_tree
    cen = governado
    attrs = cen.repo / ".gitattributes"
    attrs.write_text("*.txt filter=redator\n")
    with open(attrs, "r+b") as fh:
        fh.truncate(git_tree.ATTR_MAX_GIT - 1)
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    r = cen.add("segredo.txt")
    assert r.efeito_aplicado
    assert not cen.cru_no_store()


def test_r4_14_CONTROLE_sem_cancelamento_o_filtro_roda(governado):
    """O controle positivo de todos os acima: o caminho legítimo funciona."""
    cen = governado
    (cen.repo / ".gitattributes").write_text("*.txt filter=redator\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")
    r = cen.add("segredo.txt")
    assert r.efeito_aplicado
    sha = subprocess.run([GIT, "-C", str(cen.repo), "ls-files", "-s", "--",
                          "segredo.txt"], capture_output=True,
                        text=True).stdout.split()[1]
    corpo = subprocess.run([GIT, "-C", str(cen.repo), "cat-file", "-p", sha],
                           capture_output=True).stdout
    assert corpo == b"SENHA=REDIGIDO\n"


# ═══ `.2.N3` (P0) — cancelamento numa ÁRVORE via attr.tree, cego ao disco ════

def _mktree_cancelamento(repo: Path) -> str:
    """Uma árvore Git com `.gitattributes` que cancela o filtro.

    Escrita pelo próprio Git (`hash-object` + `mktree`), não à mão: o que se
    mede é a árvore que o Git de fato lê, não uma aproximação.
    """
    env = dict(os.environ, GIT_DIR=str(repo / ".git"))
    blob = subprocess.run([GIT, "hash-object", "-w", "--stdin"],
                          input=b"segredo.txt !filter\n",
                          capture_output=True, env=env).stdout.decode().strip()
    return subprocess.run(
        [GIT, "mktree"],
        input=f"100644 blob {blob}\t.gitattributes\n".encode(),
        capture_output=True, env=env).stdout.decode().strip()


@pytest.mark.parametrize("via", ["config", "include"])
def test_r4_20_cancelamento_em_ARVORE_via_attr_tree_e_recusa(governado, via):
    """MEDIDO: `!filter` numa árvore -> check-attr `unspecified` -> segredo cru.

    `attr.tree` lê os atributos de uma ÁRVORE Git em vez da working tree. Um
    `!filter` plantado ali cancela a redação, e o `check-attr` responde
    `unspecified` — indistinguível de 'não há regra'. A varredura de disco de
    `_recusar_cancelamento_de_filtro` não alcança a árvore, e a resposta do Git
    não deixa auditar. Ponta a ponta antes do conserto: ok=True, segredo EM
    CLARO no store.

    As duas formas de declarar: direto no config, e por `include.path` — porque
    `git config --get-all` resolve includes, então esconder a chave num arquivo
    incluído não contorna a detecção (medido: o Git honra e o get-all vê).
    """
    cen = governado
    tree = _mktree_cancelamento(cen.repo)
    if via == "config":
        subprocess.run([GIT, "-C", str(cen.repo), "config", "attr.tree", tree],
                       capture_output=True)
    else:
        inc = cen.repo / ".git" / "incluido.cfg"
        inc.write_text(f"[attr]\n\ttree = {tree}\n")
        subprocess.run([GIT, "-C", str(cen.repo), "config", "include.path",
                        str(inc)], capture_output=True)
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    with pytest.raises(supervisor.ErroSeguranca, match="attr.tree"):
        cen.add("segredo.txt")
    assert not cen.cru_no_store(), "o `!filter` da árvore vazou o segredo cru"


def test_r4_21_CONTROLE_sem_attr_tree_a_redacao_acontece(governado):
    """O controle positivo: sem `attr.tree`, o caminho legítimo redige.

    Sem ele, `test_r4_20` passaria numa implementação que recusa todo `git-add`.
    """
    cen = governado
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")
    r = cen.add("segredo.txt")
    assert r.efeito_aplicado
    sha = subprocess.run([GIT, "-C", str(cen.repo), "ls-files", "-s", "--",
                          "segredo.txt"], capture_output=True,
                        text=True).stdout.split()[1]
    corpo = subprocess.run([GIT, "-C", str(cen.repo), "cat-file", "-p", sha],
                           capture_output=True).stdout
    assert corpo == b"SENHA=REDIGIDO\n"


def test_r4_22_attr_source_NAO_e_config_e_nao_gera_recusa_falsa(governado):
    """Estrutural + medição: `attr.source` não é chave de config do Git.

    MEDIDO: `config attr.source=<árvore>` não teve efeito nenhum no
    `check-attr` (o filtro seguiu aplicando). Recusar `attr.source` seria uma
    recusa falsa de uma chave inócua — o vetor é `attr.tree`, e só ele.
    """
    cen = governado
    tree = _mktree_cancelamento(cen.repo)
    subprocess.run([GIT, "-C", str(cen.repo), "config", "attr.source", tree],
                   capture_output=True)
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")
    r = cen.add("segredo.txt")
    assert r.efeito_aplicado, "recusa FALSA por causa de attr.source inócuo"
    assert not cen.cru_no_store()


# ═══ `.6.08` / `.6.NOVO-08` (P1) — refs/heads symlink de dir na PROFUNDIDADE 2 ═

@pytest.fixture
def repo_commitavel(tmp_path):
    """Repo com um commit e um arquivo pendente, para git-add/commit governado."""
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    repo = _init(raiz / "repo")
    (repo / "a.txt").write_text("a\n")
    _git("-C", str(repo), "add", "a.txt")
    _git("-C", str(repo), "commit", "-qm", "x")

    class Cen:
        def __init__(self):
            self.raiz, self.repo, self.tmp = raiz, repo, tmp_path

        def add(self, *caminhos):
            from nomos.adapters import git_tree, filtro_governado as fg
            from nomos.adapters.contrato import (CapabilityContext,
                                                 CapabilityRequest)
            from nomos.adapters.wiring import registrar_git_tree
            from nomos.kernel.policy import PolicyEngine
            from nomos.orquestracao.registro import RegistroCapacidades
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "p.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            ctx = CapabilityContext.de_registro(rc, "git-add",
                                                "runtime-governado",
                                                raizes=(str(raiz),))
            return git_tree.GitTreeAdapter(registro=fg.RegistroDeFiltros()
                                           ).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}), ctx)

    return Cen()


def _refs_heads_para_symlink(gd: Path) -> None:
    """`<gd>/refs/heads` vira symlink para um dir REAL dentro do git dir.

    O alvo mora DENTRO da raiz de escrita já concedida, então não é fuga de
    raiz: é a estrutura de refs saindo do alcance do guard de profundidade 1.
    """
    reais = gd / "heads_reais"
    reais.mkdir()
    for f in (gd / "refs" / "heads").iterdir():
        shutil.move(str(f), str(reais / f.name))
    shutil.rmtree(gd / "refs" / "heads")
    (gd / "refs" / "heads").symlink_to(reais, target_is_directory=True)


def test_r4_30_refs_heads_symlink_profundidade_2_e_recusado(repo_commitavel):
    """MEDIDO 8/8: `rglob` não recursa em symlink de dir; refs/heads escapava.

    O guard de `.8.NEW-REFSDIR-SYMLINK` via só profundidade 1 (`refs`, `logs`).
    Com `refs/heads` (profundidade 2) como symlink, as refs sob ele saíam do
    instantâneo e da transação, e um commit governado mutava tag / instalava
    refs/replace com ok=True.
    """
    cen = repo_commitavel
    _refs_heads_para_symlink(cen.repo / ".git")
    (cen.repo / "b.txt").write_text("b\n")
    with pytest.raises(supervisor.ErroSeguranca, match="refs/ ou logs/"):
        cen.add("b.txt")


def test_r4_31_ref_de_terceiro_nao_avanca_em_operacao_recusada(repo_commitavel):
    """`.6.NOVO-08-REFS-FORA-DA-TRANSACAO`: o critério é o EFEITO no branch.

    Como o instantâneo RECUSA antes do exec, o commit nunca roda e o branch não
    pode avançar. Sem o conserto, a operação saía ok=True e `refs/heads/main`
    apontava para objeto que a quarentena destruía.
    """
    cen = repo_commitavel
    head0 = _git("-C", str(cen.repo), "rev-parse", "HEAD").stdout.strip()
    _refs_heads_para_symlink(cen.repo / ".git")
    (cen.repo / "b.txt").write_text("b\n")
    with pytest.raises(supervisor.ErroSeguranca):
        cen.add("b.txt")
    # O branch real (agora em heads_reais/main) não pode ter avançado.
    ref = cen.repo / ".git" / "heads_reais" / "main"
    assert ref.read_text().strip() == head0, "o branch avançou numa recusa"


@pytest.mark.parametrize("onde", ["refs/tags", "refs/heads/sub", "logs/refs"])
def test_r4_32_symlink_em_QUALQUER_profundidade_de_refs_e_recusado(
        repo_commitavel, onde):
    """A descida é por componente: symlink em tags, num subdir de heads, em logs.

    Um único ponto de symlink em qualquer nível da árvore de refs derruba a
    transação; o teste varre três profundidades e dois troncos (refs e logs).
    """
    cen = repo_commitavel
    gd = cen.repo / ".git"
    alvo = gd / onde
    fora = gd / "escondido"
    fora.mkdir()
    (fora / "x").write_text("dead\n")
    alvo.parent.mkdir(parents=True, exist_ok=True)
    if alvo.exists():
        shutil.rmtree(alvo)
    alvo.symlink_to(fora, target_is_directory=True)
    (cen.repo / "b.txt").write_text("b\n")
    with pytest.raises(supervisor.ErroSeguranca, match="refs/ ou logs/"):
        cen.add("b.txt")


def test_r4_33_CONTROLE_refs_PROFUNDAS_e_legitimas_continuam_valendo(
        repo_commitavel):
    """`refs/heads/feature/x` — dirs reais em 3 níveis — tem de funcionar.

    Sem este controle, os testes acima passariam numa implementação que recusa
    toda estrutura de refs com profundidade. A descida por componente aceita
    diretórios reais em qualquer nível; só o symlink é recusado.
    """
    cen = repo_commitavel
    _git("-C", str(cen.repo), "branch", "feature/x")
    _git("-C", str(cen.repo), "tag", "v1.0")
    assert (cen.repo / ".git" / "refs" / "heads" / "feature" / "x").is_file()
    (cen.repo / "b.txt").write_text("b\n")
    r = cen.add("b.txt")
    assert r.efeito_aplicado


# ═══ `.1.N1` (P1) — `.git` AUTO-REFERENTE: o git dir É a working tree ═══════

def _repo_auto_referente(raiz: Path, ponteiro: str) -> Path:
    """Monta o layout auto-certificante: git dir == working tree.

    A "prova" de titularidade (`[core] worktree`) mora em `<repo>/config`, que
    é um arquivo da própria working tree — escrito por quem a prova deveria
    autenticar.
    """
    repo = raiz / "hostil"
    repo.mkdir()
    (repo / "objects").mkdir()
    (repo / "refs" / "heads").mkdir(parents=True)
    (repo / "HEAD").write_text("ref: refs/heads/main\n")
    (repo / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
        f"\tworktree = {repo}\n")
    (repo / ".git").write_text(f"gitdir: {ponteiro}\n")
    (repo / "ARQUIVO_DO_PROJETO.txt").write_text("intacto\n")
    return repo


@pytest.mark.parametrize("ponteiro", [".", "./", "sub/..", "ABSOLUTO"])
def test_r4_40_gitdir_auto_referente_e_recusado(tmp_path, ponteiro):
    """MEDIDO: a raiz de ESCRITA deixava de ser o git dir e virava o repo INTEIRO.

    Contraste no mesmo processo — repo normal: `escrita = ('<repo>/.git',)`;
    repo hostil: `escrita = ('<repo>',)`. Isso revoga a invariante que
    `confinamento_de_repo` declara e justifica com medição ("a escrita para no
    DIRETÓRIO GIT"), cujo motivo é que com o repo inteiro liberado um
    `filter.clean` hostil SOBRESCREVEU arquivo do projeto durante o `git add`.

    Quatro grafias do MESMO objeto: comparar texto de caminho deixaria três
    passando. A comparação é por inode.
    """
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    repo = _repo_auto_referente(raiz, "PLACEHOLDER")
    alvo = str(repo) if ponteiro == "ABSOLUTO" else ponteiro
    if ponteiro == "sub/..":
        (repo / "sub").mkdir(exist_ok=True)
    (repo / ".git").write_text(f"gitdir: {alvo}\n")

    with pytest.raises(supervisor.ErroSeguranca, match="própria working tree"):
        git.conferir_git_dir(str(repo), (str(raiz),))


def test_r4_41_a_working_tree_nao_vira_raiz_de_escrita(tmp_path):
    """O critério é o EFEITO: nenhum confinamento com o repo inteiro gravável.

    Sem este teste, `test_r4_40` passaria numa implementação que recusa por
    outro motivo e ainda emitisse o confinamento errado onde a recusa não
    dispara.
    """
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    repo = _repo_auto_referente(raiz, ".")
    try:
        gd, cm = git.conferir_git_dir(str(repo), (str(raiz),))
        aut = git.autoridade_de(str(repo), gd, cm)
        conf = git.confinamento_de_repo(str(repo), autoridade=aut)
    except supervisor.ErroSeguranca:
        return
    canon = supervisor.canonicalizar(str(repo))
    pytest.fail(f"não recusou, e a escrita concedida foi {conf.escrita} — "
                f"a working tree {canon!r} inteira ficou gravável")


@pytest.mark.parametrize("layout", ["repo-comum", "worktree-ligada", "submodulo"])
def test_r4_42_CONTROLE_layouts_que_o_GIT_produz_seguem_aceitos(tmp_path,
                                                                 layout):
    """Nenhum layout real do Git tem git dir == working tree.

    Repo comum tem `.git/` DENTRO da working tree (inodes distintos); worktree
    ligada e submódulo apontam para fora dela; bare não tem working tree. Sem
    este controle, a invariante nova seria indistinguível de "recuse tudo".
    """
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    p = _init(raiz / "principal")
    (p / "a").write_text("a\n")
    _git("-C", str(p), "add", "a")
    _git("-C", str(p), "commit", "-qm", "x")

    if layout == "repo-comum":
        alvo = p
    elif layout == "worktree-ligada":
        alvo = raiz / "ligada"
        r = _git("-C", str(p), "worktree", "add", "-q", str(alvo))
        assert r.returncode == 0, r.stderr
    else:
        sup = _init(raiz / "super")
        r = _git("-C", str(sup), "-c", "protocol.file.allow=always",
                 "submodule", "add", "-q", str(p), "vendor")
        if r.returncode != 0:
            pytest.skip(f"submódulo por file:// bloqueado: {r.stderr[:100]}")
        alvo = sup / "vendor"

    gd, cm = git.conferir_git_dir(str(alvo), (str(raiz),))
    aut = git.autoridade_de(str(alvo), gd, cm)
    conf = git.confinamento_de_repo(str(alvo), autoridade=aut)
    canon = supervisor.canonicalizar(str(alvo))
    assert canon not in conf.escrita, (
        f"a working tree {canon!r} virou raiz de escrita em layout legítimo")


# ═══ `.11.13` (P1) — o teto era de PROFUNDIDADE, e ela é escolha do atacante ══

@pytest.mark.parametrize("prof", [3, 5, 6, 8])
def test_r4_50_git_dir_aninhado_e_achado_em_QUALQUER_profundidade(tmp_path,
                                                                   prof):
    """MEDIDO 8/8 a prof 6 e 8/8 a prof 8: escapava e o filtro gravava dentro.

    `--separate-git-dir` dá ao git dir um nome que a negação por NOME (`\\.git`)
    não alcança, então a varredura é o único jeito. Com teto de profundidade 4,
    bastava criar o repositório um nível mais fundo. Quem escolhe o nível é
    quem cria o repositório — não o "layout real" que o comentário citava.
    """
    from nomos.adapters import filtro_governado as fg
    raiz = tmp_path / "raizes"
    d = raiz
    for i in range(prof):
        d = d / f"n{i}"
    d.mkdir(parents=True)
    trab, gd = d / "proj", d / "deposito"
    trab.mkdir()
    r = subprocess.run([GIT, "init", "-q", "--separate-git-dir", str(gd),
                        str(trab)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    achados = fg._git_dirs_aninhados(str(raiz))
    canon = str(gd.resolve())
    assert any(str(Path(a).resolve()) == canon for a in achados), (
        f"git dir a profundidade {prof} escapou da varredura: {achados}")


def test_r4_51_estourar_o_ORCAMENTO_e_recusa_e_nao_silencio(tmp_path):
    """Teto que apenas SILENCIA é porta — a mesma forma de `.5.08`.

    Não terminar a varredura não prova ausência de git dir aninhado, e não
    provar é o mesmo que não conter. O orçamento real (20 mil diretórios) é
    forçado para 5 aqui: medir a PROPRIEDADE (fail-closed ao estourar) não
    exige construir vinte mil diretórios.
    """
    from nomos.adapters import filtro_governado as fg
    raiz = tmp_path / "raizes"
    for i in range(30):
        (raiz / f"d{i}").mkdir(parents=True)
    with pytest.raises(fg.ErroFiltro, match="não terminou"):
        fg._git_dirs_aninhados(str(raiz), teto=5)


def test_r4_52_CONTROLE_arvore_normal_nao_estoura_nem_custa(tmp_path):
    """Sem este controle, o de cima passaria numa implementação que recusa tudo.

    400 diretórios rasos — mais que qualquer workspace real por nível — passam
    sem recusa. O teto é para árvore patológica, não para trabalho.
    """
    from nomos.adapters import filtro_governado as fg
    raiz = tmp_path / "raizes"
    for i in range(400):
        (raiz / f"d{i}").mkdir(parents=True)
    assert fg._git_dirs_aninhados(str(raiz)) == []


# ═══ `.11.09` (P1) — o ramo TODOS-GOVERNADOS acusava o NOSSO estagiamento ════

def test_r4_60_ramo_todos_governados_nao_acusa_o_proprio_estagiamento(
        governado):
    """MEDIDO 8/8 com gatilho REAL do repositório (ablação: 8/8 antes, 0/8 depois).

    Quando TODOS os caminhos são governados não sobra `git add` para rodar, e o
    ramo retornava ANTES de `janela` ser populada. `_estagiar` já reescreveu o
    índice; com `idx_antes`/`idx_depois` em None, o desfazer caía no fallback
    `esperado = dados` (instantâneo PRÉ-OPERAÇÃO) e acusava como TERCEIRO
    exatamente o efeito que NÓS aplicamos — incidente forense falso, sem
    concorrência nenhuma.

    O gatilho é do próprio repositório, sem injeção: ele planta
    `.git/objects/<2hex>` como ARQUIVO REGULAR no prefixo do sha determinístico
    do blob REDIGIDO, e a promoção falha porque o Git quer um diretório ali.

    As fotos passaram a enquadrar TODOS os nossos efeitos, não só o exec.
    """
    import hashlib
    cen = governado
    (cen.repo / "base.txt").write_text("legitimo\n")
    _git("-C", str(cen.repo), "add", "base.txt")
    (cen.repo / ".gitattributes").write_text("segredo.txt filter=redator\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    red = b"SENHA=REDIGIDO\n"
    sha = hashlib.sha1(b"blob %d\0" % len(red) + red).hexdigest()  # noqa: S324
    pref = cen.repo / ".git" / "objects" / sha[:2]
    if pref.exists():
        shutil.rmtree(pref)
    pref.write_text("bloqueio")     # o Git quer um DIRETÓRIO aqui

    erro = ""
    try:
        cen.add("segredo.txt")
    except Exception as e:                                   # noqa: BLE001
        erro = str(e)
    assert erro, "o cenário não chegou a exercitar o desfazer"
    assert "trabalho de terceiro foi perdido" not in erro, (
        f"INCIDENTE FORENSE FALSO no ramo todos-governados: o índice foi "
        f"reescrito pelo NOSSO `_estagiar`, não por terceiro. {erro[:200]}")


def test_r4_61_CONTROLE_o_canal_de_terceiro_continua_vivo(governado,
                                                           monkeypatch):
    """Fechar o falso positivo não pode calar o sinal REAL.

    O par de `test_r4_60`: um `git add` de terceiro de verdade, na janela, ainda
    tem de produzir incidente. Sem este controle, o conserto seria
    indistinguível de "nunca mais acuse ninguém".
    """
    from nomos.adapters import git_tree
    cen = governado
    (cen.repo / "base.txt").write_text("legitimo\n")
    _git("-C", str(cen.repo), "add", "base.txt")
    (cen.repo / "zz.txt").write_text("x\n")
    (cen.repo / "concorrente.txt").write_text("de outro\n")

    real = git_tree._instantaneo_das_refs

    def espiao(*a, **k):
        est = real(*a, **k)
        _git("-C", str(cen.repo), "add", "concorrente.txt")
        return est
    monkeypatch.setattr(git_tree, "_instantaneo_das_refs", espiao)
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            RuntimeError("recusa pos-exec")))

    with pytest.raises(RuntimeError) as ei:
        cen.add("zz.txt")
    assert "trabalho de terceiro foi perdido" in str(ei.value), (
        "o `git add` de terceiro foi sobreposto pelo desfazer SEM incidente")


@pytest.fixture
def campo_add(tmp_path):
    """Repo com trabalho estagiado, um alvo e um arquivo de terceiro pronto."""
    from nomos.adapters import git_tree as _gt
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    repo = _init(raiz / "repo")
    (repo / "a.txt").write_text("a\n")
    _git("-C", str(repo), "add", "a.txt")
    (repo / "zz.txt").write_text("x\n")
    (repo / "concorrente.txt").write_text("trabalho de outro\n")

    class Cen:
        def __init__(self):
            self.raiz, self.repo, self.tmp = raiz, repo, tmp_path

        def add(self, *caminhos):
            from nomos.adapters import filtro_governado as fg
            from nomos.adapters.contrato import (CapabilityContext,
                                                 CapabilityRequest)
            from nomos.adapters.wiring import registrar_git_tree
            from nomos.kernel.policy import PolicyEngine
            from nomos.orquestracao.registro import RegistroCapacidades
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pa.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            ctx = CapabilityContext.de_registro(rc, "git-add",
                                                "runtime-governado",
                                                raizes=(str(raiz),))
            return _gt.GitTreeAdapter(registro=fg.RegistroDeFiltros()).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}), ctx)

    return Cen()

# ═══ `.8.05-08` / `.8.NEW-REFS-TERCEIRO` (P1) — a JANELA B, em path-space ════

def test_r4_70_terceiro_DURANTE_o_exec_emite_incidente(campo_add, monkeypatch):
    """MEDIDO 10/10 determinístico: sobreposto em SILÊNCIO antes do conserto.

    O canal de incidente compara BYTES do índice, e por isso enxerga as janelas
    A (instantâneo→foto de antes) e C (foto de depois→desfazer), mas não a B: a
    escrita de terceiro que acontece DURANTE o nosso exec cai ENTRE as duas
    fotos, junto com o nosso próprio efeito, e as duas comparações dão "igual".

    Em byte-space não há como separar os dois. Em path-space há, e o dado já
    existia: `_conferir_escopo_estagiado` calcula os caminhos que apareceram no
    índice e não são nossos. Reaproveitá-lo não custa subprocesso novo — o que
    importa, porque cada subprocesso a mais é superfície para morte por sinal.

    O trabalho de terceiro AINDA é sobreposto (a operação foi recusada e o
    índice tem de voltar); o que muda é que deixa de ser silencioso.
    """
    cen = campo_add
    real_exec = git_tree_mod.supervisor.executar
    feito = {}

    def espiao(argv, **kw):
        p = real_exec(argv, **kw)
        if any(a == "add" for a in argv) and "rodou" not in feito:
            feito["rodou"] = True
            feito["rc"] = _git("-C", str(cen.repo), "add",
                               "concorrente.txt").returncode
        return p
    monkeypatch.setattr(git_tree_mod.supervisor, "executar", espiao)
    monkeypatch.setattr(git_tree_mod.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            RuntimeError("recusa pos-exec")))

    with pytest.raises(RuntimeError) as ei:
        cen.add("zz.txt")

    assert feito.get("rc") == 0, "o terceiro não chegou a ser aceito"
    msg = str(ei.value)
    assert "trabalho de terceiro foi perdido" in msg, (
        f"janela B: o `git add` de terceiro (rc=0) foi sobreposto pelo desfazer "
        f"SEM incidente — perda silenciosa de trabalho aceito. {msg[:200]}")
    assert "concorrente.txt" in msg, (
        f"o incidente não nomeia o caminho perdido: {msg[:200]}")


def test_r4_71_CONTROLE_sem_terceiro_nenhum_incidente_e_emitido(campo_add,
                                                                 monkeypatch):
    """O par: path-space não pode acusar quando não há terceiro nenhum.

    Sem este controle, `test_r4_70` passaria numa implementação que acusa
    sempre — que é o defeito `.11.09` recém-fechado, de volta por outra porta.
    """
    cen = campo_add
    monkeypatch.setattr(git_tree_mod.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            RuntimeError("recusa pos-exec")))
    with pytest.raises(RuntimeError) as ei:
        cen.add("zz.txt")
    assert "trabalho de terceiro foi perdido" not in str(ei.value), (
        "acusou terceiro sem terceiro — falso positivo destrói o sinal")


# ═══ `.2.N7` (P2) — recusa FALSA do uso mais legítimo de `-filter` ══════════

@pytest.mark.parametrize("regra", [
    "*.png -filter",          # binário não passa por redator: o uso canônico
    "*.bin binary",           # macro que expande para -diff -merge -text
    "outro.txt -filter",      # cancelamento em caminho que NÃO foi pedido
])
def test_r4_80_cancelamento_que_NAO_alcanca_o_caminho_pedido_nao_recusa(
        governado, regra):
    """A guarda recusava por EXISTÊNCIA de cancelamento em qualquer fonte.

    `*.png -filter` é o uso mais comum e mais legítimo de `-filter`: binário
    não deve passar pelo redator. Recusar a operação inteira por causa dele —
    com o pedido em `segredo.txt`, que casa `*.txt filter=redator` — é recusa
    falsa, e recusa falsa treina quem lê a suíte a contornar a guarda.

    O discriminador NÃO reimplementa casamento de padrão (essa é a classe de
    divergência que `check-attr` existe para eliminar). Ele cruza dois sinais
    que já existem: a varredura diz que HÁ cancelamento declarado, e o
    `check-attr` diz o valor efetivo DAQUELE caminho. Se o caminho pedido vem
    com filtro de verdade, o cancelamento não o alcança.
    """
    cen = governado
    (cen.repo / ".gitattributes").write_text(
        f"*.txt filter=redator\n{regra}\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    r = cen.add("segredo.txt")
    assert r.efeito_aplicado, f"recusa FALSA por causa de {regra!r}"
    sha = subprocess.run([GIT, "-C", str(cen.repo), "ls-files", "-s", "--",
                          "segredo.txt"], capture_output=True,
                        text=True).stdout.split()[1]
    corpo = subprocess.run([GIT, "-C", str(cen.repo), "cat-file", "-p", sha],
                           capture_output=True).stdout
    assert corpo == b"SENHA=REDIGIDO\n", "o filtro deixou de rodar"


@pytest.mark.parametrize("cancelamento", ["!filter", "-filter"])
def test_r4_81_CONTROLE_cancelamento_QUE_ALCANCA_continua_recusado(governado,
                                                                    cancelamento):
    """O par obrigatório: afrouxar `.2.N7` não pode reabrir `.2.N1`.

    Mesmo arquivo, mesma guarda — só muda se a regra casa o caminho pedido.
    Quando casa, `check-attr` responde `unspecified`/`unset` e a recusa vale.
    """
    cen = governado
    (cen.repo / ".gitattributes").write_text(
        f"*.txt filter=redator\nsegredo.txt {cancelamento}\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    with pytest.raises(supervisor.ErroSeguranca):
        cen.add("segredo.txt")
    assert not cen.cru_no_store(), "o cancelamento vazou o segredo cru"


def test_r4_82_a_deteccao_de_config_le_a_DECLARACAO_nao_o_valor_efetivo():
    """Regressão de um defeito que EU introduzi ao colapsar duas chamadas.

    `_config_do_repo` trocou dois `git config --get-all <chave>` por um único
    `git config --list`, para reduzir a superfície de morte por SIGKILL no
    caminho governado. Só que `_base` injeta `-c core.attributesFile=` (a
    neutralização de `_NEUTRALIZAR_TREE`), e `--list` emite AS DUAS ocorrências
    — a do repositório e a vazia. Guardando a última (regra do Git: a última
    vence), o valor efetivo virou `""` e a detecção MORREU: `test_c2_11` deixou
    de recusar `core.attributesFile`, e a fonte externa voltaria a ser ignorada
    em silêncio.

    O que a política decide não é o valor EFETIVO — é a DECLARAÇÃO do
    repositório. Este teste prende o argv: neutralização não entra na consulta
    que detecta declaração, senão a defesa apaga a própria evidência.
    """
    from nomos.adapters import git_tree as gt
    fonte = Path(gt.__file__).read_text("utf-8")
    i = fonte.index("def _config_do_repo")
    corpo = fonte[i:fonte.index("\n    def ", i + 10)]
    assert 'argv = [self._git' in corpo, (
        "a consulta de declaração voltou a montar o argv por `_base`; a "
        "neutralização entra junto e o `--list` passa a reportar o valor "
        "EFETIVO (vazio) em vez do declarado")
    # Só as linhas de CÓDIGO: o docstring cita `_NEUTRALIZAR_TREE` para
    # explicar por que ela NÃO entra aqui, e um teste que casasse o texto
    # proibiria a própria explicação.
    codigo = [ln for ln in corpo.splitlines()
              if ln.strip() and not ln.strip().startswith("#")]
    dentro = "\n".join(codigo[codigo.index(next(
        ln for ln in codigo if "argv = " in ln)):])
    assert "_NEUTRALIZAR" not in dentro, (
        "neutralização no argv da detecção: ela apaga a declaração que a "
        "detecção existe para ver")


# ═══ `N-A7-03` / `.1.N2` (P2) — o ORÁCULO residual de 1 BIT ═════════════════

_HOST_EXISTEM = ["/etc/passwd", "/etc/hosts", "/var/db/sudo", "/dev/null",
                 "/Applications", "/usr/libexec"]
_HOST_AUSENTES = ["/etc/nao-existe-xyz", "/var/db/nao-existe-xyz",
                  "/dev/nao-existe-xyz", "/Applications/nao-existe-xyz",
                  "/usr/libexec/nao-existe-xyz", "/nao-existe-r5-xyz"]


def _sondar_git_symlink(tmp_path, alvo_host: str, n: int) -> str:
    """Resposta do NOMOS a `.git` = symlink para um caminho do HOST."""
    from nomos.adapters import git_tree
    from nomos.adapters import filtro_governado as fg
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.wiring import registrar_git_tree
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades
    raiz = tmp_path / f"raizes{n}"
    repo = raiz / "r"
    repo.mkdir(parents=True)
    (repo / ".git").symlink_to(alvo_host)
    (repo / "x.txt").write_text("x\n")
    rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / f"p{n}.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-add", "runtime-governado",
                                        raizes=(str(raiz),))
    try:
        git_tree.GitTreeAdapter(registro=fg.RegistroDeFiltros()).executar(
            CapabilityRequest(capacidade="git-add", alvo=str(repo),
                              argumentos={"caminhos": ["x.txt"]}), ctx)
        return "ACEITOU"
    except Exception as e:                                   # noqa: BLE001
        # A CLASSE da exceção é o canal: dois tipos distintos = 1 bit vazado.
        return type(e).__name__


def test_r4_90_existencia_no_host_e_INDISTINGUIVEL(tmp_path):
    """MEDIDO: 2 classes de resposta, separação PERFEITA — 6 existem, 6 não.

    O `.exists()` que rodava ANTES de `conferir_git_dir` nos quatro adapters
    SEGUE o symlink e responde sem confrontar o destino com as raízes. Caminho
    ausente virava `ErroInvalido: não é repositório git`; caminho existente
    virava `ErroSeguranca: FORA das raízes`. Um bit por sonda, sobre qualquer
    caminho do host.

    Era redundante além de vazante: `conferir_git_dir` já recusa o que não é
    repositório, e recusa DEPOIS de confrontar com as raízes. Uma pré-checagem
    que antecipa a mesma decisão sem escopo não protege nada.

    O critério não é "recusou" — é a resposta ser a MESMA para os doze.
    """
    respostas = {alvo: _sondar_git_symlink(tmp_path, alvo, i)
                 for i, alvo in enumerate(_HOST_EXISTEM + _HOST_AUSENTES)}
    classes = set(respostas.values())
    assert len(classes) == 1, (
        f"a resposta DISTINGUE existência no host: {classes}. "
        f"Detalhe: { {a: r for a, r in respostas.items()} }")


def test_r4_91_CONTROLE_repo_legitimo_e_nao_repo_seguem_corretos(tmp_path):
    """Remover a pré-checagem não pode aceitar não-repositório nem quebrar repo.

    Sem este controle, `test_r4_90` passaria numa implementação que devolve a
    mesma coisa para tudo — inclusive aceitando o que não é repositório.
    """
    from nomos.adapters import git_tree
    from nomos.adapters import filtro_governado as fg
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
    from nomos.adapters.wiring import registrar_git_tree
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades

    def rodar(tipo):
        raiz = tmp_path / f"raiz_{tipo}"
        repo = raiz / "r"
        repo.mkdir(parents=True)
        if tipo == "repo":
            subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)],
                           check=True, capture_output=True)
        (repo / "x.txt").write_text("x\n")
        rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / f"c{tipo}.json"),
                                 approver=lambda *a, **k: True)
        registrar_git_tree(rc, raizes=(str(raiz),))
        ctx = CapabilityContext.de_registro(rc, "git-add", "runtime-governado",
                                            raizes=(str(raiz),))
        return git_tree.GitTreeAdapter(registro=fg.RegistroDeFiltros()).executar(
            CapabilityRequest(capacidade="git-add", alvo=str(repo),
                              argumentos={"caminhos": ["x.txt"]}), ctx)

    assert rodar("repo").efeito_aplicado, "repositório legítimo parou de funcionar"
    with pytest.raises(Exception, match="não é repositório git"):
        rodar("sem-git")
