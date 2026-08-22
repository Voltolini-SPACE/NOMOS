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

## O escape do process group, e por que `killpg` não bastava

Uma versão anterior desta docstring afirmava que o supervisor DETECTAVA o
descendente que faz `setsid()`. Era falso, e de um jeito instrutivo: a detecção
existia enquanto a saída era lida por `communicate()`, e morreu quando ela
passou a ser drenada por threads com `join(timeout)` — a afirmação sobreviveu à
mudança que a invalidou.

A medição mostrou pior que isso. `killpg` num grupo vazio devolve
`ProcessLookupError`, e `_matar_arvore` traduzia isso para "nada sobreviveu".
Grupo vazio é exatamente a ASSINATURA do escape bem-sucedido: o falso negativo
não era acidente, era construção. Um `git add` com filtro hostil retornava
`efeito_aplicado=True` deixando quatro processos vivos.

E o discriminante não é `setsid()`: `setpgid(0,0)` escapa igual, mantendo a
sessão e trocando só o grupo. Qualquer troca de process group basta.

Por isso `killpg` continua — é o caminho rápido, e mata tudo que NÃO trocou de
grupo — mas a prova de ausência vem de `adapters/processos.py`, que identifica
os processos desta execução pelo perfil de sandbox que eles carregam. A
pós-condição passou a ser `ZERO descendentes vivos`, não `grupo original
vazio`.
"""
from __future__ import annotations

import os
import re
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from types import ModuleType

from nomos.adapters import processos
from nomos.adapters.contrato import ErroInvalido, ErroLimite

# `resource` é Unix-only. Este módulo é só-macOS por desenho (sandbox-exec) e
# recusa fail-closed noutras plataformas, mas o import CRU quebrava a coleta
# do pytest inteira no Windows — o CI acusava dezenas de ImportError em
# módulos que nem exercitam o supervisor. Mesmo padrão guardado já usado em
# `runtime/sandbox.py` e `kernel/plataforma.py`. O uso real (`setrlimit`)
# vive dentro do `preexec_fn`, que só roda em POSIX.
resource: ModuleType | None
try:
    import resource
except ImportError:   # pragma: no cover - exercitado no runner Windows
    resource = None

SANDBOX = "/usr/bin/sandbox-exec"

# `mach-lookup` irrestrito era o canal de delegação aberto do perfil: pedir
# trabalho a um serviço de sistema que NÃO está sandboxado. O censo mediu que UM
# único nome basta.
#
# A causa é a toolchain, não o Git: `/usr/bin/git` neste host é o shim do xcrun
# (116K), que delega ao git do Xcode (3,5M). O shim chama
# `confstr(_CS_DARWIN_USER_TEMP_DIR)`, e é isso que resolve por `dirhelper`.
#
# Remover a linha INTEIRA também funciona — `git add` e `git commit` devolvem
# rc=0 —, mas custa 78× em latência (0,045s → 3,53s por ciclo) e enche o stderr
# com 1092 bytes de ruído do xcrun. O ruído não é cosmético: os adapters
# reportam erro com `stderr[:400]`, e a janela inteira vira lixo — um
# `git add` de caminho inexistente deixa de mostrar o "fatal: pathspec ...".
# Perder diagnóstico é perder a capacidade de investigar incidente.
MACH = '(allow mach-lookup (global-name "com.apple.bsd.dirhelper"))'

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


class TipoDeProcesso(Enum):
    """A CLASSE do processo supervisionado. Explícita, nunca inferida.

    O supervisor nasceu como fronteira do Git e virou a fronteira ÚNICA de
    execução. A exigência de ambiente seguiu sendo a do Git para TODO mundo — o
    que estava certo enquanto só havia Git, e passou a ser errado no instante em
    que um filtro governado precisou rodar por aqui:

        Git             exige a NEUTRALIZAÇÃO de Git (as 4 de EXIGIDAS_NO_AMBIENTE)
        filtro governado exige o MÍNIMO dele ({LANG, LC_ALL}) e nada de Git

    As duas regras estão certas isoladamente e são incompatíveis se aplicadas
    globalmente. Por isso a exigência passa a ser POR TIPO — e não por
    relaxamento da regra do Git, que continua idêntica byte a byte.

    O tipo é um ENUM, e é passado explicitamente por quem chama. NÃO se deduz do
    argv, do nome do binário nem de `"git" in comando`: heurística sobre string
    é adivinhação, e adivinhação erra do lado de conceder. Um adapter novo que
    esqueça de declarar o tipo cai no default GIT — que EXIGE MAIS, então o erro
    sai como recusa (`neutralização obrigatória ausente`), nunca como permissão
    a mais. Essa direção do erro é deliberada.
    """

    GIT = "git"
    FILTRO_GOVERNADO = "filtro-governado"


# O mínimo do filtro governado, espelhando `PoliticaDeFiltro.ambiente()`, que
# nasce vazio e recebe {LANG, LC_ALL} + a allowlist nomeada pela política.
# Exigi-las prende a regressão inversa: um ambiente de filtro que perca a
# localidade C passa a depender da locale do host, e o resultado da
# transformação deixaria de ser reprodutível.
EXIGIDAS_NO_FILTRO = {"LANG": "C", "LC_ALL": "C"}

EXIGIDAS_POR_TIPO: dict[TipoDeProcesso, dict[str, str]] = {
    TipoDeProcesso.GIT: EXIGIDAS_NO_AMBIENTE,
    TipoDeProcesso.FILTRO_GOVERNADO: EXIGIDAS_NO_FILTRO,
}

# O filtro governado não é Git e não tem por que carregar NADA de Git. Proibir o
# prefixo inteiro é mais forte do que proibir nomes conhecidos: uma variável
# `GIT_*` que ainda não existe hoje já nasce recusada aqui. Não é conveniência —
# é a fronteira de tipo sendo afirmada nas duas direções (o Git exige a
# neutralização dele; o filtro recusa até a neutralização, porque não é dele).
PROIBIDOS_PREFIXO_POR_TIPO: dict[TipoDeProcesso, tuple[str, ...]] = {
    TipoDeProcesso.GIT: (),
    TipoDeProcesso.FILTRO_GOVERNADO: ("GIT_",),
}


class ErroSeguranca(ErroInvalido):
    """Preparo de confinamento falhou. SEMPRE recusa, nunca degradação."""


# O Git emite estes marcadores em stderr AINDA QUANDO sai com rc=0.
#
# MEDIDO, não suposto: `git add` num repositório cujo `filter.<driver>.clean`
# falha devolve rc=0, indexa o arquivo assim mesmo e grava o conteúdo CRU —
# reclamando só aqui. O Git só trata falha de filtro como fatal quando
# `filter.<driver>.required` está ligado, e essa config vem do REPOSITÓRIO,
# isto é, do lado não confiável: quem ataca escolhe se o erro é fatal.
#
# A consequência não é cosmética. O padrão documentado de usar `clean` como
# REDATOR de segredo inverte de sentido: com o filtro quebrado, `SENHA=...`
# entra em claro no índice e o adapter — que olhava só o rc — reporta SUCESSO.
# Provado ponta a ponta pelo caminho governado antes desta checagem existir.
#
# `warning:` fica de fora de propósito: é comum e benigno (CRLF, etc.), e
# recusar nele transformaria operação legítima em falha.
_MARCADOR_ERRO = re.compile(rb"^(?:error|fatal):", re.MULTILINE)


def conferir_sinal(p, o_que: str) -> None:
    """Morte por SINAL não é erro da ferramenta. Levanta `ErroLimite` se for.

    Existe porque esta correção foi feita QUATRO vezes em call sites diferentes
    antes de virar função: `symbolic-ref` (`.6.10`), `git config` (`.11.12`), e
    depois `update-index`/`hash-object`/`ls-files`/`ls-remote`. Todos caíam no
    mesmo ramo `rc != 0` e subiam como erro de sintaxe da ferramenta.

    MEDIDO, e foi a bateria de CORRIDA que pegou: sob carga (duas suítes
    completas concorrentes), o `update-index` foi morto e o adapter reportou
    `ErroInvalido: update-index falhou em q26.txt:` — com stderr VAZIO, que é a
    assinatura exata de sinal. Intermitente 1/16 sob carga, 0/58 isolado: um
    "flake" que era classificação errada de um evento real.

    `rc < 0` é a forma POSIX: `subprocess` devolve `-N` quando o processo morreu
    com o sinal N. Stderr vazio junto com `rc != 0` não é diagnóstico — é a
    ausência dele.
    """
    if getattr(p, "morto_por_timeout", False) or p.returncode < 0:
        raise ErroLimite(
            f"{o_que} foi encerrado por SINAL (rc={p.returncode})"
            f"{' após o prazo' if getattr(p, 'morto_por_timeout', False) else ''}"
            " — o processo morreu, não houve saída a interpretar. Sob carga "
            "isto acontece sem que nada esteja errado com o repositório")


def conferir_saida(stderr: bytes, operacao: str) -> None:
    """Recusa quando o Git relatou erro apesar de ter saído com rc=0.

    Fail-closed por desenho. Sem isto, a frase "rc=0 significa que a operação
    fez o que dizia" é FALSA para toda capacidade que toca a working tree.
    """
    achado = _MARCADOR_ERRO.search(stderr)
    if achado is None:
        return
    linha = stderr[achado.start():].split(b"\n", 1)[0]
    raise ErroSeguranca(
        f"{operacao} saiu com rc=0 MAS o Git relatou erro — recuso por "
        f"degradação silenciosa: {linha.decode('utf-8', 'replace')[:300]}")


@dataclass(frozen=True)
class Confinamento:
    """A autoridade concedida a UMA execução. Montado pelo adapter, nunca pelo
    plano."""
    escrita: tuple[str, ...] = ()
    # Raízes de LEITURA. Vazio = leitura ampla (o estado histórico). Declarar
    # raízes liga o piso medido de `_bloco_de_leitura` — adesão explícita,
    # capacidade a capacidade, em vez de uma troca global que quebraria tudo.
    leitura: tuple[str, ...] = ()
    # Subcaminhos NEGADOS dentro de uma raiz já concedida. Emitidos DEPOIS dos
    # allows: em SBPL a última regra que casa vence, então o deny mais
    # específico sobrepõe o allow do diretório que o contém.
    negacao_de_escrita: tuple[str, ...] = ()
    # Nomes de arquivo negados em QUALQUER profundidade, como regex de SBPL.
    # Existe porque `subpath` responde a pergunta errada para `.gitattributes`:
    # ele é criável em todo diretório da working tree, inclusive em diretórios
    # que o próprio filtro criar durante a operação. MEDIDO: um filtro governado
    # com `write_roots=(repo,)` gravou `.gitattributes` na raiz do working tree
    # — e `.gitattributes` é FONTE DE ATRIBUTO, então o filtro contido escolhia
    # a política da PRÓXIMA operação. É a mesma propriedade de A6, num lugar que
    # a negação por caminho não alcança.
    negacao_por_nome: tuple[str, ...] = ()
    # Executáveis permitidos, POR CAPACIDADE. Vazio = `process-exec` amplo (o
    # estado histórico). Uma allowlist GLOBAL foi medida e REFUTADA: para o
    # push local funcionar seria preciso admitir /bin/sh, e isso reabre a
    # execução de código escolhido pelo repositório.
    #
    # CONTRATO PERMANENTE desta fronteira:
    #   o repositório PODE declarar que precisa de um filtro;
    #   o repositório NÃO PODE conceder autoridade de execução;
    #   a política do NOMOS é a única autoridade de execução.
    exec_permitido: tuple[str, ...] = ()
    rede: bool = False
    marca: object | None = None      # processos.Marca desta execução
    # As capacidades de LEITURA não escrevem nada — medido: `git log`, `git show`
    # e `git diff ref ref` rodam com saída byte-idêntica sem nenhum allow de
    # escrita no repositório. Sem esta declaração explícita, o supervisor recusa
    # confinamento vazio por ambiguidade, e a redução ficaria impossível de
    # exprimir. O caminho é "a capacidade não escreve, E DIZ ISSO".
    declara_sem_escrita: bool = False
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
    residuais_mortos: int = 0        # descendentes que escaparam do grupo
    grupo_resistiu: bool = False


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

def _bloco_de_exec(conf: Confinamento) -> list[str]:
    """`process-exec` amplo, ou a allowlist da capacidade.

    `process-fork` PERMANECE sempre. Removê-lo foi medido: `git commit`
    devolve rc=0 COM `error: cannot fork() for maintenance` — degradação
    silenciosa, exatamente o modo de falha que esta série vem eliminando.

    Sempre `(literal ...)`, NUNCA `(subpath ...)`: subpath sobre um diretório
    de binários concede tudo que vier a existir ali depois.
    """
    if not conf.exec_permitido:
        return ["(allow process-exec process-fork)"]
    linhas = ["(allow process-fork)"]
    for bruto in conf.exec_permitido:
        linhas.append(f'(allow process-exec (literal "{canonicalizar(bruto)}"))')
    return linhas


def _toolchain_legivel() -> list[str]:
    """Mínimo de leitura que o Git deste host exige, derivado em RUNTIME.

    Nada aqui é caminho fixo por escolha: `/usr/bin/git` neste Mac é o shim do
    xcrun, que delega ao Git dentro do Xcode. Fixar o caminho faria a política
    apontar para o lugar errado assim que alguém rodasse `xcode-select -s`.

    Medido por bissecção leave-one-out — tracing NÃO existe utilizável neste
    host: `(trace ...)` roda sem criar arquivo, `(debug deny)` não loga, e
    negação de perfil `-f` não aparece no unified log.

    Duas descobertas que a medição impôs e que não são óbvias:

    - `(literal "/")` com `file-read*` é OBRIGATÓRIO. Sem ele o dyld aborta
      TUDO com rc=134 e sem mensagem — falha muda, o pior modo possível.
      Ele permite LISTAR `/`, e nada além disso: os filhos continuam negados.
    - `/var` e `/etc` são SYMLINK neste sistema, então precisam de allow
      próprio para o componente resolver. `file-read-metadata` basta e NÃO
      permite ler conteúdo (medido nos dois sentidos).
    """
    linhas = [
        '(allow file-read* (literal "/"))',
        '(allow file-read-metadata (literal "/var"))',
        '(allow file-read-metadata (literal "/etc"))',
        '(allow file-read* (subpath "/System/Library"))',
        '(allow file-read* (subpath "/usr/lib"))',
        '(allow file-read* (subpath "/private/var/select"))',
        f'(allow file-read* (literal "{os.devnull}"))',
    ]
    dev = os.path.realpath("/var/select/developer_dir")
    if not os.path.isdir(dev):
        raise ErroSeguranca(
            f"developer dir não resolve ({dev}) — recuso em vez de cair para "
            "leitura irrestrita: perder a fronteira para consertar a "
            "toolchain seria trocar segurança por conveniência")
    xc = os.path.dirname(dev)
    linhas += [
        f'(allow file-read* (subpath "{dev}"))',
        f'(allow file-read* (literal "{xc}/Info.plist"))',
        f'(allow file-read* (literal "{xc}/version.plist"))',
    ]
    # Sem os dois plists o xcrun cai para `xcodebuild` e o dyld falha em
    # DVTSystemPrerequisites (rc=71, 1430 B de stderr) — medido.
    cache = os.path.join(os.path.realpath(tempfile.gettempdir()), "xcrun_db")
    linhas.append(f'(allow file-read* (literal "{cache}"))')
    return linhas


def _ancestrais(caminho: str) -> list[str]:
    """Cada ancestral até `/` exclusive.

    O Git resolve o caminho componente a componente; sem metadata do ancestral
    ele para com `Invalid path <X>` (rc=128). Medido: faltar UM ancestral de
    UMA das raízes já quebra.
    """
    saida, atual = [], os.path.dirname(caminho.rstrip("/"))
    while atual and atual != "/":
        saida.append(atual)
        atual = os.path.dirname(atual)
    return saida


def _bloco_de_leitura(conf: Confinamento) -> list[str]:
    """`(allow file-read*)` global, ou o piso medido quando há raízes.

    A capacidade que NÃO declara raízes de leitura continua com leitura ampla:
    a redução entra por adesão explícita, capacidade a capacidade, e não por
    mudança global que quebraria tudo de uma vez.
    """
    if not conf.leitura:
        return ["(allow file-read*)"]
    linhas = _toolchain_legivel()
    # DOIS conjuntos, e a separação é o conserto de um defeito medido. Com um
    # `vistos` único, um caminho já emitido como ANCESTRAL (só
    # `file-read-metadata`) bloqueava o `file-read*` completo dele mais adiante.
    #
    # MEDIDO em WORKTREE LIGADA: `leitura` traz (worktree, git_dir, common), e
    # `common` (`main/.git`) é ancestral de `git_dir`
    # (`main/.git/worktrees/wt`). O ancestral entrava primeiro, e quando a vez
    # do `common` chegava ele era pulado — o perfil concedia METADADO onde
    # precisava conceder LEITURA, e todo `git add` em worktree ligada morria em
    # `unable to access '…/main/.git/config': Operation not permitted`.
    #
    # Falha por SUB-concessão é traiçoeira: parece contenção correta e é
    # produto quebrado. Emitir os dois é seguro — ambos são `allow`, e a regra
    # de "último que casa vence" do SBPL só decide entre allow e deny.
    completos: set[str] = set()
    metadados: set[str] = set()
    for bruto in conf.leitura:
        real = canonicalizar(bruto)
        if real not in completos:
            completos.add(real)
            linhas.append(f'(allow file-read* (subpath "{real}"))')
        for pai in _ancestrais(real):
            if pai not in metadados and pai not in completos:
                metadados.add(pai)
                linhas.append(f'(allow file-read-metadata (literal "{pai}"))')
    return linhas


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
        *_bloco_de_exec(conf),
        *_bloco_de_leitura(conf),
        "(allow sysctl-read)",
        MACH,
        f'(allow file-write* (literal "{os.devnull}"))',
    ]
    linhas.insert(2, "(allow network*)" if conf.rede else "(deny network*)")
    for bruto in conf.escrita:
        real = canonicalizar(bruto)
        linhas.append(f'(allow file-write* (subpath "{real}"))')
    for bruto in conf.negacao_de_escrita:
        # Sem `existente()`: o alvo pode legitimamente não existir ainda (um
        # repositório sem `hooks/` é normal), e a negação tem de valer para o
        # caminho que VIER a existir durante a operação — que é exatamente o
        # caso do filtro que tenta se instalar.
        linhas.append(f'(deny file-write* (subpath "{canonicalizar(bruto)}"))')
    for padrao in conf.negacao_por_nome:
        # Negação por NOME, em qualquer profundidade. `subpath` não alcança isto:
        # `.gitattributes` é criável em TODO diretório da working tree, e
        # enumerar os diretórios que existem hoje deixaria de fora os que o
        # próprio filtro criar durante a operação.
        #
        # `(/|$)` e não `$`: MEDIDO (`.11.10` e `.11.11`) — ancorar só no fim
        # nega o DIRETÓRIO `.git` e deixa TODO o conteúdo dele gravável, porque
        # `<raiz>/proj/.git/hooks/pre-commit` não termina em `/.git`. O filtro
        # instalava hook, reescrevia config e plantava ref dentro de qualquer
        # repositório aninhado na raiz de escrita. Para `.gitattributes`, que é
        # arquivo, o `$` bastava; para `.git`, que é diretório, não.
        linhas.append(f'(deny file-write* (regex #"/{padrao}(/|$)"))')
    if conf.marca is not None:
        # POR ÚLTIMO: em SBPL a regra que casa por último vence, e o `deny` do
        # subdiretório precisa sobrepor o `allow` do diretório.
        linhas.extend(conf.marca.regras_do_perfil())
    return "\n".join(linhas) + "\n"


def criar_marca() -> "processos.Marca":
    """Cria o diretório-nonce desta execução, com os dois caminhos EXISTINDO.

    A existência não é detalhe: com caminho ausente o `sandbox_check` devolve
    resposta errada sem sinalizar erro, e todo processo do host passaria a
    casar a marca.
    """
    nonce = uuid.uuid4().hex
    base = tempfile.mkdtemp(prefix=f"nomos-exec-{nonce[:12]}-")
    execdir = os.path.realpath(base)
    os.makedirs(os.path.join(execdir, "NEG"), exist_ok=True)
    permitido = os.path.join(execdir, "CANARIO")
    negado = os.path.join(execdir, "NEG", "alvo")
    for caminho in (permitido, negado):
        with open(caminho, "w") as fh:
            fh.write(nonce)
    return processos.Marca(nonce=nonce, execdir=execdir,
                           permitido=permitido, negado=negado)


# ------------------------------------------------------------------- ambiente

def conferir_ambiente(env: dict[str, str],
                      tipo: TipoDeProcesso = TipoDeProcesso.GIT) -> None:
    """Recusa se o ambiente construído carregar autoridade indevida.

    A lista de PASSO 5 não substitui o teste adversarial, mas prende a
    regressão: se alguém acrescentar `GIT_SSH_COMMAND` ao ambiente mínimo por
    conveniência, a execução para aqui em vez de rodar um binário escolhido
    por variável.

    As PROIBIÇÕES de `PROIBIDAS_NO_AMBIENTE`/`PROIBIDOS_PREFIXO` valem para
    TODO tipo, sem exceção: `HOME`, `DYLD_*` e `LD_*` concedem autoridade a
    qualquer processo, não só ao Git. O que varia por tipo é o que cada classe
    EXIGE (e, no caso do filtro, o prefixo extra que ela recusa).

    O default é `GIT` por uma razão de direção do erro, não de conveniência:
    a exigência do Git é a mais ESTRITA das duas, então quem esquecer de
    declarar o tipo recebe RECUSA, nunca autoridade a mais.
    """
    if not isinstance(tipo, TipoDeProcesso):
        raise ErroSeguranca(
            f"tipo de processo {tipo!r} não é TipoDeProcesso — a classe do "
            "processo é decisão tipada, não string vinda do chamador")
    for chave in env:
        if chave in PROIBIDAS_NO_AMBIENTE:
            raise ErroSeguranca(
                f"ambiente carrega {chave!r}, que concede autoridade externa "
                "ao Git — o ambiente do supervisor é construído, não herdado")
        if chave.startswith(PROIBIDOS_PREFIXO):
            raise ErroSeguranca(
                f"ambiente carrega {chave!r} — injeção de configuração/biblioteca")
        if chave.startswith(PROIBIDOS_PREFIXO_POR_TIPO[tipo]):
            raise ErroSeguranca(
                f"ambiente de {tipo.value} carrega {chave!r} — variável de OUTRO "
                "tipo de processo: autoridade não atravessa a fronteira de tipo")
    for chave, valor in EXIGIDAS_POR_TIPO[tipo].items():
        if env.get(chave) != valor:
            raise ErroSeguranca(
                f"neutralização obrigatória ausente para {tipo.value}: "
                f"{chave}={valor!r} (veio {env.get(chave)!r}) — sem ela o "
                "processo lê config/locale do host")


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
    """Caminho RÁPIDO: encerra o grupo original. Devolve se o grupo resistiu.

    ATENÇÃO — o valor de retorno NÃO é prova de ausência de resíduo. Grupo
    vazio (`ProcessLookupError`) devolve `False`, e grupo vazio é justamente o
    que um `setsid()`/`setpgid()` bem-sucedido produz. Quem prova ausência é
    `processos.exterminar`, pela marca de sandbox.
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


