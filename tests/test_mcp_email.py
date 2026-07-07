"""Conector MCP nomos↔E-mail (MC46) — SMTP via stdlib, governado, honesto.

Mesma disciplina de Telegram/WhatsApp: dialeto MCP em processo real,
fail-closed sem credenciais, smtplib mockado para o contrato, senha
jamais em erros, manifesto A3 no trust store. E um teste-coroa de rotina
ponta a ponta com um servidor SMTP FAKE local (sem internet).
"""
import json
import smtplib
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SERVIDOR = RAIZ / "examples" / "mcp" / "email-smtp" / "servidor.py"
MANIFESTO = RAIZ / "examples" / "mcp" / "email-smtp" / "manifesto.json"


def _carrega_modulo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("email_srv", SERVIDOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stdio(mensagens: list[dict]) -> list[dict]:
    import os
    env = dict(os.environ)
    for k in ("NOMOS_SMTP_HOST", "NOMOS_SMTP_USER", "NOMOS_SMTP_PASSWORD"):
        env.pop(k, None)
    entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
    p = subprocess.run([sys.executable, str(SERVIDOR)], input=entrada,
                       capture_output=True, text=True, timeout=20, env=env)
    return [json.loads(ln) for ln in p.stdout.splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# 1. dialeto MCP em processo real + fail-closed
# ---------------------------------------------------------------------------
def test_dialeto_e_fail_closed_sem_credenciais():
    r = _stdio([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "email_enviar",
                    "arguments": {"destinatario": "a@b.com",
                                  "assunto": "x", "texto": "y"}}},
    ])
    assert r[0]["result"]["serverInfo"]["name"] == "nomos-email-smtp"
    assert [t["name"] for t in r[1]["result"]["tools"]] == [
        "email_quem_sou", "email_enviar"]
    assert "NOMOS_SMTP_HOST" in r[2]["error"]["message"]


# ---------------------------------------------------------------------------
# 2. envio com smtplib mockado (nenhum byte real na rede)
# ---------------------------------------------------------------------------
class _SmtpFalso:
    ultimo = None

    def __init__(self, host, porta, timeout=None):
        _SmtpFalso.ultimo = self
        self.host, self.porta = host, porta
        self.enviados = []
        self.logado = None

    def ehlo(self):
        pass

    def has_extn(self, nome):
        return True                 # oferece STARTTLS

    def starttls(self, context=None):
        pass

    def login(self, user, senha):
        self.logado = (user, senha)

    def send_message(self, msg):
        self.enviados.append(msg)

    def noop(self):
        pass

    def quit(self):
        pass

    def close(self):
        pass


def _cfg_ok(monkeypatch):
    monkeypatch.setenv("NOMOS_SMTP_HOST", "smtp.exemplo.com")
    monkeypatch.setenv("NOMOS_SMTP_PORT", "587")
    monkeypatch.setenv("NOMOS_SMTP_USER", "eu@exemplo.com")
    monkeypatch.setenv("NOMOS_SMTP_PASSWORD", "s3nha")


def test_enviar_com_smtplib_mockado(monkeypatch):
    mod = _carrega_modulo()
    _cfg_ok(monkeypatch)
    monkeypatch.setattr(mod.smtplib, "SMTP", _SmtpFalso)
    r = mod._rodar_tool("email_enviar",
                        {"destinatario": "voce@dominio.com",
                         "assunto": "Oi", "texto": "corpo do e-mail"})
    assert r == {"enviado": True, "para": "voce@dominio.com", "assunto": "Oi"}
    env = _SmtpFalso.ultimo
    assert env.logado == ("eu@exemplo.com", "s3nha")
    msg = env.enviados[0]
    assert msg["To"] == "voce@dominio.com" and msg["Subject"] == "Oi"
    assert msg["From"] == "eu@exemplo.com"      # FROM cai no USER


def test_quem_sou_valida_sem_enviar(monkeypatch):
    mod = _carrega_modulo()
    _cfg_ok(monkeypatch)
    monkeypatch.setattr(mod.smtplib, "SMTP", _SmtpFalso)
    r = mod._rodar_tool("email_quem_sou", {})
    assert r["autenticado"] is True and r["remetente"] == "eu@exemplo.com"
    assert _SmtpFalso.ultimo.enviados == []      # NADA enviado


def test_recusa_texto_claro_sem_starttls(monkeypatch):
    mod = _carrega_modulo()
    _cfg_ok(monkeypatch)

    class _SemTLS(_SmtpFalso):
        def has_extn(self, nome):
            return False             # servidor sem STARTTLS

    monkeypatch.setattr(mod.smtplib, "SMTP", _SemTLS)
    with pytest.raises(RuntimeError, match="texto claro"):
        mod._rodar_tool("email_quem_sou", {})


def test_validacoes_destinatario_e_assunto(monkeypatch):
    mod = _carrega_modulo()
    _cfg_ok(monkeypatch)
    monkeypatch.setattr(mod.smtplib, "SMTP", _SmtpFalso)
    with pytest.raises(ValueError, match="e-mail válido"):
        mod._rodar_tool("email_enviar", {"destinatario": "semarroba",
                                         "assunto": "x", "texto": "y"})
    with pytest.raises(ValueError, match="assunto"):
        mod._rodar_tool("email_enviar", {"destinatario": "a@b.com",
                                         "assunto": "", "texto": "y"})


def test_senha_jamais_vaza(monkeypatch):
    mod = _carrega_modulo()
    senha = "SENHA-SECRETA-XYZ"
    monkeypatch.setenv("NOMOS_SMTP_HOST", "h")
    monkeypatch.setenv("NOMOS_SMTP_USER", "u@x.com")
    monkeypatch.setenv("NOMOS_SMTP_PASSWORD", senha)

    def explode(*a, **k):
        raise smtplib.SMTPException(f"falha com senha {senha}")

    monkeypatch.setattr(mod.smtplib, "SMTP", explode)
    resp = mod._despachar({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "email_quem_sou",
                                      "arguments": {}}})
    assert senha not in json.dumps(resp) and "***" in resp["error"]["message"]


