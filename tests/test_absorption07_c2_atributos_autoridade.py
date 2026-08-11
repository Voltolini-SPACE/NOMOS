"""C2 — quem decide se um caminho pede filtro é o GIT, não um parser nosso.

A propriedade que esta bateria persegue:

    NOMOS_E_GIT_CONCORDAM_SOBRE_QUAL_FILTRO_SE_APLICA = TRUE

Ela foi medida FALSA em OITO formas idiomáticas. `_pedidos_de_filtro` lia
`repo/.gitattributes` e casava padrão com `fnmatch`; o Git lê uma CADEIA de
fontes, com precedência própria, e tem gramática de padrão que não é `fnmatch`.
Cada divergência produzia o mesmo desfecho, e é o pior possível:

    CapabilityResult(ok=True, efeito_aplicado=True)
    índice = b'SENHA=hunter2\\n'          <- o SEGREDO, EM CLARO

Isto é `FAIL_CLOSED = FALSE`: o NOMOS relata SUCESSO de uma operação em que o
filtro que deveria redigir o segredo simplesmente não foi visto. Um filtro
ausente que RECUSA é seguro; um filtro ausente que diz `ok=True` é um vazamento
com carimbo de aprovação.

## Por que a correção não foi consertar o parser

Cada uma das oito é um bug diferente do parser, e a lista NÃO FECHA: a semântica
de atributos pertence ao Git e muda com ele. Corrigir oito deixaria a nona
aberta, e a nona também indexaria o segredo em claro dizendo `ok=True`.

`check-attr` roda com o MESMO argv base, o MESMO ambiente e a MESMA working tree
pinada do `add` que vem depois. Os dois enxergam as mesmas fontes por
CONSTRUÇÃO — não por uma tabela que alguém precisa manter sincronizada.

## O controle que impede esta bateria de virar "negue tudo"

`test_c2_00_*` exige que o caminho LEGÍTIMO continue funcionando, e
`test_c2_12_*` que um arquivo SEM regra continue passando intacto. Sem os dois,
todos os outros passariam igual num sistema que quebrou o filtro governado
inteiro.

## Landmine registrada

`-c attr.tree=` **NÃO** desliga `attr.tree` — MEDIDO. É a mesma armadilha de
`core.worktree`: neutralização por linha de comando que parece funcionar e é
no-op silencioso. Uma defesa feita só de neutralização ficaria furada
exatamente ali. `test_c2_13_*` prende essa medição para que ninguém "simplifique"
a autoridade do `check-attr` de volta para uma lista de `-c`.
"""
from __future__ import annotations

import os
import shutil
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
SEGREDO = "SENHA=hunter2\n"
REDIGIDO = b"SENHA=REDIGIDO\n"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cen(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "a@b.c"), ("user.name", "T")):
        subprocess.run([GIT, "-C", str(repo), "config", k, v],
                       check=True, capture_output=True)

    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art_red = fg.ArmazemDeExecutaveis(tmp_path / "s1").importar(binario)

    # `passa` precisa ser PASSAGEM REAL. Se ele redigisse igual ao `redator`,
    # os testes de REBAIXAMENTO não distinguiriam "escolheu o filtro certo" de
    # "escolheu o errado" — e passariam com o defeito presente.
    gato = tmp_path / "gato"
    shutil.copyfile("/bin/cat", gato)     # copy2 falha: copystat em binário SIP
    gato.chmod(0o755)
    art_gato = fg.ArmazemDeExecutaveis(tmp_path / "s2").importar(gato)

    class Cen:
        repo = None

        def registro(self, *ids):
            reg = fg.RegistroDeFiltros()
            for fid in (ids or ("redator",)):
                ex, art = ((str(gato), art_gato) if fid == "passa"
                           else (str(binario), art_red))
                reg.registrar(fid, fg.PoliticaDeFiltro(
                    filter_id=fid, canonical_executable=ex,
                    managed_artifact=art, read_roots=(str(repo),),
                    write_roots=(str(repo),)))
            return reg

        def ctx(self, capacidade="git-add"):
            rc = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                     approver=lambda *a, **k: True)
            registrar_git_tree(rc, raizes=(str(tmp_path),))
            return CapabilityContext.de_registro(rc, capacidade,
                                                 "runtime-governado",
                                                 raizes=(str(tmp_path),))

        def add(self, *caminhos, ids=("redator",)):
            adapter = git_tree.GitTreeAdapter(registro=self.registro(*ids))
            return adapter.executar(
                CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                  argumentos={"caminhos": list(caminhos)}),
                self.ctx())

        def escrever(self, rel: str, corpo: str = SEGREDO) -> Path:
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(corpo)
            return p

        def indice(self, rel: str) -> bytes:
            r = subprocess.run([GIT, "-C", str(repo), "show", f":{rel}"],
                               capture_output=True)
            return r.stdout if r.returncode == 0 else b"<AUSENTE>"

    c = Cen()
    c.repo = repo
    return c


