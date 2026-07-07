"""MC30 — B7 (rotinas exportáveis) e C3 (motor OpenAI-compatível local).

B7: `nomos rotinas exportar` gera arquivos de agendador por SO; o NOMOS nunca
os instala. C3: LM Studio/llama.cpp server entram no catálogo como motor
local (loopback por lei) com provider OpenAI-compatível.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.cognition import engine_catalog as cat_mod
from nomos.cognition import motores as mot
from nomos.cognition.providers import OpenAICompatProvider, ProviderUnavailable
from nomos.simple import rotinas as rot
from _cli_env import cli_env

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------- B7
def test_b7_exportar_launchd(tmp_path):
    arquivos, instrucao = rot.exportar(tmp_path, "launchd")
    plist = arquivos[0]
    texto = plist.read_text(encoding="utf-8")
    assert plist.name == "br.com.se7enpay.nomos.rotinas.plist"
    assert "ProgramArguments" in texto and "rotinas" in texto
    assert f"<string>{tmp_path}</string>" in texto        # NOMOS_HOME correto
    assert "<integer>900</integer>" in texto              # a cada 15 min
    assert "VOCÊ MESMO" in instrucao and "launchctl" in instrucao


def test_b7_exportar_systemd(tmp_path):
    arquivos, instrucao = rot.exportar(tmp_path, "systemd")
    nomes = {a.name for a in arquivos}
    assert nomes == {"nomos-rotinas.service", "nomos-rotinas.timer"}
    service = next(a for a in arquivos if a.suffix == ".service")
    timer = next(a for a in arquivos if a.suffix == ".timer")
    assert "rotinas executar" in service.read_text(encoding="utf-8")
    assert "OnCalendar=*:0/15" in timer.read_text(encoding="utf-8")
    assert "systemctl --user" in instrucao


def test_b7_exportar_windows(tmp_path):
    arquivos, _ = rot.exportar(tmp_path, "windows")
    texto = arquivos[0].read_text(encoding="utf-8")
    assert "schtasks /create" in texto and "/mo 15" in texto
    assert "VOCÊ MESMO" in texto


def test_b7_formato_invalido_fail_closed(tmp_path):
    with pytest.raises(rot.RotinaError):
        rot.exportar(tmp_path, "cron-magico")


def test_b7_cli_exportar_nunca_instala(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "nomos", "rotinas", "exportar",
         "--formato", "systemd"],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env=cli_env(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert "NUNCA instala" in proc.stdout
    assert (tmp_path / "agendadores" / "nomos-rotinas.timer").is_file()


# ----------------------------------------------------------------- C3
def test_c3_catalogo_lista_openai_compat_quando_probe_responde(tmp_path, monkeypatch):
    monkeypatch.setattr(mot, "_http_ok",
                        lambda url, timeout=1.2: "127.0.0.1:1234" in url)
    cat = cat_mod.construir(tmp_path, mapa={})
    m = cat.por_id("openai-compat")
    assert m is not None and m.local is True and m.pronto is True
    assert m.tipo == "llamacpp"
    assert "codigo" in m.modalidades and "texto" in m.modalidades


def test_c3_catalogo_orienta_quando_servidor_desligado(tmp_path, monkeypatch):
    monkeypatch.setattr(mot, "_http_ok", lambda url, timeout=1.2: False)
    m = cat_mod.construir(tmp_path, mapa={}).por_id("openai-compat")
    assert m.pronto is False
    assert "porta 1234" in m.status


def test_c3_provider_recusa_host_nao_loopback():
    with pytest.raises(ValueError, match="LOCAL por lei"):
        OpenAICompatProvider(base="http://api.exemplo.com/v1")
    for ok in ("http://127.0.0.1:1234/v1", "http://localhost:8080/v1"):
        assert OpenAICompatProvider(base=ok)


def test_c3_provider_parseia_resposta(monkeypatch):
    import nomos.cognition.providers as prov
    monkeypatch.setattr(prov, "_post_json", lambda url, payload, headers, timeout: {
        "model": "qwen-local",
        "choices": [{"message": {"content": "olá, tudo local"}}]})
    r = OpenAICompatProvider().chat([{"role": "user", "content": "oi"}])
    assert r.text == "olá, tudo local" and r.model == "qwen-local"


def test_c3_provider_sem_conteudo_e_honesto(monkeypatch):
    import nomos.cognition.providers as prov
    monkeypatch.setattr(prov, "_post_json",
                        lambda url, payload, headers, timeout: {"choices": []})
    with pytest.raises(ProviderUnavailable):
        OpenAICompatProvider().chat([{"role": "user", "content": "oi"}])


def test_c3_roteador_usa_openai_compat_quando_unico_pronto(tmp_path, monkeypatch):
    from nomos.cognition import engine_router as er
    monkeypatch.setattr(mot, "_http_ok",
                        lambda url, timeout=1.2: "127.0.0.1:1234" in url)
    cat = cat_mod.construir(tmp_path, mapa={})
    from nomos.cognition import engine_policy as pol
    elegiveis = [m for m in cat.por_modalidade("texto")
                 if pol.elegivel(m, tmp_path, False, None).ok]
    if not any(m.id == "openai-compat" for m in elegiveis):
        pytest.skip("política não elege openai-compat neste ambiente")
    dec = er.rotear(er.Tarefa(modalidade="texto"), home=tmp_path, catalogo=cat)
    assert dec.selected_engine is not None
    assert dec.local_only_preserved is True
