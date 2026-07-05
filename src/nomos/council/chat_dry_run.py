"""Chat command do Motor Council — dry-run `/conselho simular` (MC18-UX).

Habilita **apenas** `/conselho simular <texto>` no chat, chamando só o
`CouncilOrchestratorDryRun` (o orquestrador puro/dry-run de MC8) e devolvendo
uma resposta **redigida**. Espelha o padrão seguro já usado na CLI
(`nomos conselho simular`, MC15-UX), mas devolve **strings** (o loop do chat faz
`say(handle_chat_dry_run(linha))`), não imprime.

Roteamento:

    /conselho simular ...   -> dry-run (este módulo)
    /conselho <qualquer>    -> DESABILITADO (chat_disabled.disabled_message)
    mensagem não /conselho  -> None (o chat segue seu fluxo normal)

Continua: REAL_ENGINE_EXECUTION=false, REAL_POLICY=false, REAL_AUDIT=false,
REAL_VAULT=false, CLOUD=false, NETWORK=false, SUBPROCESS=false,
PERSISTENCE=false. Nunca ecoa o prompt; o JSON é montado à mão com escalares
seguros — o resultado inteiro do orquestrador (trace/envelope/metadados) nunca
é serializado. Pureza provada por AST: importa só stdlib (`json`) + o
orquestrador dry-run + o `chat_disabled`; não importa harness/policy/vault/
audit reais, rede, subprocess, cloud; não toca FS/env; não usa relógio nem
aleatoriedade.
"""
from __future__ import annotations

import json

from nomos.council.chat_disabled import disabled_message, is_conselho_command

# --------------------------------------------------------------------------
# Códigos legíveis (estáveis para o usuário/testes)
# --------------------------------------------------------------------------
DRY_RUN_CODE = "[NOMOS-MC-CHAT-DRY-RUN]"
GATE_BLOCKED_CODE = "[NOMOS-MC-CHAT-GATE-BLOCKED]"
BLOCKED_CODE = "[NOMOS-MC-CHAT-BLOCKED]"
DENIED_CODE = "[NOMOS-MC-CHAT-DENIED]"

# session_id fixo: não vem do prompt; sem relógio/aleatoriedade.
_SESSION_ID = "chat-conselho-simular"

# Português (UX) -> valor interno do CouncilMode.
_MODE_MAP = {
    "rapido": "fast",
    "balanceado": "balanced",
    "critico": "critical",
    "paranoico": "paranoid",
}
_MODE_DEFAULT = "balanceado"

_FORBIDDEN_FLAGS = {
    "--real", "--enable", "--ativar", "--force", "--unsafe", "--cloud",
    "--audit-real", "--policy-real", "--vault-real", "--engine-real",
}

_DRY_RUN_MESSAGE = (
    "[NOMOS-MC-CHAT-DRY-RUN] Conselho simulado com segurança.\n"
    "DRY_RUN=true\n"
    "REAL_ENGINE_EXECUTION=false\n"
    "REAL_POLICY=false\n"
    "REAL_AUDIT=false\n"
    "REAL_VAULT=false\n"
    "PERSISTENCE=false"
)

_GATE_BLOCKED_MESSAGE = (
    "[NOMOS-MC-CHAT-GATE-BLOCKED] Resposta bloqueada pelo Policy Gate dry-run.\n"
    "Nada foi executado.\n"
    "Nada foi persistido.\n"
    "Conteúdo bloqueado não será exibido."
)


def _deny(motivo: str) -> str:
    """Recusa fail-closed. `motivo` é texto FIXO interno; nunca inclui o prompt
    ou qualquer token digitado pelo usuário."""
    return (f"{DENIED_CODE} {motivo}\n"
            "Nada foi executado.\n"
            "Nada foi persistido.")


