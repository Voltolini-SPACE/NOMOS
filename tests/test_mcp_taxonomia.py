"""Fase 1.2 — taxonomia honesta: tool de conector é A3_CONNECTOR_USE.

A categoria "conector" já existia na política (rótulo "A3 · usar conector",
tradução amigável "usar uma conta conectada sua"), mas o caminho MCP rotulava
TUDO como A3_CRED_USE ("usar credencial") — menos fiel. Aqui travamos o rótulo
correto. O EFEITO não muda: segue REQUIRE_APPROVAL, ou seja, o gate continua
obrigatório. E a impressão de confiança é sobre o MANIFESTO (strings "A3"),
não sobre o mapa NIVEIS — então trocar a categoria não mexe em nenhum hash.
"""
from pathlib import Path

from nomos.interface import mcp_client as mc
from nomos.interface.mcp_catalogo import impressao
from nomos.interface.mcp_client import carregar_manifesto
from nomos.kernel.policy import Category, Effect, PolicyEngine, gate

RAIZ = Path(__file__).resolve().parent.parent
TELEGRAM = RAIZ / "examples" / "mcp" / "telegram" / "manifesto.json"


def test_niveis_a3_e_connector_use_nao_cred_use():
    assert mc.NIVEIS["A3"] is Category.CONNECTOR_USE
    assert mc.NIVEIS["A3"] is not Category.CRED_USE


def test_tool_de_conector_decide_como_connector_use_e_exige_aprovacao(tmp_path):
    eng = PolicyEngine(tmp_path / "policy.json")
    manifesto = carregar_manifesto(TELEGRAM)
    nivel = mc.nivel_da_tool(manifesto, "telegram_enviar")   # tool A3 real
    assert nivel == "A3"
    dec = eng.decide(mc.NIVEIS[nivel], target="mcp:telegram-bot:telegram_enviar")
    # rótulo fiel…
    assert dec.category == Category.CONNECTOR_USE.value == "A3_CONNECTOR_USE"
    # …e MESMO gate de sempre: sensível, exige aprovação
    assert dec.effect is Effect.REQUIRE_APPROVAL
    # sem aprovador => fail-closed (nada passa)
    assert gate(dec, None) is False
    # com aprovador que confirma => passa (o gate não sumiu, só o rótulo mudou)
    assert gate(dec, lambda d: True) is True


def test_cred_use_direto_permanece_intacto(tmp_path):
    """Usos diretos de credencial (cofre, âncora HMAC) NÃO passam por NIVEIS —
    continuam A3_CRED_USE e sensíveis."""
    eng = PolicyEngine(tmp_path / "policy.json")
    dec = eng.decide(Category.CRED_USE, target="vault:cloud_key")
    assert dec.category == "A3_CRED_USE"
    assert dec.effect is Effect.REQUIRE_APPROVAL


def test_impressao_e_estavel_e_independente_do_mapa_niveis():
    """A confiança é sobre o manifesto canônico (strings 'A3'), não sobre a
    categoria de runtime — trocar NIVEIS não muda hash nenhum."""
    manifesto = carregar_manifesto(TELEGRAM)
    # o manifesto carregado guarda o NÍVEL como string, não a Category
    assert manifesto["nivel_padrao"] == "A3"
    assert all(n == "A3" for n in manifesto["tools"].values())
    # e a impressão é determinística
    assert impressao(manifesto) == impressao(carregar_manifesto(TELEGRAM))
