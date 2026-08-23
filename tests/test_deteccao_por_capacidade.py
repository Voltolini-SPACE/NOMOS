"""O detector pergunta ao Ollama o que o modelo SABE, em vez de adivinhar pelo nome.

Bug de classe corrigido: `PREFER["visao"]` casava substring do nome
("llava","vl","vision","moondream"). `qwen3.5:4b-q8_0` declara vision no
/api/show e não casa nenhum prefixo — então todo modelo novo entrava como
"sem motor" até alguém lembrar de editar a tupla.
"""
from __future__ import annotations

import pytest

from nomos.cognition import motores


@pytest.fixture
def caps(monkeypatch):
    """Substitui a sonda de capacidades por uma tabela controlada."""
    tabela: dict[str, tuple[str, ...]] = {}
    monkeypatch.setattr(motores, "capacidades_ollama",
                        lambda n, host=None: tabela.get(n, ()))
    return tabela


def test_acha_visao_por_capacidade_e_nao_por_nome(caps):
    """O caso real: nome sem 'llava'/'vl', mas capability 'vision' declarada."""
    caps["qwen3.5:4b-q8_0"] = ("completion", "vision", "tools", "thinking")
    achado = motores._melhor_por_capacidade(
        ["qwen3.5:4b-q8_0"], "vision", prefixos=motores.PREFER["visao"])
    assert achado == "qwen3.5:4b-q8_0"
    # e o detector ANTIGO (por nome) não acharia — este é o controle:
    assert motores._melhor(["qwen3.5:4b-q8_0"], motores.PREFER["visao"]) is None


def test_nao_inventa_visao_em_quem_nao_declara(caps):
    """Se o Ollama responde e diz que não tem visão, a resposta é não."""
    caps["llama3.2:1b"] = ("completion",)
    assert motores._melhor_por_capacidade(
        ["llama3.2:1b"], "vision", prefixos=motores.PREFER["visao"]) is None


def test_fail_safe_com_ollama_antigo(caps):
    """Ollama velho não devolve capabilities: só aí volta a heurística do nome."""
    # tabela vazia => nenhuma capacidade conhecida para nenhum modelo
    assert motores._melhor_por_capacidade(
        ["llava:7b"], "vision", prefixos=motores.PREFER["visao"]) == "llava:7b"


def test_ferramentas_por_capacidade(caps):
    caps["qwen3.5:4b-q8_0"] = ("completion", "tools")
    assert motores._melhor_por_capacidade(
        ["qwen3.5:4b-q8_0"], "tools") == "qwen3.5:4b-q8_0"


# --------------------------------------------------------------------- whisper
def test_whisper_binario_sem_modelo_nao_e_pronto(monkeypatch, tmp_path):
    """A armadilha: achar o binário e cantar vitória seria uma mentira nova.

    Medido: whisper-cli sem -m morre em 'failed to open models/ggml-base.en.bin'.
    """
    monkeypatch.setattr(motores.shutil, "which",
                        lambda n: "/opt/homebrew/bin/whisper-cli"
                        if n == "whisper-cli" else None)
    monkeypatch.setattr(motores, "_DIRS_WHISPER", (str(tmp_path),))  # vazio
    monkeypatch.delenv("NOMOS_WHISPER_MODEL", raising=False)
    b, m, motivo = motores.whisper_disponivel()
    assert b and m is None
    assert "modelo ausente" in motivo


def test_whisper_acha_whisper_cli_com_modelo(monkeypatch, tmp_path):
    """whisper-cli é o nome atual do whisper.cpp no Homebrew — era ignorado."""
    modelo = tmp_path / "ggml-base.bin"
    modelo.write_bytes(b"x" * 2_000_000)
    monkeypatch.setattr(motores.shutil, "which",
                        lambda n: "/opt/homebrew/bin/whisper-cli"
                        if n == "whisper-cli" else None)
    monkeypatch.setattr(motores, "_DIRS_WHISPER", (str(tmp_path),))
    monkeypatch.delenv("NOMOS_WHISPER_MODEL", raising=False)
    b, m, motivo = motores.whisper_disponivel()
    assert b.endswith("whisper-cli") and m == str(modelo) and motivo == "pronto"


def test_whisper_ignora_arquivo_truncado(monkeypatch, tmp_path):
    """Um .bin de 3 bytes é download interrompido, não modelo."""
    (tmp_path / "ggml-base.bin").write_bytes(b"abc")
    monkeypatch.setattr(motores.shutil, "which",
                        lambda n: "/opt/homebrew/bin/whisper-cli"
                        if n == "whisper-cli" else None)
    monkeypatch.setattr(motores, "_DIRS_WHISPER", (str(tmp_path),))
    monkeypatch.delenv("NOMOS_WHISPER_MODEL", raising=False)
    _, m, motivo = motores.whisper_disponivel()
    assert m is None and "modelo ausente" in motivo


def test_openai_whisper_baixa_sozinho(monkeypatch):
    """O `whisper` do PyPI busca o modelo na 1ª execução — não exige -m."""
    monkeypatch.setattr(motores.shutil, "which",
                        lambda n: "/Users/x/.local/bin/whisper"
                        if n == "whisper" else None)
    b, m, motivo = motores.whisper_disponivel()
    assert b.endswith("/whisper") and "1ª execução" in motivo


