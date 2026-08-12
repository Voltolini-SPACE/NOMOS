"""C6 — A6 vale para o FILTRO governado também, e não valia.

`confinamento_de_repo` nega `hooks/`, `config` e `info/` ao processo do GIT — os
três lugares de onde o repositório faz código sobreviver à operação. O filtro
governado (A5.5) montava o confinamento dele a partir da política e **não
herdava nada disso**.

MEDIDO, com `write_roots=(repo,)` — o valor natural para um redator que grava no
próprio repositório — a sonda de escrita do `redator.c` gravou `PLANTADO` em:

    .git/hooks/pre-commit      programa que o Git executa em eventos futuros
    .git/info/attributes       liga arquivo a filtro, como .gitattributes
    .gitattributes             idem, versionado

todos com `rc=0`. A assimetria era o furo inteiro: contém-se o Git e deixa-se o
programa que o Git chamou instalar o PRÓXIMO. A contenção valeria uma execução
só — exatamente a propriedade que A6 existe para negar.

## Por que negar o `.git` inteiro e não os três nomes

Um filtro de conteúdo lê stdin e escreve stdout; ele não tem o que fazer dentro
de um diretório Git. Enumerar `hooks`, `config` e `info` deixaria `index`,
`objects` e `refs` de fora — e é assim que esta série já se queimou uma vez, ao
tentar descer abaixo do git dir com allowlist (`HEAD.lock` transitório, depois
`cannot lock ref 'AUTO_MERGE'` com rc=0, degradação silenciosa).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import supervisor

FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


@pytest.fixture
def cen(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["/usr/bin/git", "init", "-q", "-b", "main", str(repo)],
                   check=True, capture_output=True)
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)

    class Cen:
        def __init__(self):
            self.repo, self.tmp, self.binario, self.art = repo, tmp_path, binario, art

        def politica(self, *argv):
            return fg.PoliticaDeFiltro(
                filter_id="redator", canonical_executable=str(binario),
                managed_artifact=art, argv_policy=tuple(argv),
                read_roots=(str(repo),), write_roots=(str(repo),))

        def sondar_escrita(self, alvo: Path):
            """Roda a sonda NATIVA sob o confinamento REAL da política.

            `tipo=FILTRO_GOVERNADO` e `entrada=` são os mesmos que
            `_aplicar_filtro_governado` usa: medir com outro tipo de processo
            mediria outro ambiente, e o resultado não valeria para o caminho real.
            """
            pol = self.politica("--sonda-escrita", str(alvo))
            return supervisor.executar(
                pol.comando(), cwd=repo, env=pol.ambiente(), prazo=10.0,
                confinamento=pol.confinamento(),
                tipo=supervisor.TipoDeProcesso.FILTRO_GOVERNADO, entrada=b"")

    return Cen()


ALVOS = [
    (".git/hooks/pre-commit", "programa que o Git executa em eventos futuros"),
    (".git/info/attributes", "liga arquivo a filtro, como .gitattributes"),
    (".git/config", "filter.*.clean, core.fsmonitor, aliases com !"),
    (".git/index", "o índice não é conteúdo, e o filtro só transforma conteúdo"),
    (".gitattributes", "FONTE DE ATRIBUTO na working tree: escolhe qual filtro "
                       "roda na PRÓXIMA operação"),
    ("sub/.gitattributes", "e vale em QUALQUER profundidade, inclusive num "
                           "diretório que o próprio filtro criar"),
]


@pytest.mark.parametrize("relativo,porque", ALVOS)
def test_c6_filtro_governado_NAO_escreve_no_git_dir(cen, relativo, porque):
    """Cada alvo é um jeito diferente de a contenção valer uma vez só."""
    alvo = cen.repo / relativo
    alvo.parent.mkdir(parents=True, exist_ok=True)
    cen.sondar_escrita(alvo)

    # O critério é o EFEITO no disco, não o rc: a sonda pode sair 0 e não ter
    # escrito, e pode sair != 0 depois de escrever. Só o arquivo decide.
    escreveu = alvo.exists() and alvo.read_bytes() == b"PLANTADO\n"
    assert not escreveu, (
        f"o filtro governado escreveu em {relativo} ({porque}) — um filtro "
        "contido que instala o próximo torna a contenção válida por UMA execução")


def test_c6_CONTROLE_POSITIVO_a_sonda_escreve_onde_a_politica_permite(cen):
    """Sem este controle, os quatro acima passariam com a sonda quebrada.

    O mesmo binário, o mesmo argv, o mesmo confinamento — mudando só o alvo para
    a área que a política REALMENTE concede. Se este falhar, os testes de recusa
    não medem contenção, medem sonda morta.
    """
    alvo = cen.repo / "saida.txt"
    p = cen.sondar_escrita(alvo)

    assert p.returncode == 0, f"a sonda não rodou: {p.stderr[:300]!r}"
    assert alvo.read_bytes() == b"PLANTADO\n", (
        "a sonda não conseguiu escrever nem na área concedida — o teste de "
        "recusa acima não distingue contenção de sonda quebrada")


def test_c6_CONTROLE_a_area_concedida_continua_gravavel_apos_a_negacao(cen):
    """A negação não pode ter comido a raiz de escrita inteira."""
    conf = cen.politica().confinamento()
    assert conf.escrita == (str(cen.repo),)
    assert conf.negacao_de_escrita, "nenhuma negação foi declarada"


def test_c6_negacao_cobre_o_git_dir_INTEIRO_nao_so_tres_nomes(cen):
    """Estrutural: enumerar `hooks/config/info` deixaria index/objects/refs.

    Prende a decisão de projeto. Alguém que "simplifique" a negação para os três
    nomes de A6 reabre a escrita em `.git/objects` e `.git/refs` — que é pior,
    porque lá o filtro planta OBJETO e REF, não só configuração.
    """
    conf = cen.politica().confinamento()
    negados = set(conf.negacao_de_escrita)
    assert f"{cen.repo}/.git" in negados, (
        "a negação não cobre o git dir inteiro; index, objects e refs ficariam "
        "graváveis pelo filtro")


@pytest.mark.parametrize("rel", [
    ".git/hooks/pre-commit", ".git/config", ".git/refs/heads/plantado",
])
def test_c6_git_ANINHADO_na_raiz_de_escrita_nao_e_gravavel(tmp_path, rel):
    """`.11.10`/`.11.11` (P0): negar o NOME `.git` não bastava.

    A negação por nome era emitida como `(deny file-write* (regex #"/\\.git$"))`
    — ancorada no FIM. Isso nega o DIRETÓRIO `.git` e deixa TODO o conteúdo
    gravável, porque `<raiz>/proj/.git/hooks/pre-commit` não termina em
    `/.git`. O filtro instalava hook, reescrevia config e plantava ref dentro
    de qualquer repositório aninhado na raiz de escrita.

    Para `.gitattributes`, que é ARQUIVO, o `$` bastava; para `.git`, que é
    DIRETÓRIO, não. Dois casos cobertos aqui: `write_roots` ANCESTRAL (o valor
    natural quando o escopo do filtro é o workspace) e `write_roots=(repo,)` (o
    valor que a própria suíte usa), porque o `.git` aninhado alcança os dois.
    """
    from nomos.adapters import filtro_governado as fg
    from nomos.adapters import supervisor as sup

    raiz = tmp_path / "raizes"
    raiz.mkdir()
    proj = raiz / "proj"
    proj.mkdir()
    subprocess.run(["/usr/bin/git", "init", "-q", "-b", "main", str(proj)],
                   capture_output=True)
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C: {r.stderr[:160]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)

    for escopo in (raiz, proj):
        alvo = proj / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        pol = fg.PoliticaDeFiltro(
            filter_id="f", canonical_executable=str(binario),
            managed_artifact=art, argv_policy=("--sonda-escrita", str(alvo)),
            read_roots=(str(escopo),), write_roots=(str(escopo),))
        sup.executar(pol.comando(), cwd=proj, env=pol.ambiente(), prazo=10.0,
                     confinamento=pol.confinamento(),
                     tipo=sup.TipoDeProcesso.FILTRO_GOVERNADO, entrada=b"")
        plantou = alvo.exists() and alvo.read_bytes() == b"PLANTADO\n"
        assert not plantou, (
            f"o filtro plantou {rel} num `.git` ANINHADO com "
            f"write_roots={escopo.name!r} — a negação por nome não cobre o "
            "conteúdo do diretório")
