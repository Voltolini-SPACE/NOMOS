"""NOMOS adapters.processos — quem nasceu desta execução, e como terminá-lo.

`killpg` contém enquanto os descendentes ficam no grupo. Um `filter.clean` que
chame `setsid()` — ou apenas `setpgid(0,0)` — sai do grupo e sobrevive ao fim da
capability. Pior: `killpg` num grupo vazio devolve `ProcessLookupError`, e o
supervisor lia isso como "nada sobreviveu". Grupo vazio é a ASSINATURA do escape
bem-sucedido, e o código a interpretava como sucesso: falso negativo por
construção, não por acidente.

A pós-condição correta não é `ORIGINAL_PROCESS_GROUP_DEAD`. É:

    CAPABILITY_RETURNED → ZERO descendentes vivos criados pela capability

O que obriga a responder uma pergunta que PGID e PPID não respondem mais:
**quais processos deste host nasceram desta execução?**

## Por que não marcador de ambiente

A primeira ideia — injetar `NOMOS_EXEC_ID` e varrer o ambiente dos processos —
foi MEDIDA e falha nas duas direções:

- **falso negativo**: `unset VAR; exec` ou `os.execve` com ambiente limpo apagam
  o marcador. E há um caminho ainda mais barato: ao terminar em `exec /bin/cat`
  (ou `/bin/sh`, `/bin/sleep`), binários `restricted` do sistema, o
  `KERN_PROCARGS2` passa a devolver SÓ o argv — `rc=0`, sem erro, ausência
  silenciosa. O hostil desaparece da varredura sem apagar variável nenhuma;
- **falso positivo**: o marcador é herdado por qualquer processo que o usuário
  lance a partir de um ambiente contaminado.

Um sinal que o adversário apaga com uma linha não decide um `SIGKILL`.

## O sinal que ele não apaga: o próprio sandbox

O rótulo de sandbox vive na credencial do processo. O kernel o propaga por
`fork` e o PRESERVA através de `execve` — inclusive para binário do sistema.
O descendente não tem como removê-lo (tentar reaplicar perfil por dentro falha
com `sandbox_apply: Operation not permitted`).

Falta torná-lo específico DESTA execução. Perguntar "este pid é sandboxado?"
não serve — quase metade do host é. A marca é um par CONTRADITÓRIO sobre um
nonce único:

    (allow file-write* (subpath "<execdir>"))
    (deny  file-write* (subpath "<execdir>/NEG"))     ← última regra vence

Um processo sob o NOSSO perfil responde `permitido` para `<execdir>/CANARIO` e
`negado` para `<execdir>/NEG/alvo`. Nenhum outro perfil do sistema produz esse
par: quem libera `/private/tmp` amplamente responde `(permitido, permitido)`;
quem o nega amplamente responde `(negado, negado)`. Só quem carrega ESTE perfil
responde `(permitido, negado)`.

Medido neste host: 1 acerto em 382 processos do usuário — o fugitivo — com o
fugitivo tendo feito `setsid` + double-fork + `exec /bin/sleep`. Zero falsos
positivos. Uma primeira versão do discriminante, sem a regra de negação, deu
6 acertos, 5 deles alheios: daemons do sistema também são sandboxados e também
escrevem em `/private/tmp`.

## Dois modos de falha SILENCIOSA de `sandbox_check`

Ambos com `errno=0`, ambos medidos, ambos capazes de mandar o NOMOS matar
processo do host:

1. **caminho inexistente**: a resposta deixa de refletir a política. Um processo
   SEM sandbox nenhum passou a ler como "negado". Por isso `Marca.conferir()`
   exige que os dois caminhos existam, sempre;
2. **`argtypes` errado**: a função é variádica (`pid, operação, tipo, ...`). Com
   os quatro parâmetros declarados fixos, TODO pid devolve `-1`. Os três
   primeiros são fixos; o caminho vai como variádico.

Contra os dois, `Marca.conferir()` roda uma auto-validação antes de qualquer
varredura: o próprio processo do NOMOS, que não está sob o perfil, TEM de ler
`(permitido, permitido)`. Se ler outra coisa, o discriminante não está
funcionando e nada é morto.

## PID reuse é real

Não é hipótese: foi reproduzido neste host (97744 forks em 88 s reciclaram um
PID). Entre catalogar e matar, o número pode pertencer a outro processo. Por
isso a identidade não é o PID, é `(pid, início_tvsec, início_tvusec)`, e a
digital é reconferida imediatamente antes do `SIGKILL`.

`SIGTERM` não entra: um descendente com `trap '' TERM` sobreviveu a quatro.
Aqui já se está depois do fim da capability — não há término gracioso a
negociar com quem não deveria estar vivo.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import signal
import time
from dataclasses import dataclass

from nomos.adapters.contrato import ErroInvalido

PROC_UID_ONLY = 4
PROC_PIDTBSDINFO = 3
SANDBOX_FILTER_PATH = 1
PERMITIDO, NEGADO = 0, 1

# Latência medida entre o SIGKILL e o processo sumir da tabela: mediana 758 µs,
# máximo 7 ms em processo trivial. Um processo grande demora mais para o kernel
# desmontar, então o teto é generoso — e a verificação é em laço, nunca
# instantânea. Verificar cedo demais dá PASS falso.
PRAZO_MORTE_S = 3.0
RONDAS_MINIMAS = 2


class ErroProcessos(ErroInvalido):
    """Não foi possível PROVAR a ausência de resíduo. Sempre fail-closed."""


class _BSDInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32), ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32), ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _carregar():
    try:
        lib = ctypes.CDLL(ctypes.util.find_library("System"), use_errno=True)
        chk = lib.sandbox_check
        chk.restype = ctypes.c_int
        # SÓ os três fixos. O caminho é variádico — declará-lo aqui faz TODA
        # chamada devolver -1, silenciosamente.
        chk.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        return lib, chk
    except (OSError, AttributeError):        # pragma: no cover - fora do macOS
        return None, None


_LIB, _CHECK = _carregar()
DISPONIVEL = _LIB is not None and _CHECK is not None


def _sandbox_check(pid: int, caminho: str) -> int:
    ctypes.set_errno(0)
    return _CHECK(ctypes.c_int(pid), b"file-write-data",
                  ctypes.c_int(SANDBOX_FILTER_PATH),
                  ctypes.c_char_p(os.fsencode(caminho)))


def pids_do_usuario() -> list[int]:
    """PIDs do uid atual, via libproc.

    `proc_listpids` mede 0,019 ms contra 33,5 ms de um `ps`, com resultado
    idêntico. E não depende de parsear texto.
    """
    uid = os.getuid()
    n = _LIB.proc_listpids(PROC_UID_ONLY, uid, None, 0)
    if n <= 0:
        raise ErroProcessos("proc_listpids não devolveu tamanho")
    # Folga para os processos que nascem entre dimensionar e ler — o host cria
    # ~18 por segundo.
    buf = (ctypes.c_int * (n // 4 + 256))()
    got = _LIB.proc_listpids(PROC_UID_ONLY, uid, buf, ctypes.sizeof(buf))
    if got <= 0:
        raise ErroProcessos("proc_listpids falhou na leitura")
    return [p for p in buf[:got // 4] if p]


def digital(pid: int) -> tuple[int, int, int] | None:
    """`(pid, início_tvsec, início_tvusec)` — a IDENTIDADE do processo.

    O PID sozinho é endereço, não identidade: ele é reciclado.
    """
    info = _BSDInfo()
    r = _LIB.proc_pidinfo(pid, PROC_PIDTBSDINFO, ctypes.c_uint64(0),
                          ctypes.byref(info), ctypes.sizeof(info))
    if r != ctypes.sizeof(info):
        return None
    return (pid, int(info.pbi_start_tvsec), int(info.pbi_start_tvusec))


@dataclass(frozen=True)
class Marca:
    """A marca desta execução, gravada no perfil do sandbox.

    `permitido` e `negado` são caminhos REAIS que precisam EXISTIR — com
    caminho ausente o `sandbox_check` devolve resposta errada sem erro.
    """
    nonce: str
    execdir: str
    permitido: str
    negado: str

    def regras_do_perfil(self) -> list[str]:
        """As duas linhas que tornam esta execução identificável de fora.

        A ordem importa: em SBPL a última regra que casa vence, então o `deny`
        do subdiretório vem DEPOIS do `allow` do diretório.
        """
        return [f'(allow file-write* (subpath "{self.execdir}"))',
                f'(deny file-write* (subpath "{self.execdir}/NEG"))']

    def conferir(self) -> None:
        """Fail-closed contra os dois modos de falha silenciosa."""
        if not DISPONIVEL:
            raise ErroProcessos(
                "libproc/sandbox_check indisponíveis: não há como PROVAR "
                "ausência de processo residual, então não há execução")
        for caminho in (self.permitido, self.negado):
            if not os.path.exists(caminho):
                raise ErroProcessos(
                    f"caminho da marca não existe: {caminho}. Com caminho "
                    "ausente o sandbox_check devolve resposta errada SEM erro, "
                    "e todo processo do host passaria a casar a marca")
        # Auto-validação: eu NÃO estou sob este perfil, logo tenho de ler
        # (permitido, permitido). Qualquer outra coisa significa que o
        # discriminante não está funcionando neste sistema.
        a = _sandbox_check(os.getpid(), self.permitido)
        b = _sandbox_check(os.getpid(), self.negado)
        if (a, b) != (PERMITIDO, PERMITIDO):
            raise ErroProcessos(
                f"auto-validação do discriminante falhou: o próprio NOMOS leu "
                f"({a}, {b}) e deveria ler (0, 0). O sandbox_check não está "
                "respondendo como medido — nada será morto")

    def pertence(self, pid: int) -> bool:
        """O par contraditório: permitido no diretório, negado no subdiretório.

        Nenhum perfil do sistema produz isso por acidente — para casar, o
        processo precisa carregar ESTE perfil, com ESTE nonce.
        """
        return (_sandbox_check(pid, self.permitido) == PERMITIDO
                and _sandbox_check(pid, self.negado) == NEGADO)


def residuais(marca: Marca, ignorar: frozenset[int] = frozenset()) -> list[tuple]:
    """Digitais dos processos vivos que carregam a marca desta execução."""
    achados = []
    for pid in pids_do_usuario():
        if pid in ignorar or pid == os.getpid():
            continue
        try:
            if marca.pertence(pid):
                d = digital(pid)
                if d is not None:
                    achados.append(d)
        except OSError:
            continue                 # morreu no meio da varredura: ótimo
    return achados


def _vivo(d: tuple) -> bool:
    """Vivo E ainda o MESMO processo.

    `os.kill(pid, 0)` não serve sozinho: um filho zumbi continua respondendo
    até o `waitpid`, e um PID reciclado responde por outro processo.
    """
    return digital(d[0]) == d


def exterminar(marca: Marca, ignorar: frozenset[int] = frozenset(),
               prazo: float = PRAZO_MORTE_S) -> tuple[list, list]:
    """Mata todo resíduo desta execução. Devolve `(mortos, sobreviventes)`.

    Repete a varredura: um resíduo pode gerar outro enquanto o primeiro é
    morto, e uma única passada declararia limpeza cedo demais.
    """
    mortos, limite = [], time.monotonic() + prazo
    rondas = 0
    while True:
        alvos = residuais(marca, ignorar)
        if not alvos:
            rondas += 1
            # Duas rondas limpas seguidas. Uma só não distingue "acabou" de
            # "ainda não nasceu".
            if rondas >= RONDAS_MINIMAS or time.monotonic() >= limite:
                return mortos, []
            time.sleep(0.05)
            continue
        rondas = 0
        for d in alvos:
            # Reconferir a digital IMEDIATAMENTE antes de matar: entre a
            # varredura e aqui o PID pode ter sido reciclado, e matar o número
            # errado é atingir processo alheio do host.
            if not _vivo(d):
                continue
            try:
                os.kill(d[0], signal.SIGKILL)
                mortos.append(d)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass                 # não é nosso para matar; a varredura dirá
        if time.monotonic() >= limite:
            return mortos, residuais(marca, ignorar)
        time.sleep(0.03)
