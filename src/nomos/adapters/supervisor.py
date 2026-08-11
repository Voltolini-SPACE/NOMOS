"""NOMOS adapters.supervisor — o ÚNICO ponto por onde processo externo executa.

Antes deste módulo havia três fronteiras: `git.py`, `git_write.py` e
`git_push.py` chamavam `subprocess.run` cada um por conta própria. Três lugares
para acertar, três para esquecer. Um adapter novo que copiasse o padrão
herdaria a forma sem herdar a política.

Agora a cadeia tem um gargalo:

    CALLER → PDP decision → typed capability → adapter
                                                 ↓
                                          supervisor.executar()
                                                 ↓
                                  sandbox-exec + setsid + rlimits
                                                 ↓
                                            git process

Os adapters montam o argv; o supervisor decide COM QUE AUTORIDADE ele roda.
Nenhum adapter chama `subprocess` diretamente — há teste estrutural que varre o
pacote e falha se alguém voltar a chamar.

## Fail-closed, sem exceção

Toda falha de preparo — canonicalizar, gerar perfil, criar sandbox, aplicar
rlimit, criar process group — vira RECUSA. Nunca degradação para "executa o
git sem sandbox": um sandbox que se desliga sozinho quando dá problema protege
exatamente enquanto não é preciso.

Isso tem um custo assumido: em plataforma sem `sandbox-exec`, as capacidades
Git ficam INDISPONÍVEIS. É o lado correto do erro — a alternativa é executar
código de repositório desconhecido com a autoridade do usuário.

## Por que `rede` é parâmetro e não constante

`deny network*` é o padrão. Mas `git-push` tem o egresso como EFEITO
AUTORIZADO — negar rede nele não seria contenção, seria quebrar a capacidade.
Quem decide não é o plano: a autoridade de rede vem do destino governado pela
política (C2b), e um destino `file://` não recebe rede nenhuma. O plano não
tem como pedir `rede=True`.

## Por que a árvore morre TAMBÉM no sucesso

O primeiro desenho matava o grupo só no timeout. Um teste de árvore que
gravava a marca FORA do repo escondeu o defeito: a marca não aparecia porque o
sandbox negava a escrita, não porque o processo tinha morrido. Corrigida a
marca para dentro do repo, o neto apareceu — vivo, depois de um `git add`
BEM-SUCEDIDO.

Um filtro hostil que faz `( sleep 30; ... ) &` sobrevive à operação que o
invocou. Ele continua confinado, mas continua. A autoridade concedida foi
"executar este `git add`", não "executar este `git add` e mais o que ele
deixar para trás": o grupo é encerrado em TODO caminho de saída.

Isso também eliminou uma espera acidental. Com `communicate()`, o neto
segurava a ponta do pipe e o supervisor ficava bloqueado até ele terminar —
30 segundos num `add` que levou milissegundos. Agora a saída é drenada por
threads e o `wait` observa só o processo principal.

## Limite conhecido: neto que faz setsid

`killpg` alcança o grupo de processos. Um descendente que chame `setsid()` sai
do grupo e sobrevive ao kill. Isso está MEDIDO, não suposto: o supervisor
detecta o caso (o `communicate` final não retorna) e devolve
`UNKNOWN_SECURITY_STATE`, que o adapter converte em recusa. Preferi um estado
final honesto a um `PASS` que ignora o caso.
"""
from __future__ import annotations

import os
import resource
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from nomos.adapters.contrato import ErroInvalido, ErroLimite

SANDBOX = "/usr/bin/sandbox-exec"

# Graça entre o término controlado e o kill. Curta de propósito: já estamos
# depois do prazo do nó, e quem ignorou o SIGTERM não vai colaborar mais.
GRACA_S = 1.5
# Teto para o processo morrer depois do SIGKILL. Estourar isto significa que
# alguém escapou do grupo — estado desconhecido, não "demorou".
REAP_S = 5.0

CPU_S = 60
ARQUIVO_BYTES = 256 * 1024 * 1024
DESCRITORES = 512

