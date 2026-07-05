"""Motor Council — helper compartilhado de saída segura/redigida (MC21).

Módulo **isolado**: transforma o resultado de um dry-run do Motor Council numa
estrutura segura (`CouncilSafeOutput`) que carrega **apenas** campos escalares
permitidos, e renderiza saídas humanas/JSON redigidas para as duas superfícies
(`interface="cli"` ou `"chat"`).

Esta fase **implementa** o helper conforme
`docs/architecture/MOTOR_COUNCIL_SHARED_OUTPUT_REDACTION_SPEC_v1.md` (MC20), mas
**não migra** a CLI (`cli_dry_run.py`) nem o chat (`chat_dry_run.py`) — eles
seguem com seu código próprio até MC22/MC23.

Garantias (provadas por teste em `tests/test_council_safe_output.py`):

- nunca emite prompt/content/final_content/candidate_content/engine_id/secret/
  token/api_key/authorization/bearer/trace/audit_envelope/candidate/raw_result;
- nunca serializa o resultado inteiro do orquestrador nem chama seus métodos de
  dump/representação — o objeto de saída carrega só escalares seguros;
- a serialização JSON só recebe o dict seguro de
  ``CouncilSafeOutput.to_json_dict``;
- `dry_run=true`, `would_execute=false`, `would_write_audit=false` são travados
  por construção (nunca lidos do resultado);
- `private_mode` ⇒ `persist_allowed=false`;
- resultado inválido → fail-closed (`SAFE_OUTPUT_INVALID_RESULT`);
- `interface`/`mode` inválidos → `ValueError` (não tenta corrigir texto);
- puro: sem rede/subprocess/threading/asyncio/cloud/motor; sem FS/env; sem
  relógio/aleatoriedade.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

CouncilInterface = Literal["cli", "chat"]

_INTERFACES = ("cli", "chat")

# Modos NORMALIZADOS (valor interno do CouncilMode). Nunca texto do usuário.
_NORMALIZED_MODES = ("fast", "balanced", "critical", "paranoid")

# Código de falha usado quando o resultado recebido é estruturalmente inválido.
SAFE_OUTPUT_INVALID_RESULT = "SAFE_OUTPUT_INVALID_RESULT"

# Códigos legíveis por interface (prefixos distintos preservados por
# compatibilidade com o que CLI/Chat já emitem hoje).
_CODES = {
    "cli": {
        "dry_run": "[NOMOS-MC-DRY-RUN]",
        "gate": "[NOMOS-MC-GATE-BLOCKED]",
        "blocked": "[NOMOS-MC-BLOCKED]",
        "denied": "[NOMOS-MC-CLI-DENIED]",
    },
    "chat": {
        "dry_run": "[NOMOS-MC-CHAT-DRY-RUN]",
        "gate": "[NOMOS-MC-CHAT-GATE-BLOCKED]",
        "blocked": "[NOMOS-MC-CHAT-BLOCKED]",
        "denied": "[NOMOS-MC-CHAT-DENIED]",
    },
}

_SUCCESS_PHRASE = {
    "cli": "Motor Council simulado com sucesso.",
    "chat": "Conselho simulado com segurança.",
}

_DRY_RUN_BLOCK = (
    "DRY_RUN=true\n"
    "REAL_ENGINE_EXECUTION=false\n"
    "REAL_POLICY=false\n"
    "REAL_AUDIT=false\n"
    "REAL_VAULT=false\n"
    "PERSISTENCE=false"
)

_NADA = "Nada foi executado.\nNada foi persistido."

# Sentinela para detectar resultado inválido sem levantar exceção ao ler.
_MISSING = object()

# Código de falha que sinaliza bloqueio pelo Policy Gate dry-run.
_GATE_FAILURE_CODE = "ORCH_POLICY_GATE_DENIED"


@dataclass(frozen=True)
class CouncilSafeOutput:
    """Saída segura do Motor Council dry-run — só campos escalares permitidos."""

    interface: CouncilInterface
    dry_run: bool
    allowed: bool
    blocked: bool
    would_execute: bool
    would_write_audit: bool
    private_mode: bool
    persist_allowed: bool
    failure_code: str | None
    mode: str

    def to_json_dict(self) -> dict[str, object]:
        """Dict só com as 10 chaves seguras (nunca conteúdo/prompt/engine_id)."""
        return {
            "interface": self.interface,
            "dry_run": self.dry_run,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "would_execute": self.would_execute,
            "would_write_audit": self.would_write_audit,
            "private_mode": self.private_mode,
            "persist_allowed": self.persist_allowed,
            "failure_code": self.failure_code,
            "mode": self.mode,
        }


def _require_interface(interface: str) -> None:
    if interface not in _INTERFACES:
        raise ValueError(f"interface inválida: {interface!r} (use 'cli' ou 'chat')")


def _normalize_failure_code(fc: object) -> str | None:
    if fc is None:
        return None
    # enum -> valor; qualquer outra coisa -> str (nunca conteúdo bruto: o
    # failure_code do orquestrador é sempre um código curto, não texto livre).
    valor = getattr(fc, "value", _MISSING)
    if valor is not _MISSING:
        return str(valor)
    return str(fc)


def build_safe_output(
    result: object,
    *,
    interface: CouncilInterface,
    mode: str,
    private_mode: bool,
) -> CouncilSafeOutput:
    """Constrói uma `CouncilSafeOutput` lendo SÓ escalares permitidos do result.

    Lê apenas `allowed`/`blocked`/`failure_code` via `getattr` — nunca métodos
    de dump/representação do resultado nem qualquer campo de conteúdo.
    `dry_run`, `would_execute` e `would_write_audit` são travados por
    construção; `persist_allowed = not private_mode`.

    Fail-closed: `interface`/`mode` inválidos ⇒ `ValueError`; resultado sem o
    atributo `allowed` (estruturalmente inválido) ⇒ saída bloqueada com
    `failure_code=SAFE_OUTPUT_INVALID_RESULT`.
    """
    _require_interface(interface)
    if mode not in _NORMALIZED_MODES:
        raise ValueError(f"mode não normalizado: {mode!r} (use {list(_NORMALIZED_MODES)})")

    priv = bool(private_mode)

    raw_allowed = getattr(result, "allowed", _MISSING)
    if raw_allowed is _MISSING:
        # objeto inválido — fail-closed, sem tentar ler mais nada dele
        return CouncilSafeOutput(
            interface=interface, dry_run=True, allowed=False, blocked=True,
            would_execute=False, would_write_audit=False,
            private_mode=priv, persist_allowed=not priv,
            failure_code=SAFE_OUTPUT_INVALID_RESULT, mode=mode)

    allowed = bool(raw_allowed)
    blocked = bool(getattr(result, "blocked", not allowed))
    failure_code = _normalize_failure_code(getattr(result, "failure_code", None))

    return CouncilSafeOutput(
        interface=interface, dry_run=True, allowed=allowed, blocked=blocked,
        would_execute=False, would_write_audit=False,
        private_mode=priv, persist_allowed=not priv,
        failure_code=failure_code, mode=mode)


def render_json_output(output: CouncilSafeOutput) -> str:
    """Serializa SÓ o dict seguro (`to_json_dict`) — nunca o resultado inteiro."""
    return json.dumps(output.to_json_dict(), sort_keys=True, ensure_ascii=False)


def render_human_output(output: CouncilSafeOutput) -> str:
    """Saída humana redigida, escolhendo prefixo/frase por `interface`."""
    codes = _CODES[output.interface]
    if output.allowed:
        return f"{codes['dry_run']} {_SUCCESS_PHRASE[output.interface]}\n{_DRY_RUN_BLOCK}"
    if output.failure_code == _GATE_FAILURE_CODE:
        return render_gate_blocked_output(output.interface)
    return (f"{codes['blocked']} Simulação bloqueada (fail-closed).\n"
            f"{_NADA}\n"
            f"failure_code={output.failure_code}")


def render_gate_blocked_output(interface: CouncilInterface) -> str:
    """Bloqueio pelo Policy Gate dry-run — nunca exibe o conteúdo bloqueado."""
    _require_interface(interface)
    return (f"{_CODES[interface]['gate']} Resposta bloqueada pelo Policy Gate dry-run.\n"
            f"{_NADA}\n"
            "Conteúdo bloqueado não será exibido.")


def render_denied_output(interface: CouncilInterface,
                         reason: str | None = None) -> str:
    """Recusa fail-closed. `reason` é texto FIXO interno; nunca o prompt/flag."""
    _require_interface(interface)
    if reason is None:
        reason = ("Comando negado para Motor Council." if interface == "cli"
                  else "Comando negado para Motor Council Chat.")
    return f"{_CODES[interface]['denied']} {reason}\n{_NADA}"


def render_exception_output(interface: CouncilInterface) -> str:
    """Exceção do orquestrador vira bloqueio seguro (sem traceback nem prompt)."""
    _require_interface(interface)
    return (f"{_CODES[interface]['blocked']} Não foi possível simular com segurança "
            f"(fail-closed).\n{_NADA}")
