"""O INDICE.md não pode divergir do catálogo.

DEFEITO QUE ISTO PRENDE, medido em 23/08: o índice era escrito à mão, abria
afirmando "Estado medido nesta máquina — não é promessa, é medição", e tinha
**13 linhas dizendo "falta chave"** para skills às quais falta o CÓDIGO.
`higgsfield-bootstrad` aparecia como "pronta" sem ter um `.py`. Um documento
que se declara medição e descreve outra coisa gasta a confiança que pede.

Agora ele é GERADO. Este teste é o que impede alguém de voltar a editá-lo à
mão — sem ele, o gerador seria só uma sugestão.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
GERADOR = RAIZ / "tools" / "gerar_indice_skills.py"
INDICE = RAIZ / "src" / "nomos" / "skills_do_dono" / "INDICE.md"


def _carregar():
    if not GERADOR.exists():
        pytest.skip("gerador ausente (instalação sem a árvore do repo)")
    spec = importlib.util.spec_from_file_location("_ger", GERADOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ger"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_indice_esta_em_dia_com_o_catalogo():
    """Se falhar: `python3 tools/gerar_indice_skills.py`."""
    ger = _carregar()
    if not INDICE.exists():
        pytest.skip("INDICE.md ausente")
    assert INDICE.read_text(encoding="utf-8") == ger.render(), (
        "INDICE.md divergiu do catálogo — rode "
        "`python3 tools/gerar_indice_skills.py`")


def test_indice_avisa_que_e_gerado():
    """Sem o aviso, o próximo humano edita à mão e a divergência volta."""
    if not INDICE.exists():
        pytest.skip("INDICE.md ausente")
    t = INDICE.read_text(encoding="utf-8")
    assert "ARQUIVO GERADO" in t
    assert "gerar_indice_skills.py" in t


def test_nao_afirma_medicao_que_nao_faz():
    """A frase antiga ("não é promessa, é medição") prometia rigor que o
    arquivo não tinha. Não pode voltar."""
    if not INDICE.exists():
        pytest.skip("INDICE.md ausente")
    t = INDICE.read_text(encoding="utf-8")
    assert "não é promessa, é medição" not in t
    assert "todos validados" not in t


def _sem_comentario(t: str) -> str:
    """Tira o bloco <!-- … -->: ele CITA o erro antigo para explicar por que o
    arquivo é gerado. Citação não é afirmação — foi o mesmo cuidado que o
    teste de cor literal do painel precisou."""
    import re
    return re.sub(r"<!--.*?-->", "", t, flags=re.S)


def test_nao_chama_de_falta_de_chave_o_que_e_falta_de_codigo():
    """O erro original, em uma linha: 13 skills sem código descritas como se
    só faltasse credencial. Quem lesse compraria a chave e não resolveria."""
    if not INDICE.exists():
        pytest.skip("INDICE.md ausente")
    t = _sem_comentario(INDICE.read_text(encoding="utf-8"))
    assert "falta chave" not in t
    assert "em preparação" in t


def test_gerador_usa_home_temporaria():
    """O índice descreve o PRODUTO. Se lesse a home real, uma skill instalada
    na máquina de quem gera mudaria o arquivo versionado."""
    src = GERADOR.read_text(encoding="utf-8") if GERADOR.exists() else ""
    if not src:
        pytest.skip("gerador ausente")
    assert "tempfile.mkdtemp" in src
    assert "Path.home()" not in src


def test_pipe_na_descricao_nao_quebra_a_tabela():
    """Uma descrição contém "curl | sh". Sem escape, a linha vira 6 colunas
    e a tabela some — e justamente o aviso mais importante seria o perdido."""
    ger = _carregar()
    linha = ger._linha({"nome": "x", "risco": "alto", "status": "s",
                        "permissoes": ["A2_NET_EGRESS"],
                        "descricao": "instala via 'curl | sh' SEM CHECKSUM"})
    import re
    # conta só os separadores REAIS: `\|` é conteúdo escapado, não coluna
    separadores = len(re.findall(r"(?<!\\)\|", linha))
    assert separadores == 6, f"colunas erradas ({separadores}): {linha}"
    assert "\\|" in linha
    assert "SEM CHECKSUM" in linha


def test_check_devolve_zero_quando_em_dia():
    ger = _carregar()
    if not INDICE.exists():
        pytest.skip("INDICE.md ausente")
    assert ger.main(["--check"]) == 0
