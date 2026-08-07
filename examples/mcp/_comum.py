#!/usr/bin/env python3
"""NOMOS conectores.mcp — `_comum.py`: redação de segredo compartilhada.

Achado P1-5 da auditoria de 2026-07-17: cada conector (signal, slack,
telegram, whatsapp-cloud, email-imap, email-smtp) mantinha sua PRÓPRIA cópia
de `_redigir`, e metade delas não normalizava o segredo com `.strip()` antes
de comparar — um valor colado de um `.env` com espaço em branco extra nas
pontas escaparia da redação exatamente nessas cópias. Este módulo único,
importado por todos, fecha essa lacuna de uma vez e evita que ela reapareça
numa cópia futura.

Cada `servidor.py` roda como processo standalone (``python3 servidor.py``,
com ``cwd`` = a própria pasta do conector — veja ``comando``/``cwd=base`` no
manifesto.json e em ``ClienteMCP``), então este arquivo fica um nível ACIMA
das pastas dos conectores (``conectores/mcp/_comum.py``) e cada `servidor.py`
resolve o caminho por ``__file__`` (não por cwd, não pelo pacote `nomos`
instalado) antes de importar — funciona igual na cópia de exemplos do
repositório (`examples/mcp/`) e na cópia empacotada que vai no wheel
(`src/nomos/conectores/mcp/`), com ou sem o NOMOS instalado no ambiente.

O conector `calendario` não usa este módulo: não lida com nenhum segredo
(só o caminho de um arquivo .ics local, via ``NOMOS_ICS_PATH``).
"""
from __future__ import annotations


def redigir(texto: str, *segredos: str | None) -> str:
    """Troca toda ocorrência de cada segredo (após ``.strip()``, se não
    vazio) por ``***`` em `texto`. Segredo vazio ou ``None`` é ignorado —
    nunca troca ``""`` por ``"***"``, o que corromperia qualquer texto sem
    segredo nenhum configurado."""
    saida = texto
    for bruto in segredos:
        s = (bruto or "").strip()
        if s:
            saida = saida.replace(s, "***")
    return saida