def test_sem_binario_nenhum(monkeypatch):
    monkeypatch.setattr(motores.shutil, "which", lambda n: None)
    b, m, motivo = motores.whisper_disponivel()
    assert b is None and m is None and "nenhum binário" in motivo


# ------------------------------------------------------------------------ say
def test_say_e_motor_de_fala(monkeypatch):
    """/usr/bin/say existe em todo Mac; o detector só conhecia o piper."""
    monkeypatch.setattr(motores.shutil, "which",
                        lambda n: "/usr/bin/say" if n == "say" else None)
    assert motores.say_disponivel() == "/usr/bin/say"


def test_detectar_expoe_say_e_ferramentas(monkeypatch, caps):
    """As duas modalidades novas aparecem no mapa que o painel consome."""
    caps["qwen3.5:4b-q8_0"] = ("completion", "vision", "tools")
    monkeypatch.setattr(motores, "modelos_ollama",
                        lambda host=None: ["qwen3.5:4b-q8_0"])
    monkeypatch.setattr(motores, "_http_ok", lambda u, t=1.0: False)
    monkeypatch.setattr(motores.shutil, "which",
                        lambda n: "/usr/bin/say" if n == "say" else None)
    d = motores.detectar()
    assert "ferramentas" in d, "function calling precisa ser linha própria"
    ids = {m["id"] for m in d["audio"]}
    assert "say" in ids
    visao = [m for m in d["imagem"] if m["id"] == "visao-ollama"][0]
    assert visao["disponivel"] is True, "visão por capacidade, não por nome"


# ------------------------------------------------------- estados honestos
def test_os_cinco_estados_existem():
    """Um booleano não sabe dizer 'existe mas falta o modelo'."""
    assert motores.ORDEM_ESTADOS == (
        "ausente", "presente_sem_modelo", "configurado_nao_provado",
        "provado", "desligado_pelo_dono")


def test_binario_sem_modelo_tem_estado_proprio():
    """O caso do whisper: nem ausente, nem pronto — e o conserto é um comando."""
    m = {"id": "whisper", "disponivel": False,
         "detalhe": "binário presente, modelo ausente — baixe um ggml-*.bin"}
    e = motores.estado_de(m)
    assert e["estado"] == motores.PRESENTE_SEM_MODELO
    assert "ggml" in e["por_que"]


def test_por_que_nao_repete_identificador():
    """Regressão: `detalhe` é identificador, não motivo. 'ausente: nomos-mini'
    não ensinava nada a quem lê a tela."""
    e = motores.estado_de({"id": "embutido", "disponivel": False,
                           "detalhe": "nomos-mini"})
    assert e["por_que"] != "nomos-mini"
    assert "PATH" in e["por_que"]


def test_servico_fora_do_ar_diz_o_endereco():
    e = motores.estado_de({"id": "sdwebui", "disponivel": False,
                           "detalhe": "http://127.0.0.1:7860"})
    assert e["por_que"] == "não respondeu em http://127.0.0.1:7860"


def test_disponivel_sem_carimbo_nao_e_provado():
    """'Deveria funcionar' não é 'funcionou'."""
    e = motores.estado_de({"id": "say", "disponivel": True,
                           "detalhe": "/usr/bin/say"})
    assert e["estado"] == motores.CONFIGURADO_NAO_PROVADO


def test_carimbo_promove_para_provado():
    e = motores.estado_de({"id": "say", "disponivel": True, "detalhe": "x"},
                          provados={"say": "2026-08-23T13:00:00+00:00"})
    assert e["estado"] == motores.PROVADO
    assert "2026-08-23" in e["por_que"]


def test_escolha_do_dono_vence_a_deteccao():
    e = motores.estado_de({"id": "say", "disponivel": True, "detalhe": "x"},
                          desligados=frozenset({"say"}))
    assert e["estado"] == motores.DESLIGADO_PELO_DONO


def test_estado_publica_o_path_do_servico(monkeypatch):
    """Sem isso, todo diagnóstico em Mac vira briga de versões da realidade:
    o serviço sob launchd não tem ~/.local/bin, o terminal do dono tem."""
    monkeypatch.setenv("PATH", "/opt/homebrew/bin:/usr/bin")
    e = motores.estado_de({"id": "x", "disponivel": False, "detalhe": ""})
    assert e["path_do_servico"] == "/opt/homebrew/bin:/usr/bin"


def test_registrar_prova_persiste_e_e_lida(monkeypatch, tmp_path):
    monkeypatch.setattr(motores.config, "nomos_home", lambda: tmp_path)
    assert motores.provas() == {}
    motores.registrar_prova("say", "2026-08-23T13:00:00+00:00")
    assert motores.provas()["say"] == "2026-08-23T13:00:00+00:00"


def test_arquivo_de_provas_corrompido_nao_prova_nada(monkeypatch, tmp_path):
    """Fail-closed: JSON quebrado não pode virar 'todos provados'."""
    monkeypatch.setattr(motores.config, "nomos_home", lambda: tmp_path)
    (tmp_path / "motores_provados.json").write_text("{ isto não é json")
    assert motores.provas() == {}
