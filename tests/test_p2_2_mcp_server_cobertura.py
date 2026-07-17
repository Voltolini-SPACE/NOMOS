"""P2-2 (auditoria de 2026-07-17): elevar cobertura de interface/mcp_server.py.

Achado: `coverage` reportava ~9% para este módulo (108 statements, ~98
nunca executados dentro do processo do pytest). Investigação: NÃO é um
módulo mal testado — `tests/test_mc31_c1_mcp.py` já cobre o protocolo
inteiro (handshake, tools/list, tool de status, redação de segredo,
erros fail-closed, read-only+auditoria, resiliência a JSON inválido, CLI
`mcp tools`) com bastante rigor. O problema é COMO ele é testado: todo
teste existente fala com o servidor via `subprocess.run([... "mcp",
"servir"], ...)` — um processo Python totalmente separado. `coverage.py`
só instrumenta o processo onde o pytest roda; código executado num
subprocesso é invisível a ele (a menos que se configure rastreamento de
subprocesso via COVERAGE_PROCESS_START, o que este projeto não faz e que
mudar agora teria alcance bem maior que este achado — afetaria a medição
de TODOS os módulos exercitados via subprocess em toda a suíte, não só
este). A escolha de menor risco/mais direta é chamar o servidor NO MESMO
PROCESSO do teste.

Este arquivo NÃO duplica as asserções de protocolo do test_mc31_c1_mcp.py
(esse continua sendo a prova de ponta-a-ponta via subprocess real) — ele
chama `mcp_server.servir()`/`_despachar()` diretamente, com `entrada`/
`saida` injetados (parâmetros que o módulo já expõe para isso), cobrindo
os ramos de erro e as 5 tools que o teste por subprocess não precisa
exercitar individualmente porque valida o protocolo, não cada branch.

Nenhuma linha de produção de mcp_server.py foi alterada — achado é
puramente de lacuna de teste/medição, não de comportamento.
"""
from __future__ import annotations

import io
import json

import pytest

from nomos.cognition import motores
from nomos.interface import mcp_server
from nomos.kernel.audit import AuditLog


@pytest.fixture(autouse=True)
def _sem_rede(monkeypatch):
    """Mesmo padrão de test_painel_tema_e_abas.py: engine_catalog.construir()
    (usado pela tool nomos_status) detecta motores via rede/subprocess por
    padrão — neutralizado para o teste ficar rápido e determinístico."""
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def _ctx(home, com_audit=True):
    home.mkdir(parents=True, exist_ok=True)
    (home / "skills").mkdir(exist_ok=True)
    d = {"home": home}
    if com_audit:
        d["audit"] = AuditLog(home / "logs" / "audit.jsonl")
    return d


def _rodar(ctx, mensagens):
    """servir() de verdade, no mesmo processo — só entrada/saida trocadas."""
    entrada = io.StringIO("".join(json.dumps(m) + "\n" for m in mensagens))
    saida = io.StringIO()
    rc = mcp_server.servir(ctx, entrada=entrada, saida=saida)
    respostas = [json.loads(linha) for linha in saida.getvalue().splitlines()
                if linha.strip()]
    return rc, respostas


# ------------------------------------------------------------ servir(): protocolo

