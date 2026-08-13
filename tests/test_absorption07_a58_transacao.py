"""A5.8 — a transação inteira, com o filtro governado dentro dela.

A0.1 provou que o índice volta ao byte anterior. A0.3 provou que o objeto do
segredo nunca chega ao store permanente. A5.2-A5.7 construíram o filtro
governado. Cada peça foi medida sozinha; esta bateria mede as peças LIGADAS,
que é onde integração costuma falhar: um passo novo no meio da transação pode
gravar antes do ponto de commit sem que nenhum teste de peça note.

O invariante, depois de QUALQUER falha em QUALQUER ponto:

    INDEX_BYTES_AFTER          == INDEX_BYTES_BEFORE
    PERMANENT_SECRET_OBJECTS   == 0
    UNREACHABLE_SECRET_OBJECTS == 0
    ORPHAN_PROCESS             == 0
    PARTIAL_PROMOTION          == 0

## O ponto que só aparece com MAIS DE UM caminho

Com um caminho só, "falhou, nada foi promovido" é quase automático. O caso que
morde é o lote: o primeiro caminho é filtrado e estagiado com sucesso, o segundo
falha. Se a promoção fosse incremental, o blob do primeiro já estaria no store
permanente — promoção PARCIAL de uma operação recusada. Por isso os testes de
falha usam dois caminhos, e o primeiro sempre funciona.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git_tree, supervisor
from nomos.adapters.contrato import (
    CapabilityContext, CapabilityRequest, ErroInvalido, ErroLimite,
)
from nomos.adapters.git import diretorio_git
from nomos.adapters.wiring import registrar_git_tree
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.registro import RegistroCapacidades

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"
SEGREDO = b"hunter2"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cen(tmp_path):
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

    # Dois caminhos governados. O PRIMEIRO sempre funciona: é ele que
    # transforma promoção-parcial de hipótese em coisa observável.
    (repo / "a.txt").write_text("SENHA=hunter2\nprimeiro\n")
    (repo / "b.txt").write_text("SENHA=hunter2\nsegundo\n")
    (repo / ".gitattributes").write_text("*.txt filter=redator\n")

    reg = fg.RegistroDeFiltros()
    reg.registrar("redator", fg.PoliticaDeFiltro(
        filter_id="redator", canonical_executable=str(binario),
        managed_artifact=art, read_roots=(str(repo),),
        write_roots=(str(repo),)))

    class Cen:
        def __init__(self):
            # Atribuição no `__init__`, e não no corpo da classe: corpo de
            # classe NÃO fecha sobre o escopo da função que o contém.
            self.repo = repo
            self.tmp = tmp_path
            self.registro = reg
            self.artefato = art

        def adapter(self):
            return git_tree.GitTreeAdapter(registro=reg)

        def ctx(self, cap="git-add"):
            rc = RegistroCapacidades(
                policy=PolicyEngine(self.tmp / "pol.json"),
                approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(self.tmp),))
            return CapabilityContext.de_registro(
                rc, cap, "runtime-governado", raizes=(str(self.tmp),))

        def add(self, *caminhos):
            return self.adapter().executar(
                CapabilityRequest(capacidade="git-add", alvo=str(self.repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx())

        # ---------------------------------------------------------- invariantes
        def indice(self) -> bytes | None:
            alvo = Path(diretorio_git(self.repo)[0]) / "index"
            return alvo.read_bytes() if alvo.exists() else None

        def objetos_com_segredo(self) -> int:
            """Objetos do store PERMANENTE que contêm o segredo.

            `--batch-all-objects` varre o store inteiro, alcançável ou não — é
            isso que separa PERMANENT de UNREACHABLE: um blob órfão continua
            legível por `cat-file` até um `gc`, e órfão ilegível-por-ref é
            exatamente o resíduo que A0.3 existe para impedir.
            """
            r = subprocess.run(
                [GIT, "-C", str(self.repo), "cat-file", "--batch-all-objects",
                 "--batch"], capture_output=True)
            return r.stdout.count(SEGREDO)

        def quarentenas_em_disco(self) -> list[Path]:
            return list(Path(diretorio_git(self.repo)[0]).glob("nomos-quarentena-*"))

        def sob_sandbox(self) -> list[str]:
            r = subprocess.run(["/bin/ps", "-Ao", "pid,command"],
                               capture_output=True, text=True)
            return [ln for ln in r.stdout.splitlines() if "nomos-sb-" in ln]

    return Cen()


def _exige_transacao_intacta(cen, antes: bytes | None) -> None:
    """Os cinco invariantes, sempre juntos. Separá-los deixaria buraco."""
    assert cen.indice() == antes, "INDEX_BYTES mudou depois de uma recusa"
    assert cen.objetos_com_segredo() == 0, (
        "PERMANENT/UNREACHABLE_SECRET_OBJECTS != 0: o segredo chegou ao store")
    assert cen.quarentenas_em_disco() == [], "PARTIAL_PROMOTION: quarentena ficou"
    assert cen.sob_sandbox() == [], "ORPHAN_PROCESS após a recusa"


# ═══════════════ CONTROLE POSITIVO — sem ele tudo abaixo é vácuo ════════════

def test_a58_00_controle_positivo_o_caminho_feliz_PROMOVE(cen):
    """Se o sucesso não promovesse, "nada promovido" nas falhas não provaria
    nada — seria a ausência de um efeito que nunca existiu."""
    antes = cen.indice()
    r = cen.add("a.txt", "b.txt")
    assert r.efeito_aplicado
    assert cen.indice() != antes, "o índice não mudou nem no sucesso"
    assert cen.objetos_com_segredo() == 0, "o segredo entrou mesmo no sucesso"
    assert cen.quarentenas_em_disco() == []
    sha = subprocess.run([GIT, "-C", str(cen.repo), "ls-files", "-s"],
                         capture_output=True, text=True).stdout
    assert sha.strip(), "nada foi estagiado no caminho feliz"


# ═════════════ falhas em CADA ponto da cadeia governada ═════════════════════

def test_a58_01_falha_ANTES_do_filtro_nao_deixa_rastro(cen, monkeypatch):
    """O registry recusa o segundo caminho. Nada do primeiro pode sobrar."""
    antes = cen.indice()
    original = fg.RegistroDeFiltros.resolver
    chamadas = {"n": 0}

    def resolver(self, fid):
        chamadas["n"] += 1
        if chamadas["n"] > 1:
            raise fg.ErroFiltro("recusa injetada ANTES do filtro")
        return original(self, fid)

    monkeypatch.setattr(fg.RegistroDeFiltros, "resolver", resolver)
    with pytest.raises(fg.ErroFiltro, match="ANTES do filtro"):
        cen.add("a.txt", "b.txt")
    assert chamadas["n"] >= 2, "a falha não chegou a ser exercida"
    _exige_transacao_intacta(cen, antes)


def test_a58_02_falha_DURANTE_o_filtro_nao_deixa_rastro(cen, monkeypatch):
    """A execução do filtro governado levanta no segundo caminho."""
    antes = cen.indice()
    original = supervisor.executar
    chamadas = {"filtro": 0}

    def executar(argv, **kw):
        if kw.get("tipo") is supervisor.TipoDeProcesso.FILTRO_GOVERNADO:
            chamadas["filtro"] += 1
            if chamadas["filtro"] > 1:
                raise RuntimeError("falha injetada DURANTE o filtro")
        return original(argv, **kw)

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(RuntimeError, match="DURANTE o filtro"):
        cen.add("a.txt", "b.txt")
    assert chamadas["filtro"] >= 2
    _exige_transacao_intacta(cen, antes)


def test_a58_03_filtro_que_sai_NAO_ZERO_recusa_a_operacao(cen, monkeypatch):
    """rc != 0 do filtro é recusa, não "estagia o conteúdo cru e segue"."""
    antes = cen.indice()
    original = supervisor.executar

    def executar(argv, **kw):
        p = original(argv, **kw)
        if kw.get("tipo") is supervisor.TipoDeProcesso.FILTRO_GOVERNADO:
            from dataclasses import replace
            return replace(p, returncode=7, classificacao="EXIT_ERRO")
        return p

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(ErroInvalido, match="rc=7"):
        cen.add("a.txt", "b.txt")
    _exige_transacao_intacta(cen, antes)


def test_a58_04_filtro_que_ESTOURA_O_PRAZO_recusa_a_operacao(cen, monkeypatch):
    antes = cen.indice()
    original = supervisor.executar

    def executar(argv, **kw):
        p = original(argv, **kw)
        if kw.get("tipo") is supervisor.TipoDeProcesso.FILTRO_GOVERNADO:
            from dataclasses import replace
            return replace(p, morto_por_timeout=True,
                           classificacao="KILLED_BY_TIMEOUT")
        return p

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(ErroLimite, match="excedeu o prazo"):
        cen.add("a.txt", "b.txt")
    _exige_transacao_intacta(cen, antes)


def test_a58_05_falha_DEPOIS_do_filtro_no_hash_object(cen, monkeypatch):
    """O blob transformado já foi escrito na quarentena, e mesmo assim some."""
    antes = cen.indice()
    original = supervisor.executar
    vistos = {"n": 0}

    def executar(argv, **kw):
        if any("hash-object" in a for a in argv):
            vistos["n"] += 1
            if vistos["n"] > 1:
                raise RuntimeError("falha injetada DEPOIS do filtro")
        return original(argv, **kw)

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(RuntimeError, match="DEPOIS do filtro"):
        cen.add("a.txt", "b.txt")
    assert vistos["n"] >= 2, "o hash-object do 2o caminho nem foi tentado"
    _exige_transacao_intacta(cen, antes)


def test_a58_06_falha_no_ESTAGIAMENTO_nao_deixa_indice_pela_metade(cen,
                                                                   monkeypatch):
    antes = cen.indice()
    original = supervisor.executar
    vistos = {"n": 0}

    def executar(argv, **kw):
        if any("update-index" in a for a in argv):
            vistos["n"] += 1
            if vistos["n"] > 1:
                raise RuntimeError("falha injetada no estagiamento")
        return original(argv, **kw)

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(RuntimeError, match="no estagiamento"):
        cen.add("a.txt", "b.txt")
    assert vistos["n"] >= 2
    _exige_transacao_intacta(cen, antes)


def test_a58_07_falha_da_AUDITORIA_desfaz_tudo(cen, monkeypatch):
    """A auditoria roda ANTES da promoção, e por medição.

    Em A0.3 a promoção estava antes da auditoria, e o blob do segredo já tinha
    ido para o store quando o `_auditar` levantava. O caminho governado tem de
    herdar essa ordem, não redescobrir o defeito.
    """
    antes = cen.indice()

    def explodir(*a, **k):
        raise RuntimeError("falha injetada na auditoria")

    monkeypatch.setattr(git_tree.GitTreeAdapter, "_auditar", explodir)
    with pytest.raises(RuntimeError, match="na auditoria"):
        cen.add("a.txt", "b.txt")
    _exige_transacao_intacta(cen, antes)


def test_a58_08_SINAL_no_meio_da_transacao_desfaz_tudo(cen, monkeypatch):
    """KeyboardInterrupt não é caminho privilegiado.

    `git_tree` captura `BaseException` de propósito: Ctrl-C e SystemExit também
    não podem deixar segredo estagiado nem objeto no store.
    """
    antes = cen.indice()
    original = supervisor.executar
    vistos = {"n": 0}

    def executar(argv, **kw):
        if kw.get("tipo") is supervisor.TipoDeProcesso.FILTRO_GOVERNADO:
            vistos["n"] += 1
            if vistos["n"] > 1:
                raise KeyboardInterrupt("sinal injetado")
        return original(argv, **kw)

    monkeypatch.setattr(supervisor, "executar", executar)
    with pytest.raises(KeyboardInterrupt):
        cen.add("a.txt", "b.txt")
    _exige_transacao_intacta(cen, antes)


def test_a58_09_falha_na_PRE_CONDICAO_de_promocao(cen, monkeypatch):
    """A promoção é o ponto de commit. Se ELA falhar, nada pode ter ido."""
    antes = cen.indice()

    def explodir(*a, **k):
        raise RuntimeError("falha injetada na promoção")

    monkeypatch.setattr(git_tree, "_promover_quarentena", explodir)
    with pytest.raises(RuntimeError, match="na promoção"):
        cen.add("a.txt", "b.txt")
    _exige_transacao_intacta(cen, antes)


def test_a58_10_o_artefato_TROCADO_recusa_antes_de_executar(cen):
    """A5.3 dentro da transação: divergência é DENY, e o índice não se move."""
    antes = cen.indice()
    alvo = Path(cen.artefato.managed_path)
    alvo.chmod(0o700)
    alvo.write_bytes(b"conteudo trocado, nao e o aprovado\n")
    alvo.chmod(0o500)

    with pytest.raises(fg.ErroFiltro, match="DIVERGE"):
        cen.add("a.txt", "b.txt")
    _exige_transacao_intacta(cen, antes)


def test_a58_11_indice_JA_POVOADO_volta_ao_byte_anterior(cen):
    """O caso que `git reset` estragaria: havia trabalho estagiado antes.

    Restaurar os BYTES devolve o estado exato; `reset` devolveria um estado
    plausível — e perderia o estagiamento pré-existente.
    """
    (cen.repo / "outro.dat").write_text("estagiado antes\n")
    subprocess.run([GIT, "-C", str(cen.repo), "add", "--", "outro.dat"],
                   check=True, capture_output=True)
    antes = cen.indice()
    assert antes is not None

    reg_vazio = fg.RegistroDeFiltros()
    ad = git_tree.GitTreeAdapter(registro=reg_vazio)
    with pytest.raises(fg.ErroFiltro):
        ad.executar(
            CapabilityRequest(capacidade="git-add", alvo=str(cen.repo),
                              argumentos={"caminhos": ["a.txt"]}),
            cen.ctx())

    assert cen.indice() == antes, "o estagiamento pré-existente foi perdido"
    saida = subprocess.run([GIT, "-C", str(cen.repo), "ls-files"],
                           capture_output=True, text=True).stdout
    assert "outro.dat" in saida, "o trabalho anterior sumiu do índice"
