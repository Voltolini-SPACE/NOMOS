"""Conector MCP nomos↔E-mail IMAP (MC51 / Fase 3) — leitura por pull, sem rede.

Contratos:
- dialeto MCP em PROCESSO REAL (initialize/tools/list/tools/call) sobre stdio;
- sem NOMOS_IMAP_*: initialize/list funcionam, chamadas falham FECHADO;
- com imaplib MOCKADO: quem_sou/recentes retornam o contrato; a SENHA jamais
  vaza (redação) e a conta aparece só MASCARADA;
- SÓ LEITURA de verdade: seleciona a caixa em ``readonly`` e usa ``BODY.PEEK``
  (nunca marca como lido);
- manifesto válido, todas as tools A3, trust store confia/reconhece.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "examples" / "mcp" / "email-imap" / "servidor.py"
MANIFESTO = RAIZ / "examples" / "mcp" / "email-imap" / "manifesto.json"

_ENVS = ("NOMOS_IMAP_HOST", "NOMOS_IMAP_USER", "NOMOS_IMAP_PASSWORD",
         "NOMOS_IMAP_PORT", "NOMOS_IMAP_MAILBOX")


def _carrega_modulo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("imap_srv", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stdio(mensagens, env_extra=None):
    env = dict(os.environ)
    for k in _ENVS:
        env.pop(k, None)
    env.update(env_extra or {})
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    p = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                       capture_output=True, text=True, timeout=20, env=env)
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


class _FakeIMAP:
    """Servidor IMAP falso: registra readonly/fetch p/ provar só-leitura."""
    ultima = None

    def __init__(self, host, port, timeout=None):
        _FakeIMAP.ultima = self
        self.host, self.port = host, port
        self.readonly = None
        self.fetch_specs = []
        self.deslogado = False

    def login(self, user, senha):
        self.user = user
        return ("OK", [b"logado"])

    def select(self, mailbox, readonly=False):
        self.readonly = readonly
        return ("OK", [b"3"])                 # 3 mensagens na caixa

    def search(self, charset, criterio):
        return ("OK", [b"2 3"]) if criterio == "UNSEEN" else ("OK", [b"1 2 3"])

    def fetch(self, i, spec):
        self.fetch_specs.append(spec)
        raw = (b"From: Ana <ana@exemplo.com>\r\n"
               b"Subject: Reuniao amanha\r\nDate: Mon, 05 Jul 2026 10:00:00\r\n\r\n")
        return ("OK", [(b"1 (headers)", raw)])

    def logout(self):
        self.deslogado = True
        return ("BYE", [b"tchau"])


# 1. dialeto MCP em processo real ------------------------------------------
def test_initialize_e_tools_list():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert r[0]["result"]["serverInfo"]["name"] == "nomos-email-imap"
    nomes = [t["name"] for t in r[1]["result"]["tools"]]
    assert nomes == ["email_imap_quem_sou", "email_imap_recentes"]


def test_sem_credencial_falha_fechado():
    r = _stdio([{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "email_imap_quem_sou", "arguments": {}}}])
    assert "NOMOS_IMAP_HOST" in r[0]["error"]["message"]


# 2. tools com imaplib MOCKADO ---------------------------------------------
def _env(monkeypatch, senha="senha-super-secreta-123"):
    monkeypatch.setenv("NOMOS_IMAP_HOST", "imap.exemplo.com")
    monkeypatch.setenv("NOMOS_IMAP_USER", "joao@exemplo.com")
    monkeypatch.setenv("NOMOS_IMAP_PASSWORD", senha)


def test_quem_sou_conta_mascarada_e_contagens(monkeypatch):
    mod = _carrega_modulo()
    _env(monkeypatch)
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _FakeIMAP)
    r = mod._rodar_tool("email_imap_quem_sou", {})
    assert r["total"] == 3 and r["nao_lidas"] == 2
    assert r["conta"] == "jo***@ex***"           # mascarada
    assert r["conta"] != "joao@exemplo.com"
    assert _FakeIMAP.ultima.readonly is True      # nunca escreve


def test_recentes_e_read_only(monkeypatch):
    mod = _carrega_modulo()
    _env(monkeypatch)
    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", _FakeIMAP)
    r = mod._rodar_tool("email_imap_recentes", {"limite": 5, "nao_lidas": True})
    assert r["so_nao_lidas"] is True
    assert r["mensagens"][0]["de"].startswith("Ana")
    assert r["mensagens"][0]["assunto"] == "Reuniao amanha"
    # prova de SÓ-LEITURA: readonly + BODY.PEEK (nunca marca \Seen)
    assert _FakeIMAP.ultima.readonly is True
    assert all("BODY.PEEK" in s for s in _FakeIMAP.ultima.fetch_specs)


def test_senha_jamais_vaza_em_erros(monkeypatch):
    mod = _carrega_modulo()
    senha = "SENHA-QUE-NAO-PODE-APARECER-999"
    _env(monkeypatch, senha=senha)

    class Explode(_FakeIMAP):
        def login(self, user, s):
            raise mod.imaplib.IMAP4.error(f"login falhou com {senha}")

    monkeypatch.setattr(mod.imaplib, "IMAP4_SSL", Explode)
    resp = mod._despachar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "email_imap_quem_sou",
                                      "arguments": {}}})
    assert senha not in json.dumps(resp)
    assert "***" in resp["error"]["message"]


# 3. manifesto + trust + ClienteMCP real ------------------------------------
def test_manifesto_valido_e_todas_tools_a3():
    from nomos.interface.mcp_client import carregar_manifesto, nivel_da_tool
    m = carregar_manifesto(MANIFESTO)
    assert m["nome"] == "email-imap"
    for t in ("email_imap_quem_sou", "email_imap_recentes"):
        assert nivel_da_tool(m, t) == "A3"
    assert nivel_da_tool(m, "qualquer") == "A3"


def test_cliente_mcp_conecta_e_lista():
    from nomos.interface.mcp_client import ClienteMCP, carregar_manifesto
    m = carregar_manifesto(MANIFESTO)
    with ClienteMCP(m, timeout=15, base=MANIFESTO.parent) as cli:
        nomes = [t["name"] for t in cli.tools()]
    assert nomes == ["email_imap_quem_sou", "email_imap_recentes"]
