"""Conector MCP nomos↔Calendário (.ics local) — Fase 2. Leitura de arquivo
LOCAL, sem rede.

Contratos:
- dialeto MCP em PROCESSO REAL (initialize/tools/list/tools/call) sobre stdio;
- sem NOMOS_ICS_PATH (ou arquivo inexistente): initialize/list funcionam,
  chamadas falham FECHADO com instrução;
- parser stdlib do .ics: dia inteiro, horário local, UTC (Z→local), dobra de
  linha, escapes de TEXT, DTSTART torto é ignorado (fail-safe);
- SÓ LEITURA de verdade: os bytes do arquivo não mudam depois das chamadas;
- manifesto válido: tools de leitura A0, nivel_padrao A5 (fail-closed p/ tool
  desconhecida); trust store reconhece; ClienteMCP real conecta e lista.
"""
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "examples" / "mcp" / "calendario" / "servidor.py"
MANIFESTO = RAIZ / "examples" / "mcp" / "calendario" / "manifesto.json"


def _carrega_modulo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cal_srv", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture_ics(tmp_path) -> Path:
    """Um .ics com: dia inteiro HOJE, evento com horário HOJE (vírgula escapada +
    local + SUMMARY dobrado), evento FUTURO em UTC, e um DTSTART TORTO (ignorado)."""
    hoje = date.today().strftime("%Y%m%d")
    fut = (date.today() + timedelta(days=3)).strftime("%Y%m%d")
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//teste//NOMOS//PT\r\n"
        "BEGIN:VEVENT\r\nUID:1\r\nSUMMARY:Aniversário da empresa\r\n"
        f"DTSTART;VALUE=DATE:{hoje}\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:2\r\nSUMMARY:Reunião de produto\\, sala 3\r\n"
        f"LOCATION:HQ\r\nDTSTART:{hoje}T143000\r\nDTEND:{hoje}T153000\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:3\r\nSUMMARY:Deploy da jan\r\n ela\r\n"    # linha dobrada (RFC 5545)
        f"DTSTART:{fut}T090000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:4\r\nSUMMARY:Sem data válida\r\n"
        "DTSTART:xxxxx\r\nEND:VEVENT\r\n"                              # torto: ignorado
        "END:VCALENDAR\r\n"
    )
    p = tmp_path / "agenda.ics"
    p.write_text(ics, encoding="utf-8")
    return p


def _stdio(mensagens, env_extra=None):
    env = dict(os.environ)
    env.pop("NOMOS_ICS_PATH", None)
    env.update(env_extra or {})
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    p = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                       capture_output=True, text=True, timeout=20, env=env)
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


# 1. dialeto MCP em processo real ------------------------------------------
def test_initialize_e_tools_list():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert r[0]["result"]["serverInfo"]["name"] == "nomos-calendario-ics"
    nomes = [t["name"] for t in r[1]["result"]["tools"]]
    assert nomes == ["calendario_quem_sou", "calendario_hoje", "calendario_proximos"]


def test_sem_caminho_falha_fechado():
    r = _stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "calendario_hoje", "arguments": {}}}])
    assert "NOMOS_ICS_PATH" in r[0]["error"]["message"]


def test_arquivo_inexistente_falha_fechado(tmp_path):
    r = _stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "calendario_hoje", "arguments": {}}}],
               env_extra={"NOMOS_ICS_PATH": str(tmp_path / "nao-existe.ics")})
    assert "existente" in r[0]["error"]["message"]


# 2. parser + tools com .ics real ------------------------------------------
def test_quem_sou_conta_eventos_e_intervalo(tmp_path, monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_ICS_PATH", str(_fixture_ics(tmp_path)))
    r = mod._rodar_tool("calendario_quem_sou", {})
    assert r["arquivo"] == "agenda.ics"          # só o nome, não o caminho
    assert r["eventos"] == 3                      # o DTSTART torto foi ignorado
    assert r["primeiro"] == date.today().strftime("%Y-%m-%d")


def test_hoje_traz_dia_inteiro_e_horario_com_escape(tmp_path, monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_ICS_PATH", str(_fixture_ics(tmp_path)))
    r = mod._rodar_tool("calendario_hoje", {})
    titulos = [e["titulo"] for e in r["eventos"]]
    assert "Aniversário da empresa" in titulos
    # vírgula escapada (\\,) foi desescapada corretamente
    assert "Reunião de produto, sala 3" in titulos
    reuniao = next(e for e in r["eventos"] if e["titulo"].startswith("Reunião"))
    assert reuniao["local"] == "HQ"
    assert "14:30" in reuniao["quando"]
    assert any("(dia inteiro)" in e["quando"] for e in r["eventos"])


def test_proximos_respeita_limite_e_converte_utc(tmp_path, monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_ICS_PATH", str(_fixture_ics(tmp_path)))
    r = mod._rodar_tool("calendario_proximos", {"limite": 1})
    assert len(r["eventos"]) == 1                 # respeita o limite
    # a linha dobrada (SUMMARY:Deploy\n janela) foi remontada
    fut = (date.today() + timedelta(days=3))
    todos = mod._rodar_tool("calendario_proximos", {"limite": 50})
    deploy = [e for e in todos["eventos"] if "Deploy" in e["titulo"]]
    assert deploy and deploy[0]["titulo"] == "Deploy da janela"   # dobra remontada
    assert deploy[0]["quando"].startswith(fut.strftime("%Y-%m-%d"))


def test_limite_e_saneado(tmp_path, monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_ICS_PATH", str(_fixture_ics(tmp_path)))
    # limite fora da faixa não explode: 1..50
    assert len(mod._rodar_tool("calendario_proximos", {"limite": 999})["eventos"]) <= 50
    assert mod._rodar_tool("calendario_proximos", {"limite": 0})["eventos"] is not None


def test_tool_desconhecida(tmp_path, monkeypatch):
    mod = _carrega_modulo()
    monkeypatch.setenv("NOMOS_ICS_PATH", str(_fixture_ics(tmp_path)))
    import pytest
    with pytest.raises(LookupError):
        mod._rodar_tool("calendario_apaga_tudo", {})


def test_so_leitura_nao_altera_o_arquivo(tmp_path, monkeypatch):
    mod = _carrega_modulo()
    fx = _fixture_ics(tmp_path)
    antes = fx.read_bytes()
    monkeypatch.setenv("NOMOS_ICS_PATH", str(fx))
    mod._rodar_tool("calendario_quem_sou", {})
    mod._rodar_tool("calendario_hoje", {})
    mod._rodar_tool("calendario_proximos", {"limite": 10})
    assert fx.read_bytes() == antes               # nunca escreveu no .ics


# 3. manifesto + trust + ClienteMCP real ------------------------------------
def test_manifesto_valido_tools_a0_padrao_a5():
    from nomos.interface.mcp_client import carregar_manifesto, nivel_da_tool
    m = carregar_manifesto(MANIFESTO)
    assert m["nome"] == "calendario-ics"
    for t in ("calendario_quem_sou", "calendario_hoje", "calendario_proximos"):
        assert nivel_da_tool(m, t) == "A0"        # leitura local honesta
    assert nivel_da_tool(m, "qualquer_outra") == "A5"   # fail-closed


def test_cliente_mcp_conecta_e_lista():
    from nomos.interface.mcp_client import ClienteMCP, carregar_manifesto
    m = carregar_manifesto(MANIFESTO)
    with ClienteMCP(m, timeout=15, base=MANIFESTO.parent) as cli:
        nomes = [t["name"] for t in cli.tools()]
    assert nomes == ["calendario_quem_sou", "calendario_hoje", "calendario_proximos"]
