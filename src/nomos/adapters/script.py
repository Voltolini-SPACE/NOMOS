"""NOMOS adapters.script — execução de script governada (ABSORPTION-04 / FASE 5).

Fecha `SCHED-11-EXEC-SCRIPT-SEM-LLM` **sem** introduzir shell arbitrário.

A tentação óbvia é `subprocess(shell=True)`. Ela seria o fim do modelo: uma
string vira comando, e `;`, `&&`, `$()`, pipes e redirecionamentos viram
autoridade que ninguém autorizou. Por isso aqui só existe `argv[]`.

## O contrato

    argv[]        lista, nunca string; argv[0] resolvido e confinado
    cwd           obrigatório e dentro do escopo autorizado
    env           ALLOWLIST — o ambiente do NOMOS não é herdado
    timeout       obrigatório, com kill do grupo de processos
    stdin         fechado por padrão
    limites       stdout/stderr truncados com marca explícita

## O que é proibido por construção, não por validação de string

Não existe caminho para shell: `subprocess.run` é chamado com uma LISTA e
`shell=False` (o default). Então `argv=["sh", "-c", "rm -rf /"]` não é um
bypass acidental — é alguém pedindo explicitamente para rodar `sh`, e o
binário `sh` é barrado pela allowlist de interpretadores. Metacaracteres em
ARGUMENTOS são inertes: viram texto para o programa, porque não há shell para
interpretá-los. Os testes adversariais provam isso em vez de assumir.

Se paridade com shell for mesmo necessária um dia, é OUTRA capacidade, com
OUTRO risco — não um parâmetro desta.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from nomos.adapters.caminho import resolver
from nomos.adapters.contrato import (
    Adapter, CapabilityRequest, CapabilityResult, ErroEscopo, ErroInvalido,
    ErroTimeout,
)

LIMITE_SAIDA = 256 * 1024        # 256 KB por fluxo
TIMEOUT_PADRAO = 30.0
TIMEOUT_MAX = 600.0

# Variáveis que um processo pode receber. O ambiente do NOMOS NÃO é herdado:
# ele carrega credenciais, tokens e caminhos que não são do script.
#
# O bloco do Windows não é conveniência: sem `SystemRoot` o interpretador filho
# MORRE no arranque com `_Py_HashRandomization_Init: failed to get random
# numbers`, porque não alcança o RNG do sistema. É a MESMA causa raiz que
# `tests/_cli_env.py` já documenta (MC46.3) para os testes de CLI — aqui ela
# reaparecia pelo adapter, que monta o env por conta própria.
#
# Deliberadamente NÃO entram `APPDATA`, `LOCALAPPDATA` nem `USERPROFILE`, que o
# `_cli_env.py` preserva: lá o subprocesso é o PRÓPRIO NOMOS e precisa achar a
# home; aqui é código de terceiro, e apontar-lhe o perfil do usuário amplia o
# que ele enxerga sem que nada no arranque exija isso. A allowlist continua
# sendo allowlist — ganhou o mínimo do SO, não o ambiente inteiro.
ENV_PERMITIDO = frozenset({"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR"})

# HERDADAS do SO, e NUNCA definíveis pelo chamador — a distinção é o ponto.
# Juntá-las ao `ENV_PERMITIDO` teria dado ao plano o poder de redefinir
# `COMSPEC` e `SystemRoot` do processo filho, que é autoridade nova em troca de
# uma correção de portabilidade. Herdar não é o mesmo que deixar escrever.
# Ausentes em Linux/macOS, então lá o env resultante é idêntico ao de antes.
ENV_BOOTSTRAP_SO = frozenset({
    "SystemRoot", "SYSTEMROOT", "SystemDrive", "windir",
    "TEMP", "TMP", "PATHEXT", "COMSPEC",
})

# Interpretadores recusados como argv[0]. Rodar um shell é pedir shell —
# ainda que via lista, e ainda que sem `shell=True`.
INTERPRETADORES_DE_SHELL = frozenset({
    "sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish",
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh",
})

CAPACIDADES = ("script-rodar",)


@dataclass(frozen=True)
class ResultadoScript:
    codigo: int
    stdout: str
    stderr: str
    truncado: bool = False
    argv: tuple[str, ...] = field(default_factory=tuple)


class ScriptAdapter(Adapter):
    """Executa `argv` num processo confinado. Sem shell, sem herança de ambiente."""

    capacidades = CAPACIDADES

    def executar(self, pedido: CapabilityRequest, ctx) -> CapabilityResult:
        self._coerente(pedido, ctx)

        argv = pedido.arg("argv")
        if not isinstance(argv, (list, tuple)) or not argv:
            raise ErroInvalido(
                "`argv` precisa ser lista não-vazia — string vira shell, e "
                "shell não é uma opção aqui")
        if not all(isinstance(a, str) for a in argv):
            raise ErroInvalido("todo item de `argv` precisa ser texto")
        if any("\x00" in a for a in argv):
            raise ErroInvalido("argumento com byte nulo")

        permitidos = pedido.arg("executaveis")
        if permitidos is not None and not isinstance(permitidos, (list, tuple)):
            raise ErroInvalido("`executaveis` precisa ser lista de caminhos")
        executavel = self._resolver_executavel(str(argv[0]), ctx, permitidos)

        cwd = pedido.arg("cwd") or ctx.home
        if not isinstance(cwd, str) or not cwd:
            raise ErroInvalido("`cwd` obrigatório")
        cwd_real = resolver(cwd, ctx.raizes)          # confinado pelo escopo
        if not cwd_real.is_dir():
            raise ErroInvalido(f"cwd não é diretório: {cwd_real}")

        timeout = self._timeout(pedido, ctx)
        env = self._env(pedido)

        self._auditar(ctx, "script.inicio", argv0=str(executavel),
                      argc=len(argv), cwd=str(cwd_real), timeout=timeout)
        try:
            proc = subprocess.run(                     # noqa: S603 - lista, shell=False
                [str(executavel), *[str(a) for a in argv[1:]]],
                cwd=str(cwd_real), env=env, timeout=timeout,
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, errors="replace",
                start_new_session=True,                # kill atinge o grupo
                shell=False)
        except subprocess.TimeoutExpired as exc:
            self._auditar(ctx, "script.timeout", argv0=str(executavel),
                          timeout=timeout)
            # efeito DESCONHECIDO: o processo pode ter mudado o mundo antes de
            # ser morto. Quem decide retry é o registro, e não isto.
            raise ErroTimeout(
                f"script excedeu {timeout}s e foi encerrado "
                f"(efeito desconhecido)", detalhe=str(exc)[:200]) from None
        except FileNotFoundError:
            raise ErroInvalido(f"executável não encontrado: {argv[0]!r}") from None
        except PermissionError as exc:
            raise ErroInvalido(f"sem permissão para executar: {exc}") from None

        out, trunc_o = self._limitar(proc.stdout or "")
        err, trunc_e = self._limitar(proc.stderr or "")
        self._auditar(ctx, "script.fim", argv0=str(executavel),
                      codigo=proc.returncode, truncado=trunc_o or trunc_e)
        return CapabilityResult(
            ok=proc.returncode == 0,
            valor=ResultadoScript(codigo=proc.returncode, stdout=out,
                                  stderr=err, truncado=trunc_o or trunc_e,
                                  argv=tuple(str(a) for a in argv)),
            efeito_aplicado=True,        # rodou processo: assuma que mudou algo
            detalhe="" if proc.returncode == 0 else f"código {proc.returncode}")

    # ------------------------------------------------------------- internos

    def _resolver_executavel(self, bruto: str, ctx, permitidos=None) -> Path:
        """argv[0] → caminho absoluto, recusando shells.

        **Escopo de DADOS ≠ allowlist de BINÁRIOS.** `ctx.raizes` diz onde o
        script pode ler e escrever; não faz sentido exigir que o interpretador
        também more lá — seria preciso copiar o Python para dentro do
        workspace. Quem autoriza rodar programa é o gate: `script-rodar` é
        A5_CODE_EXEC, o segundo maior risco da escala, e passa por aprovação.

        Para defesa em profundidade o chamador pode passar `executaveis`, uma
        allowlist explícita de caminhos absolutos.
        """
        nome = Path(bruto).name.lower()
        if nome in INTERPRETADORES_DE_SHELL:
            raise ErroInvalido(
                f"'{bruto}' é um interpretador de shell — rodar shell é OUTRA "
                "capacidade, com outro risco, não um argumento desta")
        if "/" in bruto or "\\" in bruto:
            caminho = Path(os.path.realpath(os.path.abspath(bruto)))
        else:
            achado = shutil.which(bruto)
            if not achado:
                raise ErroInvalido(f"executável não encontrado no PATH: {bruto!r}")
            caminho = Path(os.path.realpath(achado))
        if permitidos is not None:
            reais = {os.path.realpath(os.path.abspath(x)) for x in permitidos}
            if str(caminho) not in reais:
                raise ErroEscopo(
                    f"executável fora da allowlist: {caminho} "
                    f"(permitidos: {', '.join(sorted(reais)) or 'nenhum'})")
        if not caminho.exists():
            raise ErroInvalido(f"executável não existe: {caminho}")
        if caminho.is_dir():
            raise ErroInvalido(f"não é executável: {caminho}")
        if not os.access(caminho, os.X_OK):
            raise ErroInvalido(f"sem bit de execução: {caminho}")
        return caminho

    def _timeout(self, pedido, ctx) -> float:
        bruto = pedido.arg("timeout_s", TIMEOUT_PADRAO)
        try:
            t = float(bruto)
        except (TypeError, ValueError):
            raise ErroInvalido("`timeout_s` precisa ser número") from None
        if t <= 0 or t > TIMEOUT_MAX:
            raise ErroInvalido(f"`timeout_s` fora da faixa (0, {TIMEOUT_MAX}]")
        # o deadline do NÓ manda: nenhum script sobrevive ao prazo do nó
        restante = ctx.restante()
        if restante is not None:
            if restante <= 0:
                raise ErroTimeout("prazo do nó já esgotado")
            t = min(t, restante)
        return t

    def _env(self, pedido) -> dict[str, str]:
        """Ambiente por ALLOWLIST. Nada do processo pai passa por herança."""
        extra = pedido.arg("env") or {}
        if not isinstance(extra, dict):
            raise ErroInvalido("`env` precisa ser dict")
        env: dict[str, str] = {}
        for chave in ENV_PERMITIDO | ENV_BOOTSTRAP_SO:
            if chave in os.environ:
                env[chave] = os.environ[chave]
        for k, v in extra.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ErroInvalido("`env` só aceita texto→texto")
            if k not in ENV_PERMITIDO:
                raise ErroEscopo(
                    f"variável de ambiente fora da allowlist: {k!r} "
                    f"(permitidas: {', '.join(sorted(ENV_PERMITIDO))})")
            env[k] = v
        return env

    @staticmethod
    def _limitar(texto: str) -> tuple[str, bool]:
        if len(texto) <= LIMITE_SAIDA:
            return texto, False
        return texto[:LIMITE_SAIDA] + "\n…[truncado pelo NOMOS]", True
