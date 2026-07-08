"""Chat command do Motor Council — dry-run `/conselho simular` (MC18-UX,
migrado ao helper compartilhado de saída segura na MC23).

Habilita **apenas** `/conselho simular <texto>` no chat, chamando só o
`CouncilOrchestratorDryRun` (o orquestrador puro/dry-run de MC8) e devolvendo
uma resposta **redigida**. Espelha o padrão seguro da CLI
(`nomos conselho simular`, MC15/MC22), mas devolve **strings** (o loop do chat
faz `say(handle_chat_dry_run(linha))`), não imprime.

Roteamento:

    /conselho simular ...   -> dry-run (este módulo)
    /conselho <qualquer>    -> DESABILITADO (chat_disabled.disabled_message)
    mensagem não /conselho  -> None (o chat segue seu fluxo normal)

Continua: REAL_ENGINE_EXECUTION=false, REAL_POLICY=false, REAL_AUDIT=false,
REAL_VAULT=false, CLOUD=false, NETWORK=false, SUBPROCESS=false,
PERSISTENCE=false. A ESTRUTURA segura e o JSON vêm do helper compartilhado
`nomos.council.safe_output` (MC23): `build_safe_output` + `render_json_output`,
então o resultado do orquestrador nunca é serializado nem lido além de
`allowed`/`blocked`/`failure_code` (isolado no helper). As mensagens **humanas**
são específicas do chat e simples/amigáveis (sem jargão), montadas só a partir
dos campos escalares seguros — nunca do prompt. Pureza provada por AST: importa
só o `chat_disabled`, o helper de saída segura e (tardiamente) o orquestrador
dry-run; não importa harness/policy/vault/audit reais, rede, subprocess, cloud;
não toca FS/env; não usa relógio/aleatoriedade; não serializa/representa o
resultado bruto.
"""
from __future__ import annotations

from nomos.council.chat_disabled import disabled_message, is_conselho_command
from nomos.council.cli_diag import diagnostico_json, diagnostico_message
from nomos.council.cli_info import (
    ajuda_message,
    modos_json,
    modos_message,
    status_json,
    status_message,
)
from nomos.council.forbidden_flags import FORBIDDEN_FLAGS, is_forbidden_flag
from nomos.council.safe_output import build_safe_output, render_json_output

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

# MC24: contrato ÚNICO de flags proibidas — fonte única em
# `nomos.council.forbidden_flags`, o MESMO objeto usado pela CLI (decisão A). O
# chat já listava as 10; agora ambas as superfícies compartilham a fonte única,
# eliminando a divergência (a CLI passou de 8 para 10). O alias preserva o nome
# interno usado no parser.
_FORBIDDEN_FLAGS = FORBIDDEN_FLAGS

# MC23: a ESTRUTURA segura e o JSON vêm do helper compartilhado
# (`safe_output`). As mensagens HUMANAS abaixo são específicas do chat e
# **simples/amigáveis** (sem jargão), montadas só a partir dos campos escalares
# seguros — nunca do prompt/resultado bruto. O bloco técnico (`DRY_RUN=true`/
# `REAL_*`) fica sob "Status:" para quem quiser conferir.
_SUCESSO_MESSAGE = (
    "[NOMOS-MC-CHAT-DRY-RUN] Simulação segura concluída.\n"
    "\n"
    "Nada foi executado de verdade.\n"
    "Nada foi salvo.\n"
    "Nenhum dado sensível foi exibido.\n"
    "\n"
    "Status:\n"
    "DRY_RUN=true\n"
    "REAL_ENGINE_EXECUTION=false\n"
    "REAL_POLICY=false\n"
    "REAL_AUDIT=false\n"
    "REAL_VAULT=false\n"
    "PERSISTENCE=false"
)

_GATE_BLOCKED_MESSAGE = (
    "[NOMOS-MC-CHAT-GATE-BLOCKED] A simulação foi bloqueada por segurança.\n"
    "\n"
    "Nada foi executado.\n"
    "Nada foi salvo.\n"
    "O conteúdo bloqueado não será exibido."
)