# ══════════ 00 — CONTROLE POSITIVO: o caminho legítimo continua vivo ═════════

def test_c2_00_controle_positivo_atributo_na_raiz_ainda_filtra(cen):
    """Sem este teste, os onze seguintes passariam com o filtro governado morto."""
    cen.escrever("SEGREDO.txt")
    cen.escrever(".gitattributes", "SEGREDO.txt filter=redator\n")
    r = cen.add("SEGREDO.txt")
    assert r.efeito_aplicado
    assert cen.indice("SEGREDO.txt") == REDIGIDO


# ═════════ 01-08 — as formas que o Git honra e o parser próprio não via ══════

def test_c2_01_gitattributes_em_SUBDIRETORIO(cen):
    """O Git usa o arquivo de atributos MAIS PRÓXIMO; o parser lia só a raiz."""
    cen.escrever("sub/SEGREDO.txt")
    cen.escrever("sub/.gitattributes", "SEGREDO.txt filter=redator\n")
    cen.add("sub/SEGREDO.txt")
    assert cen.indice("sub/SEGREDO.txt") == REDIGIDO, (
        "SILENT_FILTER_BYPASS: o segredo foi indexado EM CLARO com ok=True")


def test_c2_02_padrao_ancorado_com_barra_inicial(cen):
    cen.escrever("SEGREDO.txt")
    cen.escrever(".gitattributes", "/SEGREDO.txt filter=redator\n")
    cen.add("SEGREDO.txt")
    assert cen.indice("SEGREDO.txt") == REDIGIDO


def test_c2_03_macro_de_atributo(cen):
    cen.escrever("SEGREDO.txt")
    cen.escrever(".gitattributes", "[attr]zz filter=redator\nSEGREDO.txt zz\n")
    cen.add("SEGREDO.txt")
    assert cen.indice("SEGREDO.txt") == REDIGIDO


def test_c2_04_padrao_entre_aspas(cen):
    cen.escrever("SEGREDO.txt")
    cen.escrever(".gitattributes", '"SEGREDO.txt" filter=redator\n')
    cen.add("SEGREDO.txt")
    assert cen.indice("SEGREDO.txt") == REDIGIDO


def test_c2_05_git_info_attributes_tem_precedencia(cen):
    """`.git/info/attributes` é o lugar canônico da regra LOCAL de redação."""
    cen.escrever("SEGREDO.txt")
    info = cen.repo / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    (info / "attributes").write_text("SEGREDO.txt filter=redator\n")
    cen.add("SEGREDO.txt")
    assert cen.indice("SEGREDO.txt") == REDIGIDO


def test_c2_06_attr_tree_le_atributos_de_uma_ARVORE(cen):
    """Caso extremo: o working tree nem TEM `.gitattributes`."""
    cen.escrever("SEGREDO.txt")
    cen.escrever(".gitattributes", "SEGREDO.txt filter=redator\n")
    subprocess.run([GIT, "-C", str(cen.repo), "add", ".gitattributes"],
                   check=True, capture_output=True)
    subprocess.run([GIT, "-C", str(cen.repo), "commit", "-qm", "attrs"],
                   check=True, capture_output=True)
    (cen.repo / ".gitattributes").unlink()
    subprocess.run([GIT, "-C", str(cen.repo), "config", "attr.tree", "HEAD"],
                   check=True, capture_output=True)
    cen.add("SEGREDO.txt")
    assert cen.indice("SEGREDO.txt") == REDIGIDO


def test_c2_07_divergencia_de_CAIXA(cen):
    """`fnmatch` compara sensível a caixa; o Git, sob `core.ignorecase`, não."""
    cen.escrever("segredo.txt")
    cen.escrever(".gitattributes", "SEGREDO.TXT filter=redator\n")
    cen.add("segredo.txt")
    assert cen.indice("segredo.txt") == REDIGIDO


def test_c2_08_REBAIXAMENTO_o_arquivo_mais_proximo_vence(cen):
    """Raiz pede `passa`, `sub/` pede `redator` — os DOIS aprovados.

    O pior desfecho medido: não é "filtro ausente", é filtro ERRADO. O NOMOS
    lia só a raiz, resolvia `passa` no registry (que existe e é legítimo),
    executava, e reportava sucesso com `(1 por filtro governado)` — parecendo
    ter governado exatamente a coisa que deixou passar.
    """
    cen.escrever("sub/SEGREDO.txt")
    cen.escrever(".gitattributes", "SEGREDO.txt filter=passa\n")
    cen.escrever("sub/.gitattributes", "SEGREDO.txt filter=redator\n")
    cen.add("sub/SEGREDO.txt", ids=("redator", "passa"))
    assert cen.indice("sub/SEGREDO.txt") == REDIGIDO, (
        "aplicou o filtro da RAIZ, não o que o Git escolheria")


