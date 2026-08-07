"""Ciclo Simples — wizard, tradução leiga, approver 'sim', seleção Hermes, chat."""
import io

import pytest

from nomos.kernel.policy import Category, Decision, Effect
from nomos.simple import amigavel, onboarding, traducao


# ---------- tradução ----------
def test_todas_categorias_tem_frase_amigavel():
    for cat in Category:
        assert cat.value in traducao.AMIGAVEL, f"sem tradução: {cat.value}"
        frase = traducao.AMIGAVEL[cat.value]
        assert "A0" not in frase and "_" not in frase   # zero jargão


def test_explicar_decisao_contem_alvo_e_motivo():
    d = Decision(category=str(Category.NET_EGRESS.value), target="api.anthropic.com",
                 effect=Effect.REQUIRE_APPROVAL, reason="conversa cloud")
    txt = traducao.explicar_decisao(d, "Luna")
    assert "Luna" in txt and "acessar a internet" in txt
    assert "api.anthropic.com" in txt and "conversa cloud" in txt
    assert "NET_EGRESS" not in txt


# ---------- approver leigo ----------
class _TTY(io.StringIO):
    def isatty(self):
        return True


class _Pipe(io.StringIO):
    def isatty(self):
        return False


def _dec():
    return Decision(category=str(Category.CODE_EXEC.value), target="echo oi",
                    effect=Effect.REQUIRE_APPROVAL, reason="teste")


@pytest.mark.parametrize("resposta,esperado", [
    ("sim", True), ("SIM", True), ("  Sim  ", True),
    ("não", False), ("nao", False), ("s", False), ("yes", False), ("", False),
])
def test_aprovador_amigavel_contrato_sim(resposta, esperado):
    ap = traducao.aprovador_amigavel("Luna", ask=lambda _: resposta,
                                     say=lambda *_: None,
                                     entrada=_TTY(), saida=_TTY())
    assert ap(_dec()) is esperado


def test_aprovador_amigavel_nega_fora_de_tty():
    chamado = []
    ap = traducao.aprovador_amigavel("Luna", ask=lambda _: chamado.append(1) or "sim",
                                     say=lambda *_: None,
                                     entrada=_Pipe(), saida=_Pipe())
    assert ap(_dec()) is False
    assert not chamado                       # nem pergunta: fail-closed


# ---------- seleção de modelo ----------
@pytest.mark.parametrize("nomes,esperado", [
    (["llama3.2:latest", "hermes3:8b"], "hermes3:8b"),
    (["qwen2:7b", "Hermes-3-Llama:Q4"], "Hermes-3-Llama:Q4"),
    (["qwen2:7b", "llama3.2"], "llama3.2"),
    (["zephyr:beta", "qwen2:7b"], "qwen2:7b"),
    ([], None),
])
def test_escolher_modelo_prefere_hermes(nomes, esperado):
    assert onboarding.escolher_modelo(nomes) == esperado


# ---------- onboarding com streams fake ----------
def _roda_onboarding(respostas, monkeypatch, nomos_home, modelos=None):
    monkeypatch.setattr(onboarding, "listar_modelos", lambda *a, **k: modelos or [])
    feed = iter(respostas)
    linhas = []
    perfil = onboarding.run_onboarding(ask=lambda _: next(feed),
                                       say=linhas.append, colorido=False)
    return perfil, "\n".join(str(x) for x in linhas)


def test_onboarding_completo_modo_demo(monkeypatch, nomos_home):
    perfil, tela = _roda_onboarding(["Luna", "2", "", ""], monkeypatch, nomos_home)
    assert perfil["agent_name"] == "Luna"
    assert perfil["personalidade"] == "direto"
    assert perfil["modo_cerebro"] == "demo" and perfil["modelo"] is None
    assert perfil["onboarding_completo"] is True and perfil["cofre"] is False
    assert "MODO DEMO" in tela and "hermes3" in tela   # orienta o iniciante