def _render_json(allowed: bool, blocked: bool, private_mode: bool,
                 failure_code) -> str:
    # Payload MÍNIMO montado só de escalares — nunca serializa
    # trace/final_envelope/audit_result, então não há como vazar
    # prompt/conteúdo/engine_id.
    payload = {
        "dry_run": True,
        "allowed": bool(allowed),
        "blocked": bool(blocked),
        "would_execute": False,
        "would_write_audit": False,
        "private_mode": bool(private_mode),
        "persist_allowed": (not private_mode),
        "failure_code": failure_code,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _render_human(allowed: bool, failure_code) -> str:
    if allowed:
        return _DRY_RUN_MESSAGE
    if failure_code == "ORCH_POLICY_GATE_DENIED":
        return _GATE_BLOCKED_MESSAGE
    # Outro bloqueio (sem candidatos, provider, etc.): mensagem segura, sem
    # conteúdo bruto; só o código de falha (um enum, nunca prompt/conteúdo).
    return (f"{BLOCKED_CODE} Simulação bloqueada (fail-closed).\n"
            "Nada foi executado.\n"
            "Nada foi persistido.\n"
            f"failure_code={failure_code}")


def _simular(tokens: list) -> str:
    """Executa `/conselho simular ...` em dry-run e devolve a resposta redigida.

    Chama SÓ o `CouncilOrchestratorDryRun`. O prompt alimenta o orquestrador,
    mas nunca é impresso/serializado/logado.
    """
    prompt_parts: list = []
    modo_pt = _MODE_DEFAULT
    privado = False
    as_json = False

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in _FORBIDDEN_FLAGS:
            return _deny("Flag não permitida para Motor Council Chat.")
        if tok == "--modo":
            if i + 1 >= n:
                return _deny("--modo exige um valor: rapido|balanceado|critico|paranoico.")
            modo_pt = tokens[i + 1]
            i += 2
            continue
        if tok == "--privado":
            privado = True
            i += 1
            continue
        if tok == "--json":
            as_json = True
            i += 1
            continue
        if tok in ("--iniciante", "--avancado"):
            # reconhecidas, porém cosméticas nesta fase
            i += 1
            continue
        if tok.startswith("--"):
            # qualquer outra flag desconhecida: fail-closed, sem ecoar o token
            return _deny("Flag desconhecida (dry-run only).")
        prompt_parts.append(tok)
        i += 1

    if modo_pt not in _MODE_MAP:
        # não ecoa o valor inválido
        return _deny("Modo inválido. Use: rapido|balanceado|critico|paranoico.")
    modo_interno = _MODE_MAP[modo_pt]
    if modo_pt == "paranoico":
        # paranoico implica modo privado (contrato de UX)
        privado = True

    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        return _deny("simular exige um texto, ex.: /conselho simular sua pergunta.")

    # Import tardio: o orquestrador (dry-run puro, MC8) só é importado no
    # caminho realmente usado.
    from nomos.council.orchestrator import (
        CouncilOrchestrationInput,
        CouncilOrchestratorDryRun,
    )

    try:
        entrada = CouncilOrchestrationInput(
            session_id=_SESSION_ID, prompt=prompt,
            mode=modo_interno, private_mode=privado)
        resultado = CouncilOrchestratorDryRun().run(entrada)
    except Exception:
        # Nunca vaza traceback nem prompt; falha do orquestrador vira bloqueio
        # seguro fail-closed.
        return (f"{BLOCKED_CODE} Não foi possível simular com segurança (fail-closed).\n"
                "Nada foi executado.\n"
                "Nada foi persistido.")

    allowed = bool(getattr(resultado, "allowed", False))
    blocked = bool(getattr(resultado, "blocked", not allowed))
    fc = getattr(resultado, "failure_code", None)
    failure_code = fc.value if fc is not None and hasattr(fc, "value") else fc

    if as_json:
        return _render_json(allowed, blocked, privado, failure_code)
    return _render_human(allowed, failure_code)


def handle_chat_dry_run(message: object) -> str | None:
    """Roteador do `/conselho` no chat (MC18-UX).

    - `/conselho simular ...` → dry-run (redigido);
    - `/conselho <qualquer outro>` (raiz incluída) → mensagem DESABILITADA;
    - mensagem que não começa com `/conselho` → `None`.

    Nunca ecoa o prompt/subcomando/flags nem chama policy/audit/vault/harness
    reais.
    """
    if not is_conselho_command(message):
        return None
    toks = message.strip().split()
    if len(toks) >= 2 and toks[1] == "simular":
        return _simular(toks[2:])
    # raiz e todos os demais subcomandos continuam desabilitados
    return disabled_message()
