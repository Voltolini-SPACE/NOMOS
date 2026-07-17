"""P1-5 da auditoria de 2026-07-17: `_redigir` deixou de ser reimplementado
em cada conector MCP — todos os que lidam com segredo (signal, slack,
telegram, whatsapp-cloud, email-imap, email-smtp) agora importam a mesma
função de `conectores/mcp/_comum.py`.

Antes da extração, metade das 6 cópias locais de `_redigir` não fazia
`.strip()` no valor do segredo antes de comparar — um token/senha colado de
um `.env` com espaço em branco extra nas pontas escaparia da redação
justamente nessas cópias. Este arquivo é o critério de aceite do achado: o
MESMO caso (segredo com espaço em branco) tem de ser redigido em TODOS os
conectores, com um único teste parametrizado.

O conector `calendario` fica de fora de propósito: não lida com segredo
nenhum (só o caminho de um arquivo .ics local via `NOMOS_ICS_PATH`).
"""
import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
MCP = RAIZ / "examples" / "mcp"

# (pasta do conector, variável de ambiente do segredo)
CONECTORES = [
    ("signal", "NOMOS_SIGNAL_NUMBER"),
    ("slack", "NOMOS_SLACK_WEBHOOK"),
    ("telegram", "NOMOS_TELEGRAM_TOKEN"),
    ("whatsapp-cloud", "NOMOS_WHATSAPP_TOKEN"),
    ("email-imap", "NOMOS_IMAP_PASSWORD"),
    ("email-smtp", "NOMOS_SMTP_PASSWORD"),
]


def _carrega(pasta: str):
    """Carrega servidor.py do jeito que ele roda de verdade: via caminho de
    arquivo, sem `nomos` no meio — replica `ClienteMCP` (cwd=pasta do
    conector) e os testes E2E de cada conector (subprocess com caminho
    absoluto). Em ambos os casos o sys.path[0] vira a pasta do conector, e é
    disso que `servidor.py` depende para achar `_comum.py` um nível acima."""
    caminho = MCP / pasta / "servidor.py"
    spec = importlib.util.spec_from_file_location(f"srv_redigir_{pasta}", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("pasta,env_var", CONECTORES, ids=[c[0] for c in CONECTORES])
def test_redigir_normaliza_espaco_em_branco_em_todos_os_conectores(pasta, env_var,
                                                                    monkeypatch):
    segredo = "s3gr3d0-de-teste-XYZ"
    # espaço em branco nas pontas — exatamente o caso que 3 das 6 cópias
    # antigas de `_redigir` deixavam vazar por não fazer `.strip()`.
    monkeypatch.setenv(env_var, f"  {segredo}  ")
    mod = _carrega(pasta)
    texto = f"falha ao chamar: valor foi {segredo} durante a operação"
    saida = mod._redigir(texto)
    assert segredo not in saida, f"{pasta}: segredo vazou em {saida!r}"
    assert "***" in saida


@pytest.mark.parametrize("pasta,env_var", CONECTORES, ids=[c[0] for c in CONECTORES])
def test_redigir_sem_segredo_configurado_nao_corrompe_o_texto(pasta, env_var,
                                                               monkeypatch):
    # trava específica do _comum.py: segredo vazio/ausente NUNCA troca ""
    # por "***" (o que geraria "***" espalhado por qualquer texto).
    monkeypatch.delenv(env_var, raising=False)
    mod = _carrega(pasta)
    texto = "erro comum, sem nenhum segredo no meio"
    assert mod._redigir(texto) == texto


def test_todos_os_conectores_com_segredo_importam_o_modulo_comum():
    # trava anti-regressão estrutural: garante que a extração aconteceu de
    # verdade e que ninguém reintroduziu uma cópia local de `_redigir`.
    for pasta, _env in CONECTORES:
        codigo = (MCP / pasta / "servidor.py").read_text(encoding="utf-8")
        assert "from _comum import redigir as _redigir_comum" in codigo, pasta
        assert codigo.count("def _redigir(") == 1, pasta


def test_calendario_nao_importa_comum_por_nao_ter_segredo():
    codigo = (MCP / "calendario" / "servidor.py").read_text(encoding="utf-8")
    assert "_comum" not in codigo