def test_onboarding_nome_invalido_pede_de_novo(monkeypatch, nomos_home):
    perfil, _ = _roda_onboarding(["1nome!", "Atlas", "", "", ""], monkeypatch, nomos_home)
    assert perfil["agent_name"] == "Atlas"
    assert perfil["personalidade"] == "caloroso"       # Enter usa o padrão


def test_onboarding_detecta_hermes_e_cria_cofre(monkeypatch, nomos_home):
    perfil, tela = _roda_onboarding(["Jarbas", "3", "senha-bem-grande-123", ""],
                                    monkeypatch, nomos_home,
                                    modelos=["llama3.2", "hermes3:8b"])
    assert perfil["modelo"] == "hermes3:8b" and perfil["modo_cerebro"] == "local"
    assert perfil["cofre"] is True and "Hermes" in tela
    from nomos.kernel.vault import Vault
    from nomos.kernel import config as cfg
    assert Vault(cfg.nomos_home() / "vault.json").exists()


def test_onboarding_senha_curta_reorienta_e_pula(monkeypatch, nomos_home):
    perfil, tela = _roda_onboarding(["Nina", "1", "curta", "", ""], monkeypatch, nomos_home)
    assert perfil["cofre"] is False and "10" in tela   # explicou o mínimo


def test_onboarding_liga_modo_iniciante_por_padrao(monkeypatch, nomos_home):
    # MC40: sem isso, todo mundo cai no menu avançado de 10 opções.
    perfil, tela = _roda_onboarding(["Luna", "2", "", ""], monkeypatch, nomos_home)
    assert perfil["modo_iniciante"] is True
    assert "codigo:" not in tela and "imagem:" not in tela   # sem jargão de motor


# ---------- chat amigável ----------
class RouterFake:
    def __init__(self, ok=True):
        self.ok = ok
        self.recebidos = None
    def chat(self, messages, **kw):
        from nomos.cognition.router import ChatOutcome
        self.recebidos = messages
        if self.ok:
            return ChatOutcome(True, "local", "olá! tudo certo por aqui.", "ollama", "hermes3")
        return ChatOutcome(False, "degradada", "", reason="sem backend")


def _chat(perfil, router, entradas, tmp_path):
    feed = iter(entradas)
    tela = []
    ctx = {"home": tmp_path}
    rc = amigavel.iniciar_chat(ctx, perfil, router,
                               ask=lambda _: next(feed), say=tela.append,
                               colorido=False)
    return rc, "\n".join(str(x) for x in tela)


def test_chat_local_com_personalidade(tmp_path):
    perfil = {"agent_name": "Luna", "personalidade": "direto",
              "modo_cerebro": "local", "modelo": "hermes3"}
    r = RouterFake(ok=True)
    rc, tela = _chat(perfil, r, ["oi", "/sair"], tmp_path)
    assert rc == 0 and "Luna: olá!" in tela
    sistema = r.recebidos[0]
    assert sistema["role"] == "system" and "Luna" in sistema["content"]
    assert "direto" in sistema["content"] and "português" in sistema["content"]


def test_chat_demo_honesto_nunca_finge(tmp_path):
    perfil = {"agent_name": "Nina", "modo_cerebro": "demo"}
    rc, tela = _chat(perfil, RouterFake(ok=True), ["qual a capital da França?", "/sair"], tmp_path)
    assert "modo demo" in tela and "NÃO" in tela        # se declara
    assert "Paris" not in tela                          # não inventa resposta


def test_chat_memoria_anotar_e_buscar(tmp_path):
    perfil = {"agent_name": "Atlas", "modo_cerebro": "demo"}
    rc, tela = _chat(perfil, RouterFake(), [
        "/memoria anotar reunião sexta com o banco",
        "/memoria buscar banco", "/status", "/sair"], tmp_path)
    assert "anotado!" in tela and "reunião sexta com o banco" in tela
    assert "memórias: 1" in tela
