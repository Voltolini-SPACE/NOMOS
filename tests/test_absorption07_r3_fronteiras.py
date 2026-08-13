"""As fronteiras que a 3ª medição global abriu — 4 P0, 3 P1 e 4 P2.

Onze achados independentes com UMA forma em comum: a defesa existia e estava
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
    .6.N1                 o mesmo falso incidente, pelo canal das refs, num
                          cenário que o repositório monta sozinho
    .9.12                 `.git` como symlink era um ORÁCULO do host: a
                          EXCEÇÃO respondia existência, tipo, modo e tamanho
    .7.19                 o repo RENOMEIA o git dir e a limpeza da quarentena
                          vira no-op silencioso — o blob cru sobrevive
    .1.07                 um diretório CHAMADO `worktrees` satisfazia a forma
                          de worktree ligada, e o efeito caía no vizinho

`.11.09`+`.8.05-08` são o mesmo par de erros opostos no mesmo mecanismo — falso
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


# ═══════ .6.N1 (P2) — o cenário EXATO do vetor, que era 2/2 antes ════════════

def test_r3_14_ref_NOVA_criada_pelo_nosso_commit_nao_acusa_terceiro(campo):
    """O vetor de `.6.N1`, sem gancho nenhum: dois arquivos que o REPO escreve.

    `.git/HEAD` num branch não-nascido + `objects/info/alternates` apontando
    para um store que não existe (mas DENTRO das raízes, então passa a guarda).
    O `git commit` sai rc=0 com erro no stderr, `conferir_saida` recusa DEPOIS
    de o commit ter criado `refs/heads/nova` e os logs, e o desfazer acusava
    perda de trabalho alheio — com o repositório sozinho na máquina.

    O contraste do vetor era o HEAD: com ref preexistente, sem acusação; com ref
    NOVA, acusação. Os dois estão aqui, porque foi o par que provou a causa.
    """
    repo = _init(campo.raiz / "repo")
    (repo / "a.txt").write_text("a\n")
    _git("-C", str(repo), "add", "a.txt")
    _git("-C", str(repo), "commit", "-qm", "x")
    (repo / "b.txt").write_text("b\n")
    _git("-C", str(repo), "add", "b.txt")
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/nova\n")
    info = repo / ".git" / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "alternates").write_text(
        str(campo.raiz / "store-que-nao-existe" / "objects") + "\n")

    with pytest.raises(Exception) as ei:
        campo.commit(repo)
    assert "degradação silenciosa" in str(ei.value), (
        "o cenário não chegou à recusa que ele existe para exercitar")
    assert "trabalho de terceiro foi perdido" not in str(ei.value), (
        "INCIDENTE FORENSE FALSO: a ref e o reflog eram do NOSSO commit")


# ═══════ .9.12 (P2) — `.git` como symlink era um ORÁCULO do host ════════════

@pytest.mark.parametrize("como", ["regular", "grande", "fifo", "diretorio",
                                   "ausente", "isca-com-gitdir"])
def test_r3_15_symlink_de_git_para_FORA_nao_responde_nada_sobre_o_alvo(
        tmp_path, como):
    """Uma resposta só para as seis sondas — senão a exceção É o oráculo.

    `_ler_ponto_git` é o ÚNICO lugar em que um symlink é deliberadamente
    seguido, e o destino era interrogado ANTES de qualquer conferência de
    escopo. MEDIDO, cada linha uma resposta DIFERENTE sobre caminho arbitrário
    do host: "arquivo .git ilegível" (existe), "não é repositório git"
    (ausente), "FORA das raízes" (diretório), "tem 123457 bytes" (TAMANHO
    exato), "modo 10644"/"modo 20666" (st_mode). E com o alvo começando por
    `gitdir:`, o resto do conteúdo saía DENTRO da mensagem — uma chave privada
    de fora das raízes entrou no processo do supervisor.

    O critério não é "recusou": é a exceção ser INDISTINGUÍVEL entre os seis.
    """
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    real = _init(raiz / "real")

    alvos = {
        "regular": lambda: (fora / "chave").write_text(
            "-----BEGIN OPENSSH PRIVATE KEY-----\nSEGREDO_DO_HOST\n"),
        "grande": lambda: (fora / "chave").write_bytes(b"x" * 123457),
        "fifo": lambda: os.mkfifo(fora / "chave"),
        "diretorio": lambda: (fora / "chave").mkdir(),
        "ausente": lambda: None,
        "isca-com-gitdir": lambda: (fora / "chave").write_text(
            f"gitdir: {real / '.git'} SENHA_DO_HOST=P4SS\n"),
    }
    alvos[como]()

    trab = raiz / "trab"
    trab.mkdir()
    (trab / ".git").symlink_to(fora / "chave")

    with pytest.raises(supervisor.ErroSeguranca) as ei:
        git.conferir_git_dir(str(trab), (str(raiz),))
    msg = str(ei.value)
    assert "é symlink para" in msg and "FORA das raízes" in msg, (
        f"a recusa mudou de forma e volta a distinguir os alvos: {msg[:200]}")
    for vazamento in ("SEGREDO_DO_HOST", "123457", "modo 1", "modo 2",
                      "P4SS", "não é repositório"):
        assert vazamento not in msg, (
            f"a mensagem responde {vazamento!r} sobre um caminho de FORA das "
            "raízes — a exceção é o oráculo")


def test_r3_16_CONTROLE_symlink_de_git_DENTRO_das_raizes_nao_e_barrado_por_aqui(
        tmp_path):
    """A guarda nova é de ESCOPO, não da forma-link.

    Sem este controle ela passaria igual num sistema que recusa todo symlink —
    e a recusa que sobra (titularidade não provável) é outra decisão, tomada em
    outro lugar por outro motivo.
    """
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    real = _init(raiz / "real")
    isca = raiz / "ponteiro"
    isca.write_text(f"gitdir: {real / '.git'}\n")
    trab = raiz / "trab"
    trab.mkdir()
    (trab / ".git").symlink_to(isca)

    with pytest.raises(supervisor.ErroSeguranca) as ei:
        git.conferir_git_dir(str(trab), (str(raiz),))
    assert "é symlink para" not in str(ei.value), (
        "o alvo está DENTRO das raízes; barrar aqui é recusar por forma, não "
        "por escopo")


# ═══ .7.19 (P2) — a limpeza por CAMINHO some quando o repo renomeia o git dir ═

def _add_com_recusa_apos_o_exec(campo, repo, monkeypatch):
    _recusa_apos_o_exec(monkeypatch)
    with pytest.raises(RuntimeError) as ei:
        campo.add(repo, "s.txt")
    return str(ei.value)


def test_r3_17_renomear_o_git_dir_nao_faz_a_quarentena_sobreviver(campo,
                                                                  monkeypatch):
    """MEDIDO 6/6 antes: o blob CRU do arquivo recusado ficava legível.

    `shutil.rmtree(<git_dir>/nomos-quarentena-*)` resolve o CAMINHO na hora de
    apagar. O repositório renomeia `.git` na janela e o caminho deixa de
    existir; `ignore_errors=True` engole a falha e a limpeza vira no-op
    SILENCIOSO. A operação sai RECUSADA, o índice volta certo, `git fsck` fica
    limpo — e `zlib.decompress` do objeto residual devolve o segredo.

    É o mesmo resolve→valida→descarta→resolve-de-novo que `AutoridadeDeRepo`
    fechou para a autoridade, sobrevivendo no DESFAZER. O descritor segue o
    INODE, então renomear deixa de ter efeito.
    """
    import zlib
    repo = _init(campo.raiz / "repo")
    (repo / "s.txt").write_bytes(b"AWS_SECRET_ACCESS_KEY=P19ESEGREDO\n")
    gd, movido = repo / ".git", repo / ".git-movido"

    def explode(self, *a, **k):
        gd.rename(movido)          # o REPOSITÓRIO renomeia o próprio git dir
        raise RuntimeError("recusa pos-exec")
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", explode)

    with pytest.raises(RuntimeError):
        campo.add(repo, "s.txt")

    assert movido.is_dir(), "o cenário não chegou a renomear o git dir"
    residuais = [q for d in (movido, gd) if d.is_dir()
                 for q in d.glob("nomos-quarentena-*")]
    legiveis = [o for q in residuais for o in q.rglob("*") if o.is_file()
                and _tem_segredo(o, zlib)]
    assert not residuais, (
        f"a quarentena sobreviveu à operação: {residuais}")
    assert not legiveis, (
        f"o conteúdo CRU do arquivo recusado ficou legível em {legiveis}")


def _tem_segredo(objeto, zlib) -> bool:
    try:
        return b"P19ESEGREDO" in zlib.decompress(objeto.read_bytes())
    except Exception:                                        # noqa: BLE001
        return False


def test_r3_18_quarentena_que_NAO_pode_ser_apagada_vira_incidente(campo,
                                                                  monkeypatch):
    """Apagar pode falhar; falhar em SILÊNCIO não pode.

    Sem este teste, o conserto acima passaria numa implementação que só trocou
    um `rmtree` silencioso por outro. O canal é a propriedade — o descritor é
    só o mecanismo.
    """
    import shutil as _sh
    repo = _init(campo.raiz / "repo")
    (repo / "s.txt").write_bytes(b"AWS_SECRET_ACCESS_KEY=P19ESEGREDO\n")

    real = _sh.rmtree

    def rmtree_quebra_so_a_limpeza(*a, **k):
        # Só a limpeza FINAL usa `dir_fd`. Sabotar o `rmtree` inteiro quebraria
        # a promoção também, e o erro original deixaria de ser o injetado —
        # o teste passaria medindo outra coisa.
        if "dir_fd" in k:
            raise OSError(1, "Operation not permitted")
        return real(*a, **k)
    monkeypatch.setattr(_sh, "rmtree", rmtree_quebra_so_a_limpeza)
    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar",
                        lambda self, *a, **k: (_ for _ in ()).throw(
                            RuntimeError("recusa pos-exec")))

    with pytest.raises(RuntimeError) as ei:
        campo.add(repo, "s.txt")
    assert "QUARENTENA não pôde ser apagada" in str(ei.value), (
        "a limpeza falhou e a recusa saiu limpa — o store com o conteúdo "
        f"recusado fica em disco sem ninguém saber: {str(ei.value)[:200]}")


def test_r3_19_no_SUCESSO_a_quarentena_residual_tambem_e_recusa(campo,
                                                                monkeypatch):
    """O outro lado da mesma propriedade, que o vetor mediu como `ok=True`.

    Numa variante da janela a capacidade devolveu `ok=True` sem ter promovido
    nada, deixando o índice apontando para blob AUSENTE. Sucesso com store
    paralelo sobrevivendo é a mesma omissão, do lado que ninguém olha.
    """
    import shutil as _sh
    repo = _init(campo.raiz / "repo")
    (repo / "ok.txt").write_text("conteudo\n")

    real = _sh.rmtree
    chamadas = {"n": 0}

    def rmtree_quebra_no_fim(*a, **k):
        # A promoção usa `rmtree` também; só a limpeza FINAL é sabotada.
        chamadas["n"] += 1
        if "dir_fd" in k:
            raise OSError(1, "Operation not permitted")
        return real(*a, **k)
    monkeypatch.setattr(_sh, "rmtree", rmtree_quebra_no_fim)

    with pytest.raises(supervisor.ErroSeguranca, match="QUARENTENA"):
        campo.add(repo, "ok.txt")


# ═══ .1.07 (P2) — um diretório CHAMADO `worktrees` não é uma worktree ligada ══

def test_r3_20_repo_comum_dentro_do_git_dir_alheio_nao_redireciona_o_efeito(
        campo):
    """MEDIDO: `AWS_SECRET_ACCESS_KEY=VAZOU_1_07` no store da VÍTIMA, ok=True.

    A guarda exigia a FORMA `<common>/worktrees/<nome>` para aceitar que
    `commondir` aponte para outro lugar. Um repositório COMUM criado em
    `<vitima>/.git/worktrees` satisfaz a forma — `gd.parent.name` é literalmente
    `worktrees` e `gd.parent.parent` é o git dir da vítima — sem que exista
    worktree ligada nenhuma. Reconhecer NOME de diretório é reconhecer algo que
    o atacante escolhe.

    O Git honra o `commondir` aqui, e isso não muda a decisão: a questão é o
    repositório redirecionar a autoridade de ESCRITA para o vizinho. O
    invariante que fecha sem depender de nome: `git worktree add` e submódulo
    SEMPRE deixam `.git` como ARQUIVO, então `.git` DIRETÓRIO nunca é worktree
    ligada.
    """
    vitima = _init(campo.raiz / "vitima")
    (vitima / "a").write_text("a\n")
    _git("-C", str(vitima), "add", "a")
    _git("-C", str(vitima), "commit", "-qm", "x")
    head0 = _git("-C", str(vitima), "rev-parse", "HEAD").stdout.strip()

    hostil = _init(vitima / ".git" / "worktrees")
    (hostil / ".git" / "commondir").write_text(str(vitima / ".git") + "\n")
    (hostil / "SEGREDO.txt").write_text("AWS_SECRET_ACCESS_KEY=VAZOU_1_07\n")

    objs = vitima / ".git" / "objects"
    antes = {p.name for p in objs.rglob("*") if p.is_file()}

    with pytest.raises(supervisor.ErroSeguranca, match="commondir"):
        campo.add(hostil, "SEGREDO.txt")

    novos = {p.name for p in objs.rglob("*") if p.is_file()} - antes
    assert not novos, f"objetos entraram no store da VÍTIMA: {sorted(novos)}"
    assert _git("-C", str(vitima), "rev-parse", "HEAD").stdout.strip() == head0


@pytest.mark.parametrize("layout", ["worktree-ligada", "principal", "submodulo"])
def test_r3_21_CONTROLE_os_tres_layouts_LEGITIMOS_continuam_aceitos(campo,
                                                                     layout):
    """Sem este controle, o de cima passaria num sistema que recusa `commondir`.

    Os três são os únicos que o Git PRODUZ, e os três têm de continuar
    funcionando — inclusive a worktree ligada, que é o caso em que `common` e
    `git_dir` legitimamente diferem (e é o layout do próprio repositório desta
    missão).
    """
    p = _init(campo.raiz / "principal")
    (p / "a").write_text("a\n")
    _git("-C", str(p), "add", "a")
    _git("-C", str(p), "commit", "-qm", "x")

    if layout == "principal":
        alvo = p
    elif layout == "worktree-ligada":
        alvo = campo.raiz / "ligada"
        r = _git("-C", str(p), "worktree", "add", "-q", str(alvo))
        assert r.returncode == 0, r.stderr
    else:
        sup = _init(campo.raiz / "super")
        r = _git("-C", str(sup), "-c", "protocol.file.allow=always",
                 "submodule", "add", "-q", str(p), "vendor")
        if r.returncode != 0:
            pytest.skip(f"submódulo por file:// bloqueado neste host: "
                        f"{r.stderr[:120]}")
        alvo = sup / "vendor"

    git.conferir_git_dir(str(alvo), (str(campo.raiz),))