# Variáveis que dão ao Git autoridade adicional e NÃO podem chegar ao processo.
# A checagem é positiva: o ambiente é construído do zero, então a presença de
# qualquer uma destas denuncia que alguém voltou a herdar do host.
#
# `GIT_CONFIG_COUNT`/`KEY`/`VALUE` injetam configuração arbitrária pelo
# ambiente — inclusive `core.fsmonitor` e `filter.*.clean`, que executam
# programa. É o `-c` da linha de comando por outra porta.
PROIBIDAS_NO_AMBIENTE = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_SSH", "GIT_SSH_COMMAND", "GIT_EXEC_PATH", "GIT_CONFIG",
    "GIT_CONFIG_COUNT", "GIT_TEMPLATE_DIR", "GIT_NAMESPACE",
    "GIT_ATTR_SOURCE", "GIT_HOOKS_PATH", "GIT_PROXY_COMMAND",
    "HOME", "XDG_CONFIG_HOME", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES",
})
# Prefixos: `GIT_CONFIG_KEY_0`, `GIT_CONFIG_VALUE_0`, ...
PROIBIDOS_PREFIXO = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_", "DYLD_", "LD_")

# Sem estas, o Git volta a ler `~/.gitconfig` e `/etc/gitconfig`. Exigi-las
# transforma "esqueci de neutralizar" em recusa, não em furo silencioso.
EXIGIDAS_NO_AMBIENTE = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
}


class ErroSeguranca(ErroInvalido):
    """Preparo de confinamento falhou. SEMPRE recusa, nunca degradação."""


@dataclass(frozen=True)
class Confinamento:
    """A autoridade concedida a UMA execução. Montado pelo adapter, nunca pelo
    plano."""
    escrita: tuple[str, ...] = ()
    rede: bool = False
    cpu_s: int = CPU_S
    arquivo_bytes: int = ARQUIVO_BYTES
    descritores: int = DESCRITORES


@dataclass(frozen=True)
class Resultado:
    returncode: int
    stdout: bytes
    stderr: bytes
    classificacao: str
    morto_por_timeout: bool = False
    sandbox_aplicado: bool = True
    argv_efetivo: tuple[str, ...] = field(default=())
    perfil_usado: str = ""


# --------------------------------------------------------------- canonicalizar

def canonicalizar(caminho: str | Path) -> str:
    """Caminho REAL, resolvido, ou recusa.

    `/tmp` é symlink para `/private/tmp` no macOS. Um perfil de sandbox escrito
    com o pathname lógico nunca casa com o caminho que o processo usa de fato,
    e a operação legítima falha com um erro que aponta para o lugar errado
    (`.git/index.lock`, tipicamente). Este landmine já custou caro duas vezes —
    ver `test_absorption07_c2c_realpath.py`.
    """
    try:
        real = os.path.realpath(str(caminho))
    except (OSError, ValueError) as exc:
        raise ErroSeguranca(f"não consegui canonicalizar {caminho!r}: {exc}") from None
    if not os.path.isabs(real):
        raise ErroSeguranca(f"caminho não absoluto após realpath: {real!r}")
    # O perfil é texto entre aspas. Um caminho com aspa, barra invertida ou
    # quebra de linha sairia do literal e viraria diretiva do sandbox.
    if any(c in real for c in ('"', "\\", "\n", "\r", "\x00")):
        raise ErroSeguranca(
            f"caminho com caractere que quebraria o perfil do sandbox: {real!r}")
    return real


def existente(caminho: str | Path) -> str:
    """Canonicaliza e exige que exista. Para capacidades que operam sobre repo
    já existente — canonicalizar um caminho ausente resolveria para o pai e
    ampliaria a fronteira sem que ninguém percebesse."""
    real = canonicalizar(caminho)
    if not os.path.exists(real):
        raise ErroSeguranca(f"alvo do confinamento não existe: {real}")
    return real


# ---------------------------------------------------------------------- perfil