def test_servir_em_processo_cobre_handshake_e_tools_list(tmp_path):
    ctx = _ctx(tmp_path)
    rc, respostas = _rodar(ctx, [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    assert rc == 0
    assert len(respostas) == 2                       # notificação não responde
    init = respostas[0]["result"]
    assert init["protocolVersion"] == mcp_server.PROTOCOLO
    assert init["serverInfo"]["name"] == "nomos"
    nomes = {t["name"] for t in respostas[1]["result"]["tools"]}
    assert nomes == {t["name"] for t in mcp_server.TOOLS}


def test_servir_linha_em_branco_e_pulada(tmp_path):
    ctx = _ctx(tmp_path)
    entrada = io.StringIO("\n   \n" + json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
    saida = io.StringIO()
    rc = mcp_server.servir(ctx, entrada=entrada, saida=saida)
    respostas = [json.loads(linha) for linha in saida.getvalue().splitlines() if linha.strip()]
    assert rc == 0
    assert len(respostas) == 1                        # só a linha de verdade respondeu


def test_servir_json_invalido_nao_derruba_loop_em_processo(tmp_path):
    ctx = _ctx(tmp_path)
    entrada = io.StringIO(
        "isto não é json\n" +
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "tools/list"}) + "\n")
    saida = io.StringIO()
    rc = mcp_server.servir(ctx, entrada=entrada, saida=saida)
    respostas = [json.loads(linha) for linha in saida.getvalue().splitlines() if linha.strip()]
    assert rc == 0
    assert respostas[0]["error"]["code"] == -32700     # parse error
    assert "tools" in respostas[1]["result"]           # loop seguiu vivo


def test_servir_json_valido_mas_nao_objeto_erro_32600(tmp_path):
    ctx = _ctx(tmp_path)
    entrada = io.StringIO("[1, 2, 3]\n" + json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
    saida = io.StringIO()
    rc = mcp_server.servir(ctx, entrada=entrada, saida=saida)
    respostas = [json.loads(linha) for linha in saida.getvalue().splitlines() if linha.strip()]
    assert rc == 0
    assert respostas[0]["error"]["code"] == -32600
    assert "objeto" in respostas[0]["error"]["message"]
    assert "tools" in respostas[1]["result"]           # loop seguiu vivo


def test_servir_excecao_inesperada_no_despachar_nao_derruba_loop(tmp_path, monkeypatch):
    """Contrato documentado no docstring do módulo: 'exceção interna nunca
    derruba o loop nem vaza detalhes'. Não há gatilho orgânico simples para
    _despachar() explodir de forma inesperada (todo erro previsível já vira
    -32602/-32601 antes); testamos o contrato diretamente, como o próprio
    código promete, via monkeypatch de _despachar."""
    ctx = _ctx(tmp_path)

    def _explode(ctx, msg):
        raise RuntimeError("boom-interno")
    monkeypatch.setattr(mcp_server, "_despachar", _explode)

    entrada = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}) + "\n")
    saida = io.StringIO()
    rc = mcp_server.servir(ctx, entrada=entrada, saida=saida)
    respostas = [json.loads(linha) for linha in saida.getvalue().splitlines() if linha.strip()]
    assert rc == 0                                     # loop não caiu
    assert respostas[0]["error"]["code"] == -32603
    assert "boom-interno" not in respostas[0]["error"]["message"]   # não vaza detalhe


def test_servir_sem_audit_no_ctx_nao_quebra(tmp_path):
    ctx = _ctx(tmp_path, com_audit=False)
    rc, respostas = _rodar(ctx, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    assert rc == 0
    assert "tools" in respostas[0]["result"]


def test_servir_audita_inicio_e_fim_quando_ctx_tem_audit(tmp_path):
    ctx = _ctx(tmp_path, com_audit=True)
    _rodar(ctx, [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    trilha = (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert "mcp.servidor.iniciado" in trilha
    assert "mcp.servidor.encerrado" in trilha


# ------------------------------------------------------------ _despachar(): erros

def test_despachar_method_nao_string(tmp_path):
    ctx = _ctx(tmp_path)
    resp = mcp_server._despachar(ctx, {"jsonrpc": "2.0", "id": 1, "method": 123})
    assert resp["error"]["code"] == -32600


def test_despachar_tools_call_params_nao_dict(tmp_path):
    ctx = _ctx(tmp_path)
    resp = mcp_server._despachar(
        ctx, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1, 2]})
    assert resp["error"]["code"] == -32602
    assert "objeto" in resp["error"]["message"]


def test_despachar_tools_call_arguments_nao_dict(tmp_path):
    ctx = _ctx(tmp_path)
    resp = mcp_server._despachar(ctx, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "nomos_status", "arguments": [1, 2]},
    })
    assert resp["error"]["code"] == -32602
    assert "arguments" in resp["error"]["message"]


def test_despachar_metodo_desconhecido(tmp_path):
    ctx = _ctx(tmp_path)
    resp = mcp_server._despachar(ctx, {"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    assert resp["error"]["code"] == -32601


def test_despachar_tools_call_excecao_generica_vira_32000(tmp_path):
    """Gatilho orgânico (sem monkeypatch): a primeira tentativa usava ctx
    sem 'home' — mas KeyError é subclasse de LookupError, então caía no
    MESMO ramo (-32602) que uma tool desconhecida, não no genérico. Achado
    do próprio teste, corrigido antes do commit (não escondido): um
    ctx['home'] de tipo errado faz Path(...) levantar TypeError — essa sim
    não é LookupError nem ValueError, então tem que virar -32000."""
    resp = mcp_server._despachar({"home": 12345}, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "nomos_status", "arguments": {}},
    })
    assert resp["error"]["code"] == -32000
    assert "TypeError" in resp["error"]["message"]


def test_despachar_tools_call_ctx_sem_home_e_lookuperror_no_32602(tmp_path):
    """KeyError é subclasse de LookupError (hierarquia real do Python) — um
    ctx sem 'home' cai no MESMO ramo de erro que uma tool desconhecida
    (-32602), não no genérico -32000. Documenta essa hierarquia por
    execução, não por suposição."""
    resp = mcp_server._despachar({}, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "nomos_status", "arguments": {}},
    })
    assert resp["error"]["code"] == -32602
    assert "home" in resp["error"]["message"]


