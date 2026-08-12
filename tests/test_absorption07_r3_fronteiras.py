"""As fronteiras que a 3ª medição global abriu — 4 P0 e 3 P1, uma por teste.

Sete achados independentes com UMA forma em comum: a defesa existia e estava
CERTA, e o repositório chegou nela por um caminho que ela não olhava.

    .2.NOVO-BANG-FILTER   trocar `-filter` por `!filter` muda a RESPOSTA do
                          check-attr de `unset` para `unspecified`
    .8.NEW-REFSDIR        `refs` como symlink de DIRETÓRIO: o guard olhava o
                          componente FINAL, e o link estava no MEIO
    .11.13                `--separate-git-dir` dá ao git dir um nome que o
                          atacante escolhe, e a negação era por NOME
    .4.08                 `[core "sub"]` é lido como `core` por um parser que
                          pega o primeiro token — prova FORJADA de titularidade
    .5.08                 o teto do BFS de alternates estava no `while` e
                          contava ENTRADAS: 120 alternates saturam o contador
                          antes do 2º salto, e o laço retorna sem conferir
    .11.09                o desfazer de refs não distinguia ref NOSSA de ref de
                          TERCEIRO: incidente forense que dispara sozinho
    .8.05-08              e o discriminador do índice só via a janela
                          exec→desfazer: terceiro que entra ANTES do exec era
                          destruído em silêncio

Os dois últimos são o mesmo par de erros opostos no mesmo mecanismo — falso
positivo e falso negativo — e por isso vivem juntos aqui: consertar um sem medir
o outro foi exatamente o que aconteceu na rodada anterior.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git, git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"


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
def campo(tmp_path):
    raiz = tmp_path / "raizes"
    raiz.mkdir()

    class Campo:
        def __init__(self):
            self.raiz, self.tmp = raiz, tmp_path

        def ctx(self, cap="git-add"):
            rc = RegistroCapacidades(
                policy=PolicyEngine(tmp_path / "pol.json"),
                approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            return CapabilityContext.de_registro(rc, cap, "runtime-governado",
                                                 raizes=(str(raiz),))

        def add(self, repo, *caminhos, registro=None):
            return git_tree.GitTreeAdapter(registro=registro).executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx())

        def commit(self, repo, msg="nosso"):
            return git_tree.GitTreeAdapter(
                registro=fg.RegistroDeFiltros()).executar(
                CapabilityRequest(capacidade="git-commit", alvo=str(repo),
                                  argumentos={"mensagem": msg}),
                self.ctx("git-commit"))

    return Campo()


@pytest.fixture
def governado(campo):
    """Repositório com o redator APROVADO — o caminho legítimo, não uma maquete.

    Sem filtro real não dá para medir a diferença entre `SENHA=hunter2` e
    `SENHA=REDIGIDO`, que é a única evidência que distingue "a defesa recusou"
    de "a defesa deixou passar o conteúdo cru".
    """
    if not os.path.exists(supervisor.SANDBOX):
        pytest.skip("sem sandbox-exec não há execução supervisionada")
    repo = _init(campo.raiz / "repo")
    binario = campo.tmp / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(campo.tmp / "store").importar(binario)
    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(binario),
        managed_artifact=art, read_roots=(str(repo),),
        write_roots=(str(repo),)))
    return campo, repo, reg


# ═════════════ .2.NOVO-BANG-FILTER (P0) — o atacante trocou um token ═════════

@pytest.mark.parametrize("cancelamento", ["-filter", "!filter"])
def test_r3_01_cancelar_o_filtro_e_RECUSA_nas_duas_grafias(governado,
                                                           cancelamento):
    """`unspecified` e `unset` são respostas DIFERENTES para o mesmo ataque.

    MEDIDO com o `check-attr` real: `-filter` responde `unset` e `!filter`
    responde `unspecified`. A defesa da rodada anterior tratava só `unset`, e
    `unspecified` estava na lista de ignorados — porque é também a resposta
    legítima de "não há regra". Sem o Git aplicar filtro nenhum, o índice fica
    com `SENHA=hunter2`.
    """
    _campo, repo, reg = governado
    (repo / ".gitattributes").write_text(
        f"*.txt filter=redator\nsegredo.txt {cancelamento}\n")
    (repo / "segredo.txt").write_text("SENHA=hunter2\n")

    with pytest.raises(supervisor.ErroSeguranca):
        _campo.add(repo, "segredo.txt", registro=reg)

    saida = subprocess.run([GIT, "-C", str(repo), "cat-file",
                            "--batch-all-objects", "--batch"],
                           capture_output=True).stdout
    assert b"hunter2" not in saida, (
        f"`{cancelamento}` desligou a redação e o conteúdo cru chegou ao store")


def test_r3_02_CONTROLE_sem_cancelamento_o_filtro_roda_e_redige(governado):
    """Sem este controle, o teste acima passaria num sistema que recusa tudo."""
    _campo, repo, reg = governado
    (repo / ".gitattributes").write_text("*.txt filter=redator\n")
    (repo / "segredo.txt").write_text("SENHA=hunter2\n")

    r = _campo.add(repo, "segredo.txt", registro=reg)
    assert r.efeito_aplicado
    sha = subprocess.run([GIT, "-C", str(repo), "ls-files", "-s", "--",
                          "segredo.txt"], capture_output=True,
                        text=True).stdout.split()[1]
    corpo = subprocess.run([GIT, "-C", str(repo), "cat-file", "-p", sha],
                           capture_output=True).stdout
    assert corpo == b"SENHA=REDIGIDO\n"


# ══════ .8.NEW-REFSDIR-SYMLINK (P0) — o link estava no componente do MEIO ════

@pytest.mark.parametrize("sub", ["refs", "logs"])
def test_r3_03_refs_como_SYMLINK_DE_DIRETORIO_e_recusado(campo, tmp_path, sub):
    """`is_dir()` e `rglob` SEGUEM o link; o `lstat` final não vê nada errado.

    Os arquivos encontrados lá fora são regulares de verdade, então passam no
    guard do componente FINAL. O instantâneo leria conteúdo de fora das raízes
    no processo do supervisor, e o desfazer escreveria lá — a mesma forma de
    `.2.14` e `.3.02`, num terceiro lugar.
    """
    repo = _init(campo.raiz / "repo")
    fora = tmp_path / "fora"
    (fora / "heads").mkdir(parents=True)
    (fora / "heads" / "roubada").write_text("segredo do host\n")

    alvo = repo / ".git" / sub
    if alvo.exists():
        subprocess.run(["rm", "-rf", str(alvo)], check=True)
    alvo.symlink_to(fora, target_is_directory=True)

    aut = git.autoridade_de(str(repo), *git.conferir_git_dir(
        str(repo), (str(campo.raiz),)))
    with pytest.raises(supervisor.ErroSeguranca, match="não é diretório real"):
        git_tree._instantaneo_das_refs(aut)


# ═══ .11.13 (P0) — negação por NOME não fecha nome escolhido pelo atacante ═══

@pytest.mark.parametrize("rel", [
    "hooks/pre-commit", "config", "info/attributes", "refs/heads/plantado",
])
def test_r3_04_gitdir_SEM_o_nome_git_nao_e_gravavel_pelo_filtro(tmp_path, rel):
    """`--separate-git-dir` põe o git dir num caminho sem o componente `.git`.

    A negação era por NOME (`\\.git`), então não alcançava esse git dir: o
    filtro governado gravava hook, config, fonte de atributo e ref lá dentro —
    instalando o PRÓXIMO, que é exatamente a propriedade que A6 nega.
    """
    if not os.path.exists(supervisor.SANDBOX):
        pytest.skip("sem sandbox-exec não há execução supervisionada")
    raiz = tmp_path / "raizes"
    trabalho = raiz / "proj"
    gitdir = raiz / "deposito-do-atacante"
    trabalho.mkdir(parents=True)
    subprocess.run([GIT, "init", "-q", "--separate-git-dir", str(gitdir),
                    str(trabalho)], check=True, capture_output=True)
    assert ".git" not in str(gitdir), "o cenário perderia o sentido"

    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)

    alvo = gitdir / rel
    alvo.parent.mkdir(parents=True, exist_ok=True)
    pol = fg.PoliticaDeFiltro(
        filter_id="f", canonical_executable=str(binario), managed_artifact=art,
        argv_policy=("--sonda-escrita", str(alvo)),
        read_roots=(str(raiz),), write_roots=(str(raiz),))
    supervisor.executar(pol.comando(), cwd=trabalho, env=pol.ambiente(),
                        prazo=10.0, confinamento=pol.confinamento(),
                        tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO,
                        entrada=b"")

    plantou = alvo.exists() and alvo.read_bytes() == b"PLANTADO\n"
    assert not plantou, (
        f"o filtro plantou {rel} num git dir criado com --separate-git-dir; "
        "o nome do diretório é escolha de quem cria o repositório, então "
        "negar pelo nome nunca fecha este caso")


# ════ .4.08 (P0) — prova FORJADA de titularidade passava; a real é exata ═════

@pytest.mark.parametrize("secao", ["[core]", "[CORE]", "[Core]",
                                   '[core "sub"]', "[coreX]"])
def test_r3_05_titularidade_aceita_EXATAMENTE_o_que_o_git_honra(tmp_path,
                                                                secao):
    """O parser pegava o primeiro token da seção — `[core "sub"]` virava `core`.

    A expectativa não é minha leitura da documentação: cada caso pergunta ao
    `git config` do host, na MESMA execução, se aquela grafia é honrada, e só
    então exige que a guarda concorde. Seção que o Git IGNORA não pode servir
    de prova de titularidade (aceitar seria comprar prova FORJADA); seção que
    ele honra não pode ser recusada (recusar quebraria repositório legítimo).

    Os dois lados no mesmo teste, porque foi separá-los que deixou passar: a
    versão anterior media só a aceitação.
    """
    raiz = tmp_path / "raizes"
    trabalho = raiz / "proj"
    gitdir = raiz / "deposito"
    trabalho.mkdir(parents=True)
    subprocess.run([GIT, "init", "-q", "--separate-git-dir", str(gitdir),
                    str(trabalho)], check=True, capture_output=True)

    cfg = gitdir / "config"
    # Fora a prova LEGÍTIMA; entra só a grafia sob teste. Sem isso o `[core]`
    # original responderia por todas e o teste não mediria nada.
    linhas = [ln for ln in cfg.read_text().splitlines()
              if "worktree" not in ln]
    cfg.write_text("\n".join(linhas) + f"\n{secao}\n\tworktree = {trabalho}\n")

    git_honra = bool(_git("-C", str(trabalho), "config", "--get",
                          "core.worktree").stdout.strip())

    if git_honra:
        git.conferir_git_dir(str(trabalho), (str(raiz),))
    else:
        with pytest.raises(supervisor.ErroSeguranca):
            git.conferir_git_dir(str(trabalho), (str(raiz),))


# ═══ .5.08 (P1) — o teto do BFS de alternates era uma PORTA, agora é RECUSA ══

def test_r3_07_alternates_a_LARGURA_nao_derruba_a_transitividade(tmp_path):
    """MEDIDO: com N=3 a cadeia era recusada; com N=120 passava.

    O contador saturava ainda dentro do PRIMEIRO arquivo e a condição estava no
    `while`, então o laço terminava com a fila cheia e a função RETORNAVA — sem
    abrir o `info/alternates` de nenhum dos alternates de 1º nível. O bypass não
    era o conteúdo, era a LARGURA, e quem escolhe a largura é quem escreve o
    arquivo.
    """
    raiz = tmp_path / "raizes"
    fora = tmp_path / "fora"
    raiz.mkdir()
    fora.mkdir()
    repo = _init(raiz / "repo")
    estrangeiro = _init(fora / "estrangeiro")

    alts = [_init(raiz / f"a{i:03d}") / ".git" / "objects" for i in range(120)]
    # O 2º salto sai das raízes — e é o que a saturação escondia.
    info0 = alts[0] / "info"
    info0.mkdir(parents=True, exist_ok=True)
    (info0 / "alternates").write_text(
        str(estrangeiro / ".git" / "objects") + "\n")

    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text("".join(f"{p}\n" for p in alts))

    raizes = (str(raiz),)
    aut = git.autoridade_de(str(repo), *git.conferir_git_dir(str(repo), raizes))
    with pytest.raises(supervisor.ErroSeguranca, match="store de objetos"):
        git.conferir_alternates(str(repo), raizes, autoridade=aut)


def test_r3_08_CONTROLE_cadeia_LEGITIMA_e_larga_continua_passando(tmp_path):
    """Sem este controle, o de cima passaria num sistema que recusa por tamanho.

    120 alternates, todos dentro das raízes, nenhum saindo em nenhum salto: é
    cadeia grande e LEGÍTIMA, e tem de passar.
    """
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    repo = _init(raiz / "repo")
    alts = [_init(raiz / f"b{i:03d}") / ".git" / "objects" for i in range(120)]
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text("".join(f"{p}\n" for p in alts))

    raizes = (str(raiz),)
    aut = git.autoridade_de(str(repo), *git.conferir_git_dir(str(repo), raizes))
    git.conferir_alternates(str(repo), raizes, autoridade=aut)


def test_r3_09_estourar_o_teto_e_RECUSA_e_nao_silencio(tmp_path, monkeypatch):
    """Parar por defesa não prova contenção — e antes retornava como se provasse.

    O teto real é 1000; forçá-lo para 2 mede a PROPRIEDADE (fail-closed) sem
    construir mil repositórios, que é custo sem informação nova.
    """
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    repo = _init(raiz / "repo")
    cadeia = [_init(raiz / f"c{i}") / ".git" / "objects" for i in range(6)]
    anterior = repo / ".git" / "objects"
    for prox in cadeia:
        d = anterior / "info"
        d.mkdir(parents=True, exist_ok=True)
        (d / "alternates").write_text(f"{prox}\n")
        anterior = prox

    monkeypatch.setattr(git, "MAX_STORES", 2)
    raizes = (str(raiz),)
    aut = git.autoridade_de(str(repo), *git.conferir_git_dir(str(repo), raizes))
    with pytest.raises(supervisor.ErroSeguranca, match="não terminou"):
        git.conferir_alternates(str(repo), raizes, autoridade=aut)


# ═══════ .11.09 e .8.05-08 (P1) — os dois erros opostos do MESMO sinal ═══════

def _recusa_apos_o_exec(monkeypatch):
    """Faz a recusa cair DEPOIS do exec — a janela onde o mascaramento vivia.

    Antes do exec o desfazer já comparava com o instantâneo e acusava certo; é
    só quando existe efeito NOSSO a descontar que o discriminador entra em
    cena, e era ali que ele errava nas duas direções.
    """
    def explode(self, *a, **k):
        raise RuntimeError("recusa pos-exec")
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", explode)


def _na_janela(monkeypatch, acao):
    """Roda `acao` entre o INSTANTÂNEO e o nosso exec, deterministicamente.

    Uma thread com `sleep` mediria a mesma propriedade com resultado
    intermitente; o gancho no instantâneo das refs cai exatamente na janela.
    """
    real = git_tree._instantaneo_das_refs

    def espiao(*a, **k):
        est = real(*a, **k)
        acao()
        return est
    monkeypatch.setattr(git_tree, "_instantaneo_das_refs", espiao)


def test_r3_10_terceiro_ANTES_do_exec_nao_e_destruido_em_silencio(campo,
                                                                  monkeypatch):
    """`.8.05-08` (REGRESSION, reproduzido 12/12 e depois 4/4).

    O discriminador era `depois_do_exec`, tirado APÓS o nosso exec — então um
    `git add` de terceiro que entra ANTES do exec já está dentro das duas fotos
    comparadas. O detector conclui "igual", o rollback apaga o trabalho aceito,
    e ninguém fica sabendo. O conserto de `.11.09` fechou o falso positivo e
    abriu este falso NEGATIVO, que é o pior dos dois.
    """
    repo = _init(campo.raiz / "repo")
    (repo / "a.txt").write_text("a\n")
    _git("-C", str(repo), "add", "a.txt")
    (repo / "zz.txt").write_text("x\n")
    (repo / "concorrente.txt").write_text("trabalho de outro\n")

    feito = {}

    def terceiro():
        feito["rc"] = _git("-C", str(repo), "add",
                           "concorrente.txt").returncode
    _na_janela(monkeypatch, terceiro)
    _recusa_apos_o_exec(monkeypatch)

    with pytest.raises(RuntimeError) as ei:
        campo.add(repo, "zz.txt")

    assert feito.get("rc") == 0, "o terceiro não chegou a ser aceito"
    assert "trabalho de terceiro foi perdido" in str(ei.value), (
        "o rollback sobrepôs um `git add` de terceiro que saiu rc=0 e não "
        "emitiu incidente — perda silenciosa de trabalho aceito")


def test_r3_11_NOSSAS_refs_nao_viram_incidente_forense(campo, monkeypatch):
    """`.11.09`: sinal que dispara sozinho não é sinal.

    `git commit` cria `refs/heads/main` e o reflog; nada disso está no
    instantâneo, e o laço tratava tudo que não estivesse lá como terceiro. Sem
    concorrência nenhuma, TODA recusa de `git-commit` acusava perda de trabalho
    alheio — destruindo a confiança na única evidência que `.8.03` construiu.
    """
    repo = _init(campo.raiz / "repo")
    (repo / "a.txt").write_text("a\n")
    _git("-C", str(repo), "add", "a.txt")
    _recusa_apos_o_exec(monkeypatch)

    with pytest.raises(RuntimeError) as ei:
        campo.commit(repo)

    assert "trabalho de terceiro foi perdido" not in str(ei.value), (
        "incidente forense FALSO: as refs criadas foram as do nosso próprio "
        "exec, e não havia processo concorrente nenhum")


def test_r3_12_ref_de_TERCEIRO_na_janela_continua_virando_incidente(campo,
                                                                    monkeypatch):
    """O par do teste acima: fechar o falso positivo não pode calar o real."""
    repo = _init(campo.raiz / "repo")
    (repo / "a.txt").write_text("a\n")
    _git("-C", str(repo), "add", "a.txt")

    def terceiro():
        _git("-C", str(repo), "commit", "-q", "--allow-empty", "-m", "de outro")
        _git("-C", str(repo), "branch", "de-terceiro")
    _na_janela(monkeypatch, terceiro)
    _recusa_apos_o_exec(monkeypatch)

    erro = ""
    try:
        campo.commit(repo)
    except Exception as e:                                   # noqa: BLE001
        erro = str(e)
    assert erro, "a operação não foi recusada; o desfazer nunca rodou"
    assert "trabalho de terceiro foi perdido" in erro, (
        "a ref e o reflog criados por OUTRO processo na janela foram "
        f"apagados pelo desfazer sem incidente nenhum: {erro!r}")
    assert "refs" in erro, "o incidente não nomeia as refs"


def test_r3_13_o_incidente_diz_QUAL_estado_foi_sobreposto(campo, monkeypatch):
    """"o índice" para uma REF perdida manda a pessoa procurar no lugar errado."""
    repo = _init(campo.raiz / "repo")
    (repo / "a.txt").write_text("a\n")
    _git("-C", str(repo), "add", "a.txt")
    (repo / "zz.txt").write_text("x\n")
    (repo / "concorrente.txt").write_text("de outro\n")

    _na_janela(monkeypatch,
               lambda: _git("-C", str(repo), "add", "concorrente.txt"))
    _recusa_apos_o_exec(monkeypatch)

    with pytest.raises(RuntimeError) as ei:
        campo.add(repo, "zz.txt")
    assert "índice" in str(ei.value), (
        "o incidente não nomeia o estado sobreposto")
