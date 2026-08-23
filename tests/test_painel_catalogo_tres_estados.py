"""O catálogo do painel mostra o que veio na caixa — sem dizer que está ativo.

Medido antes: `capacidades(home, skills_dir)` sem `incluir_do_pacote` devolve
0 numa instalação nova, e a tela dizia "catálogo vazio" com 33 skills dentro
do próprio wheel. Exigir `--semear` só para ENXERGAR o que já veio era o
oposto de plug-and-play.

A fronteira que este arquivo defende: **mostrar não é registrar nem
autorizar**. "vem no NOMOS" não pode ser lido como "está ativa".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nomos.interface import painel_web as pw


def _pagina(caps):
    from nomos.interface.painel_web import dados_dashboard
    return caps


def test_contrato_traz_as_empacotadas(tmp_path):
    """Sem o parâmetro: 0. Com ele: as que vieram no pacote."""
    from nomos.ext import skill_catalogo as sc
    sem = sc.capacidades(tmp_path, tmp_path / "skills")
    com = sc.capacidades(tmp_path, tmp_path / "skills", incluir_do_pacote=True)
    assert sem == [], "home vazia devia ser vazia sem o parâmetro"
    assert len(com) > 0, "o pacote traz skills e elas têm de aparecer"
    assert all(c["status"] == "vem no NOMOS" for c in com)


def test_painel_pede_as_empacotadas(tmp_path):
    """A tela tem de passar o parâmetro — senão nasce vazia mentindo."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert d["capacidades"], "o painel continua chamando sem incluir_do_pacote"


def test_mostrar_nao_e_autorizar(tmp_path):
    """A garantia que sustenta a decisão de mostrar: nada foi registrado."""
    pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert not (tmp_path / "registry" / "catalogo.json").exists()
    assert not (tmp_path / "skills").exists() or \
        list((tmp_path / "skills").glob("*")) == []


def test_cada_estado_diz_o_que_significa(tmp_path):
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    html = pw.render_html(d)
    assert "Vêm no NOMOS" in html
    # a frase que impede a leitura errada
    assert "ainda NÃO estão instaladas" in html
    assert "não porque estejam ativas" in html


def test_mostra_o_que_a_skill_toca(tmp_path):
    """Risco sem permissões é rótulo; com permissões é informação."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    html = pw.render_html(d)
    assert "toca:" in html


def test_estado_desconhecido_nao_some_da_tela(tmp_path):
    """Se o contrato ganhar um estado novo, ele aparece em vez de sumir —
    lista que filtra por lista fixa esconde o que não previu."""
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    d["capacidades"] = list(d["capacidades"]) + [
        {"nome": "z", "status": "estado-do-futuro", "risco": "baixo",
         "descricao": "", "entrada": "", "saida": "", "permissoes": []}]
    html = pw.render_html(d)
    assert "estado-do-futuro" in html and ">z<" in html


def test_contrato_antigo_nao_derruba_o_painel(tmp_path, monkeypatch):
    """Instalação sem o parâmetro novo: degrada, não quebra."""
    from nomos.ext import skill_catalogo as sc

    def so_antigo(home, skills_dir, **kw):
        if kw:
            raise TypeError("incluir_do_pacote não existe nesta versão")
        return []

    monkeypatch.setattr(sc, "capacidades", so_antigo)
    d = pw.dados_dashboard({"home": tmp_path, "skills": tmp_path / "skills"})
    assert d["capacidades"] == []


# --------------------------------------------------------------------------
# Permissão em código é honesta e ilegível — o que na prática é meia-honestidade
# --------------------------------------------------------------------------
def test_permissao_ganha_texto_em_portugues():
    html = pw._permissoes_legiveis(["A2_NET_EGRESS", "A5_CODE_EXEC"])
    assert "fala com a internet" in html
    assert "inicia outros programas" in html
    assert "A2_NET_EGRESS" in html      # o código continua, para quem o usa


def test_permissao_desconhecida_nao_some():
    """Sumir esconderia justamente a permissão que o vocabulário não previu."""
    html = pw._permissoes_legiveis(["A9_ALGO_NOVO"])
    assert "A9_ALGO_NOVO" in html


def test_sem_permissao_diz_travessao():
    assert pw._permissoes_legiveis([]) == "—"
    assert pw._permissoes_legiveis(None) == "—"


def test_resumo_da_a_forma_antes_da_lista():
    """33 fichas em sequência não respondem 'o que entrou em casa?'."""
    caps = [{"permissoes": ["A2_NET_EGRESS"]} for _ in range(26)]
    caps += [{"permissoes": ["A5_CODE_EXEC"]} for _ in range(3)]
    caps += [{"permissoes": ["A3_CRED_USE"]}]
    html = pw._resumo_permissoes(caps)
    assert "26</b> falam com a internet" in html
    assert "3</b> iniciam outros programas" in html
    assert "1</b> usam credencial do cofre" in html
    # a garantia junto do número, senão o número assusta sem contexto
    assert "nenhuma age sem você instalar e aprovar" in html


def test_resumo_omite_o_que_e_zero():
    html = pw._resumo_permissoes([{"permissoes": ["A2_NET_EGRESS"]}])
    assert "falam com a internet" in html
    assert "iniciam outros programas" not in html


def test_resumo_vazio_nao_polui():
    assert pw._resumo_permissoes([]) == ""
    assert pw._resumo_permissoes([{"permissoes": []}]) == ""


def test_a5_e_a4_contam_juntos():
    """Duas grafias para a mesma ideia; o dono lê UMA contagem."""
    caps = [{"permissoes": ["A4_PROC_SPAWN"]}, {"permissoes": ["A5_CODE_EXEC"]}]
    assert "2</b> iniciam outros programas" in pw._resumo_permissoes(caps)