def test_despachar_tools_call_ferramenta_desconhecida_vira_32602(tmp_path):
    ctx = _ctx(tmp_path)
    resp = mcp_server._despachar(ctx, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "tool_que_nao_existe", "arguments": {}},
    })
    assert resp["error"]["code"] == -32602
    assert "desconhecida" in resp["error"]["message"]


def test_despachar_tools_call_sucesso_audita_quando_ctx_tem_audit(tmp_path):
    ctx = _ctx(tmp_path, com_audit=True)
    resp = mcp_server._despachar(ctx, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "nomos_capacidades", "arguments": {}},
    })
    assert "result" in resp
    trilha = (tmp_path / "logs" / "audit.jsonl").read_text(encoding="utf-8")
    assert '"mcp.tool"' in trilha and "nomos_capacidades" in trilha


# ------------------------------------------------------------- _rodar_tool(): as 5 tools

def test_tool_status_em_processo(tmp_path):
    ctx = _ctx(tmp_path)
    resultado = mcp_server._rodar_tool(ctx, "nomos_status", {})
    corpo = json.loads(resultado["content"][0]["text"])
    assert corpo["so_local"] is True
    assert "motores_prontos" in corpo and "memorias" in corpo


def test_tool_capacidades_em_processo(tmp_path):
    ctx = _ctx(tmp_path)
    resultado = mcp_server._rodar_tool(ctx, "nomos_capacidades", {})
    assert resultado["isError"] is False


def test_tool_evidencias_vazio_quando_pasta_nao_existe(tmp_path):
    ctx = _ctx(tmp_path)
    resultado = mcp_server._rodar_tool(ctx, "nomos_evidencias", {})
    corpo = json.loads(resultado["content"][0]["text"])
    assert corpo == []


def test_tool_evidencias_com_pacote_real_integro(tmp_path):
    from nomos.kernel import evidencia as ev
    ctx = _ctx(tmp_path)
    ev.gerar_pacote(tmp_path / "evidencias", "teste p2-2", status="PASS",
                    comandos=[{"comando": "echo oi", "retorno": 0, "resultado": "oi"}])
    resultado = mcp_server._rodar_tool(ctx, "nomos_evidencias", {})
    corpo = json.loads(resultado["content"][0]["text"])
    assert len(corpo) == 1
    assert corpo[0]["integro"] is True
    assert corpo[0]["problemas"] == []


def test_tool_memoria_buscar_rediz_segredo_em_processo(tmp_path):
    from nomos.cognition.memory import Memory
    ctx = _ctx(tmp_path)
    chave = "sk-" + "Q" * 30
    Memory(tmp_path / "memory.db").remember("note", f"minha chave é {chave}")
    resultado = mcp_server._rodar_tool(ctx, "nomos_memoria_buscar", {"consulta": "chave"})
    texto = resultado["content"][0]["text"]
    assert chave not in texto
    assert "REDIGIDO" in texto or "redig" in texto.lower()


def test_tool_memoria_buscar_consulta_vazia_levanta_valueerror(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(ValueError, match="consulta vazia"):
        mcp_server._rodar_tool(ctx, "nomos_memoria_buscar", {"consulta": "   "})


def test_tool_roteador_explicar_modalidade_valida(tmp_path):
    ctx = _ctx(tmp_path)
    resultado = mcp_server._rodar_tool(ctx, "nomos_roteador_explicar", {"modalidade": "texto"})
    assert resultado["isError"] is False


def test_tool_roteador_explicar_modalidade_invalida_levanta_valueerror(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(ValueError, match="desconhecida"):
        mcp_server._rodar_tool(ctx, "nomos_roteador_explicar", {"modalidade": "inexistente"})


def test_tool_desconhecida_levanta_lookuperror(tmp_path):
    ctx = _ctx(tmp_path)
    with pytest.raises(LookupError, match="desconhecida"):
        mcp_server._rodar_tool(ctx, "tool_fantasma", {})


# ------------------------------------------------------------------- _texto()

def test_texto_com_string_nao_reserializa():
    r = mcp_server._texto("já é texto")
    assert r == {"content": [{"type": "text", "text": "já é texto"}], "isError": False}


def test_texto_serializa_payload_nao_string():
    r = mcp_server._texto({"a": 1, "b": [1, 2]})
    assert r["isError"] is False
    de_volta = json.loads(r["content"][0]["text"])
    assert de_volta == {"a": 1, "b": [1, 2]}
