"""A2-REPO.8 — o ÍNDICE não é escolhido pelo repositório.

Dois vetores medidos, ambos no processo do SUPERVISOR — fora do sandbox, onde
todo o confinamento de A5.5 é irrelevante porque quem age é o pai.

    .git/index como SYMLINK    o instantâneo LÊ o destino escolhido pelo repo
    rollback sem index.lock    apaga `git add` concorrente que saiu com rc=0

## Por que "a operação falhou depois" não salvava o primeiro

Confidencialidade não precisa de escrita. Com
`.git/index -> /fora/das/raízes/chave.pem`, o `read_bytes()` do instantâneo
trazia a chave privada do host para dentro do processo do NOMOS; o `add` falhava
adiante, e o vazamento já tinha acontecido. Junto vinha uma mutação silenciosa:
`_restaurar_indice` faz `os.replace` sobre o caminho, então o LINK do
repositório era substituído por arquivo regular — num repositório cuja operação
foi RECUSADA.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import CapabilityContext, CapabilityRequest
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


def _git(*args):
    return subprocess.run([GIT, *args], capture_output=True, text=True)


@pytest.fixture
def campo(tmp_path):
    raiz = tmp_path / "raizes"
    raiz.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    repo = raiz / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", str(repo))
    _git("-C", str(repo), "config", "user.email", "a@b.c")
    _git("-C", str(repo), "config", "user.name", "T")
    (repo / "a.txt").write_text("conteudo\n")

    class Campo:
        def __init__(self):
            self.raiz, self.fora, self.repo, self.tmp = raiz, fora, repo, tmp_path

        def add(self, *caminhos):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(raiz),))
            ctx = CapabilityContext.de_registro(rc, "git-add",
                                                "runtime-governado",
                                                raizes=(str(raiz),))
            return git_tree.GitTreeAdapter().executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}), ctx)

    return Campo()


def test_a8_00_CONTROLE_add_normal_continua_funcionando(campo):
    """Sem isto, os testes de recusa passariam com `git add` morto."""
    r = campo.add("a.txt")
    assert r.efeito_aplicado
    assert "a.txt" in _git("-C", str(campo.repo), "ls-files").stdout


def test_a8_01_index_como_SYMLINK_nao_e_lido_pelo_supervisor(campo):
    """Confidencialidade não precisa de escrita para ser violada."""
    vitima = campo.fora / "chave_do_host.pem"
    vitima.write_text("-----BEGIN PRIVATE KEY-----\nSEGREDO\n")
    idx = campo.repo / ".git" / "index"
    if idx.exists():
        idx.unlink()
    os.symlink(str(vitima), str(idx))
    antes = vitima.read_text()

    with pytest.raises(supervisor.ErroSeguranca, match="symlink"):
        campo.add("a.txt")

    assert vitima.read_text() == antes, "a vítima foi sobrescrita"
    assert idx.is_symlink(), (
        "o rollback trocou o LINK do repositório por arquivo regular numa "
        "operação que foi RECUSADA — mutação silenciosa")


def test_a8_02_index_FIFO_nao_pendura_o_supervisor(campo):
    """Mesmo ponto do FIFO no caminho governado: o `read` roda no pai."""
    idx = campo.repo / ".git" / "index"
    if idx.exists():
        idx.unlink()
    os.mkfifo(idx)
    import signal

    def estourou(*_):
        raise AssertionError("PENDUROU: o instantâneo bloqueou no FIFO")

    anterior = signal.signal(signal.SIGALRM, estourou)
    signal.alarm(20)
    try:
        with pytest.raises(supervisor.ErroSeguranca, match="arquivo regular"):
            campo.add("a.txt")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, anterior)


def test_a8_03_rollback_DETECTA_escritor_concorrente(campo):
    """A perda de trabalho concorrente não pode ser SILENCIOSA.

    Registro de uma correção TENTADA e REFUTADA: tomar `index.lock` no desfazer
    parecia a defesa óbvia — é o protocolo que um `git add` concorrente
    respeita. MEDIDO sob A9: colide com o uso que o próprio Git faz do arquivo,
    e o `update-index` da operação SEGUINTE passou a morrer com
    `Unable to create index.lock: File exists`. Defesa que cria falha nova sem
    resolver a propriedade sai.

    O que resolve é a DETECÇÃO: se o índice mudou entre o instantâneo e o
    desfazer, o incidente sobe anexado ao erro.
    """
    # COMPORTAMENTAL, não grep. MEDIDO (`.11.11`): a versão anterior procurava
    # o identificador `_TERCEIRO_DETECTADO` no corpo da função — e passava
    # porque o nome aparecia no PRÓPRIO COMENTÁRIO que explicava tê-lo
    # removido. Teste que mede o texto do código, e não o que ele faz, protege
    # a área com sinal falso.
    repo = campo.repo
    _git("-C", str(repo), "add", "a.txt")
    inst = git_tree._instantaneo_do_indice(repo)

    # Um terceiro escreve o índice depois do instantâneo.
    (repo / "de_outro.txt").write_text("trabalho alheio\n")
    _git("-C", str(repo), "add", "de_outro.txt")

    detectou = git_tree._restaurar_indice(inst)
    assert detectou is True, (
        "o desfazer não detectou o escritor concorrente — a perda de trabalho "
        "de terceiro volta a ser silenciosa")

    # E o CONTROLE: sem terceiro, não pode acusar (`.11.09`).
    inst2 = git_tree._instantaneo_do_indice(repo)
    assert git_tree._restaurar_indice(inst2) is False, (
        "acusou terceiro sem terceiro — falso positivo destrói o sinal")


def test_a8_04_rollback_nao_pendura_se_o_lock_esta_preso(campo):
    """O lock é BEST-EFFORT, e tem de ser.

    Um rollback que espera para sempre é PIOR que um rollback sem lock: deixa o
    índice sujo, com o conteúdo que a operação recusou já estagiado.
    """
    lock = campo.repo / ".git" / "index.lock"
    lock.write_text("preso por outro processo\n")
    inicio = time.monotonic()
    try:
        inst = git_tree._instantaneo_do_indice(campo.repo)
        git_tree._restaurar_indice(inst)
    finally:
        lock.unlink(missing_ok=True)
    assert time.monotonic() - inicio < 10, "o rollback pendurou esperando o lock"


def test_a8_05_add_concorrente_com_rc0_nao_e_apagado_pelo_rollback(campo):
    """A propriedade que o lock existe para garantir, medida de ponta a ponta."""
    _git("-C", str(campo.repo), "add", "a.txt")
    (campo.repo / "concorrente.txt").write_text("trabalho de outro\n")

    resultado = {}

    def concorrente():
        time.sleep(0.05)
        r = _git("-C", str(campo.repo), "add", "concorrente.txt")
        resultado["rc"] = r.returncode

    (campo.repo / "b.txt").write_text("x\n")
    t = threading.Thread(target=concorrente, daemon=True)
    t.start()
    # A operação pode falhar por causa da corrida; isso não é o critério.
    # O critério é o trabalho do concorrente sobreviver.
    with contextlib.suppress(Exception):
        campo.add("b.txt")
    t.join(timeout=10)

    if resultado.get("rc") == 0:
        assert "concorrente.txt" in _git("-C", str(campo.repo),
                                         "ls-files").stdout, (
            "o rollback apagou um `git add` concorrente que saiu com rc=0")


# ═══════════════ .8.01 / .8.03 / .8.06 — o resto do bolsão ═══════════════════

def _com_filtro_desconhecido(campo, nome="zz.txt"):
    """Gatilho de recusa que exercita o caminho de DESFAZER inteiro."""
    from nomos.adapters import filtro_governado as fg
    (campo.repo / nome).write_text("x\n")
    (campo.repo / ".gitattributes").write_text(f"{nome} filter=NAOEXISTE\n")
    rc = RegistroCapacidades(policy=PolicyEngine(campo.tmp / "p8.json"),
                             approver=lambda *a, **k: True)
    registrar_git_tree(rc, raizes=(str(campo.raiz),))
    ctx = CapabilityContext.de_registro(rc, "git-add", "runtime-governado",
                                        raizes=(str(campo.raiz),))
    return git_tree.GitTreeAdapter(registro=fg.RegistroDeFiltros()).executar(
        CapabilityRequest(capacidade="git-add", alvo=str(campo.repo),
                          argumentos={"caminhos": [nome]}), ctx)


def test_a8_06_split_index_operacao_recusada_deixa_o_repo_UTILIZAVEL(campo):
    """O estado do índice mora em DOIS arquivos quando o repo liga split index.

    `core.splitIndex` e `splitIndex.sharedIndexExpire` são config do
    REPOSITÓRIO. O Git apaga o `sharedindex` durante a operação, e o rollback
    devolvia um `.git/index` apontando para arquivo inexistente — `ls-files`,
    `status` e `commit` saindo rc=128 num repositório cuja operação foi
    RECUSADA, levando junto o trabalho legítimo já estagiado.
    """
    for k, v in (("core.splitIndex", "true"),
                 ("splitIndex.sharedIndexExpire", "now"),
                 ("splitIndex.maxPercentChange", "0")):
        _git("-C", str(campo.repo), "config", k, v)
    _git("-C", str(campo.repo), "add", "a.txt")

    with pytest.raises(Exception):                       # noqa: B017
        _com_filtro_desconhecido(campo)

    assert _git("-C", str(campo.repo), "ls-files").returncode == 0, (
        "`git ls-files` parou de funcionar depois de uma operação RECUSADA")
    assert _git("-C", str(campo.repo), "status", "--porcelain").returncode == 0
    assert "a.txt" in _git("-C", str(campo.repo), "ls-files").stdout, (
        "o trabalho legítimo que já estava estagiado foi perdido")


def test_a8_07_falha_no_DESFAZER_nao_mascara_o_ErroSeguranca(campo):
    """Mascarar a recusa é pior que a falha do rollback.

    MEDIDO: com o temporário do rollback inutilizável, o `IsADirectoryError`
    subia NO LUGAR do `ErroSeguranca` — `isinstance(e, ErroSeguranca)` virava
    False, e qualquer chamador que classifique incidente de segurança por tipo
    deixava de ver o incidente, que ficava só em `__context__`.
    """
    # O índice tem de EXISTIR: sem ele o desfazer é um `unlink` e não há
    # gravação a falhar — o teste passaria por não medir nada.
    _git("-C", str(campo.repo), "add", "a.txt")

    # A injeção é por monkeypatch, e NÃO por armadilha de nome. Pré-criar
    # `.index.nomos-rollback-<pid>` era o gatilho original — e deixou de
    # funcionar quando `_gravar_atomico` passou a usar `mkstemp` (correção de
    # `.8.NEW-ROLLBACK-TMPNAME`: o repositório não escolhe o nome do
    # temporário). O gatilho velho virou prova do conserto, não do defeito;
    # a propriedade medida aqui continua sendo "a falha do desfazer não
    # mascara o erro original".
    import nomos.adapters.git_tree as gt
    real = gt._gravar_atomico

    def explodir(alvo, dados, modo=None):
        if alvo.name == "index":
            raise OSError(13, "permissão negada no desfazer")
        return real(alvo, dados, modo)

    from nomos.adapters import filtro_governado as fg
    gt._gravar_atomico = explodir
    try:
        with pytest.raises(fg.ErroFiltro) as exc:
            _com_filtro_desconhecido(campo)
    finally:
        gt._gravar_atomico = real

    # O TIPO do erro original é preservado. A primeira versão desta correção
    # levantava `ErroSeguranca` sempre — consertava o mascaramento medido e
    # criava o MESMO defeito na direção oposta: quem classifica por
    # `except ErroFiltro` (ou `RuntimeError`) deixava de ver o erro real. A
    # bateria A9 pegou. Trocar o tipo é mascarar, mesmo mantendo o texto.
    assert "INCIDENTE NO DESFAZER" in str(exc.value), (
        "a falha do desfazer não foi reportada — some em silêncio")


def test_a8_08_escritor_concorrente_nao_tem_o_trabalho_destruido(campo):
    """O `git add` de terceiro que sai rc=0 não pode sumir sem sinal.

    MEDIDO 5/5 antes: o concorrente saía rc=0, era visto no índice, e o rollback
    restaurava os bytes antigos APAGANDO o trabalho aceito — o chamador só via o
    erro sobre o próprio caminho, e nada indicava a perda.
    """
    (campo.repo / "concorrente.txt").write_text("trabalho de outro\n")
    resultado = {}

    def concorrente():
        time.sleep(0.08)
        resultado["rc"] = _git("-C", str(campo.repo),
                               "add", "concorrente.txt").returncode

    t = threading.Thread(target=concorrente, daemon=True)
    t.start()
    erro = ""
    try:
        _com_filtro_desconhecido(campo)
    except Exception as e:                               # noqa: BLE001
        erro = str(e)
    t.join(timeout=15)

    if resultado.get("rc") != 0:
        pytest.skip("o concorrente não chegou a ser aceito nesta execução")
    sobreviveu = "concorrente.txt" in _git("-C", str(campo.repo),
                                           "ls-files").stdout
    assert sobreviveu or "OUTRO processo" in erro, (
        "o trabalho do concorrente foi destruído E o incidente não foi "
        "reportado — perda de dado silenciosa")


def test_a8_09_sharedindex_como_SYMLINK_nao_e_lido_pelo_supervisor(campo):
    """`.8.NEW`: a assimetria entre os três instantâneos era o furo.

    `_instantaneo_do_indice` (index) e `_instantaneo_das_refs` (HEAD/refs)
    faziam `lstat` e recusavam symlink ANTES de ler. `_instantaneo_do_split`
    lia `sharedindex.<sha>` com `read_bytes()` cru — e esse nome é controlado
    pelo repositório. Plantado como symlink para um segredo do host, a leitura,
    que roda no processo do supervisor FORA do sandbox, trazia o conteúdo para
    dentro do NOMOS. Confidencialidade não precisa de escrita — mesmo padrão
    que `test_a8_01` mede sobre o índice.
    """
    vitima = campo.fora / "chave_do_host.pem"
    vitima.write_text("-----BEGIN PRIVATE KEY-----\nSEGREDO\n")
    link = campo.repo / ".git" / "sharedindex.deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    os.symlink(str(vitima), str(link))

    from nomos.adapters.git import autoridade_de, conferir_git_dir
    gd, comum = conferir_git_dir(campo.repo, (str(campo.raiz),))
    aut = autoridade_de(campo.repo, gd, comum)

    with pytest.raises(supervisor.ErroSeguranca, match="arquivo regular"):
        git_tree._instantaneo_do_split(aut)
    assert vitima.read_text().startswith("-----BEGIN"), "a vítima foi tocada"


def test_a8_10_CONTROLE_sharedindex_regular_e_capturado(campo):
    """Sem isto, o teste acima passaria com o snapshot do split QUEBRADO."""
    from nomos.adapters.git import autoridade_de, conferir_git_dir
    (campo.repo / ".git" / "sharedindex.abc123").write_bytes(b"DIRC-conteudo")
    gd, comum = conferir_git_dir(campo.repo, (str(campo.raiz),))
    aut = autoridade_de(campo.repo, gd, comum)
    estado = git_tree._instantaneo_do_split(aut)
    assert any(b"DIRC-conteudo" in v for v in estado.values()), (
        "o snapshot do split parou de capturar sharedindex legítimo")


def test_a8_11_o_temporario_do_desfazer_NAO_e_escolhivel_pelo_repositorio(campo):
    """`.8.NEW-ROLLBACK-TMPNAME`: nome previsível é gatilho estático.

    Os três restauradores usavam `.<nome>.nomos-*-<pid>` dentro de diretórios
    que o REPOSITÓRIO controla. Pré-criar esse caminho como DIRETÓRIO derrubava
    o desfazer, e o índice ficava com o conteúdo RECUSADO estagiado. Não é
    corrida — é conteúdo estático, sem oráculo: basta saber o formato do nome.

    O contraste estava no mesmo arquivo: `_promover_quarentena` já usava
    `mkstemp`. Este teste prende a simetria.
    """
    fonte = Path(git_tree.__file__).read_text("utf-8")
    corpo = fonte.split("def _gravar_atomico", 1)[1].split("\ndef ", 1)[0]
    assert "mkstemp" in corpo, (
        "o temporário do desfazer voltou a ter nome derivável — o repositório "
        "pode pré-criá-lo como diretório e derrubar o rollback")
    for previsivel in (".index.nomos-rollback-", ".nomos-refs-"):
        assert previsivel not in fonte, (
            f"nome previsível {previsivel!r} voltou ao caminho de desfazer")
