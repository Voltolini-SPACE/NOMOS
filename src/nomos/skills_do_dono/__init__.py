"""Skills do DONO — viajam no wheel, mas não são os exemplos oficiais.

Por que este pacote é separado de `skills_embutidas`
----------------------------------------------------
Os 29 manifestos do dono foram primeiro colocados dentro de
`nomos/skills_embutidas/`, e isso deixou a branch vermelha:
`tests/test_skill_sdk_v015.py` exige que os exemplos oficiais sejam
**exatamente 4** e **todos de risco baixo**. Aquele número não é capricho — é um
contrato: "o que sai de fábrica é pouco, validado e de risco baixo". Trinta e
três skills de risco misto no mesmo diretório apagam essa garantia, e o jeito
fácil de deixar verde seria afrouxar o teste, que é exatamente o que não se faz.

Então são dois lugares com dois significados:

* `skills_embutidas/` — 4 exemplos OFICIAIS, risco baixo, cobertos por teste;
* `skills_do_dono/`  — as skills do dono, risco misto, empacotadas do mesmo
  jeito e visíveis no catálogo, sem herdar a promessa de "oficial".

As duas viajam no wheel e as duas aparecem em `skills_embutidas.origens()`.
Separar não esconde nada: muda só o que cada diretório PROMETE.

Fronteira: este pacote guarda manifestos. Não instala e não autoriza — instalar
continua passando pelo gate.
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["diretorio"]


def diretorio() -> Path:
    """O diretório que viajou com o pacote instalado."""
    return Path(__file__).resolve().parent
