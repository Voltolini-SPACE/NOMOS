"""CLI do Motor Council — ESQUELETO DESABILITADO (fail-closed).

Fase MC14-UX. Este módulo registra o *comportamento* do futuro comando
`nomos conselho`, mas ele **nasce desabilitado por construção**. Nenhum uso:

- executa o orquestrador (`CouncilOrchestratorDryRun`);
- chama motor, Ollama, subprocess, HTTP, cloud;
- chama policy/audit/vault/approval reais;
- persiste qualquer coisa em disco;
- processa ou ecoa o prompt/argumento do usuário.

O módulo é deliberadamente **puro**: não importa rede, subprocess, threading,
asyncio, SDKs de nuvem, motores, nem o orquestrador/harness/policy/audit do
Council. Não lê variáveis de ambiente, não abre arquivos, não usa relógio nem
aleatoriedade.
A única saída possível é uma mensagem genérica de bloqueio — provada por AST em
`tests/council/test_cli_conselho_disabled.py`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Trava literal. Não vem de env, config ou argumento; não existe função pública
# que a ligue (enable/activate/unlock/set_enabled). Alterá-la exige uma edição
# explícita e auditável deste arquivo — e mesmo assim `run_disabled` continua
# fail-closed (não há caminho de execução real neste módulo).
# ---------------------------------------------------------------------------
MOTOR_COUNCIL_CLI_ENABLED = False

# Comando informativo: rodar `nomos conselho` e receber "está desabilitado" é um
# sucesso operacional (como `nomos status`/`nomos doutor`), então o código de
# saída é 0. O projeto não tem um código específico para "comando indisponível";
# 0 está entre os valores permitidos pela missão (0 ou 2).
DISABLED_EXIT_CODE = 0

# Código legível da mensagem de bloqueio (estável, para logs/testes do usuário).
DISABLED_CODE = "[NOMOS-MC-CLI-DISABLED]"

# Subcomandos previstos para o futuro (todos ainda bloqueados nesta fase). São
# apenas nomes para documentação/UX; nada aqui os executa.
FUTURE_SUBCOMMANDS = (
    "status",
    "modos",
    "simular",
    "perguntar",
    "revisar",
    "explicar",
)

_DISABLED_MESSAGE = (
    "[NOMOS-MC-CLI-DISABLED] Motor Council CLI ainda não está habilitado.\n"
    "\n"
    "Já disponível (não executa motor):\n"
    "  nomos conselho status              — estado e travas\n"
    "  nomos conselho modos [--avancado]  — os 4 modos (aceita --json)\n"
    "  nomos conselho simular <texto>     — simulação segura (dry-run)\n"
    "\n"
    "Ainda desabilitado (exigiria execução real):\n"
    "  CLI_ENABLED=false\n"
    "  REAL_ENGINE_EXECUTION=false\n"
    "  REAL_POLICY=false\n"
    "  REAL_AUDIT=false\n"
    "  REAL_VAULT=false\n"
    "  PERSISTENCE=false\n"
    "\n"
    "perguntar/revisar não executam nada, nenhum prompt é processado e nada é\n"
    "gravado. Detalhes:\n"
    "  docs/architecture/MOTOR_COUNCIL_INDEX_v1.md\n"
    "  docs/architecture/MOTOR_COUNCIL_UX_SPEC_v1.md"
)


def disabled_message() -> str:
    """Mensagem genérica e fixa de bloqueio.

    NUNCA inclui o prompt, o subcomando ou qualquer flag que o usuário tenha
    digitado — é uma constante, sem interpolação de entrada.
    """
    return _DISABLED_MESSAGE


def run_disabled(args: object | None = None) -> int:
    """Handler fail-closed do `nomos conselho` (MC14-UX).

    `args` é aceito por compatibilidade de assinatura, mas é **completamente
    ignorado**: nada do que o usuário digitou (subcomando, prompt, flags como
    ``--enable``/``--force``/``--real``/``--cloud``) é lido, processado, ecoado,
    logado ou persistido. Sempre imprime a mensagem genérica e retorna o código
    de "indisponível".
    """
    # Defesa em profundidade: mesmo que a constante fosse adulterada em runtime,
    # este handler não tem caminho para execução real — ele só imprime.
    print(_DISABLED_MESSAGE)
    return DISABLED_EXIT_CODE
