"""A5.4 — quem escolhe os ARGUMENTOS.

A série tem três donos, e agora os três são o mesmo:

    A5.2  WHO_SELECTS_EXECUTABLE        = NOMOS
    A5.3  WHICH_EXECUTABLE_OBJECT       = NOMOS_MANAGED_ARTIFACT
    A5.4  WHAT_ARGUMENTS_IT_RECEIVES    = NOMOS

Sem A5.4 os dois primeiros não valem nada: `/usr/bin/sed` é aprovado,
íntegro, importado — e inofensivo apenas até receber `-e 's/.*/rm -rf/e'`.
Um executável aprovado vira executor genérico no instante em que o argv aceita
entrada.

A prova central deste arquivo NÃO é uma lista de metacaracteres bloqueados. É
estrutural: `comando()` não tem parâmetro. Não existe canal por onde o
repositório contribua com um elemento do argv — nem sanitizado, nem escapado,
nem "só um". Bloquear caractere é defesa em profundidade; a fronteira é a
ausência de canal.
"""
from __future__ import annotations

import dataclasses
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.kernel import plataforma
from nomos.adapters import filtro_governado as fg
from nomos.adapters.filtro_governado import (
    ArmazemDeExecutaveis,
    ErroFiltro,
    PoliticaDeFiltro,
    conferir_argv,
)

REDATOR = "#!/bin/sh\nexec /usr/bin/sed \"$@\"\n"


@pytest.fixture
def armazem(tmp_path):
    return ArmazemDeExecutaveis(tmp_path / "store")


@pytest.fixture
def sed_art(armazem, tmp_path):
    origem = tmp_path / "redator.sh"
    origem.write_text(REDATOR)
    origem.chmod(0o755)
    return armazem.importar(origem)


def _pol(art, argv=("-e", "s/SENHA=.*/SENHA=REDIGIDO/")):
    return PoliticaDeFiltro(filter_id="synthetic-redactor",
                            canonical_executable="/usr/bin/sed",
                            argv_policy=argv, managed_artifact=art)


# ══════ A PROVA ESTRUTURAL — não existe canal para argv do repositório ══════

def test_comando_NAO_ACEITA_PARAMETRO():
    """A fronteira é a ausência de canal, não a filtragem de conteúdo.

    Se `comando()` ganhar um parâmetro um dia, sanitizar o que entra por ele
    vira uma corrida que o defensor perde eventualmente. Aqui não há entrada.
    """
    sig = inspect.signature(PoliticaDeFiltro.comando)
    assert list(sig.parameters) == ["self"], (
        f"comando() ganhou parâmetro {list(sig.parameters)[1:]} — abriu canal "
        "de argv; a partir daí a defesa vira filtragem, e filtragem falha")


@pytest.mark.filtro_posix
def test_argv_vem_INTEIRO_da_politica(sed_art):
    pol = _pol(sed_art)
    cmd = pol.comando()
    assert cmd[0] == sed_art.managed_path      # A5.3: o artefato
    assert tuple(cmd[1:]) == pol.argv_policy   # A5.4: a política, e só


@pytest.mark.parametrize("mutacao", ["append", "replace", "extend"])
@pytest.mark.filtro_posix
def test_politica_de_argv_e_IMUTAVEL(sed_art, mutacao):
    pol = _pol(sed_art)
    with pytest.raises(dataclasses.FrozenInstanceError):
        pol.argv_policy = ("-e", "s/.*/OWNED/")     # type: ignore[misc]
    # E a tupla devolvida não é a interna: mexer nela não alcança a política.
    cmd = pol.comando()
    if mutacao == "append":
        cmd.append("--exec=/bin/sh")
    elif mutacao == "replace":
        cmd[1] = "--exec=/bin/sh"
    else:
        cmd.extend(["-e", "s/.*/OWNED/e"])
    assert pol.comando()[1:] == list(pol.argv_policy), (
        "mutar a lista devolvida alterou o argv governado")


# ══════════════ Flags que pedem execução de OUTRO programa ══════════════════

@pytest.mark.parametrize("flag", [
    "--exec", "--command", "--program", "--helper", "--shell",
    "--interpreter", "--config", "--rcfile", "--init-file", "--eval",
])
def test_flag_de_execucao_secundaria_e_RECUSADA_na_construcao(flag):
    """Recusa na CONSTRUÇÃO: política perigosa nunca chega a existir."""
    with pytest.raises(ErroFiltro, match="OUTRO programa"):
        conferir_argv((flag, "/bin/sh"), "synthetic-redactor")


def test_argv_com_NUL_e_recusado():
    with pytest.raises(ErroFiltro, match="NUL"):
        conferir_argv(("-e", "s/a/b/\x00"), "f")


def test_argv_LISTA_e_recusado():
    """Lista é mutável — argv mutável é argv que alguém estende depois."""
    with pytest.raises(ErroFiltro, match="não é tupla"):
        conferir_argv(["-e", "x"], "f")      # type: ignore[arg-type]


def test_argv_com_nao_string_e_recusado():
    with pytest.raises(ErroFiltro, match="não é str"):
        conferir_argv(("-e", 42), "f")       # type: ignore[arg-type]


# ═══════ Metacaracteres NÃO ganham semântica — porque não há shell ══════════

