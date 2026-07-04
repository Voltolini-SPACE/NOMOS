"""v1.2 — agente que age: oferta de skill na conversa, com gate e honestidade."""
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.ext import skill_intencao as intencao
from nomos.ext import skill_registry as reg
from nomos.ext import skill_status as st
from nomos.kernel.policy import PolicyEngine
from nomos.simple import amigavel

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _instala(nomos_home, tmp_path, name="organiza-pasta",
             keywords=("organiza", "organizar a pasta"),
             permissions=("A0_READ_LOCAL",)):
    src = tmp_path / f"src-{name}"
    src.mkdir()
    corpo = 'import json\nprint(json.dumps({"ok": True, "feito": "varredura"}))\n'
    (src / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    (src / "skill.json").write_text(json.dumps({
        "name": name, "version": "1.0.0", "entry": "main.py",
        "permissions": list(permissions), "keywords": list(keywords),
        "description": "organiza uma pasta",
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}))
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True)
    return engine


# ---------------- sugestão por intenção ----------------

def test_sugere_por_keyword_declarada(nomos_home, tmp_path):
    _instala(nomos_home, tmp_path)
    s = intencao.sugerir_skill("você pode organizar a pasta de downloads?",
                               nomos_home, nomos_home / "skills")
    assert s and s["name"] == "organiza-pasta"
    assert "organizar a pasta" in s["keywords_casadas"]


def test_frase_neutra_nao_sugere(nomos_home, tmp_path):
    _instala(nomos_home, tmp_path)
    assert intencao.sugerir_skill("como anda o clima hoje por aí?",
                                  nomos_home, nomos_home / "skills") is None


def test_desativada_e_quebrada_nunca_sao_oferecidas(nomos_home, tmp_path):
    _instala(nomos_home, tmp_path)
    st.ativar(nomos_home, "organiza-pasta", False)
    assert intencao.sugerir_skill("organiza a pasta pra mim",
                                  nomos_home, nomos_home / "skills") is None
    st.ativar(nomos_home, "organiza-pasta", True)
    (nomos_home / "skills" / "organiza-pasta" / "main.py").write_text("adulterada")
    assert intencao.sugerir_skill("organiza a pasta pra mim",
                                  nomos_home, nomos_home / "skills") is None


# ---------------- conversa: oferta → sim/não ----------------

class _RouterEco:
    def __init__(self):
        self.recebidos = None

    def chat_stream(self, messages, on_token):
        from nomos.cognition.router import ChatOutcome
        self.recebidos = messages
        on_token("resposta do motor")
        return ChatOutcome(True, "local", "resposta do motor", "embutido", "m")


def _conversa(nomos_home, entradas, router):
    feed = iter(entradas)
    tela, tokens = [], []
    ctx = {"home": nomos_home, "policy": PolicyEngine(nomos_home / "policy.json"),
           "skills": nomos_home / "skills"}
    rc = amigavel.iniciar_chat(ctx, {"agent_name": "Luna"}, router=router,
                               ask=lambda _: next(feed), say=tela.append,
                               colorido=False, aprovador=lambda d: True,
                               say_token=tokens.append)
    return rc, "\n".join(str(x) for x in tela) + "\n" + "".join(tokens)


def test_oferta_sim_executa_e_responde(nomos_home, tmp_path, monkeypatch):
    _instala(nomos_home, tmp_path)
    monkeypatch.setattr(reg, "executar_json",
                        lambda *a, **k: (0, {"ok": True, "feito": "varredura"}, ""))
    router = _RouterEco()
    rc, tela = _conversa(nomos_home,
                         ["organiza a pasta de fotos?", "sim", "/sair"], router)
    assert rc == 0
    assert "posso usar a skill 'organiza-pasta'" in tela
    assert "feito: varredura" in tela              # resultado virou resposta
    assert router.recebidos is None                # motor NÃO foi chamado


def test_oferta_nao_segue_para_o_motor(nomos_home, tmp_path, monkeypatch):
    _instala(nomos_home, tmp_path)

    def _nunca(*a, **k):
        raise AssertionError("skill não deveria executar com 'não'")
    monkeypatch.setattr(reg, "executar_json", _nunca)
    router = _RouterEco()
    rc, tela = _conversa(nomos_home,
                         ["organiza a pasta de fotos?", "não", "/sair"], router)
    assert rc == 0
    assert "ok, sigo eu mesmo" in tela
    assert router.recebidos is not None            # motor respondeu normalmente
    assert "resposta do motor" in tela


