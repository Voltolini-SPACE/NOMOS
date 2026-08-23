"""Skills que VIAJAM COM O PRODUTO — instaláveis sem clonar o repositório.

Por que este pacote existe
--------------------------
Até 23/08 as skills de exemplo moravam em `examples/skills/`, na raiz do
repositório. Medido na instalação real do dono (`~/.local/share/nomos/venv`):

    (pacote)/examples existe?        False
    parents[0..2]/examples/skills →  False

E o próprio CLI sugeria `nomos skills instalar examples/skills/busca-arquivos`
— um caminho que **não existe** fora do checkout. Numa instalação normal não
havia de onde instalar skill nenhuma: o "plug-and-play" não tinha origem.

A causa não era esquecimento, eram duas regras somadas:

1. `MANIFEST.in` inclui `examples/`, mas MANIFEST.in vale para o **sdist**, e o
   instalador instala **wheel**;
2. `examples/` fica **fora de `src/`**, e `[tool.setuptools.package-data]` só
   alcança o interior de um pacote — logo aquele diretório nunca poderia ser
   empacotado onde estava.

Por isso as skills base foram movidas para cá, **dentro** de `src/nomos/`, e
declaradas em `pyproject.toml` como package-data. É o mesmo padrão que já
funcionava ao lado: `nomos.conectores` embarca `mcp/*/manifesto.json`, e o
pacote instalado tem os 7 manifestos de conector.

A ordem de procura
------------------
`origens()` devolve, em ordem: o que veio no pacote, o que o dono apontou em
`NOMOS_EXEMPLOS`, e o checkout (para quem desenvolve). Empacotado vem primeiro
de propósito: é a única origem que existe em toda instalação.

Fronteira: este módulo **acha** skills, não as instala nem as autoriza. Instalar
continua passando pelo gate — descobrir não é permitir.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["diretorio_embutido", "origens", "listar", "achar"]

NOME_MANIFESTO = "skill.json"
VAR_EXTRA = "NOMOS_EXEMPLOS"
"""Aponta um diretório extra de skills — o caminho de quem desenvolve, e a
saída honesta enquanto uma skill nova ainda não foi empacotada."""


def diretorio_embutido() -> Path:
    """O diretório que viajou junto com o pacote instalado."""
    return Path(__file__).resolve().parent


def _do_checkout() -> Path | None:
    """`examples/skills-do-dono/` do repositório, quando se roda de dentro dele.

    Existe para não quebrar o desenvolvimento: dentro do checkout as skills que
    ainda não foram empacotadas continuam visíveis. Numa instalação normal este
    caminho simplesmente não existe, e a função devolve None em vez de fingir.
    """
    aqui = Path(__file__).resolve()
    for pai in aqui.parents:
        alvo = pai / "examples" / "skills-do-dono"
        if alvo.is_dir():
            return alvo
    return None


def origens() -> list[Path]:
    """Diretórios onde procurar skills, do mais confiável ao mais circunstancial.

    1. embutido no pacote — existe em toda instalação;
    2. `NOMOS_EXEMPLOS` — escolha explícita do dono;
    3. checkout do repositório — só para quem desenvolve.
    """
    achados = [diretorio_embutido()]
    extra = os.environ.get(VAR_EXTRA)
    if extra:
        p = Path(extra).expanduser()
        if p.is_dir():
            achados.append(p)
    repo = _do_checkout()
    if repo is not None:
        achados.append(repo)
    return achados


def listar() -> list[Path]:
    """Todas as skills visíveis, sem repetir nome.

    A primeira origem vence: uma skill empacotada não é sobrescrita em silêncio
    por outra de mesmo nome vinda de `NOMOS_EXEMPLOS` ou do checkout. Silêncio
    aqui seria o caminho para trocar o que o dono instala sem ele perceber.
    """
    vistos: dict[str, Path] = {}
    for base in origens():
        for manifesto in sorted(base.glob(f"*/{NOME_MANIFESTO}")):
            vistos.setdefault(manifesto.parent.name, manifesto.parent)
    return list(vistos.values())


def achar(nome: str) -> Path | None:
    """O diretório de uma skill pelo nome, ou None. Nunca levanta."""
    for base in origens():
        alvo = base / nome
        if (alvo / NOME_MANIFESTO).is_file():
            return alvo
    return None
