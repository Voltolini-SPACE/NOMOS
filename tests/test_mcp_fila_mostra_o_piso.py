"""As duas portas de aprovação de conector MCP mostram a MESMA informação.

`nomos mcp confiar` aprova por dois caminhos: TTY (pergunta "CONFIO" na hora)
e FILA do painel (o dono aprova depois). O caminho TTY sempre imprimiu
`nivel_padrao` e as tools declaradas; a fila mostrava só o NOME. Mesma decisão,
menos informação — e o piso é justamente o que decide o consentimento.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

from nomos.interface import mcp_client as mc

CLI = pathlib.Path(__file__).resolve().parents[1] / "src" / "nomos" / "cli.py"


def _carregar(dados: dict) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(dados, f)
        p = f.name
    return mc.carregar_manifesto(pathlib.Path(p))


def test_piso_decide_a_tool_nao_declarada():
    """O porquê do teste seguinte: omitir o campo é fail-closed; declarar A0
    faz tool desconhecida rodar sem aprovação."""
    base = {"nome": "x", "comando": ["echo"], "tools": {}}
    assert mc.nivel_da_tool(_carregar(base), "qualquer") == "A5"
    assert mc.nivel_da_tool(_carregar({**base, "nivel_padrao": "A0"}),
                            "qualquer") == "A0"


def test_alvo_da_fila_carrega_o_piso():
    """O alvo que o dono lê na fila tem de trazer o piso do desconhecido."""
    fonte = CLI.read_text(encoding="utf-8")
    i = fonte.index("mcp:confiar:")
    trecho = fonte[i - 400:i + 200]
    assert "piso=" in trecho, "a fila voltou a aprovar sem mostrar o piso"
    assert "nivel_padrao" in trecho


def test_alvo_da_fila_declara_quantas_tools():
    fonte = CLI.read_text(encoding="utf-8")
    assert "tools_declaradas=" in fonte


def test_porta_tty_continua_imprimindo_o_piso():
    """Guarda a porta que já era honesta, para o conserto não a apagar."""
    fonte = CLI.read_text(encoding="utf-8")
    assert 'f"nível padrão: {manifesto[\'nivel_padrao\']} · "' in fonte \
        or "nível padrão:" in fonte