def perfil(conf: Confinamento) -> str:
    """Gera o perfil `sandbox-exec` a partir da autoridade concedida.

    Baseline medida no C2c: as quatro propriedades (git add e git commit
    funcionam; escrita fora NEGADA; rede direta e de descendente NEGADA) valem
    simultaneamente com exatamente estas linhas. `/dev/null` precisa de
    `file-write*`, não bastou `file-write-data`.
    """
    linhas = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec process-fork)",
        "(allow file-read*)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        f'(allow file-write* (literal "{os.devnull}"))',
    ]
    linhas.insert(2, "(allow network*)" if conf.rede else "(deny network*)")
    for bruto in conf.escrita:
        real = canonicalizar(bruto)
        linhas.append(f'(allow file-write* (subpath "{real}"))')
    return "\n".join(linhas) + "\n"


# ------------------------------------------------------------------- ambiente

def conferir_ambiente(env: dict[str, str]) -> None:
    """Recusa se o ambiente construído carregar autoridade indevida.

    A lista de PASSO 5 não substitui o teste adversarial, mas prende a
    regressão: se alguém acrescentar `GIT_SSH_COMMAND` ao ambiente mínimo por
    conveniência, a execução para aqui em vez de rodar um binário escolhido
    por variável.
    """
    for chave in env:
        if chave in PROIBIDAS_NO_AMBIENTE:
            raise ErroSeguranca(
                f"ambiente carrega {chave!r}, que concede autoridade externa "
                "ao Git — o ambiente do supervisor é construído, não herdado")
        if chave.startswith(PROIBIDOS_PREFIXO):
            raise ErroSeguranca(
                f"ambiente carrega {chave!r} — injeção de configuração/biblioteca")
    for chave, valor in EXIGIDAS_NO_AMBIENTE.items():
        if env.get(chave) != valor:
            raise ErroSeguranca(
                f"neutralização obrigatória ausente: {chave}={valor!r} "
                f"(veio {env.get(chave)!r}) — sem ela o Git lê config do host")


# ------------------------------------------------------------------- execução

