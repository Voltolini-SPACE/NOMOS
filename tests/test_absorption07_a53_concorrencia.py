"""A5.3 — as propriedades sob CONTENÇÃO, não por inspeção do fluxo.

O núcleo, o binding e a verificação pre-exec já estão congelados. Mas duas
afirmações centrais continuavam sendo ARGUMENTADAS pelo desenho single-thread:

    PARTIAL_ARTIFACT_PUBLISHED=0
    REGISTRY_ARTIFACT_MISMATCH_ACCEPTED=0

Raciocínio não é evidência. `temp -> relê -> verifica -> os.replace` é uma
sequência sólida, e "sólida" é exatamente o que se diz de um desenho até a
primeira corrida real. Este arquivo mede.

## O que a concorrência ataca aqui

O armazém é endereçado por conteúdo, então dois imports do MESMO binário
disputam o MESMO destino. A publicação é um `os.replace` — atômico no POSIX —,
mas o que acontece com o temporário do perdedor, com o leitor que abriu o
destino no meio, e com o `conferir()` que roda enquanto alguém tenta adulterar?

## Regra herdada desta missão

Todo canário hostil é provado FUNCIONAL antes de a ausência dele virar
evidência. Ausência de side effect só prova bloqueio depois de provado que o
side effect existiria.
"""
from __future__ import annotations

import errno
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import supervisor
from nomos.adapters.filtro_governado import ArmazemDeExecutaveis, ErroFiltro

BOM = "#!/bin/sh\necho SAIDA_BOA\n"
HOSTIL = "#!/bin/sh\necho HOSTIL > \"$CANARIO\"\necho SAIDA_HOSTIL\n"
N = 12


@pytest.fixture
def armazem(tmp_path):
    return ArmazemDeExecutaveis(tmp_path / "store")


def _script(p: Path, corpo: str) -> Path:
    p.write_text(corpo)
    p.chmod(0o755)
    return p


def _rodar(caminho, canario=None):
    env = dict(os.environ, CANARIO=str(canario or "/dev/null"))
    return subprocess.run([str(caminho)], capture_output=True, text=True,
                          timeout=20, env=env)


def _temporarios(armazem) -> list[Path]:
    return [p for p in Path(armazem.raiz).rglob(".importando-*")]


def _artefatos(armazem) -> list[Path]:
    return [p for p in Path(armazem.raiz).rglob("*")
            if p.is_file() and not p.name.startswith(".importando-")]


def _integros(armazem) -> None:
    """Nenhum artefato publicado pode divergir do próprio nome (= sha)."""
    for p in _artefatos(armazem):
        sha, _ = fg._digerir(str(p))
        assert sha == p.name, (
            f"PARTIAL_ARTIFACT_PUBLISHED: {p.name[:12]} contém {sha[:12]}")


# ═══════════ 01-04 — imports simultâneos e endereçamento por conteúdo ═══════

def test_01_imports_simultaneos_da_MESMA_origem(armazem, tmp_path):
    origem = _script(tmp_path / "f.sh", BOM)
    pronto = threading.Barrier(N)

    def importa(_):
        pronto.wait(timeout=30)
        return armazem.importar(origem)

    with ThreadPoolExecutor(max_workers=N) as ex:
        arts = list(ex.map(importa, range(N)))

    assert len({a.artifact_id for a in arts}) == 1
    assert len(_artefatos(armazem)) == 1, "duplicou artefato"
    assert _temporarios(armazem) == [], "TEMP_RESIDUE_AFTER_FAILURE"
    _integros(armazem)
    assert _rodar(arts[0].managed_path).stdout.strip() == "SAIDA_BOA"


def test_02_imports_simultaneos_MESMOS_BYTES_origens_diferentes(armazem,
                                                                tmp_path):
    origens = [_script(tmp_path / f"o{i}.sh", BOM) for i in range(N)]
    pronto = threading.Barrier(N)

    def importa(o):
        pronto.wait(timeout=30)
        return armazem.importar(o)

    with ThreadPoolExecutor(max_workers=N) as ex:
        arts = list(ex.map(importa, origens))

    assert len({a.artifact_id for a in arts}) == 1, "dedup por conteúdo falhou"
    assert len({a.managed_path for a in arts}) == 1
    assert len(_artefatos(armazem)) == 1
    _integros(armazem)


