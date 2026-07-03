"""Fase 4 — roteador automático: local-first, honesto, sem bypass de nuvem."""
import pytest

from nomos.cognition import engine_policy as epol
from nomos.cognition import engine_router as er
from nomos.cognition import motores
from nomos.kernel import localidade


@pytest.fixture(autouse=True)
def _base(monkeypatch, nomos_home):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _com_ollama(monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    motores.limpar_cache()


# ---------------- classificação ----------------

def test_classificar_tarefas():
    assert er.classificar("escreva um código python para ordenar").modalidade == "codigo"
    assert er.classificar("resuma este documento").modalidade == "resumo"
    assert er.classificar("planeje passo a passo a mudança").modalidade == "raciocinio"
    assert er.classificar("bom dia!").modalidade == "texto"


def test_classificar_detecta_dado_sensivel():
    t = er.classificar("qual o limite do meu cartão de crédito?")
    assert t.dados_sensiveis is True
    assert er.classificar("como plantar tomate").dados_sensiveis is False


def test_contexto_grande_vira_raciocinio():
    t = er.classificar("x" * (er.CONTEXTO_GRANDE + 1))
    assert t.modalidade == "raciocinio"


# ---------------- regras do roteador ----------------

def test_roteador_escolhe_local_quando_possivel(monkeypatch, nomos_home):
    _com_ollama(monkeypatch)
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home)
    assert dec.selected_engine == "ollama"
    assert dec.local_only_preserved is True
    assert dec.privacy_level.startswith("total")
    assert dec.estimated_cost == "grátis"
    assert dec.confidence >= 0.9


def test_local_ligado_nunca_escolhe_nuvem_nem_fallback(monkeypatch, nomos_home):
    _com_ollama(monkeypatch)
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home,
                    chave_configurada=True)
    assert dec.selected_engine != "anthropic"
    assert dec.fallback_engine != "anthropic"


def test_sem_motor_nao_inventa_e_orienta(nomos_home):
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home)
    assert dec.selected_engine is None and dec.fallback_engine is None
    assert "Próximo passo" in dec.reason
    assert "cerebro baixar" in dec.reason


def test_nuvem_exige_local_off_e_chave(monkeypatch, nomos_home):
    # local off + chave => nuvem elegível (aprovação continua obrigatória)
    localidade.definir(nomos_home, False)
    motores.limpar_cache()
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home,
                    chave_configurada=True)
    assert dec.selected_engine == "anthropic"
    assert dec.approval_required is True
    assert dec.local_only_preserved is False
    assert "saem da máquina" in dec.privacy_level
    # sem chave => nem elegível
    motores.limpar_cache()
    dec2 = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home,
                     chave_configurada=False)
    assert dec2.selected_engine is None


def test_dados_sensiveis_nunca_vao_para_nuvem(nomos_home):
    localidade.definir(nomos_home, False)
    motores.limpar_cache()
    dec = er.rotear(er.Tarefa("conversa", "texto", dados_sensiveis=True),
                    home=nomos_home, chave_configurada=True)
    assert dec.selected_engine is None   # sem local, e nuvem vetada p/ sensível


def test_contexto_grande_gera_pipeline(monkeypatch, nomos_home):
    _com_ollama(monkeypatch)
    dec = er.rotear(er.Tarefa("raciocinio", "raciocinio",
                              tamanho_contexto=er.CONTEXTO_GRANDE + 500),
                    home=nomos_home)
    assert dec.steps and "resumir contexto" in dec.steps[0]


def test_decisao_tem_todos_os_campos(monkeypatch, nomos_home):
    _com_ollama(monkeypatch)
    d = er.rotear(er.Tarefa(), home=nomos_home).dict()
    for campo in ("selected_engine", "fallback_engine", "reason",
                  "privacy_level", "approval_required", "estimated_cost",
                  "local_only_preserved", "confidence", "steps"):
        assert campo in d


def test_explicar_em_uma_linha(monkeypatch, nomos_home):
    _com_ollama(monkeypatch)
    dec = er.rotear(er.Tarefa(), home=nomos_home)
    assert "nada saiu dela" in er.explicar(dec).lower() or \
        "não saiu" in er.explicar(dec).lower()


# ---------------- modo automático ----------------

def test_auto_on_off_persistido(nomos_home):
    assert epol.auto_ligado({}) is True         # padrão ligado
    epol.definir_auto(False)
    assert epol.auto_ligado() is False
    epol.definir_auto(True)
    assert epol.auto_ligado() is True
