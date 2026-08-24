"""Aba Skills: leitura honesta, sem prometer execução que o sistema não dá.

Duas verdades medidas que a página tem de respeitar:
  1. `plataforma.execucao_isolada_disponivel()` é False no macOS — skill sem
     rede é recusada e skill com rede roda SEM cerca. Logo: nenhum botão de
     executar na tela.
  2. As skills de exemplo NÃO são empacotadas no wheel; só existem no
     checkout do repositório. A sugestão do CLI (`nomos skills instalar
     examples/skills/…`) não funciona numa instalação normal.
"""
from __future__ import annotations


import pytest

from nomos.interface import painel_web as pw


def test_pagina_nao_tem_botao_de_executar():
    """O ponto inteiro da página. Se isto quebrar, alguém prometeu execução."""
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": ""})
    baixo = html.lower()
    for proibido in ("<button", 'type="submit"', "/skills/rodar",
                     "action=", "<form"):
        assert proibido not in baixo, f"a aba Skills ganhou {proibido!r}"


def test_explica_a_execucao_com_o_fato_ATUAL():
    """Este teste já congelou DUAS frases vencidas, e as duas eram minhas:
      v1 "skill com rede roda SEM cerca"  -> caiu quando fecharam a cerca
      v2 "skill sem rede NÃO executa aqui" -> caiu quando o perfil base chegou
    Guardar texto que descreve um fato é guardar o fato: quando ele muda, o
    teste vira defensor do erro com autoridade de suíte verde. Aqui ele prende
    o fato ATUAL e proíbe explicitamente os dois anteriores."""
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": ""})
    assert "Como a execução acontece" in html
    # o fato medido POR EFEITO — PermissionError distingue negação de timeout
    assert "PermissionError" in html
    assert "nega rede" in html
    assert "não enxerga o seu cofre" in html
    # as duas frases vencidas não voltam
    assert "sem cerca" not in html
    assert "só-Linux" not in html
    assert "não executa neste Mac" not in html


def test_diz_por_skill_se_roda_aqui():
    """Instalar e só depois descobrir que não roda é surpresa evitável."""
    prontas = [{"nome": "x", "descricao": "", "caminho": "/x",
                "instalada": False,
                "motivo_aqui": "o confinamento desse caminho é só-Linux"}]
    html = pw._secao_skills({}, {"instaladas": [], "prontas": prontas,
                                 "diagnostico": ""})
    assert "não roda neste Mac" in html
    assert "só-Linux" in html


def test_skill_que_roda_nao_ganha_aviso():
    prontas = [{"nome": "y", "descricao": "", "caminho": "/y",
                "instalada": False, "motivo_aqui": ""}]
    html = pw._secao_skills({}, {"instaladas": [], "prontas": prontas,
                                 "diagnostico": ""})
    assert "não roda neste Mac" not in html


def test_vazio_orienta_em_vez_de_parecer_erro():
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": ""})
    assert "Você ainda não tem skills" in html
    assert "Skill é uma habilidade" in html


def test_sem_skills_prontas_nao_afirma_fato_vencido():
    """A caixa já dizia "não vêm na instalação" — verdade quando medi (viviam
    em examples/, fora de src/, e o wheel não as levava) e FALSA depois que
    passaram a ser empacotadas. Texto que descreve um fato morre com o fato."""
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": ""})
    assert "não vêm na instalação" not in html
    assert "dentro do próprio pacote" in html
    assert "NOMOS_EXEMPLOS" in html


def test_lista_exemplos_quando_existem(tmp_path, monkeypatch):
    prontas = [{"nome": "busca-arquivos", "descricao": "acha arquivo",
                "caminho": "/repo/examples/skills/busca-arquivos",
                "instalada": False}]
    html = pw._secao_skills({}, {"instaladas": [], "prontas": prontas,
                                 "diagnostico": ""})
    assert "busca-arquivos" in html
    assert "nomos skills instalar /repo/examples/skills/busca-arquivos" in html
    assert "Nenhuma skill pronta" not in html       # há exemplos: não alarma


