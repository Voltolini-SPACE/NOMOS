"""Validação UX — comandos do chat amigável (blindagem dos caminhos interativos)."""
from nomos.cognition import motores
from nomos.kernel.policy import PolicyEngine
from nomos.simple import amigavel


class RouterFake:
    def __init__(self, ok=True, texto="resposta do agente"):
        self.ok = ok
        self.texto = texto
        self.recebidos = None

    def chat(self, messages, **kw):
        from nomos.cognition.router import ChatOutcome
        self.recebidos = messages
        if self.ok:
            return ChatOutcome(True, "local", self.texto, "embutido", "nomos-mini")
        return ChatOutcome(False, "degradada", "", reason="sem backend")


def _chat(entradas, perfil=None, router=None, tmp_path=None, monkeypatch=None):
    perfil = perfil or {"agent_name": "Luna", "modo_cerebro": "demo"}
    feed = iter(entradas)
    tela = []
    ctx = {"home": tmp_path, "policy": PolicyEngine(tmp_path / "p.json")}
    rc = amigavel.iniciar_chat(ctx, perfil, router=router,
                               ask=lambda _: next(feed), say=tela.append,
                               colorido=False, aprovador=lambda d: True)
    return rc, "\n".join(str(x) for x in tela)


def test_ajuda_lista_comandos(tmp_path):
    _, tela = _chat(["/ajuda", "/sair"], tmp_path=tmp_path)
    for cmd in ["/chaves", "/motores", "/cerebro", "/tema", "/local", "/doutor", "/sair"]:
        assert cmd in tela


def test_status_mostra_local_e_cerebro(tmp_path, monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    _, tela = _chat(["/status", "/sair"], tmp_path=tmp_path)
    assert "só-local" in tela and "caixa-forte" in tela


def test_cerebro_orienta_baixar(tmp_path, monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    _, tela = _chat(["/cerebro", "/sair"], tmp_path=tmp_path)
    assert "cérebro" in tela.lower() and "nomos cerebro baixar" in tela


def test_local_ligado_por_padrao(tmp_path):
    _, tela = _chat(["/local", "/sair"], tmp_path=tmp_path)
    assert "só-local" in tela and "🔒" in tela


def test_nuvem_em_so_local_recusa_sem_pedir_senha(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("não deveria pedir senha")
    monkeypatch.setattr("getpass.getpass", _boom)
    _, tela = _chat(["/nuvem qual a capital?", "/sair"],
                    perfil={"agent_name": "Nina", "modo_cerebro": "local"},
                    router=RouterFake(), tmp_path=tmp_path)
    assert "só-local" in tela and "desplugada" in tela


def test_memoria_anotar_e_buscar(tmp_path):
    _, tela = _chat(["/memoria anotar pagar aluguel dia 5",
                     "/memoria buscar aluguel", "/sair"], tmp_path=tmp_path)
    assert "anotado" in tela and "pagar aluguel dia 5" in tela


def test_imagem_sem_motor_orienta(tmp_path, monkeypatch):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    motores.limpar_cache()
    _, tela = _chat(["/imagem um gato", "/sair"], tmp_path=tmp_path)
    assert "gerador de imagens" in tela


def test_audio_sem_piper_orienta(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *_: None)
    _, tela = _chat(["/audio ola mundo", "/sair"], tmp_path=tmp_path)
    assert "piper" in tela.lower() or "áudio" in tela.lower()


def test_conversa_local_usa_router(tmp_path):
    r = RouterFake(texto="olá! tudo certo.")
    _, tela = _chat(["oi tudo bem?", "/sair"],
                    perfil={"agent_name": "Luna", "modo_cerebro": "local"},
                    router=r, tmp_path=tmp_path)
    assert "olá! tudo certo." in tela
    assert r.recebidos[0]["role"] == "system"


def test_demo_nunca_finge(tmp_path):
    _, tela = _chat(["qual a capital da França?", "/sair"], tmp_path=tmp_path)
    assert "modo demo" in tela and "Paris" not in tela


def test_tema_troca_paleta(tmp_path):
    from nomos.kernel import config
    config.save_agent("Luna")
    _, tela = _chat(["/tema", "2", "/sair"],
                    perfil={"agent_name": "Luna", "modo_cerebro": "demo"}, tmp_path=tmp_path)
    assert "Floresta" in tela or "ficou assim" in tela


def test_linha_vazia_ignora(tmp_path):
    rc, tela = _chat(["", "/sair"], tmp_path=tmp_path)
    assert rc == 0


def test_demo_detecta_lembrete_e_anota(tmp_path):
    _, tela = _chat(["me lembra de ligar pro contador amanhã",
                     "/memoria buscar contador", "/sair"], tmp_path=tmp_path)
    assert "anotado" in tela
    assert "ligar pro contador" in tela          # ficou guardado de verdade


def test_demo_frase_normal_nao_vira_anotacao(tmp_path):
    _, tela = _chat(["qual a capital da França?", "/sair"], tmp_path=tmp_path)
    assert "anotado" not in tela and "modo demo" in tela
