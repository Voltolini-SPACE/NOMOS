"""Chat command do Motor Council — ESQUELETO DESABILITADO (fail-closed).

Fase MC16-UX. Registra o comportamento do futuro chat command `/conselho`, mas
ele nasce **desabilitado por construção** — mesma filosofia do CLI na MC14.

`handle_disabled_chat_command(message)`:

- detecta `/conselho` (e qualquer subcomando/argumento);
- **nunca** processa nem ecoa o texto do usuário;
- devolve uma mensagem fail-closed genérica;
- para mensagens que **não** começam com `/conselho`, devolve `None` — o loop
  de chat segue seu fluxo normal (contrato do chat amigável, que só age quando
  o handler devolve uma resposta).

Não chama o orquestrador, não constrói Vault/Policy/Audit, não persiste, não lê
variáveis de ambiente, não abre arquivos, não usa relógio nem aleatoriedade —
provado por AST em `tests/council/test_chat_conselho_disabled.py`. O módulo é
puro: importa só `from __future__ import annotations`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Trava literal. Não vem de env, config ou argumento; não existe função pública
# que a ligue (enable/activate/unlock/set_enabled). Ligar o chat de verdade
# virá de código novo e revisado numa fase futura, não de mudar este literal.
# ---------------------------------------------------------------------------
MOTOR_COUNCIL_CHAT_ENABLED = False

# Código legível da mensagem de bloqueio (estável para logs/testes do usuário).
CHAT_DISABLED_CODE = "[NOMOS-MC-CHAT-DISABLED]"

# O chat command futuro.
COMMAND = "/conselho"

# Subcomandos previstos para o futuro (todos ainda bloqueados nesta fase).
FUTURE_SUBCOMMANDS = (
    "simular",
    "perguntar",
    "revisar",
    "status",
    "modos",
    "explicar",
)

_DISABLED_MESSAGE = (
    "[NOMOS-MC-CHAT-DISABLED] Motor Council Chat ainda não está habilitado.\n"
    "\n"
    "Já disponível no chat (não executa motor):\n"
    "  /conselho status              — estado e travas\n"
    "  /conselho modos [--avancado]  — os 4 modos (aceita --json)\n"
    "  /conselho simular <texto>     — simulação segura (dry-run)\n"
    "\n"
    "Ainda desabilitado (exigiria execução real):\n"
    "  CHAT_ENABLED=false\n"
    "  REAL_ENGINE_EXECUTION=false\n"
    "  REAL_POLICY=false\n"
    "  REAL_AUDIT=false\n"
    "  REAL_VAULT=false\n"
    "  PERSISTENCE=false\n"
    "\n"
    "perguntar/revisar não executam nada, nenhum prompt é processado e nada\n"
    "é gravado."
)


def is_conselho_command(message: object) -> bool:
    """True se `message` é o chat command `/conselho` (com ou sem argumentos).

    Aceita exatamente `/conselho` ou `/conselho <algo>`; não casa prefixos
    coladinhos como `/conselhoxyz`.
    """
    if not isinstance(message, str):
        return False
    stripped = message.strip()
    return stripped == COMMAND or stripped.startswith(COMMAND + " ")


def disabled_message() -> str:
    """Mensagem genérica e fixa de bloqueio.

    NUNCA inclui o subcomando, o prompt ou qualquer flag que venha depois do
    comando — é uma constante, sem interpolação de entrada.
    """
    return _DISABLED_MESSAGE


def handle_disabled_chat_command(message: object) -> str | None:
    """Handler fail-closed do `/conselho` no chat.

    - `/conselho ...` → devolve a mensagem genérica de bloqueio, **sem**
      processar/ecoar nada do que veio depois (subcomando, prompt, flags
      proibidas — tudo ignorado).
    - qualquer outra coisa → devolve `None` (mensagem não relacionada).
    """
    if not is_conselho_command(message):
        return None
    return _DISABLED_MESSAGE
