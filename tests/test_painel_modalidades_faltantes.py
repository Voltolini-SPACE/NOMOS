"""A tabela de modalidades tem de mostrar o que NÃO está pronto.

Medido nesta máquina: `cat.prontos("ferramentas")` devolve só
`function-calling`, enquanto `cat.por_modalidade("ferramentas")` também traz
`skills` com pronto=False e detalhe "0 skill(s)". Usando só `prontos()`, a
tela dizia "ferramentas: ok" e escondia que não há skill nenhuma instalada —
meia-verdade pior que silêncio, porque soa completa.
"""
from __future__ import annotations

from pathlib import Path

from nomos.interface import painel_web as pw


def test_dados_expoem_os_nao_prontos(tmp_path):
    """`faltantes` existe e não repete o que já está em `modalidades`."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert "faltantes" in d
    for mod, pend in d["faltantes"].items():
        prontos = set(d["modalidades"].get(mod, []))
        for x in pend:
            assert x["id"] not in prontos, f"{x['id']} está nos dois lados"
            assert set(x) == {"id", "status", "detalhe"}


def test_forma_de_modalidades_nao_mudou(tmp_path):
    """`modalidades` é consumida em 4 lugares (contagem de motores prontos,
    KPI do topo, resumo). Acrescentar `faltantes` não pode alterá-la."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert isinstance(d["modalidades"], dict)
    for mod, ids in d["modalidades"].items():
        assert isinstance(ids, list)
        assert all(isinstance(i, str) for i in ids), f"{mod} não é lista de ids"


def test_pendente_e_visivelmente_secundario():
    """Some seria mentir por omissão; destacar seria alarmar sem motivo."""
    assert ".pendente{color:var(--fraco)}" in pw._CSS
    assert "var(--fraco)" in pw._CSS.split(".pendente{")[1][:40]


def test_a_tabela_renderiza_o_pendente(tmp_path):
    """Fim a fim: com um pendente nos dados, ele sai no HTML."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    d["faltantes"] = {"ferramentas": [{"id": "skills", "status": "instale",
                                       "detalhe": "0 skill(s)"}]}
    d["modalidades"] = dict(d["modalidades"])
    d["modalidades"]["ferramentas"] = ["function-calling"]
    html = pw.render_html(d)
    assert "function-calling" in html
    assert "skills" in html and "0 skill(s)" in html
    assert 'class="pendente"' in html


def test_sem_detalhe_usa_o_status(tmp_path):
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    d["faltantes"] = {"imagem": [{"id": "sdwebui", "status": "não respondeu",
                                  "detalhe": ""}]}
    html = pw.render_html(d)
    assert "não respondeu" in html
