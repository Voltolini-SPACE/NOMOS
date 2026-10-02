"""Componente NOMOS Reversa — mapeamento read-only de ferramentas de terceiros (MC65).

A regra Voltolini de validação exige mapear a ferramenta desejada antes de
adotá-la. Este componente é a ferramenta nossa que faz esse mapa.
"""

from nomos.reversa.mapa import (
    VERSAO,
    Achado,
    Mapa,
    classificar_licenca,
    mapear,
    para_dict,
    relatorio,
)

__all__ = ["VERSAO", "Achado", "Mapa", "classificar_licenca", "mapear",
           "para_dict", "relatorio"]
