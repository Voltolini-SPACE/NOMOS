"""CLI do Motor Council — subcomandos INFORMATIVOS `status` e `modos` (MC23-UX).

Esta é a próxima fase de UX aprovada, e ela é **puramente informativa**: os
comandos `nomos conselho status` e `nomos conselho modos` só imprimem fatos
ESTÁTICOS (o estado das travas e a tabela dos 4 modos). Diferente de
`perguntar`/`revisar`, aqui:

- nenhum motor é executado (a trava `REAL_LOCAL_ENGINE_EXECUTION_ENABLED` do
  harness continua `False` — nada nesta fase a toca);
- nenhum prompt do usuário é lido, processado, ecoado, logado ou persistido
  (não há prompt: são comandos de leitura de fatos do próprio Council);
- nada é gravado em disco; não há rede, subprocess, cloud nem policy/audit/vault
  reais.

Por isso o módulo é deliberadamente **puro**: importa só o contrato de flags
proibidas (para recusá-las fail-closed, sem ecoar). Não importa rede, subprocess,
threading, asyncio, SDK de nuvem, motor, orquestrador, harness, nem
policy/audit/vault do kernel. Não lê variáveis de ambiente, não abre arquivos,
não usa relógio nem aleatoriedade — provado por AST em
`tests/council/test_cli_conselho_info.py`.
"""
from __future__ import annotations

import json

from nomos.council.forbidden_flags import is_forbidden_flag

# Códigos legíveis e estáveis (para logs/testes do usuário).
STATUS_CODE = "[NOMOS-MC-STATUS]"
MODOS_CODE = "[NOMOS-MC-MODOS]"
INFO_DENIED_CODE = "[NOMOS-MC-CLI-DENIED]"

# Ler status/modos com sucesso é um resultado operacional válido → 0.
# Uso indevido (flag proibida/desconhecida) é negado → 3 (semântica da CLI).
INFO_EXIT_CODE = 0
INFO_DENIED_EXIT_CODE = 3

# --------------------------------------------------------------------------
# `status` — estado do Council (fatos estáticos; nenhuma execução real)
# --------------------------------------------------------------------------
_STATUS_MESSAGE = (
    "[NOMOS-MC-STATUS] Motor Council — estado atual\n"
    "\n"
    "Fase: dry-run / pré-release.\n"
    "Comando disponível: nomos conselho simular  "
    "(simulação segura — nunca executa motor real).\n"
    "Modo padrão: balanceado.\n"
    "\n"
    "Travas de segurança (todas ligadas nesta fase):\n"
    "  REAL_ENGINE_EXECUTION=false\n"
    "  REAL_POLICY=false\n"
    "  REAL_AUDIT=false\n"
    "  REAL_VAULT=false\n"
    "  PERSISTENCE=false\n"
    "  CLOUD=false\n"
    "  NETWORK=false\n"
    "\n"
    "perguntar/revisar ainda estão desabilitados (fail-closed): nada é\n"
    "executado, nenhum prompt é processado e nada é gravado.\n"
    "Detalhes: docs/architecture/MOTOR_COUNCIL_INDEX_v1.md"
)

# --------------------------------------------------------------------------
# `modos` — os 4 modos (linguagem simples por padrão; termos internos no
# modo avançado). Espelha MOTOR_COUNCIL_UX_SPEC_v1.md §7 / SPEC_v1 §5.
# --------------------------------------------------------------------------
_MODOS_MESSAGE = (
    "[NOMOS-MC-MODOS] Os 4 modos do Motor Council\n"
    "\n"
    "  rapido      resposta rápida; o conselho pode nem rodar por completo.\n"
    "  balanceado  modo padrão; compara candidatos, sem detalhe técnico.\n"
    "  critico     exige aprovação obrigatória e registro mais detalhado.\n"
    "  paranoico   só local, privado e sem memória — avisa antes de rodar.\n"
    "\n"
    'Use com: nomos conselho simular "sua pergunta" --modo <nome>'
)

