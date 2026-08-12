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
