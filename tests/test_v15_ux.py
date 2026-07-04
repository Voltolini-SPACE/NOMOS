"""F4 — UX: memória tipada, candidatas, erro humano, modo iniciante."""
import io

import pytest

from nomos.cognition.memory import Memory
from nomos.simple import erros
from nomos.simple.menu_principal import menu_principal


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ---------------- memória tipada ----------------

def test_memoria_tipada_e_compat_com_busca(nomos_home):
    mem = Memory(nomos_home / "m.db")
    mid = mem.remember_typed("prefiro respostas curtas", tipo="preferencia",
                             fonte="conversa")
    assert mid > 0
    # continua achável pela busca (guardada como note)
    achados = mem.recall_hibrido("respostas curtas")
    assert any("respostas curtas" in i.text for i in achados)


def test_tipo_invalido_recusado(nomos_home):
    mem = Memory(nomos_home / "m.db")
    with pytest.raises(ValueError, match="tipo de memória inválido"):
        mem.remember_typed("x", tipo="telepatia")


def test_migracao_de_banco_antigo(nomos_home):
    """Banco criado sem as colunas novas migra sem perder nada."""
    import sqlite3
    p = nomos_home / "antigo.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, ts REAL, "
                 "role TEXT, text TEXT)")
    conn.execute("INSERT INTO memories(ts, role, text) VALUES (1, 'note', 'antiga')")
    conn.commit()
    conn.close()
    mem = Memory(p)                            # migra ao abrir
    assert any("antiga" in i.text for i in mem.recent(10))
    mem.remember_typed("nova preferência", tipo="preferencia")   # colunas existem


def test_contradicoes_detecta_parecidas(nomos_home):
    mem = Memory(nomos_home / "m.db")
    mem.remember_typed("meu horário de trabalho é das 9 às 18", tipo="fato")
    cont = mem.contradicoes("meu horário de trabalho é das 8 às 17")
    assert cont and any("horário de trabalho" in i.text for i in cont)


# ---------------- candidatas (ISSUE-020) ----------------

def test_candidata_nao_vira_memoria_sem_aprovacao(nomos_home):
    mem = Memory(nomos_home / "m.db")
    cid = mem.propor_candidata("o usuário mora em Curitiba", tipo="fato")
    assert len(mem.candidatas()) == 1
    # não está na memória "de verdade" ainda
    assert not any("Curitiba" in i.text for i in mem.recent(50))
    # aprovar promove; descartar remove
    mid = mem.aprovar_candidata(cid)
    assert mid and mem.candidatas() == []
    assert any("Curitiba" in i.text for i in mem.recent(50))


def test_descartar_candidata(nomos_home):
    mem = Memory(nomos_home / "m.db")
    cid = mem.propor_candidata("dado incerto", tipo="fato")
    assert mem.descartar_candidata(cid) is True
    assert mem.candidatas() == []


# ---------------- erro humano (ISSUE-021) ----------------

def test_todo_codigo_tem_explicacao_humana():
    for cod in erros.CODIGOS:
        txt = erros.explicar(cod)
        assert txt.startswith(f"[{cod}]") and len(txt) > len(cod) + 5


def test_explicar_traz_proximo_passo():
    assert "nomos vault init" in erros.explicar("E001")
    assert "diagnostico" in erros.explicar("E007")


# ---------------- modo iniciante (ISSUE-022) ----------------

def test_menu_iniciante_esconde_avancado(nomos_home):
    ditos = []
    respostas = iter(["10"])
    menu_principal({"home": nomos_home}, {"modo_iniciante": True}, {},
                   ask=lambda p: next(respostas), say=ditos.append)
    tudo = "\n".join(ditos)
    assert "modo iniciante" in tudo
    assert "Gerenciar skills" not in tudo       # avançado escondido
    assert "Conversar com meu agente" in tudo   # essencial visível


def test_menu_alterna_para_avancado(nomos_home):
    ditos, chamou = [], []
    acoes = {"5": lambda: chamou.append("skills") or 0}
    respostas = iter(["avancado", "5", "10"])
    menu_principal({"home": nomos_home}, {"modo_iniciante": True}, acoes,
                   ask=lambda p: next(respostas), say=ditos.append)
    assert chamou == ["skills"]                 # opção avançada acessível após alternar
    assert "modo avançado ligado" in "\n".join(ditos)
