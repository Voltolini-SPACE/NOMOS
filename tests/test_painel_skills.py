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

from pathlib import Path

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


def test_explica_por_que_nao_executa():
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": ""})
    assert "Por que não há botão de executar" in html
    assert "sem cerca" in html          # diz o fato medido, não um genérico


def test_vazio_orienta_em_vez_de_parecer_erro():
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": ""})
    assert "Você ainda não tem skills" in html
    assert "Skill é uma habilidade" in html


def test_sem_exemplos_diz_a_verdade_sobre_o_empacotamento():
    """Não repetir a sugestão do CLI como se funcionasse fora do repo."""
    html = pw._secao_skills({}, {"instaladas": [], "prontas": [],
                                 "diagnostico": ""})
    assert "não vêm na instalação" in html
    assert "NOMOS_EXEMPLOS" in html


def test_lista_exemplos_quando_existem(tmp_path, monkeypatch):
    prontas = [{"nome": "busca-arquivos", "descricao": "acha arquivo",
                "caminho": "/repo/examples/skills/busca-arquivos",
                "instalada": False}]
    html = pw._secao_skills({}, {"instaladas": [], "prontas": prontas,
                                 "diagnostico": ""})
    assert "busca-arquivos" in html
    assert "nomos skills instalar /repo/examples/skills/busca-arquivos" in html
    assert "não vêm na instalação" not in html      # há exemplos: não alarma


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


def test_dados_skills_nao_estoura_sem_nada(tmp_path):
    """Máquina limpa: sem skills, sem exemplos, sem cofre — não pode explodir."""
    d = pw.dados_skills({"home": tmp_path})
    assert d["instaladas"] == [] and d["prontas"] == []
    assert d["raiz_exemplos"] is None
    assert isinstance(d["diagnostico"], str)


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
