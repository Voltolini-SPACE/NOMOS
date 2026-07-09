"""Propagação de capacidades — a FONTE ÚNICA reflete em README e site (gate).

Este teste é o "cadeado" da automação: se alguém adicionar uma capacidade em
``docs/CAPACIDADES.json`` e esquecer de rodar ``python tools/propagar.py --apply``,
a suíte fica VERMELHA — então a CI força a propagação. Marketing não deriva do
produto em silêncio (mesma filosofia dos invariantes SEC-01…12 e do gate
brand:site_atualizado).
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "propagar.py"


def _mod():
    spec = importlib.util.spec_from_file_location("nomos_propagar", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_registro_parseavel_e_completo():
    caps = _mod().carregar()
    assert len(caps) >= 10
    for c in caps:
        assert c.get("id") and c.get("nome") and c.get("resumo")


def test_render_deterministico():
    m = _mod()
    caps = m.carregar()
    assert m.render_site(caps) == m.render_site(caps)
    assert m.render_readme(caps) == m.render_readme(caps)


def test_marcadores_presentes_no_readme_e_site():
    m = _mod()
    for path in (ROOT / "README.md", ROOT / "site" / "index.html"):
        txt = path.read_text(encoding="utf-8")
        assert m.START in txt and m.END in txt, f"marcadores ausentes em {path.name}"


def test_repo_sincronizado():
    # O GATE: o bloco gerado tem de bater com README e site AGORA.
    m = _mod()
    problemas = m.check(m.carregar())
    assert problemas == [], (
        "capacidades dessincronizadas — rode: python tools/propagar.py --apply\n"
        + "\n".join(problemas))


def test_check_detecta_drift():
    # Se o registro ganha um item e ninguém propaga, o check tem de reclamar.
    m = _mod()
    caps = m.carregar() + [{"id": "x", "nome": "Fantasma", "resumo": "drift", "area": "x"}]
    assert m.check(caps), "o gate deveria detectar dessincronização"


def test_toda_capacidade_com_comando_aparece_no_readme():
    m = _mod()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    faltando = [c["comando"] for c in m.carregar()
                if c.get("comando") and c["comando"] not in readme]
    assert not faltando, f"comandos de capacidade fora do README: {faltando}"