def _preexec(conf: Confinamento):
    """Roda no filho, depois do fork, antes do exec.

    `setsid` primeiro: sem grupo próprio, o `killpg` do timeout atingiria o
    grupo do NOMOS. Uma exceção aqui aborta o `Popen` — que é o comportamento
    desejado, porque limite não aplicado é autoridade não contida.

    NÃO aplico `RLIMIT_NPROC`: no macOS ele conta processos do USUÁRIO, não do
    grupo. Um valor baixo derrubaria a sessão inteira do dono da máquina para
    conter um `git commit`.
    """
    def _dentro():
        os.setsid()
        resource.setrlimit(resource.RLIMIT_CPU, (conf.cpu_s, conf.cpu_s))
        resource.setrlimit(resource.RLIMIT_FSIZE,
                           (conf.arquivo_bytes, conf.arquivo_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE,
                           (conf.descritores, conf.descritores))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return _dentro


def _grupo_vivo(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return True
    return True


def _matar_arvore(pgid: int) -> bool:
    """Término controlado → escalada para kill → confirmação. Devolve se algo
    sobreviveu.

    Mata o GRUPO, não o PID. Um `filter.clean` hostil que gera neto e sai deixa
    o neto órfão vivo, e matar só o processo principal daria um `PASS` falso:
    o `git` morre, o neto continua.
    """
    for sinal, prazo in ((signal.SIGTERM, GRACA_S), (signal.SIGKILL, REAP_S)):
        try:
            os.killpg(pgid, sinal)
        except ProcessLookupError:
            return False
        except OSError:
            pass
        limite = time.monotonic() + prazo
        while time.monotonic() < limite:
            if not _grupo_vivo(pgid):
                return False
            time.sleep(0.02)
    return _grupo_vivo(pgid)


def _drenar(fh, destino: list) -> None:
    """Lê um pipe até o fim numa thread própria.

    Sem isto, o supervisor esperaria o descendente que segura a ponta do pipe —
    e um buffer cheio travaria o processo principal antes disso.
    """
    try:
        destino.append(fh.read())
    except (OSError, ValueError):
        pass
    finally:
        try:
            fh.close()
        except OSError:
            pass


def _classificar(rc: int, morto: bool) -> str:
    if morto:
        return "KILLED_BY_TIMEOUT"
    if rc == 0:
        return "EXIT_OK"
    if rc < 0:
        s = -rc
        if s in (signal.SIGXCPU, signal.SIGXFSZ):
            return "RESOURCE_LIMIT"
        return f"KILLED_BY_SIGNAL_{s}"
    return "EXIT_ERRO"


def executar(argv: list[str], *, cwd: str | Path, env: dict[str, str],
             prazo: float, confinamento: Confinamento,
             binario_sandbox: str = SANDBOX) -> Resultado:
    """Executa `argv` confinado. Qualquer falha de preparo é RECUSA."""
    if prazo <= 0:
        raise ErroLimite("prazo esgotado antes de iniciar o processo")
    if not argv:
        raise ErroSeguranca("argv vazio")
    if not os.path.exists(binario_sandbox):
        raise ErroSeguranca(
            f"{binario_sandbox} ausente: sem sandbox não há execução de Git. "
            "O NOMOS recusa em vez de rodar sem confinamento")
    if not confinamento.escrita:
        raise ErroSeguranca(
            "confinamento sem nenhuma raiz de escrita declarada — recuso por "
            "ambiguidade: ou a capacidade não escreve (e declara isso), ou "
            "alguém esqueceu de delimitar")
    conferir_ambiente(env)
    cwd_real = existente(cwd)
    texto_perfil = perfil(confinamento)

    fd, caminho_perfil = tempfile.mkstemp(prefix="nomos-sb-", suffix=".sb")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(texto_perfil)
        os.chmod(caminho_perfil, 0o600)
        completo = [binario_sandbox, "-f", caminho_perfil, *argv]
        try:
            proc = subprocess.Popen(
                completo, cwd=cwd_real, env=dict(env),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, close_fds=True, shell=False,
                preexec_fn=_preexec(confinamento))       # noqa: PLW1509
        except OSError as exc:
            raise ErroSeguranca(f"não consegui iniciar sob sandbox: {exc}") from None
        except (ValueError, subprocess.SubprocessError) as exc:
            raise ErroSeguranca(
                f"preparo do processo confinado falhou: {exc}") from None

        pgid = proc.pid          # setsid no filho ⇒ pgid == pid
        buf_out: list[bytes] = []
        buf_err: list[bytes] = []
        threads = [
            threading.Thread(target=_drenar, args=(proc.stdout, buf_out),
                             daemon=True),
            threading.Thread(target=_drenar, args=(proc.stderr, buf_err),
                             daemon=True),
        ]
        for t in threads:
            t.start()

        morto = False
        try:
            proc.wait(timeout=prazo)
        except subprocess.TimeoutExpired:
            morto = True

        # SEMPRE, não só no timeout. A autoridade era executar ESTA operação;
        # o que o processo deixou rodando não foi autorizado por ninguém.
        sobreviveu = _matar_arvore(pgid)
        for t in threads:
            t.join(REAP_S)
        try:
            proc.wait(timeout=REAP_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise ErroSeguranca(
                "UNKNOWN_SECURITY_STATE: processo principal não morreu após "
                f"SIGKILL no grupo (pgid={pgid})") from None
        if sobreviveu:
            raise ErroSeguranca(
                "UNKNOWN_SECURITY_STATE: grupo de processos sobreviveu ao "
                f"SIGKILL (pgid={pgid}) — provável escape por setsid")

        saida = b"".join(buf_out)
        erro = b"".join(buf_err)
        return Resultado(
            returncode=proc.returncode, stdout=saida, stderr=erro,
            classificacao=_classificar(proc.returncode, morto),
            morto_por_timeout=morto, sandbox_aplicado=True,
            argv_efetivo=tuple(completo), perfil_usado=texto_perfil)
    finally:
        try:
            os.unlink(caminho_perfil)
        except OSError:
            pass