def test_marca_a_que_ja_esta_instalada():
    prontas = [{"nome": "lembrete", "descricao": "", "caminho": "/x",
                "instalada": True}]
    html = pw._secao_skills({}, {"instaladas": [], "prontas": prontas,
                                 "diagnostico": ""})
    assert "instalada" in html


def test_env_aponta_os_exemplos(tmp_path, monkeypatch):
    monkeypatch.setenv("NOMOS_EXEMPLOS", str(tmp_path / "meus"))
    raizes = pw._raizes_de_exemplos(tmp_path)
    assert raizes[0] == tmp_path / "meus", "NOMOS_EXEMPLOS tem de vir primeiro"


def test_dados_skills_nao_estoura_sem_nada(tmp_path, monkeypatch):
    """Máquina limpa: sem skills instaladas — não pode explodir.

    DEFEITO QUE ESTE TESTE JÁ TEVE (achado por outra sessão): ele afirmava
    `prontas == []` sem isolar a busca. Como `dados_skills` varre também as
    skills que vêm com o NOMOS, o resultado dependia de a instalação ser
    editável ou não, e de o diretório existir naquele instante — passava
    aqui e falhava num clone limpo. Um teste cujo veredito muda com o
    ambiente não prova nada; prende-se a busca e afirma-se o que se quer.
    """
    monkeypatch.setenv("NOMOS_EXEMPLOS", str(tmp_path / "vazio"))
    monkeypatch.setattr(pw, "_raizes_de_exemplos",
                        lambda home: [tmp_path / "vazio"])
    d = pw.dados_skills({"home": tmp_path})
    assert d["instaladas"] == []
    assert d["prontas"] == []
    assert d["raiz_exemplos"] is None
    assert isinstance(d["diagnostico"], str)


def test_skills_embutidas_sao_encontradas():
    """O contrário do de cima: sem isolar, as skills que acompanham o NOMOS
    TÊM de aparecer. Elas passaram a ser empacotadas em
    `nomos.skills_embutidas` — se a página deixar de achá-las, o dono vê
    "nenhuma skill pronta" com quatro delas instaladas no pacote."""
    from pathlib import Path as _P

    raizes = pw._raizes_de_exemplos(_P("/nao/existe"))
    try:
        from nomos import skills_embutidas as emb
    except Exception:                      # pragma: no cover
        pytest.skip("nomos.skills_embutidas ausente nesta instalação")
    assert any(r in raizes for r in emb.origens()), (
        "a página não procura onde as skills embutidas realmente estão")


def test_env_tem_prioridade_sobre_o_embutido(tmp_path, monkeypatch):
    monkeypatch.setenv("NOMOS_EXEMPLOS", str(tmp_path / "meu"))
    raizes = pw._raizes_de_exemplos(tmp_path)
    assert raizes[0] == tmp_path / "meu"


def test_manifesto_invalido_nao_derruba_a_lista(tmp_path, monkeypatch):
    """Um diretório que não é skill deve ser ignorado, não estourar a página."""
    raiz = tmp_path / "examples" / "skills"
    (raiz / "lixo").mkdir(parents=True)
    (raiz / "lixo" / "qualquer.txt").write_text("não sou manifesto")
    monkeypatch.setenv("NOMOS_EXEMPLOS", str(raiz))
    d = pw.dados_skills({"home": tmp_path})
    assert d["prontas"] == []          # ignorado em silêncio
    assert d["raiz_exemplos"] == str(raiz)


def test_vazio_separa_sei_chamar_de_tenho_instalada():
    """A meia-verdade que isto evita: `ferramentas` conta como PRONTO por
    causa do function-calling, com ZERO skills instaladas. Quem lê "pronto"
    e não lê "nenhuma instalada" entende errado."""
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": "",
                                 "sabe_chamar": "qwen3.5:4b-q8_0"})
    assert "já sabe chamar ferramentas" in html
    assert "qwen3.5:4b-q8_0" in html
    assert "falta é ter alguma instalada" in html


def test_sem_function_calling_nao_inventa_a_frase():
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": "", "sabe_chamar": None})
    assert "já sabe chamar ferramentas" not in html
