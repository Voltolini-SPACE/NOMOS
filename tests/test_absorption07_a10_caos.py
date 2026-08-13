"""A10 — caos: falha injetada em cada ponto, e o sistema fecha em vez de mentir.

As baterias anteriores injetam falha onde o desenho previu. Caos injeta onde
NÃO se previu: disco cheio no meio da quarentena, `EACCES` no índice, saída do
Git malformada, encoding inválido, dependência que some, processo que pendura.

Cada injeção é conferida contra SETE propriedades, e a última é a que separa
esta bateria de um teste de exceção:

    FAIL_CLOSED             a operação recusa; nunca devolve sucesso parcial
    INDEX_CONSISTENT        o Git ainda LÊ o índice
    OBJECT_STORE_CONSISTENT `git fsck` não acusa objeto quebrado
    SECRET_RESIDUE=0        o segredo não ficou em objeto nenhum
    ORPHAN_PROCESS=0        nada do filtro continua vivo
    AUDIT_STATE_EXPLAINED   ou auditou, ou a falha foi ANTES do ponto de auditoria
    NEXT_OPERATION_SAFE     uma operação NORMAL, depois do caos, funciona e
                            produz o resultado CORRETO

`NEXT_OPERATION_SAFE` é a propriedade cara. Um sistema pode recusar corretamente
e ainda assim ficar num estado do qual não sai — lock órfão, índice bloqueado,
quarentena presa. Recusar bem uma vez e morrer depois não é fail-closed, é
falha adiada.
"""
from __future__ import annotations

import errno
import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.supervisor import ErroSeguranca
from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, ErroInvalido, ErroLimite,
)
from nomos.adapters.git import diretorio_git
from nomos.adapters.supervisor import TipoDeProcesso as TP
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"
SEGREDO = b"hunter2"

# Injecao de caos: o tipo do erro varia (OSError, ErroInvalido, ErroLimite,
# ErroSeguranca); o que a bateria mede e o ESTADO pos-recusa, nao o tipo.
_FALHA_FECHADA = (OSError, ErroInvalido, ErroLimite, ErroSeguranca,
                  RuntimeError, UnicodeError)

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


