"""v0.18 — cognição avançada: feedback local, visão local, lote paralelo."""
import io
import json

import pytest

from nomos import cli
from nomos.cognition import engine_router as er
from nomos.cognition import feedback as fb
from nomos.cognition import motores, visao
from nomos.cognition.engine_pipeline import EnginePipeline, PipelineStep
from nomos.kernel.policy import Category, PolicyEngine


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


# ---------------- feedback local ----------------

def test_feedback_registra_e_taxa_exige_sinal(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    fb.registrar(nomos_home, "ollama", True)
    assert fb.taxa(nomos_home, "ollama") is None      # 1 voto não é sinal
    fb.registrar(nomos_home, "ollama", True)
    fb.registrar(nomos_home, "ollama", False)
    assert fb.taxa(nomos_home, "ollama") == pytest.approx(2 / 3)
    assert fb.taxa(nomos_home, "desconhecido") is None


def test_roteador_rebaixa_motor_mal_avaliado(monkeypatch, nomos_home):
    """Com embutido e ollama prontos, feedback ruim no ollama muda a escolha."""
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    from nomos.cognition import embutido as emb
    monkeypatch.setattr(emb, "llama_disponivel", lambda: True)
    monkeypatch.setattr(emb, "esta_baixado", lambda *a: True)
    motores.limpar_cache()
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home)
    assert dec.selected_engine == "ollama"            # qualidade alta vence
    for _ in range(4):
        fb.registrar(nomos_home, "ollama", False)     # 4x 👎
    motores.limpar_cache()
    dec2 = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home)
    assert dec2.selected_engine == "embutido"         # seu voto local mandou
    assert dec2.fallback_engine == "ollama"


def test_confianca_reflete_feedback(monkeypatch, nomos_home):
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: ["hermes3:8b"])
    motores.limpar_cache()
    for _ in range(5):
        fb.registrar(nomos_home, "ollama", True)
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home)
    assert "feedback local: 100% positivo" in dec.reason
    assert dec.confidence >= 0.85


def test_cli_motores_feedback(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["motores", "feedback", "ollama", "bom"]) == 0
    out = capsys.readouterr().out
    assert "1x 👍" in out and "só na sua máquina" in out


# ---------------- visão local ----------------

def test_visao_valida_formato_e_host(tmp_path):
    img = tmp_path / "foto.png"
    img.write_bytes(b"\x89PNG fake")
    with pytest.raises(visao.VisaoError, match="não encontrada"):
        visao.descrever(tmp_path / "nada.png", "llava")
    (tmp_path / "doc.txt").write_text("x")
    with pytest.raises(visao.VisaoError, match="não suportado"):
        visao.descrever(tmp_path / "doc.txt", "llava")
    with pytest.raises(visao.VisaoError, match="loopback"):
        visao.descrever(img, "llava", host="http://exemplo.com:11434")


def test_visao_com_transporte_injetado(tmp_path):
    img = tmp_path / "foto.jpg"
    img.write_bytes(b"JPEG fake")
    visto = {}

    def fake_transporte(url, dados, timeout):
        visto["url"] = url
        visto["payload"] = json.loads(dados)
        return {"message": {"content": "um gato laranja dormindo"}}

    texto = visao.descrever(img, "llava:7b", transporte=fake_transporte)
    assert texto == "um gato laranja dormindo"
    assert visto["url"].startswith("http://127.0.0.1")
    assert visto["payload"]["model"] == "llava:7b"
    assert visto["payload"]["messages"][0]["images"]      # imagem embarcada


def test_visao_sem_motor_erro_honesto(tmp_path):
    img = tmp_path / "foto.png"
    img.write_bytes(b"png")

    def transporte_morto(url, dados, timeout):
        raise OSError("connection refused")
    with pytest.raises(visao.VisaoError, match="ollama pull llava"):
        visao.descrever(img, "llava", transporte=transporte_morto)


# ---------------- catálogo estendido ----------------

def test_catalogo_embutido_tem_modelos_grandes():
    from nomos.cognition import embutido as emb
    ids = [m.id for m in emb.CATALOGO]
    assert "nomos-pro" in ids and "nomos-max" in ids
    assert emb.recomendado(32.0).id == "nomos-max"
    assert emb.recomendado(2.0).id == "nomos-mini"    # leve continua leve


# ---------------- pipeline paralelo ----------------

def test_run_parallel_executa_independentes(nomos_home):
    engine = PolicyEngine(nomos_home / "policy.json")
    passos = [
        PipelineStep("resumir", "embutido", Category.READ_LOCAL,
                     executar=lambda x: f"resumo({x})"),
        PipelineStep("extrair", "heuristica", Category.READ_LOCAL,
                     executar=lambda x: f"pontos({x})"),
    ]
    r = EnginePipeline(passos, engine, None).run_parallel("doc")
    assert r.ok and r.saida == {"resumir": "resumo(doc)", "extrair": "pontos(doc)"}
    assert "Nada saiu da sua máquina" in r.explicacao


def test_run_parallel_negacao_cancela_lote_antes_de_executar(nomos_home):
    engine = PolicyEngine(nomos_home / "policy.json")
    executou = []
    passos = [
        PipelineStep("ler", "m", Category.READ_LOCAL,
                     executar=lambda x: executou.append("ler")),
        PipelineStep("gravar", "m", Category.WRITE_LOCAL,   # exige aprovação
                     executar=lambda x: executou.append("gravar")),
    ]
    r = EnginePipeline(passos, engine, approver=None).run_parallel("x")
    assert r.ok is False and r.etapa_falhou == "gravar"
    assert executou == []                    # NADA rodou: negação cancela o lote


def test_run_parallel_erro_e_falha_honesta(nomos_home):
    engine = PolicyEngine(nomos_home / "policy.json")
    passos = [
        PipelineStep("ok", "m", Category.READ_LOCAL, executar=lambda x: "vai"),
        PipelineStep("explode", "m", Category.READ_LOCAL,
                     executar=lambda x: (_ for _ in ()).throw(ValueError("x"))),
    ]
    r = EnginePipeline(passos, engine, None).run_parallel("x")
    assert r.ok is False and r.etapa_falhou == "explode"
    assert "pela metade" in r.explicacao