def _alimentar(fh, dados: bytes) -> None:
    """Escreve `dados` no stdin do filho, numa thread própria, e FECHA.

    Thread, e não escrita inline, por duas razões medidas:

    1. Um processo que NÃO LÊ o stdin enche o buffer do pipe (64 KiB neste
       host) e a escrita inline bloquearia ANTES do `proc.wait(timeout=prazo)`
       — o timeout deixaria de existir para exatamente o caso em que ele é
       mais necessário. Na thread, o `wait` continua sendo quem manda.
    2. Um processo que lê TUDO e só depois escreve precisa que o supervisor
       esteja drenando stdout ao mesmo tempo. Escrita inline serializaria as
       duas pontas e travaria em qualquer entrada maior que o buffer.

    O `close()` no `finally` é a parte que faz o filtro funcionar: sem EOF, um
    clean filter espera mais conteúdo para sempre e o prazo estoura sem que
    ninguém tenha errado. `BrokenPipeError` é saída NORMAL — o filho pode
    encerrar antes de consumir tudo (`head`-like), e isso não é falha do
    supervisor.
    """
    try:
        fh.write(dados)
        fh.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            fh.close()
        except (BrokenPipeError, OSError):
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


@dataclass(frozen=True)
class Quarentena:
    """Object store TEMPORÁRIO desta execução (A0.3).

    `GIT_OBJECT_DIRECTORY` desvia toda ESCRITA de objeto para um diretório
    descartável; `GIT_ALTERNATE_OBJECT_DIRECTORIES` mantém a LEITURA do store
    real, para o Git continuar enxergando o histórico. É o mesmo mecanismo que
    o próprio Git usa em `receive-pack` para não sujar o repositório com um
    push que ainda não foi aceito.

    Por que isto e não apagar depois: sem quarentena, o blob do `filter.clean`
    é gravado no store PERMANENTE antes de o filtro falhar — restaurar o índice
    tira a referência, não o objeto, e o segredo fica legível por
    `git cat-file` até um `gc`. Com quarentena, o segredo NUNCA chega ao store
    permanente; a falha só precisa apagar um diretório inteiro.

    As duas variáveis estão em `PROIBIDAS_NO_AMBIENTE` de propósito, e
    continuam proibidas: o guard roda sobre o ambiente do CHAMADOR, e só o
    supervisor injeta estes valores, DEPOIS da conferência. Herdar do host
    segue sendo recusa; escolher deliberadamente é uma decisão tipada.
    """
    diretorio: str          # GIT_OBJECT_DIRECTORY — escrita vai para cá
    alternativos: str       # GIT_ALTERNATE_OBJECT_DIRECTORIES — leitura de lá