def test_03_imports_simultaneos_BYTES_DIFERENTES(armazem, tmp_path):
    origens = [_script(tmp_path / f"o{i}.sh", BOM + f"# {i}\n")
               for i in range(N)]
    pronto = threading.Barrier(N)

    def importa(o):
        pronto.wait(timeout=30)
        return armazem.importar(o)

    with ThreadPoolExecutor(max_workers=N) as ex:
        arts = list(ex.map(importa, origens))

    assert len({a.artifact_id for a in arts}) == N, "colidiu conteúdo distinto"
    assert len(_artefatos(armazem)) == N
    _integros(armazem)
    for a in arts:
        assert _rodar(a.managed_path).stdout.strip() == "SAIDA_BOA"


def test_04_artefato_valido_existente_nao_e_corrompido_por_reimport(armazem,
                                                                    tmp_path):
    """VALID_EXISTING_ARTIFACT_CORRUPTED=0 sob reimport concorrente."""
    origem = _script(tmp_path / "f.sh", BOM)
    primeiro = armazem.importar(origem)
    sha0, _ = fg._digerir(primeiro.managed_path)
    pronto = threading.Barrier(N)

    def importa(_):
        pronto.wait(timeout=30)
        return armazem.importar(origem)

    with ThreadPoolExecutor(max_workers=N) as ex:
        list(ex.map(importa, range(N)))

    assert fg._digerir(primeiro.managed_path)[0] == sha0
    primeiro.conferir()


# ═══════════ 05-07 — origem mudando DURANTE o import ════════════════════════

@pytest.mark.parametrize("modo", ["replace", "unlink_recreate", "symlink"])
def test_05a07_origem_mutando_durante_o_import(armazem, tmp_path, modo):
    """A origem troca em loop enquanto importamos.

    O contrato NÃO é "o import sempre passa" — é que o que for PUBLICADO
    corresponde ao próprio digest, e que nada parcial fica visível. Import que
    recusa por conteúdo mudado no meio é comportamento CORRETO.
    """
    origem = tmp_path / "f.sh"
    _script(origem, BOM)
    hostil_corpo = HOSTIL
    parar = threading.Event()

    def atacante():
        i = 0
        while not parar.is_set() and i < 400:
            alvo = _script(tmp_path / f"h{i%3}.sh", hostil_corpo)
            try:
                if modo == "replace":
                    os.replace(alvo, origem)
                elif modo == "unlink_recreate":
                    origem.unlink(missing_ok=True)
                    _script(origem, hostil_corpo)
                else:
                    origem.unlink(missing_ok=True)
                    origem.symlink_to(alvo)
            except OSError:
                pass
            i += 1

    t = threading.Thread(target=atacante, daemon=True)
    t.start()
    resultados = []
    try:
        for _ in range(30):
            try:
                resultados.append(armazem.importar(origem))
            except ErroFiltro:
                pass                      # recusa é desfecho legítimo
            except OSError as e:
                # Mesma classe de desfecho legítimo, pelo mesmo contrato: no
                # modo `symlink` (e no `unlink_recreate`) o atacante faz
                # unlink→symlink_to, e ENTRE os dois a origem não existe (ou
                # é um link sendo trocado). Cair nessa janela é a corrida
                # acontecendo, não defeito — o que o teste mede é que nada
                # PARCIAL fica publicado (`_integros` abaixo).
                #
                # O errno DEPENDE DA PLATAFORMA para o mesmo evento: Linux
                # devolve ENOENT e o macOS devolve EINVAL no `realpath` do
                # link em troca. Filtro pela lista de sintomas de "o caminho
                # mudou embaixo" em vez de engolir OSError inteiro — erro de
                # permissão ou de I/O continua derrubando o teste, como deve.
                if e.errno not in (errno.ENOENT, errno.EINVAL,
                                   errno.ELOOP, errno.ENOTDIR):
                    raise
    finally:
        parar.set()
        t.join(timeout=15)

    _integros(armazem)                    # PARTIAL_ARTIFACT_PUBLISHED=0
    assert _temporarios(armazem) == [], "TEMP_RESIDUE_AFTER_FAILURE"
    for a in resultados:                  # todo artefato devolvido confere
        a.conferir()


# ═══════════ 08-09 — tentativa de trocar o artefato publicado ═══════════════

def test_08_09_artefato_publicado_nao_e_gravavel(armazem, tmp_path):
    """CONTROLE POSITIVO: o hostil é funcional antes de exigir sua ausência."""
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    canario = tmp_path / "C"
    hostil = _script(tmp_path / "h.sh", HOSTIL)
    assert _rodar(hostil, canario).stdout.strip() == "SAIDA_HOSTIL"
    assert canario.exists(), "canário hostil não funciona; teste seria vácuo"
    canario.unlink()

    modo = os.stat(art.managed_path).st_mode
    assert not modo & 0o222, "artefato gravável"
    with pytest.raises(OSError):
        with open(art.managed_path, "wb") as fh:
            fh.write(HOSTIL.encode())

    assert _rodar(art.managed_path, canario).stdout.strip() == "SAIDA_BOA"
    assert not canario.exists(), "UNAPPROVED_CODE_EXECUTED"
    art.conferir()


