"""MC44 — descoberta terminal-first dos conectores de exemplo.

Os conectores Telegram/WhatsApp existiam e apareciam no Dash, mas não
havia como listá-los pelo terminal. `nomos mcp exemplos` (e o helper
`conectores_exemplo`) fecham essa lacuna — com o estado de confiança real
e o comando exato para ligar, sempre honesto quando a pasta não está lá.
"""
import json
from pathlib import Path

from nomos.interface import mcp_catalogo as cat
from nomos.interface.mcp_client import carregar_manifesto

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "examples" / "mcp"


def test_lista_os_conectores_do_repo(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    conns = cat.conectores_exemplo(nomos_home, raiz=EXEMPLOS)
    nomes = {c["nome"] for c in conns}
    assert {"telegram-bot", "whatsapp-cloud"} <= nomes
    for c in conns:
        assert c["status"] in ("confiavel", "experimental", "revogado")
        assert c["nivel_padrao"] == "A3"        # credencial + rede
        assert c["manifesto"].endswith("manifesto.json")


def test_manifesto_sempre_com_barra_normal(nomos_home):
    """Cross-platform: o caminho do manifesto é o que o usuário COPIA para
    `nomos mcp confiar` — tem de usar barra normal em todo SO (no Windows,
    str(Path) sairia com '\\', quebrando o comando e a paridade com a doc)."""
    nomos_home.mkdir(parents=True, exist_ok=True)
    for c in cat.conectores_exemplo(nomos_home, raiz=EXEMPLOS):
        assert "\\" not in c["manifesto"], c["manifesto"]
        assert c["manifesto"].startswith("examples/mcp/") or \
            c["manifesto"].endswith("/manifesto.json")


def test_status_reflete_o_trust_store(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    # antes de confiar: tudo experimental (disponível, desligado)
    antes = {c["nome"]: c["status"]
             for c in cat.conectores_exemplo(nomos_home, raiz=EXEMPLOS)}
    assert antes["telegram-bot"] == "experimental"
    cat.confiar(nomos_home, carregar_manifesto(
        EXEMPLOS / "telegram" / "manifesto.json"))
    depois = {c["nome"]: c["status"]
              for c in cat.conectores_exemplo(nomos_home, raiz=EXEMPLOS)}
    assert depois["telegram-bot"] == "confiavel"      # ligado
    assert depois["whatsapp-cloud"] == "experimental"  # segue disponível


def test_sem_pasta_devolve_vazio_sem_derrubar(nomos_home, tmp_path):
    nomos_home.mkdir(parents=True, exist_ok=True)
    vazio = tmp_path / "nao-existe"
    assert cat.conectores_exemplo(nomos_home, raiz=vazio) == []


def test_manifesto_torto_e_ignorado(nomos_home, tmp_path):
    nomos_home.mkdir(parents=True, exist_ok=True)
    base = tmp_path / "mcp"
    (base / "bom").mkdir(parents=True)
    (base / "bom" / "manifesto.json").write_text(json.dumps({
        "nome": "bom", "comando": ["python3", "x.py"],
        "nivel_padrao": "A3", "tools": {}}), encoding="utf-8")
    (base / "ruim").mkdir(parents=True)
    (base / "ruim" / "manifesto.json").write_text("{ isto não é json",
                                                  encoding="utf-8")
    conns = cat.conectores_exemplo(nomos_home, raiz=base)
    assert [c["nome"] for c in conns] == ["bom"]       # o torto ficou de fora


def test_cli_exemplos_json_e_texto(nomos_home, monkeypatch, capsys):
    from nomos.cli import cmd_mcp
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    nomos_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(RAIZ)                    # rodar "do projeto"
    ctx = {"home": nomos_home,
           "policy": PolicyEngine(nomos_home / "policy.json"),
           "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
           "skills": nomos_home / "skills"}

    class _Args:
        mcp_cmd = "exemplos"
        json = True

    assert cmd_mcp(ctx, _Args()) == 0
    dados = json.loads(capsys.readouterr().out)
    assert any(c["nome"] == "telegram-bot" for c in dados["conectores"])

    _Args.json = False
    assert cmd_mcp(ctx, _Args()) == 0
    saida = capsys.readouterr().out
    assert "telegram-bot" in saida and "ligar: nomos mcp confiar" in saida
    assert "passa pelo gate" in saida


def test_parser_tem_mcp_exemplos():
    from nomos.cli import build_parser
    a = build_parser().parse_args(["mcp", "exemplos", "--json"])
    assert a.mcp_cmd == "exemplos" and a.json is True
