"""CROSS_REPO + transação de REFS — quatro achados, três formas de confusão.

    .5.04   `commondir` -> git dir de OUTRO repo, com `.git` DIRETÓRIO
    .9.07   `.git` como SYMLINK -> git dir de OUTRO repo
    .11.08  filtro com `write_roots=(<git dir>,)` grava refs/objects/HEAD
    .11.06  commit RECUSADO deixava o repositório CORROMPIDO

## O gate que não disparava

`_conferir_titularidade` existe exatamente contra confusão cross-repo, e em dois
layouts ela nunca era chamada:

    `.git` SYMLINK      o gate era `if not ponto.is_dir()`, e `is_dir()` SEGUE
                        link — devolvia True e o gate não disparava
    `commondir`         o gate (corretamente) não dispara com `.git` DIRETÓRIO,
                        e ninguém conferia a SEGUNDA indireção

Nos dois, `git-add` estagiou no índice da VÍTIMA e `git-commit` AVANÇOU
`refs/heads/main` dela para um commit com `AWS_SECRET_ACCESS_KEY` — com a
auditoria registrando o repositório do ATACANTE como alvo.

## Por que `rc != 0` não é o critério aqui

Uma recusa que já mexeu no repositório da vítima não é recusa. Cada teste de
negação prova `INDEX_UNCHANGED`, `REFS_UNCHANGED` e store intacto.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


def _git(*args):
    return subprocess.run([GIT, *args], capture_output=True, text=True)


@pytest.fixture
def campo(tmp_path):
    raiz = tmp_path / "raizes"
    raiz.mkdir()

    class Campo:
        def __init__(self):
            self.raiz, self.tmp = raiz, tmp_path

        def repo(self, onde: Path, nome="ok.txt") -> Path:
            onde.mkdir(parents=True, exist_ok=True)
            _git("init", "-q", "-b", "main", str(onde))
            _git("-C", str(onde), "config", "user.email", "a@b.c")
            _git("-C", str(onde), "config", "user.name", "T")
            (onde / nome).write_text("ok\n")
            _git("-C", str(onde), "add", nome)
            _git("-C", str(onde), "commit", "-qm", "inicial")
            return onde

        def ctx(self, cap="git-add"):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            return CapabilityContext.de_registro(rc, cap, "runtime-governado",
                                                 raizes=(str(raiz),))

        def add(self, repo, *caminhos, registro=None):
            return git_tree.GitTreeAdapter(registro=registro).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx("git-add"))

        def commit(self, repo, msg="m", registro=None):
            return git_tree.GitTreeAdapter(registro=registro).executar(
                CapabilityRequest(capacidade="git-commit", alvo=str(repo),
                                  argumentos={"mensagem": msg}),
                self.ctx("git-commit"))

        def estado(self, repo: Path) -> tuple[str, str]:
            """O par que uma recusa não pode ter mexido."""
            return (_git("-C", str(repo), "rev-parse", "refs/heads/main").stdout,
                    _git("-C", str(repo), "ls-files").stdout)

    return Campo()


# ═══════════════ .5.04 e .9.07 — as duas formas de cross-repo ════════════════

def test_cross_repo_COMMONDIR_para_outro_repo_e_RECUSADO(campo):
    """A SEGUNDA indireção também tem dono, e ninguém a conferia."""
    vitima = campo.repo(campo.raiz / "vitima")
    hostil = campo.repo(campo.raiz / "hostil", nome="seed.txt")
    antes = campo.estado(vitima)

    (hostil / ".git" / "commondir").write_text(f"{vitima / '.git'}\n")
    (hostil / "segredo.txt").write_text("AWS_SECRET_ACCESS_KEY=vazou\n")

    with pytest.raises(supervisor.ErroSeguranca, match="commondir"):
        campo.add(hostil, "segredo.txt")
    assert campo.estado(vitima) == antes, "REFS/INDEX da vítima mudaram"


def test_cross_repo_DOTGIT_SYMLINK_e_RECUSADO(campo):
    """`is_dir()` SEGUE link — o gate da titularidade nunca disparava."""
    vitima = campo.repo(campo.raiz / "vitima")
    hostil = campo.raiz / "hostil"
    hostil.mkdir()
    os.symlink(str(vitima / ".git"), str(hostil / ".git"))
    (hostil / "segredo.txt").write_text("AWS_SECRET_ACCESS_KEY=abc123\n")
    antes = campo.estado(vitima)

    with pytest.raises(supervisor.ErroSeguranca):
        campo.add(hostil, "segredo.txt")
    assert campo.estado(vitima) == antes, "REFS/INDEX da vítima mudaram"


def test_cross_repo_CONTROLE_worktree_ligada_continua_funcionando(campo):
    """Sem isto, os dois acima passariam num sistema que parou de aceitar
    `commondir` — que é o mecanismo NORMAL de worktree ligada."""
    principal = campo.repo(campo.raiz / "principal", nome="a.txt")
    wt = campo.raiz / "wt"
    _git("-C", str(principal), "worktree", "add", "-q", str(wt), "-b", "b2")
    (wt / "novo.txt").write_text("novo\n")

    r = campo.add(wt, "novo.txt")
    assert r.efeito_aplicado
    assert "novo.txt" in _git("-C", str(wt), "ls-files").stdout


# ═════════════ .11.06 — commit RECUSADO não pode corromper o repo ════════════

def test_commit_recusado_nao_deixa_o_repositorio_CORROMPIDO(campo):
    """A configuração NORMAL de quem usa clean filter (git-lfs, git-crypt).

    `git commit` avança `refs/heads/<b>` e escreve o reflog ANTES de
    `conferir_saida` recusar; os objetos do commit estão na QUARENTENA, que o
    `finally` destrói. Sem as refs na transação, sobrava `HEAD` apontando para
    objeto INEXISTENTE — `git log` e `git status` parando de funcionar num
    repositório cuja operação foi RECUSADA.
    """
    repo = campo.repo(campo.raiz / "repo")
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)
    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(binario),
        managed_artifact=art, read_roots=(str(repo),), write_roots=(str(repo),)))

    (repo / "segredo.txt").write_text("SENHA=hunter2\n")
    (repo / ".gitattributes").write_text("segredo.txt filter=redator\n")
    _git("-C", str(repo), "config", "filter.redator.clean", str(binario))

    # O `add` governado FUNCIONA — o filtro do repo não executa, o governado
    # sim. Quem quebra é o `commit`, e é esse o ponto do achado.
    campo.add(repo, "segredo.txt", registro=reg)
    head_antes = _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip()

    with pytest.raises(supervisor.ErroSeguranca):
        campo.commit(repo, registro=reg)

    assert _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip() == head_antes, (
        "a ref avançou numa operação RECUSADA")
    assert _git("-C", str(repo), "log", "--oneline").returncode == 0, (
        "`git log` parou de funcionar — o repositório ficou inutilizável")
    fsck = _git("-C", str(repo), "fsck")
    assert fsck.returncode == 0, f"fsck acusou corrupção: {fsck.stderr[:200]}"


def test_commit_CONTROLE_commit_legitimo_ainda_avanca_a_ref(campo):
    """A transação de refs não pode ter desfeito o caminho que FUNCIONA."""
    repo = campo.repo(campo.raiz / "repo")
    (repo / "novo.txt").write_text("novo\n")
    campo.add(repo, "novo.txt")
    antes = _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip()

    r = campo.commit(repo, "commit legitimo")
    assert r.efeito_aplicado
    assert _git("-C", str(repo), "rev-parse", "HEAD").stdout.strip() != antes
    assert _git("-C", str(repo), "fsck").returncode == 0


# ═══════════ .11.08 — filtro com o GIT DIR como raiz de escrita ══════════════

@pytest.mark.parametrize("rel", [
    "refs/heads/plantado", "packed-refs", "objects/plantado", "HEAD", "logs/x",
])
def test_filtro_com_gitdir_como_raiz_nao_escreve_estado_do_git(campo, rel):
    """A forma de política que o código dizia estar coberta — e não estava.

    Com `write_roots=(<git dir>,)`, o termo `<raiz>/.git` aponta para um caminho
    que NÃO EXISTE, então sobravam graváveis `refs/`, `HEAD`, `packed-refs` e
    `objects/` — onde o filtro planta OBJETO e REF, não só configuração.
    """
    repo = campo.repo(campo.raiz / "repo")
    gd = repo / ".git"
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)

    alvo = gd / rel
    alvo.parent.mkdir(parents=True, exist_ok=True)
    pol = fg.PoliticaDeFiltro(
        filter_id="f", canonical_executable=str(binario), managed_artifact=art,
        argv_policy=("--sonda-escrita", str(alvo)),
        read_roots=(str(gd),), write_roots=(str(gd),))
    supervisor.executar(pol.comando(), cwd=repo, env=pol.ambiente(), prazo=10.0,
                        confinamento=pol.confinamento(),
                        tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO,
                        entrada=b"")

    escreveu = alvo.exists() and alvo.read_bytes() == b"PLANTADO\n"
    assert not escreveu, f"o filtro plantou estado do Git em {rel}"


def test_filtro_com_gitdir_como_raiz_NEGA_o_git_dir_INTEIRO(campo):
    """A raiz de escrita que É um git dir é negada por INTEIRO.

    A versão anterior deste teste era um CONTROLE que exigia a sonda escrevendo
    em `<git dir>/saida-do-filtro.txt` — e isso encodava a VULNERABILIDADE: uma
    lista de nomes negados nunca fecha (`sharedindex.<sha>`, `MERGE_HEAD`, o
    próximo nome que o Git inventar), então o filtro sempre achava um lugar
    gravável dentro do git dir. Um filtro de conteúdo lê stdin e escreve stdout;
    não tem o que escrever num diretório Git. Quando a raiz É um git dir, ela é
    negada inteira.
    """
    repo = campo.repo(campo.raiz / "repo")
    gd = repo / ".git"
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)

    alvo = gd / "qualquer-nome-que-o-git-nunca-teve.txt"
    pol = fg.PoliticaDeFiltro(
        filter_id="f", canonical_executable=str(binario), managed_artifact=art,
        argv_policy=("--sonda-escrita", str(alvo)),
        read_roots=(str(gd),), write_roots=(str(gd),))
    supervisor.executar(pol.comando(), cwd=repo, env=pol.ambiente(), prazo=10.0,
                        confinamento=pol.confinamento(),
                        tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO,
                        entrada=b"")
    assert not (alvo.exists() and alvo.read_bytes() == b"PLANTADO\n"), (
        "o filtro escreveu no git dir por um nome que a lista não previa — a "
        "negação por nome nunca fecha; o git dir tem de ser negado inteiro")


def test_filtro_com_working_tree_como_raiz_CONTROLE_area_concedida(campo):
    """Controle honesto: a sonda escreve onde a política concede DE VERDADE.

    A área concedida legítima de um filtro é uma área de conteúdo, não o git
    dir. Aqui a raiz é a WORKING TREE, e a sonda tem de conseguir escrever nela
    — senão os testes de recusa não distinguem contenção de sonda morta.
    """
    repo = campo.repo(campo.raiz / "repo")
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)

    alvo = repo / "saida-do-filtro.txt"
    pol = fg.PoliticaDeFiltro(
        filter_id="f", canonical_executable=str(binario), managed_artifact=art,
        argv_policy=("--sonda-escrita", str(alvo)),
        read_roots=(str(repo),), write_roots=(str(repo),))
    supervisor.executar(pol.comando(), cwd=repo, env=pol.ambiente(), prazo=10.0,
                        confinamento=pol.confinamento(),
                        tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO,
                        entrada=b"")
    assert alvo.exists() and alvo.read_bytes() == b"PLANTADO\n", (
        "a sonda não escreve nem na área de conteúdo concedida — os testes de "
        "recusa acima não distinguem contenção de sonda morta")


# ═══════════ .7.13 — a auditoria nomeia a autoridade CONSUMIDA ═══════════════

def test_auditoria_registra_o_git_dir_EFETIVO_nao_so_o_alvo(campo):
    """O operador nomeia a working tree; o efeito cai no git dir/common.

    MEDIDO: o registro trazia só `alvo`. Numa worktree ligada LEGÍTIMA o objeto
    foi para o COMMON DIR, e quem lê a auditoria via `alvo=<raizes>/wt` sem ter
    como saber onde o efeito caiu. Combinado com confusão cross-repo, o registro
    apontava para o repositório do ATACANTE — errado exatamente no caso em que
    ele mais importa.
    """
    principal = campo.repo(campo.raiz / "principal", nome="a.txt")
    wt = campo.raiz / "wt"
    _git("-C", str(principal), "worktree", "add", "-q", str(wt), "-b", "b2")
    (wt / "novo.txt").write_text("novo\n")

    registros = []

    class Espia:
        def append(self, evento, **campos):
            registros.append((evento, campos))

    rc = RegistroCapacidades(policy=PolicyEngine(campo.tmp / "aud.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(campo.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-add", "runtime-governado",
                                        raizes=(str(campo.raiz),),
                                        audit=Espia())
    git_tree.GitTreeAdapter().executar(
        CapabilityRequest(capacidade="git-add", alvo=str(wt),
                          argumentos={"caminhos": ["novo.txt"]}), ctx)

    assert registros, "nenhum evento de auditoria foi emitido"
    _evento, campos = registros[-1]
    gd = _git("-C", str(wt), "rev-parse", "--absolute-git-dir").stdout.strip()
    comum = _git("-C", str(wt), "rev-parse", "--git-common-dir").stdout.strip()
    valores = " ".join(str(v) for v in campos.values())
    assert gd in valores, (
        f"a auditoria não nomeia o git dir EFETIVO ({gd}); campos={sorted(campos)}")
    assert Path(comum).name and str(Path(comum).resolve()) in valores or comum in valores, (
        f"a auditoria não nomeia o common dir EFETIVO ({comum})")


# ══════ .4.07 — a allowlist do push cobre o transporte, e ainda CONTÉM ═══════

def test_push_allowlist_inclui_helpers_de_transporte():
    """REGRESSION de caso LEGÍTIMO, medida: `git-remote-http` não é o `git`.

    O docstring da allowlist afirmava que os helpers compartilham o inode do
    `git` e concluía que "dois literais já cobrem os helpers". Vale para
    `git-receive-pack`/`git-upload-pack` (hardlink), e é FALSO para o transporte
    remoto — inodes medidos distintos. Com só os dois literais, TODO push
    http/https morria em `cannot exec 'git-remote-http'`.
    """
    from nomos.adapters import git as gmod
    helpers = gmod.helpers_de_transporte()
    if not helpers:
        pytest.skip("host sem helpers de transporte do Git")
    assert any("git-remote-http" in h for h in helpers)


def test_push_allowlist_AINDA_CONTEM_apesar_dos_helpers(campo):
    """Alargar a allowlist não pode devolver a execução arbitrária.

    Este é o controle que impede a correção de `.4.07` de virar o defeito que
    C13 fechou: o shell está na lista, os helpers estão na lista, e mesmo assim
    um binário de fora dela não executa.
    """
    from nomos.adapters import git as gmod
    from nomos.adapters import git_push
    repo = campo.repo(campo.raiz / "repo")
    bare = campo.raiz / "cofre.git"
    _git("init", "-q", "--bare", str(bare))
    d = git_push.DestinoGovernado(remote_id="o", url=f"file://{bare}",
                                  branch_destino="main")
    conf = git_push.GitPushAdapter(destinos={"o": d}).confinamento(repo, d)

    p = supervisor.executar(["/bin/sh", "-c", "/usr/bin/id"], cwd=repo,
                            env=gmod.ambiente_minimo(), prazo=15.0,
                            confinamento=conf)
    assert p.returncode != 0, (
        "o shell da allowlist executou /usr/bin/id — a contenção de C13 "
        "regrediu ao acrescentar os helpers de transporte")


# ═════ probes reclassificados: o CONTROLE POSITIVO falha, não há vetor ══════

def test_probe_ref_symlink_NAO_e_canal_de_escrita_para_fora(campo, tmp_path):
    """`.6.08` era INVALID_PROBE, e este teste PRENDE a razão.

    A premissa era: `refs/heads/main` como symlink faria o commit escrever o
    novo sha ATRAVÉS do link, fora das raízes. MEDIDO no git CRU: não escreve —
    o Git SUBSTITUI o symlink por arquivo regular e o alvo de fora fica intacto.

    Sem efeito hostil no controle positivo não há vetor a fechar, e classificar
    como CLOSED seria creditar ao NOMOS uma defesa que é do Git. Se um dia o Git
    mudar, este teste falha e o vetor volta a ser real — que é exatamente o
    serviço que um probe inválido deve prestar depois de reclassificado.
    """
    repo = campo.repo(campo.raiz / "repo")
    fora = tmp_path / "branch-roubado"
    fora.write_text("0" * 40 + "\n")
    antes = fora.read_text()

    ref = repo / ".git" / "refs" / "heads" / "main"
    ref.unlink(missing_ok=True)
    os.symlink(str(fora), str(ref))

    (repo / "n.txt").write_text("n\n")
    _git("-C", str(repo), "add", "n.txt")
    _git("-C", str(repo), "commit", "-qm", "cru")

    assert fora.read_text() == antes, (
        "o Git passou a escrever ATRAVÉS do symlink de ref — a premissa de "
        "`.6.08` voltou a valer e o vetor precisa ser reavaliado")


def test_probe_hardlink_o_git_CRU_tambem_indexa(campo, tmp_path):
    """`.9.08` era INVALID_PROBE, e a razão fica presa aqui.

    Um hardlink dentro da raiz para um inode de fora faz o conteúdo chegar ao
    índice — mas o git CRU faz o MESMO. Não há divergência: hardlink não é
    indireção que o NOMOS possa resolver (o arquivo É o inode, não há link a
    canonicalizar), e negá-lo exigiria comparar inodes contra todo o disco.

    O invariante que sustenta essa aceitação é `C6` — nenhuma capacidade
    governada CRIA hardlink —, e ele tem teste próprio. Aqui prende-se só a
    premissa: se o git cru passar a recusar, a divergência nasce e o vetor
    volta.
    """
    repo = campo.repo(campo.raiz / "repo")
    segredo = tmp_path / "seg.pem"
    segredo.write_text("AWS_SECRET_ACCESS_KEY=abc123\n")
    os.link(str(segredo), str(repo / "vaza.txt"))

    r = _git("-C", str(repo), "add", "--no-all", "--", "vaza.txt")
    assert r.returncode == 0, (
        "o git CRU passou a recusar hardlink — agora HÁ divergência a medir "
        "entre ele e o caminho governado, e `.9.08` deixa de ser probe inválido")


# ═════ .6.09 / .11.07 — HEAD/refs/reflog como symlink ou FIFO ════════════════

@pytest.mark.parametrize("rel", ["HEAD", "packed-refs", "ORIG_HEAD",
                                 "refs/heads/main"])
def test_ref_como_SYMLINK_para_fora_e_recusada(campo, tmp_path, rel):
    """`_instantaneo_das_refs` lê no processo do supervisor, fora do sandbox.

    Os nomes são do REPOSITÓRIO. Como symlink para fora, a leitura trazia
    conteúdo de fora das raízes e o `os.replace` do rollback trocava o link por
    arquivo regular. `lstat` + só arquivo regular fecha.
    """
    repo = campo.repo(campo.raiz / "repo")
    vitima = tmp_path / "segredo-de-fora"
    vitima.write_text("conteudo-de-fora\n")
    alvo = repo / ".git" / rel
    alvo.parent.mkdir(parents=True, exist_ok=True)
    if alvo.exists():
        alvo.unlink()
    os.symlink(str(vitima), str(alvo))
    antes = vitima.read_text()
    (repo / "n.txt").write_text("n\n")

    with pytest.raises(supervisor.ErroSeguranca):
        campo.add(repo, "n.txt")
    assert vitima.read_text() == antes, "a vítima de fora foi tocada"
    assert alvo.is_symlink(), "o rollback trocou o link por arquivo regular"


def test_ref_como_FIFO_nao_pendura_o_supervisor(campo):
    """Mesma família do FIFO no índice: o `read` roda no pai."""
    import signal
    repo = campo.repo(campo.raiz / "repo")
    alvo = repo / ".git" / "ORIG_HEAD"
    if alvo.exists():
        alvo.unlink()
    os.mkfifo(alvo)
    (repo / "n.txt").write_text("n\n")

    def estourou(*_):
        raise AssertionError("PENDUROU: o instantâneo de refs bloqueou no FIFO")

    anterior = signal.signal(signal.SIGALRM, estourou)
    signal.alarm(20)
    try:
        with pytest.raises(supervisor.ErroSeguranca, match="arquivo regular"):
            campo.add(repo, "n.txt")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, anterior)


# ═════ .11.08 — nomes VARIÁVEIS que a lista de negados nunca fecha ═══════════

@pytest.mark.parametrize("rel", ["sharedindex.abc123def", "MERGE_HEAD",
                                 "objects/pack/plantado", "refs/heads/x",
                                 "packed-refs.lock"])
def test_filtro_gitdir_nega_nomes_variaveis(campo, rel):
    """A negação por nome nunca fecha; o git dir inteiro é negado."""
    repo = campo.repo(campo.raiz / "repo")
    gd = repo / ".git"
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)

    alvo = gd / rel
    alvo.parent.mkdir(parents=True, exist_ok=True)
    pol = fg.PoliticaDeFiltro(
        filter_id="f", canonical_executable=str(binario), managed_artifact=art,
        argv_policy=("--sonda-escrita", str(alvo)),
        read_roots=(str(gd),), write_roots=(str(gd),))
    supervisor.executar(pol.comando(), cwd=repo, env=pol.ambiente(), prazo=10.0,
                        confinamento=pol.confinamento(),
                        tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO,
                        entrada=b"")
    assert not (alvo.exists() and alvo.read_bytes() == b"PLANTADO\n"), (
        f"o filtro plantou em {rel} — nome fora da lista, git dir não negado "
        "por inteiro")


# ═════ .5.03 — a cadeia de alternates é TRANSITIVA ══════════════════════════

def test_alternates_TRANSITIVO_para_fora_e_recusado(campo):
    """repo -> elo (DENTRO) -> externo (FORA): o Git segue a cadeia."""
    repo = campo.repo(campo.raiz / "repo")
    elo = campo.repo(campo.raiz / "elo")
    externo = campo.repo(campo.tmp / "externo")
    for base, alvo in ((repo, elo), (elo, externo)):
        info = base / ".git" / "objects" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "alternates").write_text(f"{alvo / '.git' / 'objects'}\n")
    (repo / "n.txt").write_text("n\n")

    with pytest.raises(supervisor.ErroSeguranca, match="alternado"):
        campo.add(repo, "n.txt")


def test_alternates_CONTROLE_cadeia_toda_dentro_funciona(campo):
    """Sem isto, o teste acima passaria com alternate legítimo quebrado."""
    repo = campo.repo(campo.raiz / "repo")
    vizinho = campo.repo(campo.raiz / "vizinho")
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(f"{vizinho / '.git' / 'objects'}\n")
    (repo / "n.txt").write_text("n\n")

    r = campo.add(repo, "n.txt")
    assert r.efeito_aplicado, "alternate legítimo dentro das raízes foi recusado"