@pytest.mark.parametrize("meta", [
    "; touch /tmp/OWNED", "&& touch /tmp/OWNED", "|| touch /tmp/OWNED",
    "$(touch /tmp/OWNED)", "`touch /tmp/OWNED`", "| touch /tmp/OWNED",
    "> /tmp/OWNED", ">> /tmp/OWNED", "< /etc/passwd", "\n touch /tmp/OWNED",
    "'quote", '"aspas', "back\\slash", "*", "?",
])
@pytest.mark.filtro_posix
def test_metacaractere_no_argv_nao_executa_nada(sed_art, tmp_path, meta):
    """CONTROLE POSITIVO EMBUTIDO: o mesmo texto sob `sh -c` faria efeito.

    Aqui ele chega ao `sed` como TEXTO. Ou o sed recusa a expressão, ou a
    aplica literalmente — em nenhum caso nasce um processo novo.
    """
    canario = tmp_path / "OWNED"
    pol = _pol(sed_art, argv=("-e", f"s/x/{meta}/"))
    entrada = "x\n"
    r = subprocess.run(pol.comando(), input=entrada, capture_output=True,
                       text=True, timeout=20)
    assert not canario.exists(), f"metacaractere executou: {meta!r}"
    assert not Path("/tmp/OWNED").exists(), "efeito colateral global"
    if r.returncode == 0:
        assert "OWNED" not in r.stdout or meta in r.stdout


@pytest.mark.filtro_posix
def test_controle_positivo_o_mesmo_texto_SOB_SHELL_executa(tmp_path):
    """Sem isto, o teste acima não distingue contenção de 'nada aconteceu'."""
    canario = tmp_path / "OWNED_SHELL"
    subprocess.run(["/bin/sh", "-c", f"touch {canario}"], timeout=20)
    assert canario.exists(), (
        "o payload nem sob shell funciona — a bateria acima seria vácuo")


def test_estrutural_nenhum_shell_no_modulo():
    fonte = Path(fg.__file__).read_text("utf-8")
    for proibido in ("shell=True", "/bin/sh", "/bin/bash", "os.system",
                     "shlex.split"):
        assert proibido not in fonte, f"{proibido} apareceu no módulo"


# ══════════════════ Argumento com aparência de opção ════════════════════════

@pytest.mark.parametrize("arg", ["-rf", "--output=/etc/passwd", "-o/etc/x",
                                 "--file=/etc/passwd"])
@pytest.mark.filtro_posix
def test_argumento_com_cara_de_opcao_vem_da_POLITICA_nao_do_repo(sed_art, arg):
    """Option smuggling só existe se houver quem contrabandeie.

    Estes argumentos são recusados quando pedem execução secundária; os demais
    são permitidos porque quem os escreveu foi o ADMINISTRADOR na política, não
    o repositório. O critério, de novo, não é a forma do argumento — é a
    titularidade.
    """
    pol = _pol(sed_art, argv=(arg,))
    assert pol.comando()[1] == arg
    assert pol.argv_policy == (arg,)


@pytest.mark.filtro_posix
def test_repo_nao_tem_como_pedir_argv(sed_art):
    """O repositório só fornece `filter_id`. `resolver()` não tem outro campo."""
    reg = fg.RegistroDeFiltros({"synthetic-redactor": _pol(sed_art)})
    sig = inspect.signature(reg.resolver)
    assert list(sig.parameters) == ["requested_filter_id"], (
        f"resolver() aceita {list(sig.parameters)} — canal além do id")
    pol = reg.resolver("synthetic-redactor")
    assert pol.argv_policy == ("-e", "s/SENHA=.*/SENHA=REDIGIDO/")


# ════════════ CONTROLE POSITIVO — o argv fixo é NECESSÁRIO ══════════════════

@pytest.mark.filtro_posix
def test_o_filtro_governado_FUNCIONA_com_o_argv_aprovado(sed_art):
    """Provar denial não basta: o argv aprovado tem de ser o que faz funcionar.

    Sem `-e s/SENHA=.*/SENHA=REDIGIDO/` o redator não redige nada. Este é o
    par obrigatório do gate: ALLOW aprovado + DENY para o resto.
    """
    pol = _pol(sed_art)
    r = subprocess.run(pol.comando(), input="SENHA=hunter2\n",
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[:300]
    assert r.stdout.strip() == "SENHA=REDIGIDO"
    assert "hunter2" not in r.stdout, "o segredo passou intacto"


@pytest.mark.skipif(
    not plataforma.EH_MAC,
    reason="depende do sed BSD: o GNU sed sem script sai com erro de uso e "
           "stdout VAZIO, então a contraprova não consegue nem rodar")
def test_sem_o_argv_aprovado_o_redator_nao_redige(sed_art):
    """Contraprova: o argv É a autoridade funcional, não decoração.

    Só vale onde `sed` sem script COPIA a entrada (BSD, macOS). No GNU sed
    (Linux) o mesmo comando devolve erro de uso e stdout vazio — o teste ficaria
    vermelho por diferença de implementação do `sed`, não por perda da
    propriedade que ele mede.
    """
    pol = _pol(sed_art, argv=())
    r = subprocess.run(pol.comando(), input="SENHA=hunter2\n",
                       capture_output=True, text=True, timeout=20)
    assert "hunter2" in r.stdout, (
        "sem argv o redator ainda redige — então o argv não era necessário e "
        "o controle positivo acima não prova nada")


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
