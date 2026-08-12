"""Configuração raiz do pytest.

Ignora na coleção diretórios de extração de sdist/build (ex.: ``nomos-1.3.0rc16/``),
que contêm cópias dos testes com os mesmos nomes de módulo e causariam
"import file mismatch" no pytest. Esses diretórios são artefatos de build untracked
(também ignorados no .gitignore) e não fazem parte da suíte real.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

collect_ignore_glob = ["nomos-[0-9]*"]


_FONTE_ESPIAO = r"""
#include <stdio.h>
int main(void) {
    FILE *f = fopen("%s", "w");
    if (f) { fputs("EXECUTOU\n", f); fclose(f); }
    return 0;
}
"""


@pytest.fixture
def espiao_nativo():
    """Fábrica de espião BINÁRIO para provar execução de programa do repositório.

    Vive aqui, e não num módulo de teste, porque duas baterias precisam dele e
    importar um teste a partir de outro depende de o rootdir estar em
    `sys.path` — frágil demais para a suíte de segurança.

    ## Por que binário e não script

    ATENÇÃO — a justificativa anterior deste bloco era FALSA, e ficou aqui por
    tempo suficiente para virar premissa de quem lesse depois (`.3.05`). Ela
    dizia que um espião `#!/bin/sh` "continuaria verde mesmo com a neutralização
    removida", isto é, que seria VÁCUO. RE-MEDIDO, no único regime em que
    "neutralização removida" tem efeito observável (exec AMPLO, onde a
    neutralização é a única defesa):

        neutralização PRESENTE (hooksPath + --no-verify)   canário = não
        neutralização REMOVIDA                             canário = SIM

    O espião shell DISCRIMINA — ele fica vermelho ao remover a defesa. E a
    allowlist LITERAL do push, medida, já contém `/bin/sh` E `/bin/bash`, então
    a razão dada ("o kernel precisa do interpretador") também não era o que o
    continha ali: o que contém é o caminho do HOOK não estar na allowlist.

    A escolha do espião nativo continua CERTA, por um motivo mais fraco e
    honesto: o espião em shell depende de duas defesas ao mesmo tempo (a
    allowlist do interpretador e a neutralização), então um verde dele não diz
    QUAL das duas segurou. O nativo tira o interpretador da equação e deixa uma
    causa só — se não rodou, foi a execução que foi negada.

    O padrão de anotar a afirmação como histórica em vez de apagá-la é o mesmo
    de `test_absorption07_hooks_contencao.py`: quem já leu a versão errada
    precisa encontrar a correção, não o silêncio.

    ## Por que o canário precisa morar na área gravável

    Quem usa esta fábrica tem de pôr o canário DENTRO da raiz de escrita da
    capacidade (o git dir). Fora dela, `not canario.exists()` é verdade mesmo
    quando o programa executou — porque ele não conseguiria gravar de qualquer
    jeito — e a asserção deixa de distinguir contenção de impossibilidade.
    Foi exatamente esse o defeito medido em C2a/C2b.
    """
    def fabricar(destino: Path, canario: Path) -> Path:
        fonte = Path(destino) / "espiao.c"
        fonte.write_text(_FONTE_ESPIAO % canario)
        binario = Path(destino) / "espiao"
        r = subprocess.run(["cc", "-O2", "-o", str(binario), str(fonte)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
        binario.chmod(0o755)
        return binario
    return fabricar
