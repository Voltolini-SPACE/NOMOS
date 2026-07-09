"""MC54 / Fase 5 — trust-UX: `nomos mcp confiar <nome>` (por nome do conector).

Sem isso, o usuário instalado por pip teria de digitar o caminho longo do
site-packages. O resolvedor aceita CAMINHO (arquivo) ou NOME do conector (a
pasta em examples/mcp ou na cópia empacotada) — sem afrouxar a confiança (o
hash é o mesmo; só o caminho é resolvido).
"""
import io
from pathlib import Path

from nomos import cli
from nomos.interface import mcp_catalogo as cat

RAIZ = Path(__file__).resolve().parent.parent
EXEMPLOS = RAIZ / "examples" / "mcp"


def test_resolver_por_nome_e_por_caminho():
    # por NOME do conector (pasta)
    p = cat.resolver_conector("telegram", raiz=EXEMPLOS)
    assert p is not None and p.name == "manifesto.json"
    assert p.parent.name == "telegram"
    # por CAMINHO existente
    caminho = EXEMPLOS / "signal" / "manifesto.json"
    assert cat.resolver_conector(str(caminho)) == caminho
    # inexistente ⇒ None (o chamador decide a mensagem)
    assert cat.resolver_conector("nao-existe-esse", raiz=EXEMPLOS) is None


def test_conectores_exemplo_traz_dir(nomos_home):
    conns = cat.conectores_exemplo(nomos_home, raiz=EXEMPLOS)
    dirs = {c["dir"] for c in conns}
    assert {"telegram", "signal", "email-imap", "email-smtp",
            "whatsapp-cloud"} <= dirs


def test_confiar_por_nome_resolve_e_confia(nomos_home, monkeypatch):
    """Confiar por NOME funciona igual a por caminho — mesma impressão."""
    monkeypatch.chdir(RAIZ)                       # examples/ no cwd
    from nomos.interface.mcp_client import carregar_manifesto
    alvo = cat.resolver_conector("telegram")
    assert alvo is not None
    esperado = cat.impressao(carregar_manifesto(alvo))
    cat.confiar(nomos_home, carregar_manifesto(alvo))
    fps = [s["impressao"] for s in cat.listar(nomos_home)["confiaveis"]]
    assert any(esperado.startswith(fp) or fp.startswith(esperado[:16]) for fp in fps)


def test_cli_confiar_nome_inexistente_erro_claro(nomos_home, monkeypatch, capsys):
    monkeypatch.chdir(RAIZ)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    rc = cli.main(["mcp", "confiar", "conector-que-nao-existe"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "não achei" in err               # resolvedor ligado (falha antes do TTY)


def test_cli_exemplos_dica_por_nome(nomos_home, monkeypatch, capsys):
    monkeypatch.chdir(RAIZ)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    rc = cli.main(["mcp", "exemplos"])
    out = capsys.readouterr().out
    assert rc == 0
    # a dica de ligar usa o NOME curto, não o caminho longo
    assert "nomos mcp confiar telegram" in out
    assert "examples/mcp/telegram/manifesto.json" not in out


# --- Fase 5 (MC64): confiar pela FILA DO PAINEL (--panel), sem TTY ----------
def _status_telegram(home):
    from nomos.interface.mcp_client import carregar_manifesto
    return cat.status(home, carregar_manifesto(
        EXEMPLOS / "telegram" / "manifesto.json"))


def test_confiar_pela_fila_do_painel_aprova(nomos_home, monkeypatch, capsys):
    monkeypatch.chdir(RAIZ)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    # simula a fila do painel APROVANDO (a decisão segue 100% humana)
    monkeypatch.setattr(cli, "_approver_for", lambda ctx, args: (lambda d: True))
    rc = cli.main(["mcp", "confiar", "telegram", "--panel"])
    assert rc == 0
    assert "fila do painel" in capsys.readouterr().out
    assert _status_telegram(nomos_home) == "confiavel"     # registrado


def test_confiar_pela_fila_negada_nao_registra(nomos_home, monkeypatch, capsys):
    monkeypatch.chdir(RAIZ)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(cli, "_approver_for", lambda ctx, args: (lambda d: False))
    rc = cli.main(["mcp", "confiar", "telegram", "--panel"])
    assert rc != 0
    assert _status_telegram(nomos_home) == "experimental"  # nada registrado


def test_parser_confiar_tem_panel():
    from nomos.cli import build_parser
    a = build_parser().parse_args(["mcp", "confiar", "telegram", "--panel"])
    assert a.mcp_cmd == "confiar" and a.panel is True
