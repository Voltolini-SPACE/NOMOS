"""CLI do Motor Council — comando dry-run `nomos conselho simular` (MC15-UX).

Único subcomando que sai do esqueleto desabilitado da MC14: `simular`. Ele chama
**apenas** o `CouncilOrchestratorDryRun` (dry-run puro, já provado em MC8) e
imprime um resultado **redigido**. Continua:

    REAL_ENGINE_EXECUTION=false   REAL_POLICY=false   REAL_AUDIT=false
    REAL_VAULT=false   CLOUD=false   NETWORK=false   SUBPROCESS=false
    PERSISTENCE=false

Nunca ecoa o prompt (nem em texto, JSON, erro ou log — só é usado para
alimentar o orquestrador, cujo resultado é metadata-only). Todos os outros
usos de `conselho` (raiz, `perguntar`, `revisar`, `status`, `modos`,
`diagnostico`, `explicar`, desconhecidos) continuam roteados para o handler
DESABILITADO (`cli_disabled.run_disabled`).

Pureza: este módulo importa só stdlib (`json`) + o orquestrador dry-run + o
handler desabilitado. Não importa rede, subprocess, threading, asyncio, SDK de
nuvem, motor, harness de execução real, nem policy/audit/vault reais do kernel.
Não lê variáveis de ambiente, não abre arquivos, não usa relógio nem
aleatoriedade — provado por AST em `tests/council/test_cli_conselho_dry_run.py`.
"""
from __future__ import annotations

import json

from nomos.council.cli_disabled import run_disabled

# --------------------------------------------------------------------------
# Códigos legíveis (estáveis para logs/testes do usuário)
# --------------------------------------------------------------------------
DRY_RUN_CODE = "[NOMOS-MC-DRY-RUN]"
GATE_BLOCKED_CODE = "[NOMOS-MC-GATE-BLOCKED]"
BLOCKED_CODE = "[NOMOS-MC-BLOCKED]"
DENIED_CODE = "[NOMOS-MC-CLI-DENIED]"

# Simulação concluída (permitida OU bloqueada pelo gate) é um resultado válido
# de dry-run → 0. Uso indevido (flag proibida, modo inválido, texto ausente) é
# negado → 3 (mesma semântica de "negado" do resto da CLI).
DRY_RUN_EXIT_CODE = 0
DENIED_EXIT_CODE = 3

# session_id fixo: não vem do prompt, não usa relógio/aleatoriedade. É só um
# identificador para o pipeline dry-run; nenhum conteúdo do usuário entra nele.
_SESSION_ID = "cli-conselho-simular"

# Português (UX) -> valor interno do CouncilMode.
_MODE_MAP = {
    "rapido": "fast",
    "balanceado": "balanced",
    "critico": "critical",
    "paranoico": "paranoid",
}
_MODE_DEFAULT = "balanceado"

_BOOL_FLAGS = {"--privado", "--json", "--iniciante", "--avancado"}
_FORBIDDEN_FLAGS = {
    "--real", "--enable", "--ativar", "--force", "--unsafe", "--cloud",
    "--audit-real", "--policy-real",
}

_DRY_RUN_MESSAGE = (
    "[NOMOS-MC-DRY-RUN] Motor Council simulado com sucesso.\n"
    "DRY_RUN=true\n"
    "REAL_ENGINE_EXECUTION=false\n"
    "REAL_POLICY=false\n"
    "REAL_AUDIT=false\n"
    "REAL_VAULT=false\n"
    "PERSISTENCE=false"
)

_GATE_BLOCKED_MESSAGE = (
    "[NOMOS-MC-GATE-BLOCKED] Resposta bloqueada pelo Policy Gate dry-run.\n"
    "Nada foi executado.\n"
    "Nada foi persistido.\n"
    "Conteúdo bloqueado não será exibido."
)


def route_conselho(tokens: list) -> int:
    """Roteia `nomos conselho <...>` (recebe os tokens APÓS `conselho`).

    Só `simular` é habilitado (dry-run); qualquer outra coisa cai no handler
    DESABILITADO, que nunca ecoa nada do que o usuário digitou.
    """
    toks = list(tokens or [])
    if toks and toks[0] == "simular":
        return simular(toks[1:])
    # raiz e todos os demais subcomandos: fail-closed / desabilitado
    return run_disabled()


def _deny(motivo: str) -> int:
    """Recusa fail-closed. `motivo` é um texto FIXO interno; nunca inclui o
    prompt ou qualquer token digitado pelo usuário."""
    print(f"{DENIED_CODE} {motivo}\nNada foi executado. Nada foi persistido.")
    return DENIED_EXIT_CODE


def _render_json(allowed: bool, blocked: bool, private_mode: bool,
                 failure_code) -> int:
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
    print(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    return DRY_RUN_EXIT_CODE


def _render_human(allowed: bool, failure_code) -> int:
    if allowed:
        print(_DRY_RUN_MESSAGE)
        return DRY_RUN_EXIT_CODE
    if failure_code == "ORCH_POLICY_GATE_DENIED":
        print(_GATE_BLOCKED_MESSAGE)
        return DRY_RUN_EXIT_CODE
    # Outro bloqueio (sem candidatos, provider, etc.): mensagem segura, sem
    # conteúdo bruto; só o código de falha (um enum, nunca prompt/conteúdo).
    print(f"{BLOCKED_CODE} Simulação bloqueada (fail-closed).\n"
          "Nada foi executado. Nada foi persistido.\n"
          f"failure_code={failure_code}")
    return DRY_RUN_EXIT_CODE


def simular(tokens: list) -> int:
    """`nomos conselho simular "texto" [--modo ...] [--privado] [--json] ...`.

    Chama SÓ o `CouncilOrchestratorDryRun`. O prompt é usado para alimentar o
    orquestrador, mas nunca é impresso/serializado/logado.
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
            # nunca ativa execução real; nem ecoa a flag/valor
            return _deny("flag não permitida nesta fase (dry-run only).")
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
            return _deny("flag desconhecida (dry-run only).")
        prompt_parts.append(tok)
        i += 1

    if modo_pt not in _MODE_MAP:
        # não ecoa o valor inválido
        return _deny("modo inválido. Use: rapido|balanceado|critico|paranoico.")
    modo_interno = _MODE_MAP[modo_pt]
    if modo_pt == "paranoico":
        # paranoico implica modo privado (contrato de UX)
        privado = True

    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        return _deny('simular exige um texto entre aspas, ex.: conselho simular "sua pergunta".')

    # Import tardio: mantém o boot da CLI leve e o import do orquestrador só
    # acontece no caminho realmente usado. O orquestrador é dry-run puro (MC8).
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
        print(f"{BLOCKED_CODE} Não foi possível simular com segurança (fail-closed).\n"
              "Nada foi executado. Nada foi persistido.")
        return DENIED_EXIT_CODE

    allowed = bool(getattr(resultado, "allowed", False))
    blocked = bool(getattr(resultado, "blocked", not allowed))
    fc = getattr(resultado, "failure_code", None)
    failure_code = fc.value if fc is not None and hasattr(fc, "value") else fc

    if as_json:
        return _render_json(allowed, blocked, privado, failure_code)
    return _render_human(allowed, failure_code)
