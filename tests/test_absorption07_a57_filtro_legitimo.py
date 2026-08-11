"""A5.7 — o filtro governado LEGÍTIMO, ponta a ponta, dentro do `git add`.

A5 fechou o caminho padrão e a negação é definitiva: um `filter.<driver>.clean`
declarado no `.git/config` do repositório não executa mais. Mas o caso legítimo
existe — redator de segredo, normalizador, LFS — e um sistema que só sabe negar
não substitui o que ele proibiu.

Aqui as duas coisas passam a valer ao mesmo tempo, e é essa simultaneidade que
esta bateria mede:

    git add + filtro declarado PELO REPOSITÓRIO     -> DENY
    git add + filtro governado com id APROVADO      -> ALLOW, e transforma
    git add + filtro governado com id DESCONHECIDO  -> DENY

A transformação de referência é a mesma que a missão especifica:

    SENHA=hunter2   ->   SENHA=REDIGIDO

## Quem aplica o filtro, e por que isso não é detalhe

Quem aplica é o NOMOS, não o Git. Se o Git aplicasse, o binário do filtro
precisaria entrar na allowlist de exec DO PROCESSO DO GIT — e a partir daí quem
escolhe o que roda volta a ser a config do repositório, que é exatamente a
autoridade que A5 tirou dele. Aplicando aqui, a máquina de filtros do Git
continua desligada (`--no-filters` explícito) e o conteúdo transformado entra
no índice por `update-index --cacheinfo`.

## O controle positivo desta bateria

O segredo tem de estar EM CLARO no arquivo antes, e AUSENTE do objeto depois.
Verificar só a presença de "REDIGIDO" aceitaria um filtro que concatenasse a
redação ao segredo original — e o objetivo é o segredo não existir no store.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, ErroInvalido,
)
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([GIT, "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture
def cenario(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([GIT, "-C", str(repo), "init", "-q", "-b", "main"],
                   check=True, capture_output=True)
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)

    class Cen:
        def __init__(self):
            self.repo = repo
            self.tmp = tmp_path
            self.artefato = art
            self.binario = binario

        def politica(self, fid="redator") -> fg.PoliticaDeFiltro:
            return fg.PoliticaDeFiltro(
                filter_id=fid, canonical_executable=str(binario),
                managed_artifact=art, read_roots=(str(repo),),
                write_roots=(str(repo),))

        def registro(self, *ids) -> fg.RegistroDeFiltros:
            reg = fg.RegistroDeFiltros()
            for fid in ids:
                reg.registrar(fid, self.politica(fid))
            return reg

        def adapter(self, registro=None) -> git_tree.GitTreeAdapter:
            return git_tree.GitTreeAdapter(registro=registro)

        def ctx(self, capacidade="git-add") -> CapabilityContext:
            reg = RegistroCapacidades(
                policy=PolicyEngine(tmp_path / "pol.json"),
                approver=lambda *a, **k: True)
            registrar_git_tree(reg, raizes=(str(tmp_path),))
            return CapabilityContext.de_registro(
                reg, capacidade, "runtime-governado",
                raizes=(str(tmp_path),))

        def add(self, adapter, *caminhos):
            pedido = CapabilityRequest(
                capacidade="git-add", alvo=str(repo),
                argumentos={"caminhos": list(caminhos)})
            return adapter.executar(pedido, self.ctx("git-add"))

        def escrever(self, nome: str, corpo: str) -> Path:
            p = repo / nome
            p.write_text(corpo)
            return p

        def atributos(self, corpo: str) -> None:
            (repo / ".gitattributes").write_text(corpo)

        def conteudo_no_indice(self, nome: str) -> bytes:
            sha = _git(self.repo, "ls-files", "-s", "--", nome).stdout.split()
            assert sha, f"{nome} não está no índice"
            return subprocess.run([GIT, "-C", str(self.repo), "cat-file",
                                   "-p", sha[1]],
                                  capture_output=True).stdout

        def segredo_em_algum_objeto(self, segredo: bytes) -> bool:
            """Varre TODO objeto do store, não só o do caminho.

            Em BYTES, nunca em texto: `--batch` despeja o conteúdo cru dos
            objetos, e um blob binário faz `text=True` estourar
            `UnicodeDecodeError` — a varredura morreria antes de olhar o objeto
            que interessa, e o teste passaria a medir o decode.
            """
            r = subprocess.run(
                [GIT, "-C", str(self.repo), "cat-file",
                 "--batch-all-objects", "--batch"], capture_output=True)
            return segredo in r.stdout

    return Cen()


# ═══════════ 01-03 — as três rotas, medidas lado a lado ═════════════════════

def test_a57_01_filtro_do_REPOSITORIO_continua_NEGADO(cenario):
    """A negação de A5 não é afrouxada por nada que A5.7 acrescente.

    O repositório declara o filtro do jeito clássico — `.gitattributes` mais
    `filter.<id>.clean` no `.git/config` — e o adapter roda SEM registry, que é
    o caminho padrão. O programa do repo não executa.
    """
    cenario.escrever("segredo.txt", "SENHA=hunter2\n")
    cenario.atributos("segredo.txt filter=hostil\n")
    hostil = cenario.tmp / "hostil.sh"
    hostil.write_text("#!/bin/sh\nsed 's/hunter2/REDIGIDO/'\n")
    hostil.chmod(0o755)
    _git(cenario.repo, "config", "filter.hostil.clean", str(hostil))

    with pytest.raises((ErroInvalido, supervisor.ErroSeguranca)):
        cenario.add(cenario.adapter())          # sem registry = caminho padrão

    assert _git(cenario.repo, "ls-files").stdout.strip() == "", (
        "o índice não voltou ao estado anterior após a recusa")


def test_a57_02_filtro_GOVERNADO_com_id_aprovado_TRANSFORMA(cenario):
    """A prova funcional da missão: SENHA=hunter2 -> SENHA=REDIGIDO."""
    cenario.escrever("segredo.txt", "SENHA=hunter2\nlinha normal\n")
    cenario.atributos("segredo.txt filter=redator\n")

    r = cenario.add(cenario.adapter(cenario.registro("redator")),
                    "segredo.txt")
    assert r.efeito_aplicado

    # CONTROLE POSITIVO: o segredo estava em claro na working tree.
    assert "hunter2" in (cenario.repo / "segredo.txt").read_text()

    indexado = cenario.conteudo_no_indice("segredo.txt")
    assert indexado == b"SENHA=REDIGIDO\nlinha normal\n"
    assert b"hunter2" not in indexado
    # E não basta o objeto do caminho: o segredo não pode estar em objeto
    # NENHUM do store — um blob cru gravado antes da transformação seria
    # exatamente o resíduo que A0.3 existe para impedir.
    assert not cenario.segredo_em_algum_objeto(b"hunter2"), (
        "o conteúdo CRU chegou ao store permanente")


def test_a57_03_filtro_governado_com_id_DESCONHECIDO_e_NEGADO(cenario):
    """Ausência de política é NEGAÇÃO, nunca fallback para o caminho padrão."""
    cenario.escrever("segredo.txt", "SENHA=hunter2\n")
    cenario.atributos("segredo.txt filter=inexistente\n")

    with pytest.raises(fg.ErroFiltro, match="não está no registry"):
        cenario.add(cenario.adapter(cenario.registro("redator")),
                    "segredo.txt")

    assert _git(cenario.repo, "ls-files").stdout.strip() == ""
    assert not cenario.segredo_em_algum_objeto(b"hunter2")


# ═══════════════ 04-07 — a fronteira de titularidade permanece ══════════════

def test_a57_04_config_do_repo_NAO_muda_o_que_executa(cenario):
    """O repositório aponta `filter.redator.clean` para um hostil; o id é o
    mesmo que o registry aprovou. Quem executa é o ARTEFATO, não a config."""
    cenario.escrever("segredo.txt", "SENHA=hunter2\n")
    cenario.atributos("segredo.txt filter=redator\n")
    canario = cenario.tmp / "CANARIO"
    hostil = cenario.tmp / "hostil.sh"
    hostil.write_text(f"#!/bin/sh\necho HOSTIL > {canario}\ncat\n")
    hostil.chmod(0o755)
    _git(cenario.repo, "config", "filter.redator.clean", str(hostil))

    r = cenario.add(cenario.adapter(cenario.registro("redator")),
                    "segredo.txt")
    assert r.efeito_aplicado
    assert not canario.exists(), (
        "o `clean` declarado pelo REPOSITÓRIO executou — a config voltou a ser "
        "autoridade de execução")
    assert cenario.conteudo_no_indice("segredo.txt") == b"SENHA=REDIGIDO\n"


def test_a57_05_id_fora_da_gramatica_nem_vira_consulta(cenario):
    """Um id que parece caminho é recusado na GRAMÁTICA, antes do registry."""
    cenario.escrever("segredo.txt", "SENHA=hunter2\n")
    cenario.atributos("segredo.txt filter=../../etc/passwd\n")
    with pytest.raises(fg.ErroFiltro, match="gramática"):
        cenario.add(cenario.adapter(cenario.registro("redator")),
                    "segredo.txt")


def test_a57_06_sem_registry_o_gitattributes_e_IGNORADO(cenario):
    """Registry AUSENTE é diferente de registry VAZIO.

    Sem registry o adapter nem olha o `.gitattributes` — comportamento
    histórico, e o filtro do repo continua sem executar por causa da allowlist.
    Um arquivo sem filtro declarado tem de continuar entrando normalmente.
    """
    cenario.escrever("comum.txt", "conteudo comum\n")
    r = cenario.add(cenario.adapter(), "comum.txt")
    assert r.efeito_aplicado
    assert cenario.conteudo_no_indice("comum.txt") == b"conteudo comum\n"


def test_a57_07_registry_VAZIO_recusa_o_pedido_por_nome(cenario):
    cenario.escrever("segredo.txt", "SENHA=hunter2\n")
    cenario.atributos("segredo.txt filter=redator\n")
    with pytest.raises(fg.ErroFiltro, match="não está no registry"):
        cenario.add(cenario.adapter(fg.RegistroDeFiltros()), "segredo.txt")


# ═══════════════ 08-11 — mistura, seletividade e integridade ════════════════

def test_a57_08_caminho_governado_e_caminho_comum_na_MESMA_operacao(cenario):
    """O `add` de um lote misto não pode transformar o que ninguém pediu."""
    cenario.escrever("segredo.txt", "SENHA=hunter2\n")
    cenario.escrever("comum.txt", "SENHA=hunter2\n")     # mesmo texto, sem filtro
    cenario.atributos("segredo.txt filter=redator\n")

    r = cenario.add(cenario.adapter(cenario.registro("redator")),
                    "segredo.txt", "comum.txt")
    assert r.efeito_aplicado
    assert cenario.conteudo_no_indice("segredo.txt") == b"SENHA=REDIGIDO\n"
    assert cenario.conteudo_no_indice("comum.txt") == b"SENHA=hunter2\n", (
        "o arquivo SEM filtro declarado foi transformado — o filtro vazou para "
        "fora do que o `.gitattributes` pediu")


def test_a57_09_conteudo_binario_atravessa_intacto(cenario):
    """Um filtro que corrompe o que não devia tocar é pior que filtro ausente."""
    bruto = bytes(range(256)) + b"\nSENHA=hunter2\n"
    (cenario.repo / "bin.dat").write_bytes(bruto)
    cenario.escrever("outro.txt", "nada aqui\n")
    cenario.atributos("outro.txt filter=redator\n")

    r = cenario.add(cenario.adapter(cenario.registro("redator")),
                    "bin.dat", "outro.txt")
    assert r.efeito_aplicado
    assert cenario.conteudo_no_indice("bin.dat") == bruto


def test_a57_10_o_commit_persiste_o_conteudo_REDIGIDO(cenario):
    """A transformação tem de sobreviver ao commit, senão só adiou o problema."""
    cenario.escrever("segredo.txt", "SENHA=hunter2\n")
    cenario.atributos("segredo.txt filter=redator\n")
    ad = cenario.adapter(cenario.registro("redator"))
    cenario.add(ad, "segredo.txt")

    pedido = CapabilityRequest(capacidade="git-commit", alvo=str(cenario.repo),
                               argumentos={"mensagem": "redigido"})
    assert ad.executar(pedido, cenario.ctx("git-commit")).efeito_aplicado

    mostrado = _git(cenario.repo, "show", "HEAD:segredo.txt").stdout
    assert mostrado == "SENHA=REDIGIDO\n"
    assert not cenario.segredo_em_algum_objeto(b"hunter2")


def test_a57_11_o_filtro_governado_roda_SOB_o_confinamento_de_A55(cenario):
    """A política que o `add` usa é a mesma de A5.5 — não uma cópia relaxada."""
    pol = cenario.politica()
    conf = pol.confinamento()
    assert conf.exec_permitido == (cenario.artefato.managed_path,)
    assert conf.rede is False
    assert set(pol.ambiente()) == {"LANG", "LC_ALL"}
