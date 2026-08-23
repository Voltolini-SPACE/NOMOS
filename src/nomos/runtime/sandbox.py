"""NOMOS runtime.sandbox — execução isolada de código (nível S0).

Garantias S0:
- ambiente MINIMAL: nenhum segredo/variável do host é herdado;
- limites de recursos (CPU, tamanho de arquivo, descritores);
- timeout de parede com kill do grupo de processos;
- rede NEGADA por padrão via user+net namespaces (unshare -rn);
- fail-closed: se o isolamento de rede não puder ser garantido e a rede
  estiver proibida, a execução é RECUSADA (IsolationUnavailable) — nunca
  executa "sem querer" com rede aberta.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess  # nosec B404 - execução isolada é o propósito do sandbox
import tempfile
from types import ModuleType

from nomos.kernel import plataforma
from nomos.kernel.audit import redact_text
from dataclasses import dataclass
from functools import lru_cache

# Horizonte 3/item 3 (2026-07-17): a anotação explícita (linha abaixo) dá ao
# mypy o tipo do nome ANTES das duas atribuições possíveis (import real no
# Unix, None no except do Windows) — sem ela, o tipo era inferido só do
# `import resource` (Module), e `resource = None` no except virava erro de
# tipo. Fica como o ÚLTIMO import do arquivo (em vez de logo após `import
# os`, como na primeira tentativa) porque o ruff só reconhece o padrão
# try/import-except-None como um bloco contíguo de imports quando não há
# nenhuma instrução "solta" (nem esta anotação) ANTES dele.
resource: ModuleType | None
try:
    import resource   # Unix-only; ausente no Windows
except ImportError:  # pragma: no cover - exercitado via simulação de SO
    resource = None


class IsolationUnavailable(Exception):
    """Isolamento de rede exigido, porém indisponível neste host."""


@dataclass(frozen=True)
class SandboxResult:
    rc: int
    stdout: str
    stderr: str
    timed_out: bool
    network_isolated: bool
    # Cerca de SISTEMA DE ARQUIVOS. Separada de `network_isolated` de propósito:
    # até 23/08 o ramo com rede tinha zero confinamento de arquivos e nada no
    # resultado dizia isso — quem auditasse veria só `network_isolated=False`,
    # que é o esperado para quem pediu rede, e concluiria que estava tudo certo.
    fs_confinado: bool = False


@lru_cache(maxsize=1)
def netns_available() -> bool:
    unshare = shutil.which("unshare")
    if not unshare:
        return False
    try:
        probe = subprocess.run(  # nosec B603 - argv fixo (unshare), sem shell
            [unshare, "-rn", "true"], capture_output=True, timeout=5
        )
        return probe.returncode == 0
    except Exception:
        return False


def _limits(cpu_seconds: int, fsize_mb: int):
    def apply():
        if hasattr(os, "setsid"):
            os.setsid()  # novo grupo => timeout mata a árvore inteira
        if resource is not None:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
            resource.setrlimit(
                resource.RLIMIT_FSIZE, (fsize_mb * 1024 * 1024, fsize_mb * 1024 * 1024)
            )
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    return apply


# --------------------------------------------------------------- macOS
# Perfil seatbelt para o ramo COM REDE. Medido em 23/08: `allow_network=True`
# rodava com acesso TOTAL ao sistema de arquivos como o usuário — listava o
# home, enxergava `~/.nomos/vault.json` e alcançava a rede. Havia env limpo,
# cwd temporário e rlimits; não havia cerca de arquivos.
#
# A inversão que isso produzia: o caso de MENOR risco (sem rede) era recusado
# fail-closed, e o de MAIOR risco (com rede) corria com menos cerca. Este
# perfil fecha o segundo. O primeiro continua só-Linux por desenho — ver
# `kernel.plataforma.execucao_isolada_disponivel`.
#
# `(literal "/")` com file-read* é OBRIGATÓRIO: sem ele o dyld aborta tudo com
# rc=134 e sem mensagem — falha muda, o pior modo. Ele permite LISTAR `/`, nada
# além; os filhos seguem negados. Lição já paga por `adapters/supervisor.py`,
# reusada aqui em vez de redescoberta.
# Base SEM rede: (deny default) já nega network-*; os allows de rede moram só
# na variante COM rede. As três permissões de suporte de rede também ficam lá
# (configd/dnssd/system-socket): no perfil sem-rede elas seriam porta entreaberta.
_PERFIL_BASE = """(version 1)
(deny default)
(allow process-fork)
(allow process-exec)
(allow sysctl-read)
(allow mach-lookup (global-name "com.apple.bsd.dirhelper"))
(allow file-read* (literal "/"))
(allow file-read-metadata (literal "/var"))
(allow file-read-metadata (literal "/etc"))
(allow file-read* (subpath "/System"))
(allow file-read* (subpath "/usr/lib"))
(allow file-read* (subpath "/usr/bin"))
(allow file-read* (subpath "/bin"))
(allow file-read* (subpath "/opt/homebrew"))
(allow file-read* (subpath "/private/var/select"))
(allow file-read* (subpath "/private/etc"))
(allow file-read* (literal "/dev/null"))
(allow file-read* (literal "/dev/dtracehelper"))
(allow mach-lookup (global-name "com.apple.system.opendirectoryd.membership"))
(allow file-read* (literal "/dev/urandom"))
(allow file-write-data (literal "/dev/null"))
(allow file-read* file-write* (subpath "{workdir}"))
"""

_PERFIL_COM_REDE = _PERFIL_BASE + """\
(allow mach-lookup (global-name "com.apple.SystemConfiguration.configd"))
(allow mach-lookup (global-name "com.apple.dnssd.service"))
(allow system-socket)
(allow network-outbound)
(allow network-inbound)
"""


# PATH de busca do interpretador. `/opt/homebrew/bin` é onde mora TUDO num Mac
# Apple Silicon, e ficava de fora: dentro da cerca `command -v python3` caía em
# `/usr/bin/python3`, que é SHIM DO XCRUN — a mesma família de landmine que já
# custou a CI em 21/08 (`/usr/bin/git` shim, rc=71).
_PATH_BUSCA = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

_PREFIXOS_LARGOS = frozenset({
    "/", "/usr", "/opt", "/var", "/private", "/tmp", "/etc", "/bin", "/sbin",
    "/Users", "/home", "/Applications", "/Library", "/System",
})
"""Prefixos que NUNCA podem virar `(subpath …)`: liberá-los é liberar o disco.
`/bin/sh` cai em "/" pela regra de dois níveis acima — e foi assim que uma
versão minha reabriu o home por acidente."""


def _regras_do_interpretador(argv: list[str]) -> tuple[list[str], list[str]]:
    """Resolve argv[0] e devolve (argv com caminho absoluto, regras do perfil).

    Sem isto, NENHUMA skill Python executava — medido em 23/08, depois que a
    cerca entrou:
        python3 <skill>                    → xcode-select: unable to read data link
        /opt/homebrew/bin/python3.11 <s>   → realpath: /opt/homebrew/bin/: Operation not permitted
        <venv>/bin/python3.14 <skill>      → execvp(): denegado
    A cerca estava fazendo o trabalho dela e fechou junto o caminho legítimo:
    uma skill instalava, aparecia instalada e morria no uso.

    A liberação é do PREFIXO DO INTERPRETADOR RESOLVIDO, não de um diretório
    genérico: quem roda `/opt/homebrew/bin/python3.11` ganha `/opt/homebrew`;
    quem roda o python do venv ganha o venv. O home do dono e `~/.nomos`
    continuam fora — foi o buraco que esta cerca veio fechar.
    """
    if not argv:
        return argv, []
    exe = argv[0]
    if not os.path.isabs(exe):
        achado = shutil.which(exe, path=_PATH_BUSCA)
        if achado:
            exe = achado
    real = os.path.realpath(exe)
    if not os.path.exists(real):
        return argv, []
    # o binário pode ser alcançado pelo nome original (symlink) — libera os dois
    alias = [c for c in dict.fromkeys((exe, real)) if c != real]
    prefixo = os.path.dirname(os.path.dirname(real)) or "/"
    # O BINÁRIO EXATO sempre; o PREFIXO só quando for específico o bastante.
    # Sem esta guarda, `/bin/sh` produzia prefixo "/" e a regra liberava o DISCO
    # INTEIRO — medido: `ls ~` voltou a listar o home do dono, desfazendo em
    # silêncio a cerca que este módulo existe para manter. Foi um teste antigo
    # que pegou; por isso ele não pode ser afrouxado quando "atrapalhar".
    regras = [f'(allow file-read* process-exec (literal "{real}"))']
    regras += [f'(allow file-read* process-exec (literal "{a}"))'
               for a in alias if '"' not in a]
    if prefixo not in _PREFIXOS_LARGOS and prefixo.count("/") >= 3:
        regras.append(f'(allow file-read* process-exec (subpath "{prefixo}"))')
    # `realpath()` percorre cada componente do caminho: sem metadata nos
    # ancestrais o interpretador não consegue nem se localizar. Mesma lição que
    # `/var` e `/etc` impuseram ao perfil do supervisor.
    p = os.path.dirname(prefixo)
    while p and p != "/":
        regras.append(f'(allow file-read-metadata (literal "{p}"))')
        p = os.path.dirname(p)

    # O SCRIPT que o interpretador vai rodar mora fora do workdir (a skill
    # instalada fica em NOMOS_HOME/skills/<nome>/). Sem isto o Python arranca e
    # morre em "can't open file … Operation not permitted" — medido.
    # LEITURA apenas, e só do diretório da entrada: a skill lê os próprios
    # arquivos e importa os próprios módulos, mas não ESCREVE onde foi
    # instalada, e o resto do disco continua fora. Quem escolhe esse caminho é
    # o executor (código do NOMOS), nunca o código confinado.
    for arg in argv[1:]:
        if isinstance(arg, str) and os.path.isfile(arg):
            # AS DUAS FORMAS do caminho, e a ordem do defeito importa: eu
            # emitia só o `realpath`, supondo que o kernel resolvesse antes de
            # casar. Ele casa como VEIO. Medido em 23/08, mesmo arquivo:
            #   /tmp/…/s.py          rc=2  can't open file
            #   /private/tmp/…/s.py  rc=0  RODOU
            # No macOS `/tmp` e `/var` são symlink, então qualquer teste que
            # escreva em /tmp caía nisso. Emitir as duas cobre o caso venha o
            # caminho resolvido ou não — e não alarga a cerca: são dois nomes
            # do MESMO diretório.
            bruto = os.path.dirname(arg)
            for pasta in dict.fromkeys((bruto, os.path.realpath(bruto))):
                if not pasta or '"' in pasta or "\\" in pasta:
                    continue
                regras.append(f'(allow file-read* (subpath "{pasta}"))')
                # E METADATA EM CADA ANCESTRAL. Abrir um arquivo percorre o
                # caminho componente a componente, e no macOS `/tmp` e `/var`
                # são SYMLINK: sem metadata em `/tmp`, `/tmp/x/s.py` é negado
                # mesmo com `/private/tmp/x` liberado — medido, `[Errno 1]
                # Operation not permitted`. Já era a lição de `/var` e `/etc`
                # no perfil base; `/tmp` era o terceiro e eu não tinha visto.
                anc = os.path.dirname(pasta)
                while anc and anc != "/":
                    if '"' not in anc:
                        regras.append(
                            f'(allow file-read-metadata (literal "{anc}"))')
                    anc = os.path.dirname(anc)
            # SEM break: o executor pode passar MAIS de um arquivo — o entry
            # (argv[1]) E o arquivo de argumentos (argv[2], skill-args-*.json).
            # O break original parava no primeiro, e o segundo ficava proibido:
            # medido em 23/08, toda skill chamada COM argumentos morria em
            # "não li os argumentos de '…/sandbox/skill-args-….json'" — a cerca
            # deixava ler o script e negava o JSON logo ao lado. Quem decide
            # quais caminhos entram continua sendo o executor, nunca o confinado.
    return [real, *argv[1:]], regras


def isolamento_sem_rede_disponivel() -> bool:
    """Esta máquina consegue executar NEGANDO rede com garantia?

    Linux: user namespaces (`unshare -rn`). macOS: seatbelt com o perfil BASE,
    cujo (deny default) nega network-*. É o critério que `pode_executar_aqui`
    consulta — mora AQUI para previsor e executor lerem a mesma fonte; se
    divergirem, o teste de não-divergência acusa.
    """
    if plataforma.EH_MAC:
        sbx = shutil.which("sandbox-exec") or plataforma.SANDBOX_EXEC
        return os.path.exists(sbx)
    return netns_available()


def _perfil_seatbelt(workdir: str, extras: list[str] | None = None,
                     com_rede: bool = True) -> str:
    """O perfil com o workdir embutido — única área gravável.

    O caminho vai para dentro de aspas no perfil. Aspa, barra invertida ou
    quebra de linha no caminho fechariam a string e o resto viraria política
    do atacante. Recusar é a única resposta segura: não há como escapar isso
    de forma confiável na linguagem do seatbelt.
    """
    real = os.path.realpath(workdir)   # /tmp é symlink para /private/tmp
    if any(c in real for c in ('"', "\\", "\n", "\r")):
        raise IsolationUnavailable(
            f"caminho com caractere que quebraria o perfil do sandbox: {real!r}")
    base = _PERFIL_COM_REDE if com_rede else _PERFIL_BASE
    perfil = base.replace("{workdir}", real)
    if extras:
        perfil += "\n".join(extras) + "\n"
    return perfil


def _confinamento_macos(argv: list[str], workdir: str,
                        com_rede: bool = True) -> tuple[list[str], bool]:
    """Envolve `argv` em sandbox-exec no macOS. Devolve (argv, confinado).

    Fora do macOS, ou sem o binário, devolve o argv intacto e `False` — quem
    chama decide o que fazer com a ausência de cerca. Esta função não escolhe
    política; só oferece o confinamento quando ele existe.
    """
    if not plataforma.EH_MAC:
        return argv, False
    sbx = shutil.which("sandbox-exec") or plataforma.SANDBOX_EXEC
    if not os.path.exists(sbx):
        return argv, False
    argv, extras = _regras_do_interpretador(argv)
    return [sbx, "-p", _perfil_seatbelt(workdir, extras, com_rede), *argv], True


def run(
    cmd: str | list[str],
    timeout: int = 30,
    allow_network: bool = False,
    cpu_seconds: int = 10,
    fsize_mb: int = 64,
    workdir: str | None = None,
    redact_output: bool = True,
) -> SandboxResult:
    argv = ["/bin/sh", "-c", cmd] if isinstance(cmd, str) else list(cmd)

    isolated = False
    confinado_fs = False
    if not allow_network and plataforma.EH_MAC:
        # A INVERSÃO, desfeita: até 23/08 este ramo recusava no macOS ("user
        # namespaces indisponíveis"), então a skill MAIS SEGURA (sem rede) era
        # justamente a que não executava — enquanto a com rede rodava sob o
        # seatbelt. Mas (deny default) já nega network-*: o perfil BASE, sem
        # os allows de rede, dá a garantia que o unshare dava no Linux, e com
        # cerca de arquivos junto. Só se o seatbelt não existir é que se cai
        # na recusa fail-closed de sempre — nunca em execução sem cerca.
        cwd = workdir or tempfile.mkdtemp(prefix="nomos-sbx-")
        workdir = cwd
        argv, ok = _confinamento_macos(argv, cwd, com_rede=False)
        if not ok:
            raise IsolationUnavailable(
                "sandbox-exec ausente: recuso executar sem garantia de rede "
                "negada (fail-closed).")
        isolated = True
        confinado_fs = True
    elif not allow_network:
        if not netns_available():
            raise IsolationUnavailable(
                "user namespaces indisponíveis: recuso executar com garantia de "
                "rede negada ausente (fail-closed). Aprove explicitamente "
                "allow_network=True via política ou habilite unshare/rootless."
            )
        unshare = shutil.which("unshare")
        # Horizonte 3/item 3: netns_available() (linha acima) já confirmou
        # 'unshare' via este mesmo shutil.which() como sua primeira
        # checagem — chamar de novo aqui é só para obter o caminho, não
        # para revalidar. O assert documenta essa garantia para o mypy e
        # falha alto (em vez de silenciosamente passar None ao Popen) no
        # caso extremo de TOCTOU (binário removido do PATH entre as duas
        # chamadas) — mais seguro que o comportamento anterior, não menos.
        assert unshare is not None, "netns_available() já confirmou 'unshare' no PATH"
        argv = [unshare, "-rn", "--", *argv]
        isolated = True

    env = {"PATH": _PATH_BUSCA, "LANG": "C.UTF-8", "HOME": "/tmp"}  # nosec B108 - HOME efêmero dentro do processo isolado
    cwd = workdir or tempfile.mkdtemp(prefix="nomos-sbx-")   # já criado no ramo mac sem-rede

    # Ramo COM rede: até 23/08 não tinha cerca de sistema de arquivos NENHUMA —
    # medido lendo o home do dono e o `~/.nomos/vault.json`. No macOS o
    # seatbelt fecha isso sem tirar a rede, que é o que o chamador pediu.
    # Fora do macOS o argv segue intacto: esta função não inventa isolamento
    # onde não existe, e `network_isolated` continua dizendo a verdade.
    if allow_network:
        argv, confinado_fs = _confinamento_macos(argv, cwd)

    proc = subprocess.Popen(  # nosec B603 - argv construído localmente, sem shell
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        preexec_fn=_limits(cpu_seconds, fsize_mb) if os.name == "posix" else None,
        text=True,
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except ProcessLookupError:
            pass
        out, err = proc.communicate()
    out, err = out or "", err or ""
    if redact_output:
        out, err = redact_text(out), redact_text(err)
    return SandboxResult(
        rc=proc.returncode,
        stdout=out,
        stderr=err,
        timed_out=timed_out,
        network_isolated=isolated,
        fs_confinado=confinado_fs,
    )