def test_10_mismatch_registry_artefato_nunca_e_aceito(armazem, tmp_path):
    """REGISTRY_ARTIFACT_MISMATCH_ACCEPTED=0, com o artefato adulterado."""
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    os.chmod(art.managed_path, 0o700)
    Path(art.managed_path).write_text(HOSTIL)
    for _ in range(5):
        with pytest.raises(ErroFiltro, match="DIVERGE"):
            art.conferir()
    assert art.sha256 != fg._digerir(art.managed_path)[0]


# ═══════════ 11-15 — interrupção em cada ponto da publicação ════════════════

@pytest.mark.parametrize("onde", ["antes_verify", "antes_replace",
                                  "depois_replace"])
def test_11a14_interrupcao_em_cada_ponto(armazem, tmp_path, monkeypatch, onde):
    """Injeta falha em cada janela da sequência temp->verify->replace."""
    origem = _script(tmp_path / "f.sh", BOM)
    real_digerir, real_replace = fg._digerir, os.replace
    estado = {"n": 0}

    def digerir_explode(caminho):
        # 1ª chamada = digest da origem; 2ª = releitura do temporário
        estado["n"] += 1
        if onde == "antes_verify" and estado["n"] == 2:
            raise OSError("falha injetada relendo o temporário")
        return real_digerir(caminho)

    def replace_explode(a, b):
        if onde == "antes_replace":
            raise OSError("falha injetada antes do replace")
        real_replace(a, b)
        if onde == "depois_replace":
            raise OSError("falha injetada depois do replace")

    monkeypatch.setattr(fg, "_digerir", digerir_explode)
    monkeypatch.setattr(os, "replace", replace_explode)
    with pytest.raises((ErroFiltro, OSError)):
        armazem.importar(origem)
    monkeypatch.undo()

    assert _temporarios(armazem) == [], (
        f"{onde}: sobrou temporário — publicação parcial visível")
    _integros(armazem)
    if onde != "depois_replace":
        assert _artefatos(armazem) == [], f"{onde}: publicou apesar da falha"
    else:
        # `os.replace` já concluiu: o que existe é ÍNTEGRO, não parcial.
        for p in _artefatos(armazem):
            assert fg._digerir(str(p))[0] == p.name


def test_15_temporarios_nao_sobrevivem_a_falhas_repetidas(armazem, tmp_path):
    for _ in range(10):
        with pytest.raises(ErroFiltro):
            armazem.importar(tmp_path / "nao-existe")
    assert _temporarios(armazem) == []
    assert _artefatos(armazem) == []


# ═══════════ 16-20 — leitura, verificação e execução durante publish ════════

def test_16a19_leitura_verificacao_execucao_concorrentes(armazem, tmp_path):
    """Enquanto imports acontecem, leitores conferem e executam.

    UNVERIFIED_ARTIFACT_EXECUTED=0: só executa o que `executavel()` devolveu,
    e `executavel()` confere antes de devolver.
    """
    origem = _script(tmp_path / "f.sh", BOM)
    art0 = armazem.importar(origem)
    pol = fg.PoliticaDeFiltro(filter_id="redator",
                              canonical_executable=str(origem),
                              managed_artifact=art0)
    parar = threading.Event()
    erros: list[str] = []

    def importador():
        i = 0
        while not parar.is_set() and i < 60:
            try:
                armazem.importar(_script(tmp_path / f"x{i%5}.sh",
                                         BOM + f"# {i%5}\n"))
            except ErroFiltro:
                pass
            i += 1

    def leitor():
        for _ in range(40):
            if parar.is_set():
                return
            try:
                caminho = pol.executavel()          # confere DENTRO
                saida = _rodar(caminho).stdout.strip()
                if saida != "SAIDA_BOA":
                    erros.append(f"executou saída inesperada: {saida!r}")
            except ErroFiltro as e:
                erros.append(f"conferir falhou sem adulteração: {e}")

    ts = [threading.Thread(target=importador, daemon=True) for _ in range(3)]
    ts += [threading.Thread(target=leitor, daemon=True) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=90)
    parar.set()

    assert erros == [], erros[:3]
    _integros(armazem)
    assert _temporarios(armazem) == []