def _acompanhar(proc, pgid: int, marca, prazo: float, entrada: bytes | None,
                completo: list[str], texto_perfil: str) -> Resultado:
    """Do processo nascido até o Resultado: drenar, alimentar, esperar, encerrar.

    Extraído de `executar` para que exista UM ponto onde o caminho feliz
    termina e um `except BaseException` possa cercá-lo inteiro. Enquanto isto
    era corpo inline, "encerrar a árvore" só acontecia se a espera terminasse
    normalmente — e uma exceção no meio pulava a pós-condição toda.
    """
    buf_out: list[bytes] = []
    buf_err: list[bytes] = []
    threads = [
        threading.Thread(target=_drenar, args=(proc.stdout, buf_out),
                         daemon=True),
        threading.Thread(target=_drenar, args=(proc.stderr, buf_err),
                         daemon=True),
    ]
    # A alimentação entra na MESMA lista das drenagens de propósito: as três
    # pontas do processo têm o mesmo dono, o mesmo ciclo de vida e o mesmo
    # `join` — e nenhuma delas pode segurar o supervisor além do prazo.
    if entrada is not None and proc.stdin is not None:
        threads.append(
            threading.Thread(target=_alimentar,
                             args=(proc.stdin, bytes(entrada)), daemon=True))
    for t in threads:
        t.start()

    morto = False
    try:
        proc.wait(timeout=prazo)
    except subprocess.TimeoutExpired:
        morto = True

    # SEMPRE, não só no timeout. A autoridade era executar ESTA operação;
    # o que o processo deixou rodando não foi autorizado por ninguém.
    grupo_resistiu = _matar_arvore(pgid)
    for t in threads:
        t.join(REAP_S)
    try:
        proc.wait(timeout=REAP_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise ErroSeguranca(
            "UNKNOWN_SECURITY_STATE: processo principal não morreu após "
            f"SIGKILL no grupo (pgid={pgid})") from None
    # A PROVA de ausência. `_matar_arvore` só sabe do grupo ORIGINAL, e
    # quem trocou de grupo o esvazia — o que aquela função lê como sucesso.
    mortos, sobreviventes = processos.exterminar(marca)
    if sobreviventes or grupo_resistiu:
        raise ErroSeguranca(
            "PROCESS_CONFINEMENT=FAIL: sobraram "
            f"{len(sobreviventes)} processo(s) desta execução após o "
            f"SIGKILL (grupo_resistiu={grupo_resistiu}). Processo residual "
            "NUNCA vira PASS só porque a resposta ao caller foi negada")

    return Resultado(
        returncode=proc.returncode, stdout=b"".join(buf_out),
        stderr=b"".join(buf_err),
        classificacao=_classificar(proc.returncode, morto),
        morto_por_timeout=morto, sandbox_aplicado=True,
        argv_efetivo=tuple(completo), perfil_usado=texto_perfil,
        residuais_mortos=len(mortos), grupo_resistiu=grupo_resistiu)


def _encerrar_a_forca(pgid: int, marca, causa: BaseException) -> None:
    """Encerra a árvore quando a saída é por EXCEÇÃO, e não pelo caminho feliz.

    Melhor-esforço em tudo, MENOS na conclusão: se sobrar processo, isto vira
    `ErroSeguranca` encadeada na causa original. Encadear e não substituir
    porque as duas informações importam — o que interrompeu, e o que ficou
    vivo. Engolir a segunda transformaria vazamento de processo em "o operador
    cancelou", que é o tipo de silêncio que esta série existe para eliminar.

    O `Ctrl-C` do operador continua sendo `KeyboardInterrupt` para quem chamou
    — a troca por `ErroSeguranca` só acontece quando há resíduo REAL, isto é,
    quando o estado deixou de ser o que o cancelamento prometia.
    """
    falha_ao_matar: BaseException | None = None
    try:
        _matar_arvore(pgid)
    except BaseException as e:      # noqa: BLE001 - a prova é `exterminar`
        # NÃO é silêncio: se nada sobreviver, o caminho rápido ter falhado é
        # irrelevante — quem prova ausência é `exterminar`, pela marca. Se algo
        # sobreviver, esta causa entra na mensagem, que é onde ela importa.
        falha_ao_matar = e
    try:
        _, sobreviventes = processos.exterminar(marca)
    except BaseException:           # noqa: BLE001
        # Sem prova de ausência, não invento uma — e não troco a exceção
        # original por um veredito meu. A falha que trouxe o fluxo até aqui já
        # é ruidosa; sobrepô-la esconderia a causa raiz do incidente.
        return
    if sobreviventes:
        raise ErroSeguranca(
            f"PROCESS_CONFINEMENT=FAIL: {len(sobreviventes)} processo(s) "
            f"sobreviveram ao encerramento forçado após {type(causa).__name__}"
            f"{f' (killpg falhou: {falha_ao_matar!r})' if falha_ao_matar else ''}"
            ". Sair por exceção não pode ser um caminho mais permissivo que o "
            "prazo") from causa


def executar(argv: list[str], *, cwd: str | Path, env: dict[str, str],
             prazo: float, confinamento: Confinamento,
             binario_sandbox: str = SANDBOX,
             quarentena: "Quarentena | None" = None,
             tipo: TipoDeProcesso = TipoDeProcesso.GIT,
             entrada: bytes | None = None,
             arvore_de_trabalho: str | None = None) -> Resultado:
    """Executa `argv` confinado. Qualquer falha de preparo é RECUSA.

    `entrada` alimenta o STDIN do processo supervisionado. Existe porque a
    interface de um `filter.clean` do Git É stdin/stdout — o conteúdo do arquivo
    entra por stdin e o transformado sai por stdout —, não uma conveniência que
    se possa contornar. Sem isto, um filtro governado NÃO FUNCIONA por mais
    aprovado (A5.2), íntegro (A5.3), com argv fixo (A5.4) e confinado (A5.5) que
    esteja.

    A alternativa — abrir um `subprocess` paralelo só para alimentar stdin —
    contornaria de uma vez timeout, kill de árvore, perfil de sandbox, auditoria
    e pós-condição de resíduo. Seria trocar a fronteira única por duas.

    `entrada=None` (o default) mantém `stdin=DEVNULL`, byte a byte o
    comportamento histórico: nenhum caller do Git muda de semântica. `b""` NÃO é
    o mesmo que `None` — vai por PIPE e fecha, o que o filho vê como EOF imediato
    vindo de um pipe real, e é essa a diferença que um clean filter enxerga.
    """
    if prazo <= 0:
        raise ErroLimite("prazo esgotado antes de iniciar o processo")
    if not argv:
        raise ErroSeguranca("argv vazio")
    if entrada is not None and not isinstance(entrada, (bytes, bytearray)):
        # `str` é recusado de propósito: aceitar texto obrigaria o supervisor a
        # escolher um encoding, e essa escolha alteraria os bytes que o filtro
        # recebe. Quem sabe o encoding é quem tem o conteúdo, não a fronteira.
        raise ErroSeguranca(
            f"entrada de stdin é {type(entrada).__name__}, não bytes — o "
            "supervisor não escolhe encoding por ninguém")
    if not os.path.exists(binario_sandbox):
        raise ErroSeguranca(
            f"{binario_sandbox} ausente: sem sandbox não há execução de Git. "
            "O NOMOS recusa em vez de rodar sem confinamento")
    if not confinamento.escrita and not confinamento.declara_sem_escrita:
        raise ErroSeguranca(
            "confinamento sem nenhuma raiz de escrita declarada — recuso por "
            "ambiguidade: ou a capacidade não escreve (e declara isso), ou "
            "alguém esqueceu de delimitar")
    conferir_ambiente(env, tipo)
    if quarentena is not None:
        # DEPOIS da conferência, e nunca antes: o guard existe para denunciar
        # ambiente HERDADO, e continua fazendo isso. Aqui é o supervisor
        # escolhendo, por parâmetro tipado, para onde a escrita de objeto vai.
        env = dict(env)
        env["GIT_OBJECT_DIRECTORY"] = existente(quarentena.diretorio)
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = existente(
            quarentena.alternativos)
    if arvore_de_trabalho is not None:
        # Mesmo princípio, mesma ordem, e pela mesma razão de sempre: herdar
        # `GIT_WORK_TREE` do host segue PROIBIDO; escolhê-lo aqui é decisão
        # tipada de quem já validou o caminho.
        #
        # MEDIDO, e é o motivo de isto não ser um `-c`: `core.worktree` no
        # `.git/config` do repositório move a working tree para onde o
        # repositório quiser, e `-c core.worktree=<repo>` NÃO a traz de volta —
        # o Git continua reportando o valor do repo. Com `core.worktree=/etc`,
        # `git-add -- hosts` indexou `/etc/hosts` com sucesso. `GIT_WORK_TREE`
        # vence, e é compatível com repo comum e com worktree ligada (medido
        # nos três casos).
        env = dict(env)
        env["GIT_WORK_TREE"] = existente(arvore_de_trabalho)
    cwd_real = existente(cwd)
    # A marca é criada e AUTO-VALIDADA antes de existir processo algum: se o
    # discriminante não estiver funcionando neste sistema, não há execução.
    # Sem ele, não haveria como provar ausência de resíduo depois.
    marca = confinamento.marca or criar_marca()
    try:
        marca.conferir()
        confinamento = replace(confinamento, marca=marca)
        texto_perfil = perfil(confinamento)
    except BaseException:
        # Recusa antes do `try` principal não passaria pelo `finally` que
        # remove o diretório-nonce, e cada recusa deixaria lixo em /var/folders.
        shutil.rmtree(marca.execdir, ignore_errors=True)
        raise

    fd, caminho_perfil = tempfile.mkstemp(prefix="nomos-sb-", suffix=".sb")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(texto_perfil)
        os.chmod(caminho_perfil, 0o600)
        completo = [binario_sandbox, "-f", caminho_perfil, *argv]
        try:
            proc = subprocess.Popen(
                completo, cwd=cwd_real, env=dict(env),
                stdin=(subprocess.DEVNULL if entrada is None
                       else subprocess.PIPE),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, close_fds=True, shell=False,
                preexec_fn=_preexec(confinamento))       # noqa: PLW1509
        except OSError as exc:
            raise ErroSeguranca(f"não consegui iniciar sob sandbox: {exc}") from None
        except (ValueError, subprocess.SubprocessError) as exc:
            raise ErroSeguranca(
                f"preparo do processo confinado falhou: {exc}") from None

        pgid = proc.pid          # setsid no filho ⇒ pgid == pid
        try:
            return _acompanhar(proc, pgid, marca, prazo, entrada,
                               completo, texto_perfil)
        except BaseException as exc:
            # A saída por EXCEÇÃO não pode ser mais permissiva que a saída pelo
            # prazo. MEDIDO: sem este bloco, um `KeyboardInterrupt` durante o
            # `wait` pulava o encerramento da árvore INTEIRO e deixava 4
            # descendentes vivos — e o `finally` abaixo ainda apagava o
            # diretório-nonce, destruindo o único jeito de reencontrá-los
            # depois. Bastava cancelar para transformar contenção em vazamento.
            _encerrar_a_forca(pgid, marca, exc)
            raise
    finally:
        try:
            os.unlink(caminho_perfil)
        except OSError:
            pass
        # O diretório-nonce sai por último: enquanto ele existir, a marca
        # continua avaliável — e `conferir()` recusa marca com caminho ausente.
        if confinamento.marca is not None:
            shutil.rmtree(confinamento.marca.execdir, ignore_errors=True)
