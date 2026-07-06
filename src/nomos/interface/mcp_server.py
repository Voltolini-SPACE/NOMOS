"""NOMOS interface.mcp_server — servidor MCP local, somente leitura (MC31/C1).

O NOMOS entra no ecossistema de agentes SEM trair o local-first: expõe um
servidor **Model Context Protocol** sobre **stdio** (JSON-RPC 2.0) que um
cliente local (Claude Desktop, IDEs, outros agentes) conecta como subprocesso.
Não há socket de rede — o transporte é stdin/stdout do processo local.

Modelo de segurança (alinhado à SECURITY_POLICY):
- **Somente leitura (A0)**: todas as tools consultam estado local; nenhuma
  escreve, executa skill, aprova nada ou toca rede/segredo.
- **Redação**: qualquer texto vindo da memória/auditoria passa por
  ``kernel.audit.redact_text`` antes de sair.
- **Auditoria**: cada chamada de tool gera evento ``mcp.tool`` (metadados).
- **Fail-closed**: método desconhecido => erro JSON-RPC; tool desconhecida =>
  erro; exceção interna nunca derruba o loop nem vaza detalhes.

Protocolo: MCP 2024-11-05 (initialize → notifications/initialized →
tools/list → tools/call). Stdlib-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROTOCOLO = "2024-11-05"

TOOLS = [
    {
        "name": "nomos_status",
        "description": "Status do NOMOS local: versão, cadeado de localidade, "
                       "motores prontos por modalidade e memória.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "nomos_capacidades",
        "description": "Catálogo de capacidades (skills) com risco, permissões "
                       "e exemplos — o que o NOMOS sabe fazer.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "nomos_evidencias",
        "description": "Pacotes de evidências de missões com verificação de "
                       "integridade (SHA-256) feita na hora.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "nomos_memoria_buscar",
        "description": "Busca nas memórias locais do usuário (FTS5). Saída "
                       "redigida: segredos nunca aparecem.",
        "inputSchema": {"type": "object",
                        "properties": {"consulta": {"type": "string"}},
                        "required": ["consulta"]},
    },
    {
        "name": "nomos_roteador_explicar",
        "description": "Decisão explicada do roteador de motores para uma "
                       "modalidade (candidatos, motivos, regras).",
        "inputSchema": {"type": "object",
                        "properties": {"modalidade": {"type": "string"}},
                        "required": ["modalidade"]},
    },
]


def _texto(payload) -> dict:
    if not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return {"content": [{"type": "text", "text": payload}], "isError": False}


def _rodar_tool(ctx, nome: str, argumentos: dict) -> dict:
    from nomos.kernel.audit import redact_text
    home = Path(ctx["home"])
    if nome == "nomos_status":
        from nomos import __version__
        from nomos.cognition import engine_catalog as cat_mod
        from nomos.cognition.memory import Memory
        from nomos.kernel import localidade
        cat = cat_mod.construir(home)
        return _texto({
            "versao": __version__,
            "so_local": localidade.esta_ligado(home),
            "motores_prontos": {m: [x.id for x in cat.prontos(m)]
                                for m in cat_mod.MODALIDADES_V011},
            "memorias": Memory(home / "memory.db").count(),
        })
    if nome == "nomos_capacidades":
        from nomos.ext import skill_catalogo as scat
        return _texto(scat.capacidades(home, home / "skills"))
    if nome == "nomos_evidencias":
        from nomos.kernel import evidencia as ev
        raiz = home / "evidencias"
        pacotes = []
        if raiz.exists():
            for p in sorted(raiz.glob("EVIDENCIA_*")):
                ok, problemas = ev.verificar_pacote(p)
                pacotes.append({"nome": p.name, "integro": ok,
                                "problemas": problemas})
        return _texto(pacotes)
    if nome == "nomos_memoria_buscar":
        from nomos.cognition.memory import Memory
        consulta = str(argumentos.get("consulta", "")).strip()
        if not consulta:
            raise ValueError("consulta vazia")
        achados = Memory(home / "memory.db").recall(consulta, k=5)
        return _texto([{"id": a.id, "texto": redact_text(a.text)}
                       for a in achados])
    if nome == "nomos_roteador_explicar":
        from nomos.cognition import engine_catalog as cat_mod
        from nomos.cognition import engine_router as er
        modalidade = str(argumentos.get("modalidade", "texto"))
        if modalidade not in cat_mod.MODALIDADES_V011:
            raise ValueError(f"modalidade desconhecida: {modalidade}")
        return _texto(er.relatorio_decisao(
            er.Tarefa(tipo=modalidade, modalidade=modalidade), home=home))
    raise LookupError(f"tool desconhecida: {nome}")


def _despachar(ctx, msg: dict) -> dict | None:
    mid = msg.get("id")
    metodo = msg.get("method", "")
    if metodo == "initialize":
        from nomos import __version__
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOLO,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "nomos", "version": __version__},
            "instructions": ("NOMOS local, somente leitura. Todas as tools "
                             "consultam estado da máquina do usuário; nada "
                             "sai para a rede e nada é executado/escrito."),
        }}
    if metodo.startswith("notifications/"):
        return None                       # notificações não têm resposta
    if metodo == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if metodo == "tools/call":
        params = msg.get("params") or {}
        nome = str(params.get("name", ""))
        argumentos = params.get("arguments") or {}
        try:
            resultado = _rodar_tool(ctx, nome, argumentos)
        except (LookupError, ValueError) as exc:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": str(exc)}}
        except Exception as exc:          # nunca vaza detalhes internos
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32000,
                              "message": f"tool falhou: {type(exc).__name__}"}}
        if ctx.get("audit"):
            ctx["audit"].append("mcp.tool", tool=nome)
        return {"jsonrpc": "2.0", "id": mid, "result": resultado}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"método não suportado: {metodo}"}}


def servir(ctx, entrada=None, saida=None) -> int:
    """Loop MCP sobre stdio. Read-only; encerra no EOF do cliente."""
    entrada = entrada or sys.stdin
    saida = saida or sys.stdout
    if ctx.get("audit"):
        ctx["audit"].append("mcp.servidor.iniciado", transporte="stdio")
    for linha in entrada:
        linha = linha.strip()
        if not linha:
            continue
        try:
            msg = json.loads(linha)
        except Exception:
            resposta = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": "JSON inválido"}}
            saida.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            saida.flush()
            continue
        resposta = _despachar(ctx, msg)
        if resposta is not None:
            saida.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            saida.flush()
    if ctx.get("audit"):
        ctx["audit"].append("mcp.servidor.encerrado")
    return 0
