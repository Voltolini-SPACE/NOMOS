"""A5.7 — alcançabilidade pelo RUNTIME REAL, não só pelo adapter.

A5.7 estava classificado como PASS porque o adapter funcionava e os testes
isolados eram verdes. Uma medição desfez a classificação:

    RuntimeGovernado(...)  ->  capacidades registradas:
        fs-*, git-diff, git-log, git-show, git-tag
        git-add    AUSENTE
        git-commit AUSENTE

Nenhum caminho do runtime chamava `registrar_git_tree`. Toda a maquinaria de
A0.1 (índice transacional), A0.3 (quarentena) e A5.2-A5.9 (filtro governado)
existia como BIBLIOTECA com testes — e era inalcançável pelo produto. A suíte
ficava verde porque os testes instanciavam o adapter diretamente.

É a forma mais silenciosa de falso fechamento desta série: nada quebra, nada
avisa, e o gate parece fechado. Por isso a classificação passou a distinguir:

    A5.7_IMPLEMENTATION       o adapter faz o que promete
    A5.7_RUNTIME_REACHABILITY a capacidade EXISTE para o runtime

## As quatro propriedades da injeção

O registry não pode voltar a ser autoridade difusa. Ele é:

    INJETADO EXPLICITAMENTE  parâmetro do composition root, e nada mais
    NÃO SINGLETON GLOBAL     dois runtimes têm registries independentes
    NÃO DO REPOSITÓRIO       o repo PEDE por id; quem responde é o registry
    NÃO DO AMBIENTE          nenhuma variável de ambiente o define

Cada uma tem teste próprio abaixo, porque cada uma é uma forma diferente de o
repositório ou o host recuperarem a decisão que A5.2 tirou deles.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import supervisor
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.governado import RuntimeGovernado

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cen(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    repo = ws / "repo"
    repo.mkdir()
    subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)

    class Cen:
        def __init__(self):
            self.tmp, self.ws, self.repo = tmp_path, ws, repo
            self.home, self.binario, self.artefato = home, binario, art

        def registro_de_filtros(self, *ids: str) -> fg.RegistroDeFiltros:
            reg = fg.RegistroDeFiltros()
            for fid in ids:
                reg.registrar(fid, fg.PoliticaDeFiltro(
                    filter_id=fid, canonical_executable=str(binario),
                    managed_artifact=art, read_roots=(str(repo),),
                    write_roots=(str(repo),)))
            return reg

        def runtime(self, **kw) -> RuntimeGovernado:
            ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
                   "audit": AuditLog(home / "logs" / "audit.jsonl")}
            return RuntimeGovernado(ctx, lambda _d: True,
                                    caminhos=(str(ws),), adapters=True,
                                    git_tree=True, **kw)

        def plano_add(self, rt, *caminhos):
            return rt.rodar("a57", passos=[{
                "id": "p", "ferramenta": "git-add",
                "params": {"alvo": str(repo),
                           "caminhos": list(caminhos)}}])

        def no_indice(self, nome: str) -> bytes:
            campos = subprocess.run(
                [GIT, "-C", str(repo), "ls-files", "-s", "--", nome],
                capture_output=True, text=True).stdout.split()
            assert campos, f"{nome} não está no índice"
            return subprocess.run([GIT, "-C", str(repo), "cat-file", "-p",
                                   campos[1]], capture_output=True).stdout

        def algum_objeto_tem(self, agulha: bytes) -> bool:
            return agulha in subprocess.run(
                [GIT, "-C", str(repo), "cat-file", "--batch-all-objects",
                 "--batch"], capture_output=True).stdout

    return Cen()


# ═══════════ 01 — a capacidade EXISTE para o runtime ════════════════════════

def test_a57rt_01_git_add_e_commit_sao_registrados_pelo_runtime(cen):
    """A medição que reabriu A5: as duas capacidades estavam AUSENTES."""
    rt = cen.runtime()
    caps = set(rt.capacidades_adapter)
    assert "git-add" in caps, "git-add não é alcançável pelo runtime"
    assert "git-commit" in caps, "git-commit não é alcançável pelo runtime"


def test_a57rt_02_sem_optin_a_capacidade_NAO_existe(cen):
    """Opt-in explícito: `git_tree=False` (default) não registra nada.

    Indexar e commitar tocam working tree, índice e object store. Nascer ligado
    daria ao plano uma autoridade que ninguém pediu na construção.
    """
    ctx = {"home": cen.home, "policy": PolicyEngine(cen.home / "p2.json"),
           "audit": AuditLog(cen.home / "logs" / "a2.jsonl")}
    rt = RuntimeGovernado(ctx, lambda _d: True, caminhos=(str(cen.ws),),
                          adapters=True)
    assert "git-add" not in set(rt.capacidades_adapter)


# ═══════════ 03-05 — os TRÊS caminhos, pelo runtime real ════════════════════

def test_a57rt_03_filtro_APROVADO_e_alcancavel_e_TRANSFORMA(cen):
    """ALLOW: o id está no registry injetado, e a transformação acontece."""
    (cen.repo / ".gitattributes").write_text("*.txt filter=redator\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\nresto\n")

    rt = cen.runtime(filtros_governados=cen.registro_de_filtros("redator"))
    res = cen.plano_add(rt, "segredo.txt")
    assert res.ok, res.motivo

    # CONTROLE POSITIVO: o segredo está em claro na working tree.
    assert "hunter2" in (cen.repo / "segredo.txt").read_text()
    assert cen.no_indice("segredo.txt") == b"SENHA=REDIGIDO\nresto\n"
    assert not cen.algum_objeto_tem(b"hunter2"), (
        "o conteúdo CRU chegou ao store permanente")


def test_a57rt_04_filtro_DESCONHECIDO_e_negado_pelo_runtime(cen):
    """DENY: ausência de política é negação, nunca fallback."""
    (cen.repo / ".gitattributes").write_text("*.txt filter=inexistente\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    rt = cen.runtime(filtros_governados=cen.registro_de_filtros("redator"))
    res = cen.plano_add(rt, "segredo.txt")
    assert not res.ok, "um id fora do registry foi aceito"
    assert not cen.algum_objeto_tem(b"hunter2")


def test_a57rt_05_filtro_COMUM_do_repositorio_e_negado_pelo_runtime(cen):
    """DENY: o `filter.<id>.clean` do `.git/config` não volta a executar.

    O repositório declara o filtro do jeito clássico E o runtime tem registry.
    O canário prova que o programa do repo não rodou; o índice prova que o
    conteúdo não foi transformado por ele.
    """
    canario = cen.tmp / "CANARIO"
    hostil = cen.tmp / "hostil.sh"
    hostil.write_text(f"#!/bin/sh\necho H > {canario}\nsed 's/hunter2/X/'\n")
    hostil.chmod(0o755)
    subprocess.run([GIT, "-C", str(cen.repo), "config", "filter.redator.clean",
                    str(hostil)], check=True, capture_output=True)
    (cen.repo / ".gitattributes").write_text("*.txt filter=redator\n")
    (cen.repo / "segredo.txt").write_text("SENHA=hunter2\n")

    rt = cen.runtime(filtros_governados=cen.registro_de_filtros("redator"))
    assert cen.plano_add(rt, "segredo.txt").ok
    assert not canario.exists(), (
        "o `clean` do REPOSITÓRIO executou — a config voltou a ser autoridade")
    assert cen.no_indice("segredo.txt") == b"SENHA=REDIGIDO\n", (
        "quem transformou não foi o filtro governado")


def test_a57rt_06_sem_registry_o_gitattributes_e_IGNORADO_no_runtime(cen):
    """Registry AUSENTE != registry VAZIO, também pelo runtime.

    Sem registry o `.gitattributes` não é lido, e o arquivo entra CRU — o que é
    correto: o NOMOS nunca prometeu redigir. Quem promete é a política.
    """
    (cen.repo / ".gitattributes").write_text("*.txt filter=redator\n")
    (cen.repo / "comum.txt").write_text("SENHA=hunter2\n")

    rt = cen.runtime()                       # sem `filtros_governados`
    assert cen.plano_add(rt, "comum.txt").ok
    assert cen.no_indice("comum.txt") == b"SENHA=hunter2\n"


# ═══════════ 07-10 — as quatro propriedades da injeção ══════════════════════

def test_a57rt_07_injecao_e_EXPLICITA_no_composition_root(cen):
    """O registry chega por parâmetro, e o adapter usa ESSE objeto."""
    reg = cen.registro_de_filtros("redator")
    rt = cen.runtime(filtros_governados=reg)
    assert "git-add" in set(rt.capacidades_adapter)
    assert reg.conhecidos() == ("redator",)


def test_a57rt_08_NAO_e_singleton_global(cen):
    """Dois runtimes na mesma imagem têm registries independentes.

    Singleton de módulo seria autoridade mutável por qualquer código que
    importasse o pacote — inclusive por um plugin carregado depois.
    """
    r1 = cen.registro_de_filtros("redator")
    r2 = cen.registro_de_filtros("outro")
    cen.runtime(filtros_governados=r1)
    cen.runtime(filtros_governados=r2)
    assert r1.conhecidos() == ("redator",)
    assert r2.conhecidos() == ("outro",)

    modulo = Path(fg.__file__).read_text()
    for suspeito in ("REGISTRO_GLOBAL", "_registro_padrao", "registro_global"):
        assert suspeito not in modulo, (
            f"{suspeito} sugere singleton de módulo em filtro_governado")


def _funcoes_que_leem_o_ambiente(caminho: Path) -> set[str]:
    """Nomes das funções que tocam `os.environ`, por AST e não por substring.

    Busca textual não serve aqui: `environment_allowlist` é um CAMPO legítimo
    da política e casaria com qualquer `"environ" in fonte`. O teste
    precisa da pergunta certa — QUEM lê o ambiente — e não de uma que
    acidentalmente responde outra coisa.
    """
    import ast
    arvore = ast.parse(caminho.read_text())
    achados: set[str] = set()
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dentro in ast.walk(no):
            if (isinstance(dentro, ast.Attribute)
                    and dentro.attr == "environ"
                    and isinstance(dentro.value, ast.Name)
                    and dentro.value.id == "os"):
                achados.add(no.name)
    return achados


def test_a57rt_09_NAO_vem_do_AMBIENTE(cen):
    """Nenhuma variável de ambiente define ou amplia o REGISTRY.

    A leitura de `os.environ` não é proibida em bloco: `PoliticaDeFiltro.
    ambiente()` a usa de propósito, para materializar a `environment_allowlist`
    que a POLÍTICA nomeou — a política decide, o ambiente só fornece o valor.

    O que não pode existir é ambiente definindo QUAIS FILTROS EXISTEM. Por isso
    o teste fixa a lista de funções autorizadas a ler o ambiente: qualquer
    função nova que passe a lê-lo aparece aqui e exige decisão explícita.
    """
    lendo = _funcoes_que_leem_o_ambiente(Path(fg.__file__))
    assert lendo == {"ambiente"}, (
        f"em filtro_governado, estas funções leem o ambiente: {sorted(lendo)}. "
        "Só `ambiente()` pode — e só para materializar a allowlist que a "
        "política nomeou. Registry vindo de variável herdada seria autoridade "
        "que ninguém declarou")

    git_tree_mod = __import__("nomos.adapters.git_tree", fromlist=["x"])
    lendo_tree = _funcoes_que_leem_o_ambiente(Path(git_tree_mod.__file__))
    assert lendo_tree == set(), (
        f"git_tree passou a ler o ambiente em {sorted(lendo_tree)}")


def test_a57rt_10_NAO_vem_do_REPOSITORIO(cen):
    """O repo PEDE por id; registrar é do NOMOS.

    Um `.gitattributes` que nomeie um id não registrado não pode criar a
    política — se pudesse, o `.gitattributes` seria o registry.
    """
    reg = cen.registro_de_filtros("redator")
    (cen.repo / ".gitattributes").write_text("*.txt filter=inventado\n")
    (cen.repo / "x.txt").write_text("SENHA=hunter2\n")

    rt = cen.runtime(filtros_governados=reg)
    assert not cen.plano_add(rt, "x.txt").ok
    assert reg.conhecidos() == ("redator",), (
        "o pedido do repositório alterou o registry")
