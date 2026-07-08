"""CLI do Motor Council — diagnóstico fail-closed AO VIVO (MC26-UX).

`nomos conselho diagnostico` (e `/conselho diagnostico`) NÃO imprime uma string
fixa: ele LÊ a trava de execução real direto do harness
(`real_execution_enabled()`, que devolve `REAL_LOCAL_ENGINE_EXECUTION_ENABLED`)
e reporta o estado. É a prova executável do lema "evidência, não promessa" — se
a trava algum dia mudasse, esta saída mudaria junto (provado por teste que a
monkeypatcha).

Segurança/pureza: o módulo importa só a LEITURA da trava
(`real_execution_enabled`) e o contrato de flags proibidas. Nunca executa motor
(jamais chama `LocalExecutionHarness.execute`), não importa rede, subprocess,
threading, asyncio, SDK de nuvem, orquestrador, policy/audit/vault do kernel;
não lê variáveis de ambiente, não abre arquivos, não usa relógio nem
aleatoriedade — provado por AST em `tests/council/test_conselho_diagnostico.py`.
"""
from __future__ import annotations

import json

from nomos.council.forbidden_flags import is_forbidden_flag
from nomos.council.local_harness import real_execution_enabled

DIAG_CODE = "[NOMOS-MC-DIAG]"
DIAG_DENIED_CODE = "[NOMOS-MC-CLI-DENIED]"
DIAG_EXIT_CODE = 0
DIAG_DENIED_EXIT_CODE = 3


def diagnostico_message() -> str:
    """Relatório do diagnóstico, com a trava lida AO VIVO do harness."""
    ligada = bool(real_execution_enabled())
    trava = "true" if ligada else "false"
    if not ligada:
        veredito = (
            "Resultado: FAIL-CLOSED — nenhum motor real é executado nesta fase.\n"
            "Nada é gravado, nenhum prompt é processado."
        )
    else:  # pragma: no cover - a trava é False por construção; ramo de alerta
        veredito = (
            "Resultado: ATENÇÃO — a trava de execução real está LIGADA.\n"
            "Isto só deveria ocorrer numa fase explicitamente aprovada."
        )
    return (
        f"{DIAG_CODE} Motor Council — diagnóstico (leitura ao vivo)\n"
        "\n"
        "Trava de execução real, lida do harness agora:\n"
        f"  REAL_LOCAL_ENGINE_EXECUTION_ENABLED = {trava}\n"
        "\n"
        f"{veredito}\n"
        "Confira você mesmo: nomos conselho diagnostico"
    )


def diagnostico_json() -> str:
    """`diagnostico --json`: a MESMA leitura viva da trava, legível por máquina
    (schema v1) — para monitoramento/scripts."""
    ligada = bool(real_execution_enabled())
    return json.dumps({
        "schema": "nomos.council.diagnostico.v1",
        "real_engine_execution_enabled": ligada,
        "fail_closed": not ligada,
    }, ensure_ascii=False, sort_keys=True)


def _deny(motivo: str) -> int:
    """Recusa fail-closed. `motivo` é texto FIXO; nunca ecoa o token digitado."""
    print(f"{DIAG_DENIED_CODE} {motivo}")
    return DIAG_DENIED_EXIT_CODE


def run_diagnostico(tokens: list | None = None) -> int:
    """`nomos conselho diagnostico [--json]`. Só LÊ a trava e imprime; recusa
    flags proibidas/desconhecidas fail-closed (sem ecoar). Nunca executa nada."""
    as_json = False
    for tok in list(tokens or []):
        if is_forbidden_flag(tok):
            return _deny("Este comando não aceita essa opção.")
        if tok == "--json":
            as_json = True
            continue
        if isinstance(tok, str) and tok.startswith("--"):
            return _deny("Essa opção não existe para este comando.")
    print(diagnostico_json() if as_json else diagnostico_message())
    return DIAG_EXIT_CODE