# ═══════════ 20 — o que a adulteração concorrente prova, e contra QUEM ══════
#
# A versão anterior deste bloco era UM teste, e ele era intermitente: 2 falhas
# em 10 execuções sob carga, com o produto intacto. A causa foi medida, não
# suposta — o tamper eram 80 reescritas de arquivo (microssegundos cada) contra
# 60 execuções de processo (~45 ms cada), então a thread atacante terminava
# INTEIRA antes de a primeira execução sair do lugar sempre que o escalonador
# desse azar, e o próprio guard de vácuo do teste (`detectou > 0`) disparava.
#
# Amarrar o tamper à mesma condição de parada das execuções (o conserto óbvio)
# trocou a intermitência por uma falha DETERMINÍSTICA e muito mais informativa.
# Medido com contadores, 5 rodadas de 60 execuções, todas iguais no desfecho:
#
#     tamper FIXO(80)   HOSTIL=0/60,  detectou=0..6     <- a corrida mal ocorria
#     tamper CONTÍNUO   HOSTIL=2..10/60, detectou=35..48, CANÁRIO=True (5/5)
#
# Isto é: com um escritor que reescreve o ARTEFATO GERENCIADO em laço, o
# verificar-e-depois-executar É vencido e código não aprovado executa. Não é
# novidade teórica — é exatamente a conclusão de A5.3.1, que por isso tirou a
# corrida do caminho de execução em vez de tentar vencê-la.
#
# O que decide se isso é BRECHA ou FRONTEIRA é uma pergunta de alcançabilidade
# que os 22 testes de A5.5 não faziam: o atacante do modelo — o repositório,
# agindo pelo processo do filtro — consegue escrever no armazém? MEDIDO em
# `test_20b`, com controle positivo: NÃO. Só um processo de mesmo uid FORA do
# sandbox consegue, e esse é o lado confiável, onde o dono da máquina já pode
# trocar o próprio NOMOS.
#
# Por isso o bloco virou três testes que afirmam o que é verdade e provável:
#   20a  o atacante DO MODELO (a origem externa) nunca executa       — canário
#   20b  o filtro confinado não alcança o armazém                    — a razão
#   20c  artefato divergente é DETECTADO, com corrida real           — não vácuo

def test_20a_origem_mutando_nunca_executa_codigo_nao_aprovado(armazem,
                                                              tmp_path):
    """A propriedade de A5.3: o SOURCE externo nunca executa após a aprovação.

    Este é o atacante do modelo. Ele controla a origem — pode reescrevê-la,
    apagá-la, trocá-la por symlink para hostil — e não controla o armazém. Aqui
    a corrida é CONTÍNUA de propósito: é ela que dá sentido ao canário ausente.
    """
    origem = _script(tmp_path / "f.sh", BOM)
    art = armazem.importar(origem)
    canario = tmp_path / "CANARIO"
    pol = fg.PoliticaDeFiltro(filter_id="redator",
                              canonical_executable=str(origem),
                              managed_artifact=art)

    # CONTROLE POSITIVO: o hostil produz efeito quando executado.
    hostil = _script(tmp_path / "h.sh", HOSTIL)
    assert _rodar(hostil, canario).stdout.strip() == "SAIDA_HOSTIL"
    assert canario.exists(), "canário não funciona; o teste seria vácuo"
    canario.unlink()

    parar = threading.Event()
    voltas = {"n": 0}

    def tamper():
        while not parar.is_set():
            try:
                origem.chmod(0o700)
                origem.write_text(HOSTIL)
                origem.chmod(0o755)
            except OSError:
                pass
            voltas["n"] += 1

    t = threading.Thread(target=tamper, daemon=True)
    t.start()
    try:
        for _ in range(30):
            saida = _rodar(pol.executavel(), canario).stdout.strip()
            assert saida == "SAIDA_BOA", (
                f"EXECUTOU_A_ORIGEM: saída {saida!r} — o artefato deveria ser "
                "imune ao que acontece com o source depois da aprovação")
    finally:
        parar.set()
        t.join(timeout=20)

    assert voltas["n"] > 0, "o tamper não rodou; o teste seria vácuo"
    assert not canario.exists(), (
        "UNAPPROVED_CODE_EXECUTED: o hostil da ORIGEM produziu efeito")
    art.conferir()                        # o artefato seguiu íntegro


