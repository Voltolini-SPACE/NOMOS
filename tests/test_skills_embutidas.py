"""As skills base viajam com o wheel — antes não havia de onde instalar.

Medido em 23/08 na instalação real: `(pacote)/examples` não existe, e o CLI
sugeria `nomos skills instalar examples/skills/busca-arquivos`, caminho que só
existe dentro do checkout. Duas regras somadas causavam isso: MANIFEST.in vale
para o sdist (o instalador usa wheel) e `examples/` fica fora de `src/`, logo
inalcançável por package-data.
"""
from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:      # stdlib só no 3.11+; no 3.10 o teste que o
    tomllib = None               # usa declara o fato e os demais seguem vivos

from nomos import skills_embutidas as se

BASE = ("busca-arquivos", "lembrete", "organizador", "sistema-info")


def test_as_skills_base_viajam_dentro_do_pacote():
    d = se.diretorio_embutido()
    assert d.is_dir()
    nomes = {p.name for p in d.iterdir() if (p / "skill.json").is_file()}
    for n in BASE:
        assert n in nomes, f"{n} não está empacotada"


@pytest.mark.skipif(tomllib is None, reason="tomllib é stdlib do 3.11+ — no "
                    "py3.10 este contrato é coberto pelo resto da matriz")
def test_package_data_declarado_no_pyproject():
    """Sem esta linha o diretório existe no repo e some do wheel — que era
    exatamente o defeito. O teste prende a declaração, não o arquivo."""
    raiz = Path(__file__).resolve().parent.parent
    cfg = tomllib.loads((raiz / "pyproject.toml").read_text())
    pd = cfg["tool"]["setuptools"]["package-data"]
    assert "nomos.skills_embutidas" in pd
    assert any("skill.json" in p for p in pd["nomos.skills_embutidas"])


def test_embutido_vem_primeiro_na_ordem():
    """É a única origem que existe em TODA instalação — as outras são
    circunstanciais (variável do dono, checkout de quem desenvolve)."""
    assert se.origens()[0] == se.diretorio_embutido()


def test_variavel_do_dono_entra_como_origem(monkeypatch, tmp_path):
    (tmp_path / "minha-skill").mkdir()
    (tmp_path / "minha-skill" / "skill.json").write_text("{}")
    monkeypatch.setenv(se.VAR_EXTRA, str(tmp_path))
    assert tmp_path in se.origens()
    assert "minha-skill" in {p.name for p in se.listar()}


def test_variavel_apontando_para_o_nada_e_ignorada(monkeypatch):
    """Caminho inexistente não pode virar origem — nem estourar."""
    monkeypatch.setenv(se.VAR_EXTRA, "/caminho/que/nao/existe")
    assert se.origens()[0] == se.diretorio_embutido()


def test_primeira_origem_vence_sem_silencio(monkeypatch, tmp_path):
    """Uma skill empacotada não pode ser trocada em silêncio por outra de mesmo
    nome vinda de fora — seria mudar o que o dono instala sem ele perceber."""
    impostora = tmp_path / "busca-arquivos"
    impostora.mkdir()
    (impostora / "skill.json").write_text('{"name":"impostora"}')
    monkeypatch.setenv(se.VAR_EXTRA, str(tmp_path))
    achado = se.achar("busca-arquivos")
    assert achado == se.diretorio_embutido() / "busca-arquivos"
    assert achado != impostora


def test_achar_desconhecida_devolve_none_sem_levantar():
    assert se.achar("nao-existe-em-lugar-nenhum") is None


def test_listar_nao_repete_nome(monkeypatch, tmp_path):
    dup = tmp_path / "lembrete"
    dup.mkdir()
    (dup / "skill.json").write_text("{}")
    monkeypatch.setenv(se.VAR_EXTRA, str(tmp_path))
    nomes = [p.name for p in se.listar()]
    assert nomes.count("lembrete") == 1


def test_todas_as_embutidas_tem_manifesto_legivel():
    """Skill que viaja com o produto não pode ter manifesto quebrado."""
    import json
    for p in se.diretorio_embutido().iterdir():
        mf = p / "skill.json"
        if mf.is_file():
            d = json.loads(mf.read_text())
            assert d.get("name"), f"{p.name}: manifesto sem 'name'"
            assert "permissions" in d, f"{p.name}: manifesto sem 'permissions'"
