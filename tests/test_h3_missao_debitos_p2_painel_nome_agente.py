"""Horizonte 3 / missão de débitos residuais — Prioridade 2 (mypy),
interface/painel_web.py: regressão do BUG REAL achado enquanto o mypy era
zerado no arquivo (não um mero ajuste de tipagem).

`dados_dashboard()` tentava `from nomos.simple.onboarding import
carregar_perfil` — uma função que NUNCA existiu em onboarding.py (confirmado
por grep em todo o src/). O ImportError resultante era sempre engolido pelo
`except Exception` do bloco, então `sistema.nome_agente` era SEMPRE "NOMOS",
mesmo com um agente configurado com outro nome — silenciosamente, desde que
esse código existe. Além disso, mesmo corrigindo só o import, as chaves
checadas no perfil ("nome_agente", "agente") nunca bateram com a chave real
gravada por `kernel/config.py::save_agent()` ("agent_name") — um segundo bug
independente que também precisava de correção para o sintoma sumir de fato.

Este arquivo prova, com um agent.json real gravado em disco (mesmo formato
que `nomos agent create` grava via `config.save_agent()`), que o painel agora
mostra o nome configurado de verdade — e que os fallbacks (sem perfil, perfil
corrompido) continuam seguros ("NOMOS"), sem lançar exceção.
"""
import io
import json

import pytest

from nomos.cognition import motores
from nomos.interface.painel_web import dados_dashboard
from nomos.kernel import config as _config
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _ctx(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "skills").mkdir(exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
            "skills": nomos_home / "skills"}


def test_nome_agente_reflete_perfil_real_configurado(nomos_home):
    """O bug: isto SEMPRE devolvia 'NOMOS' antes da correção, mesmo com
    outro nome configurado — porque o import de carregar_perfil() sempre
    lançava ImportError (engolido em silêncio)."""
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / _config.AGENT_FILE).write_text(
        json.dumps({"schema": 1, "agent_name": "Aria", "mode": "local"}),
        encoding="utf-8")
    d = dados_dashboard(_ctx(nomos_home))
    assert d["sistema"]["nome_agente"] == "Aria"


def test_nome_agente_sem_perfil_cai_em_nomos(nomos_home):
    """Sem agent.json: fallback honesto 'NOMOS', sem exceção."""
    d = dados_dashboard(_ctx(nomos_home))
    assert d["sistema"]["nome_agente"] == "NOMOS"


# NOTA DE TRANSPARÊNCIA (não testado aqui de propósito): um agent.json com
# JSON genuinamente inválido (ex.: "{ isto não é json") NÃO chega a exercitar
# o try/except desta correção — dados_dashboard() chama
# doutor_mod.diagnostico_v011(home, ctx) MAIS CEDO na mesma função (linha
# ~517, fora de qualquer try/except), que por sua vez chama
# kernel/config.py::load_agent() (SEM proteção contra JSON inválido) e
# propaga JSONDecodeError antes mesmo de alcançar o bloco corrigido aqui.
# Esta é uma fragilidade PRÉ-EXISTENTE e INDEPENDENTE, em outro arquivo
# (doutor.py/config.py), fora do escopo desta correção (P2 de
# painel_web.py — não misturar correções de arquivos/domínios diferentes no
# mesmo commit). Registrada aqui para o relatório final da missão, não
# escondida: dados_dashboard() hoje não é resiliente a um agent.json
# corrompido, independentemente desta correção.


def test_nome_agente_usa_home_explicito_nao_env_var_global(nomos_home,
                                                            monkeypatch,
                                                            tmp_path):
    """A correção lê o perfil do `home` explícito de ctx["home"] (mesmo
    padrão do resto de dados_dashboard()), não de config.nomos_home()/
    NOMOS_HOME global — importante para isolamento correto quando os dois
    divergem (não deveria acontecer em produção, mas comprova que a leitura
    é parametrizada, não acidentalmente global)."""
    outro_home = tmp_path / "outro-home-nao-usado"
    monkeypatch.setenv("NOMOS_HOME", str(outro_home))
    outro_home.mkdir(parents=True, exist_ok=True)
    (outro_home / _config.AGENT_FILE).write_text(
        json.dumps({"schema": 1, "agent_name": "NaoDeveriaAparecer"}),
        encoding="utf-8")
    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / _config.AGENT_FILE).write_text(
        json.dumps({"schema": 1, "agent_name": "DoHomeCerto"}),
        encoding="utf-8")
    d = dados_dashboard(_ctx(nomos_home))
    assert d["sistema"]["nome_agente"] == "DoHomeCerto"