@pytest.mark.git_governado
def test_20b_filtro_confinado_NAO_alcanca_o_armazem(armazem, tmp_path):
    """A razão pela qual `test_20c` é fronteira e não brecha.

    Se o processo do filtro alcançasse o armazém, o TOCTOU de `test_20c` seria
    alcançável PELO REPOSITÓRIO e A5.3 estaria furado. Ele não alcança — e isto
    é medido com controle positivo em cada alvo, porque "não escreveu" só prova
    bloqueio depois de provado que a escrita aconteceria.
    """
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    escopo = tmp_path / "escopo"
    escopo.mkdir()
    pol = fg.PoliticaDeFiltro(filter_id="redator",
                              canonical_executable=str(tmp_path / "f.sh"),
                              managed_artifact=art,
                              read_roots=(str(escopo),),
                              write_roots=(str(escopo),))
    conf = pol.confinamento()

    dentro = tuple(conf.escrita)
    assert dentro == (str(escopo),), (
        f"write_roots do filtro = {dentro} — o armazém não pode entrar aqui")

    # A prova estrutural acima é sobre a POLÍTICA. Esta é sobre o PERFIL que
    # chega ao sandbox: o armazém não aparece em nenhuma regra de escrita.
    texto = supervisor.perfil(conf)
    raiz = str(Path(armazem.raiz))
    for linha in texto.splitlines():
        if "write" in linha and raiz in linha:
            raise AssertionError(
                f"o perfil concede escrita no armazém: {linha.strip()!r}")

    # E esta é sobre o ARTEFATO: ele é 0500, não gravável nem pelo dono.
    modo = os.stat(art.managed_path).st_mode & 0o777
    assert modo == 0o500, f"artefato publicado com modo {modo:o}, esperado 500"


def test_20c_artefato_divergente_e_DETECTADO_com_corrida_real(armazem,
                                                              tmp_path):
    """FRONTEIRA declarada: quem escreve no armazém é o lado CONFIÁVEL.

    O que se pode exigir de `conferir()` é que ele DETECTE a divergência quando
    ela existe. É isso que se mede aqui, com corrida contínua — e por isso sem
    vácuo, ao contrário da versão que exigia a mesma coisa de um tamper que
    terminava antes de a corrida começar.

    O que NÃO se afirma aqui: que o hostil nunca execute. Sob um escritor de
    mesmo uid no armazém ele executa (2..10 de 60, medido), e nenhum hash fecha
    essa janela — A5.3.1 já havia concluído isso. Afirmar o contrário seria
    fazer o teste prometer o que o sistema não entrega; a contenção real desse
    atacante é `test_20b`, não este.
    """
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    caminho = Path(art.managed_path)
    pol = fg.PoliticaDeFiltro(filter_id="redator",
                              canonical_executable=str(tmp_path / "f.sh"),
                              managed_artifact=art)

    parar = threading.Event()
    voltas = {"n": 0}

    def tamper():
        while not parar.is_set():
            try:
                caminho.chmod(0o700)
                caminho.write_text(HOSTIL)
                caminho.chmod(0o500)
            except OSError:
                pass
            voltas["n"] += 1

    t = threading.Thread(target=tamper, daemon=True)
    t.start()
    detectou = 0
    try:
        for _ in range(40):
            try:
                pol.executavel()
            except ErroFiltro:
                detectou += 1             # divergência vista = desfecho correto
    finally:
        parar.set()
        t.join(timeout=20)

    assert voltas["n"] > 0, "o tamper não rodou; o teste seria vácuo"
    assert detectou > 0, (
        f"conferir() não viu divergência nenhuma em 40 tentativas com "
        f"{voltas['n']} reescritas — ou o tamper não estava acontecendo, ou a "
        "verificação de integridade parou de verificar")

# ═══════════ 21-22 — idempotência e resíduo após crash ══════════════════════

def test_21_import_duplicado_e_idempotente(armazem, tmp_path):
    origem = _script(tmp_path / "f.sh", BOM)
    a = armazem.importar(origem)
    for _ in range(5):
        b = armazem.importar(origem)
        assert (b.artifact_id, b.managed_path, b.sha256) == (
            a.artifact_id, a.managed_path, a.sha256)
    assert len(_artefatos(armazem)) == 1


def test_22_temporario_abandonado_nao_e_confundido_com_artefato(armazem,
                                                                tmp_path):
    """Simula crash: temporário órfão no armazém.

    Ele não pode ser resolvido como artefato — o nome não é o digest, e a
    integridade é verificada pelo NOME (endereçamento por conteúdo).
    """
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    orfao = Path(art.managed_path).parent / ".importando-orfao"
    orfao.write_text(HOSTIL)
    try:
        assert orfao not in _artefatos(armazem), (
            "temporário órfão contado como artefato publicado")
        _integros(armazem)
        art.conferir()
    finally:
        orfao.unlink(missing_ok=True)


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
