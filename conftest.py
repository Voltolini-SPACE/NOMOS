"""Configuração raiz do pytest.

Ignora na coleção diretórios de extração de sdist/build (ex.: ``nomos-1.3.0rc16/``),
que contêm cópias dos testes com os mesmos nomes de módulo e causariam
"import file mismatch" no pytest. Esses diretórios são artefatos de build untracked
(também ignorados no .gitignore) e não fazem parte da suíte real.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from nomos.kernel import plataforma

collect_ignore_glob = ["nomos-[0-9]*"]

_MOTIVO_SEM_GIT_GOVERNADO = (
    "capacidade Git governada exige sandbox-exec — INDISPONÍVEL fora do macOS "
    "por desenho (adapters/supervisor.py, 'Fail-closed, sem exceção')")

_MOTIVO_SEM_SERVICO = (
    "serviço persistente (NH-014) exige launchd e fcntl.flock — INDISPONÍVEL "
    "nesta plataforma por desenho (kernel/plataforma.py, "
    "servico_persistente_disponivel)")

_MOTIVO_SEM_POSIX = (
    "bateria A5 (filtro governado + armazém de artefatos) exige ferramentas "
    "POSIX (/bin/sh, /usr/bin/sed) e semântica Unix de permissão — "
    "INDISPONÍVEL nesta plataforma")

_MOTIVO_SEM_PERMISSAO_UNIX = (
    "asserção de bit de permissão Unix (0600/0700) — nesta plataforma o chmod "
    "não pega e a proteção vem das permissões do perfil do usuário "
    "(kernel/plataforma.chmod_privado)")

_FILTRO_EXECUTAVEIS = ("/bin/sh", "/usr/bin/sed")


def _ferramentas_posix_do_filtro() -> bool:
    """Os DOIS fatos de que a bateria A5 depende, medidos — não deduzidos.

    1. **Ferramentas POSIX.** Os testes escrevem um filtro `#!/bin/sh` que faz
       `exec /usr/bin/sed "$@"` e o executam. Sem shebang e sem `sed` não há o
       que exercitar: o modelo de ameaça inteiro (injeção por argv em `sed`)
       tem formato POSIX.

    2. **Semântica Unix de permissão.** O armazém publica o artefato
       NÃO-GRAVÁVEL (`0o500`) — é essa a defesa. No Windows os bits não mapeiam
       e, pior, não se apaga nem substitui arquivo somente-leitura: a limpeza
       vira `PermissionError`, a publicação atômica deixa temporário para trás,
       e asserções como "armazém deve ser 0700" comparam número com número
       errado.

    Medir em vez de perguntar `platform.system()` é a mesma escolha de
    `capacidade_git_governada_disponivel` e `servico_persistente_disponivel`, e
    pelo mesmo motivo registrado lá: já houve na suíte um condicional preso ao
    caminho ERRADO, afirmando sucesso onde a capacidade não existe.
    """
    return (all(os.access(c, os.X_OK) for c in _FILTRO_EXECUTAVEIS)
            and permissao_unix_pega())


def permissao_unix_pega() -> bool:
    """O bit de permissão PEGA nesta plataforma?

    Fato separado porque tem consumidor próprio: vários pontos do NOMOS gravam
    0600 (proposta de aprovação, medição de uso, `pausa.json`, sidecars do WAL)
    e a asserção "está 0600" é a prova de que o segredo não vazou para outro
    usuário. No Windows os bits Unix não mapeiam — `kernel/plataforma.
    chmod_privado` já documenta isso e engole o erro de propósito, porque lá a
    proteção vem das permissões do perfil.

    Um `chmod` que o SO ignora em SILÊNCIO é pior que a ausência da ferramenta:
    a defesa pareceria ligada. Por isso mede escrevendo de verdade e lendo de
    volta, em vez de perguntar `os.name`.
    """
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        alvo = Path(tmp.name)
    try:
        alvo.chmod(0o600)
        return (alvo.stat().st_mode & 0o777) == 0o600
    except (OSError, NotImplementedError):
        return False
    finally:
        try:
            alvo.chmod(0o600)
        except OSError:
            pass
        alvo.unlink(missing_ok=True)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "git_governado: exige a capacidade Git governada (sandbox-exec, só "
        "macOS). Fora do macOS o teste é PULADO, não falha — a capacidade não "
        "existe ali por decisão de projeto.")
    config.addinivalue_line(
        "markers",
        "servico_persistente: exige launchd + fcntl.flock (NH-014). Onde não "
        "há, o teste é PULADO — o produto RECUSA a capacidade ali, então o "
        "teste passaria por vácuo ou morreria de ModuleNotFoundError.")
    config.addinivalue_line(
        "markers",
        "filtro_posix: exige /bin/sh + /usr/bin/sed e bits de permissão Unix "
        "que PEGAM (bateria A5: filtro governado e armazém de artefatos).")
    config.addinivalue_line(
        "markers",
        "permissao_unix: afirma bit de permissão Unix (0600/0700). Onde o "
        "chmod não pega, a asserção mede o SO e não o NOMOS.")


def pytest_collection_modifyitems(items):
    """Pula o que exige a capacidade Git governada onde ela não existe.

    Por que um hook e não `pytestmark` de módulo: nesses arquivos a MAIORIA dos
    testes é independente de plataforma (análise estática do adapter, validação
    de ref, recusa de escopo) e continua provando coisa real no Linux. Um skip
    de módulo apagaria 49 testes válidos só em `c1_git` — trocaria um vermelho
    honesto por um verde menor e silencioso.

    Por que pular em vez de deixar falhar: sem `sandbox-exec` TODA operação
    recusa, então o teste que afirma "isto foi recusado" passaria por vácuo —
    verde que continuaria verde com a defesa removida. Pular diz a verdade;
    passar por vácuo mente.
    """
    # Pelo módulo, e não por nome importado: assim um plugin de verificação
    # consegue substituir a função e provar, DE DENTRO DO MAC, que o portão
    # produz skip (e não falha) na plataforma onde a capacidade não existe.
    if not plataforma.capacidade_git_governada_disponivel():
        pular = pytest.mark.skip(reason=_MOTIVO_SEM_GIT_GOVERNADO)
        for item in items:
            if "git_governado" in item.keywords:
                item.add_marker(pular)

    # Mesmo contrato para o serviço persistente (NH-014): onde não há launchd
    # nem `fcntl.flock` o produto RECUSA a capacidade na porta, então o teste
    # que exercita trava, batimento ou instalação não tem o que medir — passaria
    # por vácuo ou morreria de ModuleNotFoundError. Os demais testes do arquivo
    # (renderização do plist, validação de argumento) são independentes de
    # plataforma e seguem valendo, que é o motivo de marcar por TESTE e não com
    # `pytestmark` de módulo.
    if not plataforma.servico_persistente_disponivel():
        pular_sv = pytest.mark.skip(reason=_MOTIVO_SEM_SERVICO)
        for item in items:
            if "servico_persistente" in item.keywords:
                item.add_marker(pular_sv)

    # Bateria A5. Medido UMA vez por sessão: o teste de permissão escreve em
    # disco, e repeti-lo por item custaria uma ida ao filesystem por teste.
    if not _ferramentas_posix_do_filtro():
        pular_px = pytest.mark.skip(reason=_MOTIVO_SEM_POSIX)
        for item in items:
            if "filtro_posix" in item.keywords:
                item.add_marker(pular_px)

    # Fato mais estreito, marcador próprio: há testes fora da bateria A5 cuja
    # ÚNICA parte não portável é a asserção de modo (proposta de aprovação,
    # medição de uso, pausa.json, sidecars do WAL). Reaproveitar `filtro_posix`
    # neles diria um motivo falso no relatório de skip.
    if not permissao_unix_pega():
        pular_pu = pytest.mark.skip(reason=_MOTIVO_SEM_PERMISSAO_UNIX)
        for item in items:
            if "permissao_unix" in item.keywords:
                item.add_marker(pular_pu)


_FONTE_ESPIAO = r"""
#include <stdio.h>
int main(void) {
    FILE *f = fopen("%s", "w");
    if (f) { fputs("EXECUTOU\n", f); fclose(f); }
    return 0;
}
"""


@pytest.fixture
def espiao_nativo():
    """Fábrica de espião BINÁRIO para provar execução de programa do repositório.

    Vive aqui, e não num módulo de teste, porque duas baterias precisam dele e
    importar um teste a partir de outro depende de o rootdir estar em
    `sys.path` — frágil demais para a suíte de segurança.

    ## Por que binário e não script

    ATENÇÃO — a justificativa anterior deste bloco era FALSA, e ficou aqui por
    tempo suficiente para virar premissa de quem lesse depois (`.3.05`). Ela
    dizia que um espião `#!/bin/sh` "continuaria verde mesmo com a neutralização
    removida", isto é, que seria VÁCUO. RE-MEDIDO, no único regime em que
    "neutralização removida" tem efeito observável (exec AMPLO, onde a
    neutralização é a única defesa):

        neutralização PRESENTE (hooksPath + --no-verify)   canário = não
        neutralização REMOVIDA                             canário = SIM

    O espião shell DISCRIMINA — ele fica vermelho ao remover a defesa. E a
    allowlist LITERAL do push, medida, já contém `/bin/sh` E `/bin/bash`, então
    a razão dada ("o kernel precisa do interpretador") também não era o que o
    continha ali: o que contém é o caminho do HOOK não estar na allowlist.

    A escolha do espião nativo continua CERTA, por um motivo mais fraco e
    honesto: o espião em shell depende de duas defesas ao mesmo tempo (a
    allowlist do interpretador e a neutralização), então um verde dele não diz
    QUAL das duas segurou. O nativo tira o interpretador da equação e deixa uma
    causa só — se não rodou, foi a execução que foi negada.

    O padrão de anotar a afirmação como histórica em vez de apagá-la é o mesmo
    de `test_absorption07_hooks_contencao.py`: quem já leu a versão errada
    precisa encontrar a correção, não o silêncio.

    ## Por que o canário precisa morar na área gravável

    Quem usa esta fábrica tem de pôr o canário DENTRO da raiz de escrita da
    capacidade (o git dir). Fora dela, `not canario.exists()` é verdade mesmo
    quando o programa executou — porque ele não conseguiria gravar de qualquer
    jeito — e a asserção deixa de distinguir contenção de impossibilidade.
    Foi exatamente esse o defeito medido em C2a/C2b.
    """
    def fabricar(destino: Path, canario: Path) -> Path:
        fonte = Path(destino) / "espiao.c"
        fonte.write_text(_FONTE_ESPIAO % canario)
        binario = Path(destino) / "espiao"
        r = subprocess.run(["cc", "-O2", "-o", str(binario), str(fonte)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
        binario.chmod(0o755)
        return binario
    return fabricar