def test_c2_09_REBAIXAMENTO_na_mesma_linha_ultima_declaracao_vence(cen):
    """`re.search` devolve a PRIMEIRA ocorrência; o Git usa a ÚLTIMA."""
    cen.escrever("SEGREDO.txt")
    cen.escrever(".gitattributes", "SEGREDO.txt filter=passa filter=redator\n")
    cen.add("SEGREDO.txt", ids=("redator", "passa"))
    assert cen.indice("SEGREDO.txt") == REDIGIDO


# ═══════════ 10-11 — a FONTE de atributo não é escolhida pelo repo ═══════════

def test_c2_10_gitattributes_como_SYMLINK_e_recusado(cen, tmp_path):
    """Quem escolhe o destino do link escolhe a política de filtro.

    E o desfecho sem a recusa é o pior: dentro do sandbox o Git não consegue
    LER o destino, então não vê pedido de filtro nenhum e indexa o conteúdo CRU
    com rc=0. Trocar o arquivo de regras por um link seria o ataque mais barato
    da série.
    """
    fora = tmp_path / "fora-das-raizes.attrs"
    fora.write_text("SEGREDO.txt filter=redator\n")
    cen.escrever("SEGREDO.txt")
    os.symlink(str(fora), str(cen.repo / ".gitattributes"))

    with pytest.raises(supervisor.ErroSeguranca, match="symlink"):
        cen.add("SEGREDO.txt")
    assert cen.indice("SEGREDO.txt") == b"<AUSENTE>"


def test_c2_11_core_attributesFile_e_RECUSA_nao_no_op(cen, tmp_path):
    """Ignorar em silêncio uma regra de REDAÇÃO publica o que ela escondia."""
    externo = tmp_path / "externo.attrs"
    externo.write_text("SEGREDO.txt filter=redator\n")
    cen.escrever("SEGREDO.txt")
    subprocess.run([GIT, "-C", str(cen.repo), "config",
                    "core.attributesFile", str(externo)],
                   check=True, capture_output=True)

    with pytest.raises(supervisor.ErroSeguranca, match="core.attributesFile"):
        cen.add("SEGREDO.txt")
    assert cen.indice("SEGREDO.txt") == b"<AUSENTE>"


# ═══════════════════ 12-13 — seletividade e a landmine medida ════════════════

def test_c2_12_arquivo_SEM_regra_atravessa_intacto(cen):
    """Segundo controle: o filtro não pode vazar para quem ninguém pediu."""
    cen.escrever("SEGREDO.txt")
    cen.escrever("comum.txt", SEGREDO)          # mesmo texto, sem regra
    cen.escrever(".gitattributes", "SEGREDO.txt filter=redator\n")
    cen.add("SEGREDO.txt", "comum.txt")
    assert cen.indice("SEGREDO.txt") == REDIGIDO
    assert cen.indice("comum.txt") == SEGREDO.encode(), (
        "o filtro transformou um arquivo que o `.gitattributes` não pediu")


def test_c2_13_landmine_attr_tree_NAO_e_neutralizavel_por_dash_c(cen):
    """PRENDE a medição que sustenta o desenho todo.

    Se `-c attr.tree=` funcionasse, alguém poderia argumentar que bastava uma
    lista de neutralizações e que perguntar ao `check-attr` é complexidade
    desnecessária. NÃO FUNCIONA — e é por isso que a autoridade sobre atributos
    é o Git, não `_NEUTRALIZAR_TREE`. Mesma família de `core.worktree`.
    """
    cen.escrever("SEGREDO.txt")
    cen.escrever(".gitattributes", "SEGREDO.txt filter=redator\n")
    subprocess.run([GIT, "-C", str(cen.repo), "add", ".gitattributes"],
                   check=True, capture_output=True)
    subprocess.run([GIT, "-C", str(cen.repo), "commit", "-qm", "a"],
                   check=True, capture_output=True)
    (cen.repo / ".gitattributes").unlink()
    subprocess.run([GIT, "-C", str(cen.repo), "config", "attr.tree", "HEAD"],
                   check=True, capture_output=True)

    r = subprocess.run([GIT, "-C", str(cen.repo), "-c", "attr.tree=",
                        "check-attr", "filter", "--", "SEGREDO.txt"],
                       capture_output=True, text=True)
    assert "filter: redator" in r.stdout, (
        "`-c attr.tree=` passou a desligar a chave neste Git. A medição que "
        "justifica a autoridade do check-attr mudou — reavalie o desenho de "
        "`_pedidos_de_filtro` ANTES de simplificar qualquer coisa")


def test_c2_14_check_attr_roda_sob_o_supervisor(cen):
    """A pergunta ao Git é EXECUÇÃO, e nesta série execução é supervisionada.

    Estrutural de propósito: um `subprocess.run` cru aqui rodaria fora do
    sandbox, sem prazo e sem árvore de processos — exatamente o que a leitura
    do filtro (A5.7) já custou uma vez.
    """
    fonte = Path(git_tree.__file__).read_text("utf-8")
    corpo = fonte.split("def _pedidos_de_filtro", 1)[1].split("\n    def ", 1)[0]
    assert "supervisor.executar" in corpo
    assert "subprocess" not in corpo