def test_skills_usar_explicito_com_json(nomos_home, tmp_path, monkeypatch):
    _instala(nomos_home, tmp_path)
    visto = {}

    def fake_exec(nome, skills_dir, policy, aprovador, argumentos=None, **kw):
        visto["nome"], visto["args"] = nome, argumentos
        return 0, {"ok": True, "eco": argumentos}, ""
    monkeypatch.setattr(reg, "executar_json", fake_exec)
    rc, tela = _conversa(nomos_home,
                         ['/skills usar organiza-pasta {"pasta": "/tmp"}', "/sair"],
                         _RouterEco())
    assert visto == {"nome": "organiza-pasta", "args": {"pasta": "/tmp"}}
    assert "resultado da skill 'organiza-pasta'" in tela


def test_skills_usar_gate_negado_mensagem_honesta(nomos_home, tmp_path, monkeypatch):
    _instala(nomos_home, tmp_path)
    monkeypatch.setattr(reg, "executar_json", lambda *a, **k: (3, None, ""))
    rc, tela = _conversa(nomos_home,
                         ["/skills usar organiza-pasta", "/sair"], _RouterEco())
    assert "permissão" in tela and "nada além do aprovado" in tela


def test_json_invalido_no_usar(nomos_home, tmp_path):
    _instala(nomos_home, tmp_path)
    rc, tela = _conversa(nomos_home,
                         ["/skills usar organiza-pasta {quebrado", "/sair"],
                         _RouterEco())
    assert "JSON válido" in tela


def test_auditoria_da_cadeia_so_metadados(nomos_home, tmp_path, monkeypatch):
    from nomos.kernel.audit import AuditLog
    _instala(nomos_home, tmp_path)
    monkeypatch.setattr(reg, "executar_json",
                        lambda *a, **k: (0, {"ok": True,
                                             "dado": "CONTEUDO-PRIVADO"}, ""))
    feed = iter(["organiza a pasta agora?", "sim", "/sair"])
    tela = []
    ctx = {"home": nomos_home, "policy": PolicyEngine(nomos_home / "p.json"),
           "skills": nomos_home / "skills",
           "audit": AuditLog(nomos_home / "logs" / "a.jsonl")}
    amigavel.iniciar_chat(ctx, {"agent_name": "L"}, router=_RouterEco(),
                          ask=lambda _: next(feed), say=tela.append,
                          colorido=False, aprovador=lambda d: True,
                          say_token=lambda t: None)
    bruto = (nomos_home / "logs" / "a.jsonl").read_text()
    assert "skill.conversa" in bruto and '"origem":"oferta"' in bruto
    assert "CONTEUDO-PRIVADO" not in bruto         # metadados, nunca conteúdo


# ---------------- busca-arquivos (skill oficial nº 4) ----------------

def test_busca_arquivos_por_nome_e_conteudo(tmp_path):
    (tmp_path / "contrato-fornecedor.txt").write_text("cláusulas do acordo")
    (tmp_path / "notas.md").write_text("o contrato vence em março")
    (tmp_path / "foto.bin").write_bytes(b"\x00\x01")
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"pasta": str(tmp_path), "termo": "contrato"}))
    main = RAIZ / "examples" / "skills" / "busca-arquivos" / "main.py"
    r = subprocess.run([sys.executable, str(main), str(args)],
                       capture_output=True, text=True, timeout=30)
    saida = json.loads(r.stdout.strip())
    assert saida["ok"] is True
    ondes = {Path(m["arquivo"]).name: m["onde"] for m in saida["encontrados"]}
    assert ondes["contrato-fornecedor.txt"] == "nome"
    assert ondes["notas.md"] == "conteudo"
    assert "foto.bin" not in ondes


def test_busca_arquivos_sem_termo_erro_honesto(tmp_path):
    args = tmp_path / "args.json"
    args.write_text(json.dumps({"pasta": str(tmp_path)}))
    main = RAIZ / "examples" / "skills" / "busca-arquivos" / "main.py"
    r = subprocess.run([sys.executable, str(main), str(args)],
                       capture_output=True, text=True, timeout=30)
    saida = json.loads(r.stdout.strip())
    assert saida["ok"] is False and "termo" in saida["erro"]