_MODOS_AVANCADO_EXTRA = (
    "\n\n"
    "(avançado) mapeamento interno CouncilMode:\n"
    "  rapido=fast   balanceado=balanced   critico=critical   paranoico=paranoid"
)


def status_message() -> str:
    """Texto fixo do `status` — sem interpolação de entrada do usuário."""
    return _STATUS_MESSAGE


def modos_message(avancado: bool = False) -> str:
    """Texto fixo do `modos`. `avancado` só ANEXA o mapeamento interno; nunca
    inclui nada digitado pelo usuário."""
    return _MODOS_MESSAGE + (_MODOS_AVANCADO_EXTRA if avancado else "")


# --------------------------------------------------------------------------
# Saída JSON estável (MC25-UX): fatos ESTÁTICOS, versionados por schema. Não há
# interpolação de entrada do usuário — os dicionários são literais fixos.
# --------------------------------------------------------------------------
_MODOS_DATA = (
    ("rapido", "fast", "resposta rápida; o conselho pode nem rodar por completo"),
    ("balanceado", "balanced", "modo padrão; compara candidatos, sem detalhe técnico"),
    ("critico", "critical", "exige aprovação obrigatória e registro mais detalhado"),
    ("paranoico", "paranoid", "só local, privado e sem memória — avisa antes de rodar"),
)


def status_json() -> str:
    """`status --json`: estado do Council como objeto estável (schema v1)."""
    return json.dumps({
        "schema": "nomos.council.status.v1",
        "phase": "dry-run",
        "default_mode": "balanceado",
        "commands_available": ["status", "modos", "simular"],
        "real_engine_execution": False,
        "real_policy": False,
        "real_audit": False,
        "real_vault": False,
        "persistence": False,
        "cloud": False,
        "network": False,
    }, ensure_ascii=False, sort_keys=True)


def modos_json() -> str:
    """`modos --json`: os 4 modos + mapeamento interno (schema v1)."""
    return json.dumps({
        "schema": "nomos.council.modos.v1",
        "default": "balanceado",
        "modes": [
            {"nome": n, "council_mode": cm, "resumo": r}
            for n, cm, r in _MODOS_DATA
        ],
    }, ensure_ascii=False, sort_keys=True)


def _deny(motivo: str) -> int:
    """Recusa fail-closed. `motivo` é texto FIXO; nunca ecoa o token digitado."""
    print(f"{INFO_DENIED_CODE} {motivo}")
    return INFO_DENIED_EXIT_CODE


def run_status(tokens: list | None = None) -> int:
    """`nomos conselho status [--json]`. Ignora posicionais; recusa flags
    proibidas/desconhecidas fail-closed (sem ecoar)."""
    as_json = False
    for tok in list(tokens or []):
        if is_forbidden_flag(tok):
            return _deny("Este comando não aceita essa opção.")
        if tok == "--json":
            as_json = True
            continue
        if isinstance(tok, str) and tok.startswith("--"):
            return _deny("Essa opção não existe para este comando.")
    print(status_json() if as_json else _STATUS_MESSAGE)
    return INFO_EXIT_CODE


def run_modos(tokens: list | None = None) -> int:
    """`nomos conselho modos [--avancado] [--json]`. Só `--avancado`/`--iniciante`/
    `--json` são reconhecidas; qualquer outra é recusada fail-closed (sem ecoar)."""
    avancado = False
    as_json = False
    for tok in list(tokens or []):
        if is_forbidden_flag(tok):
            return _deny("Este comando não aceita essa opção.")
        if tok == "--json":
            as_json = True
            continue
        if tok == "--avancado":
            avancado = True
            continue
        if tok == "--iniciante":
            avancado = False
            continue
        if isinstance(tok, str) and tok.startswith("--"):
            return _deny("Essa opção não existe para este comando.")
        # posicionais são ignorados (o comando não recebe prompt)
    print(modos_json() if as_json else modos_message(avancado))
    return INFO_EXIT_CODE