class Caos:
    def __init__(self, tmp: Path, binario: Path, artefato):
        self.tmp, self.binario, self.artefato = tmp, binario, artefato
        self.repo = tmp / "repo"
        self.repo.mkdir(exist_ok=True)
        subprocess.run([GIT, "-C", str(self.repo), "init", "-q", "-b", "main"],
                       check=True, capture_output=True)
        self.escopo = tmp / "escopo"
        self.escopo.mkdir(exist_ok=True)
        (self.repo / ".gitattributes").write_text("*.txt filter=redator\n")

    def registro(self, *argv, timeout=30.0):
        reg = fg.RegistroDeFiltros()
        reg.registrar("redator", fg.PoliticaDeFiltro(
            filter_id="redator", canonical_executable=str(self.binario),
            managed_artifact=self.artefato, argv_policy=tuple(argv),
            read_roots=(str(self.repo), str(self.escopo)),
            write_roots=(str(self.escopo),), timeout=timeout))
        return reg

    def ctx(self, cap="git-add"):
        rc = RegistroCapacidades(policy=PolicyEngine(self.tmp / "pol.json"),
                                 approver=lambda *a, **k: True)
        registrar_git_tree(rc, raizes=(str(self.tmp),))
        return CapabilityContext.de_registro(rc, cap, "runtime-governado",
                                             raizes=(str(self.tmp),))

    def add(self, nome, registro=None):
        return git_tree.GitTreeAdapter(registro=registro).executar(
            CapabilityRequest(capacidade="git-add", alvo=str(self.repo),
                              argumentos={"caminhos": [nome]}), self.ctx())

    # ------------------------------------------------------------ invariantes
    def indice_legivel(self) -> bool:
        return subprocess.run([GIT, "-C", str(self.repo), "ls-files", "-s"],
                              capture_output=True).returncode == 0

    def store_consistente(self) -> bool:
        r = subprocess.run([GIT, "-C", str(self.repo), "fsck", "--no-progress",
                            "--connectivity-only"], capture_output=True)
        return r.returncode == 0

    def objetos_com_segredo(self) -> int:
        r = subprocess.run([GIT, "-C", str(self.repo), "cat-file",
                            "--batch-all-objects", "--batch"],
                           capture_output=True)
        return r.stdout.count(SEGREDO)

    def quarentenas(self):
        return list(Path(diretorio_git(self.repo)[0]).glob("nomos-quarentena-*"))

    def orfaos(self):
        r = subprocess.run(["/bin/ps", "-Ao", "command"], capture_output=True,
                           text=True)
        return [ln for ln in r.stdout.splitlines() if "nomos-sb-" in ln]

    def proxima_operacao_segura(self) -> None:
        """A prova de que o sistema SAIU do caos, e não só reagiu a ele."""
        alvo = self.repo / "depois-do-caos.txt"
        alvo.write_text("SENHA=hunter2\napos o caos\n")
        r = self.add("depois-do-caos.txt", registro=self.registro())
        assert r.efeito_aplicado, "NEXT_OPERATION_SAFE=FALSE: não aplicou"
        sha = subprocess.run(
            [GIT, "-C", str(self.repo), "ls-files", "-s", "--",
             "depois-do-caos.txt"], capture_output=True, text=True).stdout.split()
        assert sha, "NEXT_OPERATION_SAFE=FALSE: nada estagiado"
        corpo = subprocess.run([GIT, "-C", str(self.repo), "cat-file", "-p",
                                sha[1]], capture_output=True).stdout
        assert corpo == b"SENHA=REDIGIDO\napos o caos\n", (
            f"NEXT_OPERATION_SAFE=FALSE: conteúdo errado {corpo!r}")

    def refs_consistentes(self) -> bool:
        """`HEAD` resolve e o objeto que ele nomeia EXISTE.

        Acrescentado depois de `.11.06`: um commit recusado avançava
        `refs/heads/<b>` e escrevia o reflog ANTES da recusa, enquanto os
        objetos iam para a quarentena que o `finally` destrói — sobrava `HEAD`
        apontando para objeto INEXISTENTE. `git fsck` sozinho não pegava, e a
        bateria não tinha esta propriedade: passava com o repositório inutilizável.
        """
        r = subprocess.run([GIT, "-C", str(self.repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return True          # repo sem commit ainda: não há ref a conferir
        sha = r.stdout.strip()
        return subprocess.run([GIT, "-C", str(self.repo), "cat-file", "-e", sha],
                              capture_output=True).returncode == 0

    def conferir_tudo(self, antes: bytes | None) -> None:
        assert self.indice_legivel(), "INDEX_CONSISTENT=FALSE"
        assert self.refs_consistentes(), "REFS_CONSISTENT=FALSE"
        assert self.store_consistente(), "OBJECT_STORE_CONSISTENT=FALSE"
        assert self.objetos_com_segredo() == 0, "SECRET_RESIDUE"
        assert self.quarentenas() == [], "quarentena sobreviveu"
        assert self.orfaos() == [], "ORPHAN_PROCESS"
        alvo = Path(diretorio_git(self.repo)[0]) / "index"
        agora = alvo.read_bytes() if alvo.exists() else None
        assert agora == antes, "o índice mudou numa operação que falhou"
        self.proxima_operacao_segura()


@pytest.fixture
def caos(tmp_path):
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)
    return Caos(tmp_path, binario, art)


def _indice(c: Caos):
    alvo = Path(diretorio_git(c.repo)[0]) / "index"
    return alvo.read_bytes() if alvo.exists() else None


# ═════════════ sinais e saídas de controle ══════════════════════════════════

@pytest.mark.parametrize("excecao", [
    KeyboardInterrupt, SystemExit, RuntimeError, MemoryError,
])
def test_a10_01_excecao_de_controle_no_filtro(caos, monkeypatch, excecao):
    """Inclui `SystemExit` e `MemoryError` de propósito: os dois NÃO são
    `Exception`, e um `except Exception` os deixaria passar por cima da
    transação sem desfazer nada."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)
    original = supervisor.executar

    def executar(argv, **kw):
        if kw.get("tipo") is TP.FILTRO_GOVERNADO:
            raise excecao("caos injetado")
        return original(argv, **kw)

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(excecao):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.setattr(supervisor, "executar", original)
    caos.conferir_tudo(antes)


# ═════════════ erros de I/O ═════════════════════════════════════════════════

@pytest.mark.parametrize("numero,rotulo", [
    (errno.ENOSPC, "disco cheio"),
    (errno.EACCES, "permissão negada"),
    (errno.EPIPE, "pipe quebrado"),
    (errno.EIO, "erro de I/O"),
    (errno.EDQUOT if hasattr(errno, "EDQUOT") else errno.ENOSPC, "cota"),
])
def test_a10_02_erro_de_io_na_promocao(caos, monkeypatch, numero, rotulo):
    """`os.replace` da promoção falha: o ponto de commit não completa."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)
    real = os.replace

    def replace(a, b, *args, **kw):
        # C8 mudou a promoção: copia para um temporário no diretório DESTINO e
        # só então `os.replace`. O caminho de ORIGEM deixou de conter
        # "nomos-quarentena-", então a injeção antiga não alcançava mais nada —
        # e "não levantou" seria passe VÁCUO, não contenção.
        if "/objects/" in str(b) or "nomos-quarentena-" in str(a):
            raise OSError(numero, rotulo)
        return real(a, b, *args, **kw)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(OSError):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.setattr(os, "replace", real)
    caos.conferir_tudo(antes)


def test_a10_03_leitura_curta_do_conteudo(caos, monkeypatch):
    """O arquivo some ENTRE o pedido e a leitura do conteúdo."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)
    # A leitura do conteúdo governado deixou de ser `Path.read_bytes`: virou
    # `openat` componente a componente + `os.read`, na correção do symlink de
    # DIRETÓRIO. Injetar no método antigo não toca mais o caminho medido, e
    # "não levantou" seria passe VÁCUO em vez de contenção.
    real = git_tree._abrir_sem_atravessar_link

    def sumir(repo, caminho):
        if caminho.endswith("x.txt"):
            raise OSError(errno.ENOENT, "sumiu")
        return real(repo, caminho)

    monkeypatch.setattr(git_tree, "_abrir_sem_atravessar_link", sumir)
    with pytest.raises(_FALHA_FECHADA):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.setattr(git_tree, "_abrir_sem_atravessar_link", real)
    caos.conferir_tudo(antes)


# ═════════════ índice corrompido e ausente ══════════════════════════════════

def test_a10_04_indice_CORROMPIDO_antes_da_operacao(caos):
    """Índice com lixo: a operação recusa e o índice continua o mesmo lixo.

    Não é papel do `add` consertar índice corrompido — é papel dele NÃO piorar
    e não fingir sucesso. O `conferir_tudo` completo não se aplica: o índice já
    estava ilegível ANTES.
    """
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    caos.add("x.txt", registro=caos.registro())          # cria índice válido
    alvo = Path(diretorio_git(caos.repo)[0]) / "index"
    alvo.write_bytes(b"LIXO QUE NAO E INDICE\n")
    antes = alvo.read_bytes()

    (caos.repo / "y.txt").write_text("SENHA=hunter2\n")
    with pytest.raises(_FALHA_FECHADA):
        caos.add("y.txt", registro=caos.registro())
    assert alvo.read_bytes() == antes, "piorou um índice já corrompido"
    assert caos.objetos_com_segredo() == 0, "SECRET_RESIDUE"
    assert caos.quarentenas() == [], "quarentena sobreviveu"
    assert caos.orfaos() == [], "ORPHAN_PROCESS"


def test_a10_05_indice_AUSENTE_e_recriado_corretamente(caos):
    """Sem índice, `add` cria um. E o rollback tem de saber APAGAR de novo."""
    alvo = Path(diretorio_git(caos.repo)[0]) / "index"
    alvo.unlink(missing_ok=True)
    assert not alvo.exists()
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    caos.add("x.txt", registro=caos.registro())
    assert alvo.exists(), "não criou índice"

    alvo.unlink()
    (caos.repo / "y.txt").write_text("SENHA=hunter2\n")
    with pytest.raises(_FALHA_FECHADA):
        git_tree.GitTreeAdapter(registro=fg.RegistroDeFiltros()).executar(
            CapabilityRequest(capacidade="git-add", alvo=str(caos.repo),
                              argumentos={"caminhos": ["y.txt"]}), caos.ctx())
    assert not alvo.exists(), (
        "o rollback recriou um índice que NÃO existia no instantâneo")
    caos.proxima_operacao_segura()


# ═════════════ falhas de subsistema ═════════════════════════════════════════

def test_a10_06_falha_do_registry(caos, monkeypatch):
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)

    def explodir(self, fid):
        raise RuntimeError("registry indisponível")

    monkeypatch.setattr(fg.RegistroDeFiltros, "resolver", explodir)
    with pytest.raises(RuntimeError):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.undo()
    caos.conferir_tudo(antes)


def test_a10_07_artefato_gerenciado_SOME_do_disco(caos):
    """O binário aprovado é apagado entre a aprovação e o uso."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    reg = caos.registro()
    antes = _indice(caos)
    alvo = Path(caos.artefato.managed_path)
    guardado = alvo.read_bytes()
    alvo.chmod(0o700)
    alvo.unlink()
    try:
        with pytest.raises(fg.ErroFiltro, match="ilegível|DIVERGE"):
            caos.add("x.txt", registro=reg)
    finally:
        alvo.write_bytes(guardado)
        alvo.chmod(0o500)
    caos.conferir_tudo(antes)


def test_a10_08_sandbox_AUSENTE_recusa_em_vez_de_rodar_solto(caos, monkeypatch):
    """Sem `sandbox-exec` a capacidade fica INDISPONÍVEL. É o lado certo do
    erro: a alternativa é rodar código de repositório com a autoridade do
    usuário."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)
    # `binario_sandbox: str = SANDBOX` é avaliado na DEFINIÇÃO da função, então
    # reatribuir `supervisor.SANDBOX` não alcança nada — a injeção antiga não
    # media a propriedade que o nome do teste promete. Trocar o default é o
    # ponto que o processo realmente consulta.
    real_exec = supervisor.executar
    ausente = str(caos.tmp / "nao-existe")

    def sem_sandbox(*a, **kw):
        kw["binario_sandbox"] = ausente
        return real_exec(*a, **kw)

    monkeypatch.setattr(supervisor, "executar", sem_sandbox)
    monkeypatch.setattr(git_tree.supervisor, "executar", sem_sandbox)
    with pytest.raises(_FALHA_FECHADA):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.undo()
    caos.conferir_tudo(antes)


def test_a10_09_falha_da_auditoria(caos, monkeypatch):
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)

    def explodir(self, *a, **k):
        raise RuntimeError("auditoria indisponível")

    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", explodir)
    with pytest.raises(RuntimeError):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.undo()
    caos.conferir_tudo(antes)


def test_a10_10_falha_ao_ABRIR_a_quarentena(caos, monkeypatch):
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)

    def explodir(repo, autoridade=None):
        raise OSError(errno.ENOSPC, "sem espaço para quarentena")

    monkeypatch.setattr(git_tree, "_abrir_quarentena", explodir)
    with pytest.raises(OSError):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.undo()
    caos.conferir_tudo(antes)


# ═════════════ processos pendurados ═════════════════════════════════════════

@pytest.mark.parametrize("sonda,args", [
    ("pai", ("--sonda-dorme", "60")),
    ("filho", ("--sonda-forks", "2", "60")),
    ("neto", ("--sonda-neto", "60")),
])
def test_a10_11_processo_pendurado_em_cada_geracao(caos, sonda, args):
    """O filtro pendura; o prazo fecha; a próxima operação continua sadia."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)
    argv = args + ((str(caos.escopo),) if sonda != "pai" else ())
    with pytest.raises(Exception, match="prazo|excedeu"):
        caos.add("x.txt", registro=caos.registro(*argv, timeout=2.0))
    caos.conferir_tudo(antes)


# ═════════════ saída malformada do Git ══════════════════════════════════════

def test_a10_12_hash_object_devolve_LIXO(caos, monkeypatch):
    """Um sha que não é sha nunca pode virar entrada de índice."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)
    original = supervisor.executar

    def executar(argv, **kw):
        p = original(argv, **kw)
        if any("hash-object" in a for a in argv):
            from dataclasses import replace
            return replace(p, stdout=b"nao-e-um-sha; rm -rf /\n")
        return p

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(Exception, match="não é um sha"):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.setattr(supervisor, "executar", original)
    caos.conferir_tudo(antes)


def test_a10_13_git_com_rc0_MENTIROSO_no_estagiamento(caos, monkeypatch):
    """rc=0 com `error:` no stderr é recusa — a mentira para em `conferir_saida`."""
    (caos.repo / "x.txt").write_text("SENHA=hunter2\n")
    antes = _indice(caos)
    original = supervisor.executar

    def executar(argv, **kw):
        p = original(argv, **kw)
        if any("update-index" in a for a in argv):
            from dataclasses import replace
            return replace(p, returncode=0, stderr=b"error: nao consegui\n")
        return p

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(supervisor.ErroSeguranca):
        caos.add("x.txt", registro=caos.registro())
    monkeypatch.setattr(supervisor, "executar", original)
    caos.conferir_tudo(antes)


def test_a10_14_saida_do_filtro_com_encoding_INVALIDO(caos):
    """Bytes que não são UTF-8 têm de atravessar sem quebrar nem ser reescritos.

    Um `.decode()` esquecido no caminho transformaria conteúdo binário legítimo
    em exceção — ou pior, em conteúdo alterado.
    """
    # SEM byte NUL: MEDIDO que o próprio `redator.c` (fgets) trunca ali, então
    # a asserção original cobrava da SONDA uma propriedade que ela não entrega —
    # o defeito era do arnês, não do caminho governado. O que este teste mede
    # continua sendo o que importa: bytes não-UTF-8 atravessam intactos e não
    # viram exceção nem conteúdo reescrito.
    bruto = b"\xff\xfeSENHA=hunter2\n\x80\x81"
    (caos.repo / "bin.txt").write_bytes(bruto)
    r = caos.add("bin.txt", registro=caos.registro())
    assert r.efeito_aplicado
    sha = subprocess.run([GIT, "-C", str(caos.repo), "ls-files", "-s", "--",
                          "bin.txt"], capture_output=True, text=True).stdout.split()
    corpo = subprocess.run([GIT, "-C", str(caos.repo), "cat-file", "-p", sha[1]],
                           capture_output=True).stdout
    assert corpo == b"\xff\xfeSENHA=REDIGIDO\n\x80\x81"
    assert caos.objetos_com_segredo() == 0


def test_a10_15_stderr_ENORME_nao_derruba_nem_vaza_para_stdout(caos):
    """Ruído em stderr não pode virar conteúdo indexado nem travar o supervisor."""
    pol = fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(caos.binario),
        managed_artifact=caos.artefato,
        argv_policy=("--sonda-env", "PATH"),
        read_roots=(str(caos.repo),), write_roots=(str(caos.escopo),))
    p = supervisor.executar(pol.comando(), cwd=caos.tmp, env=pol.ambiente(),
                            prazo=20.0, confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO, entrada=b"SENHA=x\n")
    assert b"SENHA=x" not in p.stderr, "a entrada vazou para o stderr"
    assert caos.orfaos() == [], "ORPHAN_PROCESS"