# ---------------------------------------------------------------------------
# 3. manifesto + trust store
# ---------------------------------------------------------------------------
def test_manifesto_a3_e_trust_store(nomos_home):
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto, nivel_da_tool
    m = carregar_manifesto(MANIFESTO)
    assert m["nivel_padrao"] == "A3"
    assert nivel_da_tool(m, "email_enviar") == "A3"
    nomos_home.mkdir(parents=True, exist_ok=True)
    cat.confiar(nomos_home, m)
    assert "email-smtp" in [s["nome"] for s in
                            cat.listar(nomos_home)["confiaveis"]]


def test_aparece_em_conectores_exemplo(nomos_home):
    from nomos.interface import mcp_catalogo as cat
    nomos_home.mkdir(parents=True, exist_ok=True)
    nomes = {c["nome"] for c in cat.conectores_exemplo(
        nomos_home, raiz=RAIZ / "examples" / "mcp")}
    assert {"telegram-bot", "whatsapp-cloud", "email-smtp"} <= nomes


# ---------------------------------------------------------------------------
# 4. teste-coroa: rotina briefing-email → SMTP fake local (SEM internet)
# ---------------------------------------------------------------------------
class _SmtpFakeServer:
    """SMTP mínimo em 127.0.0.1 — aceita a transação e guarda o DATA."""

    def __init__(self):
        import socket
        self.recebidos: list[str] = []
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(1)
        self.host, self.porta = self._srv.getsockname()
        self._parar = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while not self._parar:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            threading.Thread(target=self._sessao, args=(conn,),
                             daemon=True).start()

    def _sessao(self, conn):
        def envia(txt):
            conn.sendall(txt.encode() + b"\r\n")
        envia("220 fake ESMTP")
        buffer, em_dados, dados = b"", False, []
        conn.settimeout(10)
        try:
            while True:
                pedaco = conn.recv(1024)
                if not pedaco:
                    break
                buffer += pedaco
                while b"\r\n" in buffer:
                    linha, buffer = buffer.split(b"\r\n", 1)
                    txt = linha.decode(errors="ignore")
                    if em_dados:
                        if txt == ".":
                            self.recebidos.append("\n".join(dados))
                            em_dados = False
                            envia("250 OK queued")
                        else:
                            dados.append(txt)
                        continue
                    up = txt.upper()
                    if up.startswith("EHLO") or up.startswith("HELO"):
                        envia("250-fake")
                        envia("250 AUTH LOGIN PLAIN")
                    elif up.startswith("AUTH"):
                        envia("235 auth ok")
                    elif up.startswith("MAIL FROM") or up.startswith(
                            "RCPT TO"):
                        envia("250 OK")
                    elif up.startswith("DATA"):
                        envia("354 end with .")
                        em_dados = True
                    elif up.startswith("QUIT"):
                        envia("221 bye")
                        conn.close()
                        return
                    else:
                        envia("250 OK")
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def parar(self):
        self._parar = True
        try:
            self._srv.close()
        except OSError:
            pass


def test_e2e_rotina_briefing_email_sem_internet(nomos_home, monkeypatch):
    import io
    from datetime import datetime

    from nomos.cognition import motores
    from nomos.interface import mcp_catalogo as cat
    from nomos.interface.mcp_client import carregar_manifesto
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    from nomos.simple import rotinas as rot

    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()

    nomos_home.mkdir(parents=True, exist_ok=True)
    (nomos_home / "skills").mkdir(exist_ok=True)
    ctx = {"home": nomos_home,
           "policy": PolicyEngine(nomos_home / "policy.json"),
           "audit": AuditLog(nomos_home / "logs" / "audit.jsonl"),
           "skills": nomos_home / "skills"}
    cat.confiar(nomos_home, carregar_manifesto(MANIFESTO))
    rot.criar(nomos_home, "Briefing e-mail", "08:00",
              "briefing-email:voce@dominio.com", ctx["policy"],
              approver=lambda d: True)
    smtp = _SmtpFakeServer()
    monkeypatch.setenv("NOMOS_SMTP_HOST", smtp.host)
    monkeypatch.setenv("NOMOS_SMTP_PORT", str(smtp.porta))
    monkeypatch.setenv("NOMOS_SMTP_USER", "eu@dominio.com")
    monkeypatch.setenv("NOMOS_SMTP_PASSWORD", "s3nha")
    monkeypatch.setenv("NOMOS_SMTP_INSECURE", "1")   # fake local sem TLS
    monkeypatch.setenv("NOMOS_EMAIL_MANIFESTO", str(MANIFESTO))
    try:
        oito = datetime.now().replace(hour=8, minute=0)
        resultados = rot.executar_devidas(ctx, agora=oito,
                                          say=lambda *a: None,
                                          approver=lambda d: True)
        assert len(resultados) == 1 and resultados[0]["ok"], resultados
        import time
        for _ in range(50):
            if smtp.recebidos:
                break
            time.sleep(0.1)
        assert smtp.recebidos, "o SMTP fake não recebeu o e-mail"
        corpo = smtp.recebidos[0]
        assert "voce@dominio.com" in corpo
        assert "Briefing NOMOS" in corpo          # assunto com data
        assert "Briefing local" in corpo          # conteúdo real do briefing
        trilha = (nomos_home / "logs" / "audit.jsonl").read_text()
        assert "rotina.briefing.entregue" in trilha
    finally:
        smtp.parar()
        motores.limpar_cache()
