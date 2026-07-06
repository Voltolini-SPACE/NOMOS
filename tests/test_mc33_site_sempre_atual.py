"""MC33 — REGRA: o site sempre reflete o produto.

Contrato auto-verificável: todo comando top-level do CLI voltado ao usuário
(isto é, fora de SITE_COMANDOS_INTERNOS) DEVE ser mencionado em site/index.html.
Adicionar um comando novo sem atualizar o site quebra este teste e o gate de
CI `brand:site_atualizado` — o marketing não deriva do produto em silêncio.
"""
import importlib.util
from pathlib import Path

from nomos.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "tools" / "nomos_update_agent.py"


def _agent_mod():
    spec = importlib.util.spec_from_file_location("nomos_update_agent_mc33", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _comandos_top_level() -> set:
    parser = build_parser()
    for a in parser._subparsers._group_actions:
        if getattr(a, "choices", None):
            return set(a.choices)
    return set()


def test_todo_comando_de_usuario_esta_no_site():
    mod = _agent_mod()
    site = (ROOT / "site" / "index.html").read_text(encoding="utf-8").lower()
    faltando = sorted(c for c in _comandos_top_level()
                      if c not in mod.SITE_COMANDOS_INTERNOS
                      and c.lower() not in site)
    assert not faltando, (
        "estes comandos existem no CLI mas não aparecem no site — atualize "
        f"site/index.html OU marque como interno em SITE_COMANDOS_INTERNOS: "
        f"{faltando}")


def test_exclusoes_sao_comandos_reais_nao_lixo():
    """A lista de internos não pode 'esconder' comando que não existe mais
    (evita a regra ser furada por exclusão órfã)."""
    mod = _agent_mod()
    reais = _comandos_top_level()
    orfas = sorted(c for c in mod.SITE_COMANDOS_INTERNOS if c not in reais)
    assert not orfas, f"exclusões órfãs em SITE_COMANDOS_INTERNOS: {orfas}"


def test_check_brand_site_atualizado_roda_no_gate():
    mod = _agent_mod()
    agent = mod.NomosUpdateAgent(ROOT)
    agent.run_check()
    nomes = {c.name for c in agent.report.checks}
    assert "brand:site_atualizado" in nomes
    check = next(c for c in agent.report.checks
                 if c.name == "brand:site_atualizado")
    assert check.ok, check.detail       # o repo real precisa estar em dia
