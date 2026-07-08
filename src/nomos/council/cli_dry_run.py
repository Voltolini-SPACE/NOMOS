"""CLI do Motor Council — comando dry-run `nomos conselho simular` (MC15-UX,
migrado ao helper compartilhado de saída segura na MC22).

Único subcomando que sai do esqueleto desabilitado da MC14: `simular`. Ele chama
**apenas** o `CouncilOrchestratorDryRun` (dry-run puro, já provado em MC8).
Continua:

    REAL_ENGINE_EXECUTION=false   REAL_POLICY=false   REAL_AUDIT=false
    REAL_VAULT=false   CLOUD=false   NETWORK=false   SUBPROCESS=false
    PERSISTENCE=false

A ESTRUTURA segura e o JSON de saída vêm do helper compartilhado
`nomos.council.safe_output` (MC22): o CLI chama `build_safe_output` e
`render_json_output`, então **nunca** serializa o resultado do orquestrador nem
lê dele além de `allowed`/`blocked`/`failure_code` (isolado dentro do helper).
As mensagens **humanas** são específicas do CLI e simples/amigáveis (sem
jargão), montadas só a partir dos campos escalares seguros — nunca do prompt.

Todos os outros usos de `conselho` (raiz, `perguntar`, `revisar`, `status`,
`modos`, `diagnostico`, `explicar`, desconhecidos) continuam roteados para o
handler DESABILITADO (`cli_disabled.run_disabled`).

Pureza: este módulo importa só o handler desabilitado, o helper de saída segura
e (tardiamente) o orquestrador dry-run. Não importa rede, subprocess, threading,
asyncio, SDK de nuvem, motor, harness de execução real, nem policy/audit/vault
reais do kernel. Não lê variáveis de ambiente, não abre arquivos, não usa
relógio nem aleatoriedade, e não serializa/representa o resultado bruto —
provado por AST em `tests/council/test_cli_conselho_dry_run.py`.
"""
from __future__ import annotations

from nomos.council.cli_diag import run_diagnostico
from nomos.council.cli_disabled import run_disabled
from nomos.council.cli_info import run_modos, run_status
from nomos.council.forbidden_flags import FORBIDDEN_FLAGS, is_forbidden_flag
from nomos.council.safe_output import build_safe_output, render_json_output

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

# MC24: contrato ÚNICO de flags proibidas — fonte única em
# `nomos.council.forbidden_flags`, reconciliado com o chat no MESMO conjunto de
# 10 (decisão A). Antes da MC24 a CLI listava só 8 (sem `--vault-real`/
# `--engine-real`); agora as duas superfícies compartilham o mesmo objeto. O
# alias preserva o nome interno usado no parser.
_FORBIDDEN_FLAGS = FORBIDDEN_FLAGS

# MC22: a ESTRUTURA segura e o JSON vêm do helper compartilhado
# (`safe_output`). As mensagens HUMANAS abaixo são específicas do CLI e
# **simples/amigáveis** (sem jargão técnico), montadas só a partir dos campos
# escalares seguros — nunca do resultado bruto. O bloco de flags técnicas
# (`DRY_RUN=true`/`REAL_*`) fica sob "Status:" para quem quiser conferir.
_SUCESSO_MESSAGE = (
    "[NOMOS-MC-DRY-RUN] Simulação segura concluída.\n"
    "Nada foi executado de verdade.\n"
    "Nada foi salvo.\n"
    "Nenhum dado sensível foi exibido.\n"
    "Status:\n"
    "DRY_RUN=true\n"
    "REAL_ENGINE_EXECUTION=false\n"
    "REAL_POLICY=false\n"
    "REAL_AUDIT=false\n"
    "REAL_VAULT=false\n"
    "PERSISTENCE=false"
)

_GATE_BLOCKED_MESSAGE = (
    "[NOMOS-MC-GATE-BLOCKED] A simulação foi bloqueada por segurança.\n"
    "Nada foi executado.\n"
    "Nada foi salvo.\n"
    "O conteúdo bloqueado não será exibido."
)

_BLOQUEIO_MESSAGE = (
    "[NOMOS-MC-BLOCKED] Não consegui simular com segurança agora.\n"
    "Nada foi executado.\n"
    "Nada foi salvo."
)


def route_conselho(tokens: list) -> int:
    """Roteia `nomos conselho <...>` (recebe os tokens APÓS `conselho`).

    Só `simular` é habilitado (dry-run); qualquer outra coisa cai no handler
    DESABILITADO, que nunca ecoa nada do que o usuário digitou.
    """
    toks = list(tokens or [])
    if toks and toks[0] == "simular":
        return simular(toks[1:])
    # MC23-UX: subcomandos PURAMENTE INFORMATIVOS (fatos estáticos; não
    # executam motor, não leem prompt, não gravam nada). `status`/`modos` já
    # foram finalizados — `perguntar`/`revisar` seguem fail-closed abaixo.
    if toks and toks[0] == "status":
        return run_status(toks[1:])
    if toks and toks[0] == "modos":
        return run_modos(toks[1:])
    if toks and toks[0] == "diagnostico":
        # lê a trava real (só leitura) e reporta — não executa nada
        return run_diagnostico(toks[1:])
    # raiz e todos os demais subcomandos: fail-closed / desabilitado
    return run_disabled()


def _deny(motivo: str) -> int:
    """Recusa fail-closed, com mensagem simples e amigável. `motivo` é um texto
    FIXO interno; nunca inclui o prompt ou qualquer token digitado pelo
    usuário."""
    print(f"{DENIED_CODE} {motivo}\nNada foi executado.\nNada foi salvo.")
    return DENIED_EXIT_CODE


def _render_human(output) -> int:
    """Saída humana simples/amigável, lendo SÓ os campos escalares seguros do
    `CouncilSafeOutput` — nunca o resultado bruto do orquestrador."""
    if output.allowed:
        print(_SUCESSO_MESSAGE)
        return DRY_RUN_EXIT_CODE
    if output.failure_code == "ORCH_POLICY_GATE_DENIED":
        print(_GATE_BLOCKED_MESSAGE)
        return DRY_RUN_EXIT_CODE
    # Outro bloqueio (sem motor elegível, etc.): mensagem simples e segura, sem
    # conteúdo bruto e sem jargão (o código técnico fica só no --json).
    print(_BLOQUEIO_MESSAGE)
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
        if is_forbidden_flag(tok):
            # nunca ativa execução real; nem ecoa a flag/valor
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
        return _deny('Escreva o que você quer simular. Ex.: conselho simular "sua pergunta".')

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
        # seguro fail-closed (mensagem simples e amigável).
        print(_BLOQUEIO_MESSAGE)
        return DENIED_EXIT_CODE

    # MC22: a estrutura segura e o JSON vêm do helper compartilhado. O `output`
    # só carrega escalares seguros; o resultado bruto nunca é serializado nem
    # lido além de allowed/blocked/failure_code (feito dentro do helper).
    output = build_safe_output(
        resultado, interface="cli", mode=modo_interno, private_mode=privado)

    if as_json:
        print(render_json_output(output))
        return DRY_RUN_EXIT_CODE
    return _render_human(output)