_BLOQUEIO_MESSAGE = (
    "[NOMOS-MC-CHAT-BLOCKED] Não consegui simular com segurança agora.\n"
    "\n"
    "Nada foi executado.\n"
    "Nada foi salvo."
)


def _deny(motivo: str) -> str:
    """Recusa fail-closed, com mensagem simples e amigável. `motivo` é texto
    FIXO interno; nunca inclui o prompt ou qualquer token digitado pelo
    usuário."""
    return (f"{DENIED_CODE} {motivo}\n"
            "\n"
            "Nada foi executado.\n"
            "Nada foi salvo.")


def _render_human(output) -> str:
    """Saída humana simples/amigável, lendo SÓ os campos escalares seguros do
    `CouncilSafeOutput` — nunca o resultado bruto do orquestrador."""
    if output.allowed:
        return _SUCESSO_MESSAGE
    if output.failure_code == "ORCH_POLICY_GATE_DENIED":
        return _GATE_BLOCKED_MESSAGE
    # Outro bloqueio (sem motor elegível, etc.): mensagem simples e segura, sem
    # conteúdo bruto e sem jargão (o código técnico fica só no --json).
    return _BLOQUEIO_MESSAGE


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
        if is_forbidden_flag(tok):
            return _deny("Este comando não pode ser usado com essa opção.")
        if tok == "--modo":
            if i + 1 >= n:
                return _deny("Diga qual modo: rapido, balanceado, critico ou paranoico.")
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
            return _deny("Essa opção não existe para este comando.")
        prompt_parts.append(tok)
        i += 1

    if modo_pt not in _MODE_MAP:
        # não ecoa o valor inválido
        return _deny("Esse modo não existe. Use: rapido, balanceado, critico ou paranoico.")
    modo_interno = _MODE_MAP[modo_pt]
    if modo_pt == "paranoico":
        # paranoico implica modo privado (contrato de UX)
        privado = True

    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        return _deny("Escreva o que você quer simular. Ex.: /conselho simular sua pergunta.")

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
        # seguro fail-closed (mensagem simples e amigável).
        return _BLOQUEIO_MESSAGE

    # MC23: a estrutura segura e o JSON vêm do helper compartilhado. O `output`
    # só carrega escalares seguros; o resultado bruto nunca é serializado nem
    # lido além de allowed/blocked/failure_code (feito dentro do helper).
    output = build_safe_output(
        resultado, interface="chat", mode=modo_interno, private_mode=privado)

    if as_json:
        return render_json_output(output)
    return _render_human(output)


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
    # MC27-UX: `ajuda` — mapa amigável dos comandos (estático, fonte única).
    if len(toks) >= 2 and toks[1] == "ajuda":
        for tok in toks[2:]:
            if is_forbidden_flag(tok):
                return _deny("Este comando não aceita essa opção.")
        return ajuda_message()
    # MC24-UX: subcomandos INFORMATIVOS puros (fatos estáticos; sem motor,
    # prompt, rede ou disco) — mesmas mensagens da CLI (fonte única cli_info).
    if len(toks) >= 2 and toks[1] in ("status", "modos"):
        resto = toks[2:]
        for tok in resto:
            if is_forbidden_flag(tok):
                return _deny("Este comando não aceita essa opção.")
        as_json = "--json" in resto
        if toks[1] == "status":
            return status_json() if as_json else status_message()
        if as_json:
            return modos_json()
        return modos_message("--avancado" in resto)
    # MC26-UX: diagnóstico lê a trava real (só leitura) e reporta — não executa.
    if len(toks) >= 2 and toks[1] == "diagnostico":
        resto = toks[2:]
        for tok in resto:
            if is_forbidden_flag(tok):
                return _deny("Este comando não aceita essa opção.")
        return diagnostico_json() if "--json" in resto else diagnostico_message()
    # raiz e demais subcomandos (perguntar/revisar/explicar) continuam desabilitados
    return disabled_message()
