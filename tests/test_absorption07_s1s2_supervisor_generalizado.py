"""S1+S2 — o supervisor deixa de ser wrapper de Git e vira fronteira de execução.

O supervisor nasceu para o Git e virou a fronteira ÚNICA por onde processo
externo executa. Duas coisas ficaram com a forma antiga, e ambas foram MEDIDAS
como bloqueio de A5.6 antes de qualquer linha ser escrita:

    ACHADO 1  `executar()` não tinha parâmetro de entrada e fixava
              `stdin=DEVNULL`. Um `filter.clean` do Git RECEBE o conteúdo por
              STDIN e devolve por STDOUT — é a interface, não uma conveniência.
              Sem stdin, um filtro governado não funciona por mais aprovado
              (A5.2), íntegro (A5.3), com argv fixo (A5.4) e confinado (A5.5)
              que esteja.

    ACHADO 2  `conferir_ambiente` exigia as 4 variáveis de neutralização do Git
              de TODO processo supervisionado. Correto quando supervisor = Git;
              errado para um filtro, que não é Git e cujo ambiente mínimo é
              {LANG, LC_ALL}. Colidia de frente com o ENV_BOUNDARY de A5.5.

As duas saídas fáceis eram erradas e foram recusadas: pôr variável de Git no
ambiente do filtro polui o mínimo com autoridade alheia; afrouxar o guard
enfraquece a neutralização que protege TODAS as capacidades Git congeladas
(C1/C2a/C2b/C2c). A exigência virou POR TIPO DE PROCESSO.

## O que este arquivo prova

    S1  GIT_ENV_GUARD_UNCHANGED   a regra do Git não mudou, nem em conteúdo
                                  nem em efeito
        FILTER_ENV_MINIMUM        o filtro passa com o mínimo dele
        NO_TYPE_HEURISTIC         o tipo é enum explícito, nunca deduzido
        DEFAULT_FAILS_CLOSED      esquecer o tipo RECUSA, nunca concede

    S2  SUPERVISED_STDIN          bytes entram exatos, e saem transformados
        STDIN_BINARY_SAFETY       NUL, alto-bit, CRLF, sem reencode
        STDIN_TIMEOUT             prazo continua mandando mesmo com stdin
        PROCESS_TREE_KILL         a pós-condição de resíduo não regrediu
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import pytest

from nomos.adapters import filtro_governado as fg
from nomos.adapters import git as mod_git
from nomos.adapters import supervisor
from nomos.adapters.supervisor import TipoDeProcesso as TP

GIT = "/usr/bin/git"
FONTE_NATIVA = Path(__file__).parent / "fixtures_nativas" / "redator.c"

pytestmark = pytest.mark.skipif(
    not os.path.exists(supervisor.SANDBOX),
    reason="sem sandbox-exec não há execução supervisionada neste host")


def _conf(*escrita: str, leitura: tuple[str, ...] = ()) -> supervisor.Confinamento:
    return supervisor.Confinamento(escrita=tuple(escrita),
                                   declara_sem_escrita=not escrita,
                                   leitura=leitura)


# ════════════════════════════ S1 — tipo de processo ══════════════════════════

def test_s1_01_tipo_e_enum_com_exatamente_os_tipos_previstos():
    assert {t.value for t in TP} == {"git", "filtro-governado"}


def test_s1_02_git_env_guard_INALTERADO_em_conteudo():
    """As 4 neutralizações continuam exatamente as mesmas, com os mesmos valores.

    Este teste existe para que um afrouxamento tenha de ser DELIBERADO: mexer
    aqui é mexer na proteção de C1/C2a/C2b/C2c inteiras.
    """
    assert supervisor.EXIGIDAS_NO_AMBIENTE == {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    assert supervisor.EXIGIDAS_POR_TIPO[TP.GIT] is supervisor.EXIGIDAS_NO_AMBIENTE


def test_s1_03_ambiente_real_dos_adapters_passa_com_e_sem_tipo():
    """Chamada POSICIONAL antiga e chamada tipada dão o mesmo resultado."""
    env = mod_git.ambiente_minimo()
    supervisor.conferir_ambiente(env)                 # como sempre foi
    supervisor.conferir_ambiente(env, TP.GIT)         # explícito


@pytest.mark.parametrize("chave", list(supervisor.EXIGIDAS_NO_AMBIENTE))
def test_s1_04_git_sem_neutralizacao_continua_recusado(chave):
    env = dict(mod_git.ambiente_minimo())
    del env[chave]
    with pytest.raises(supervisor.ErroSeguranca, match="obrigatória ausente"):
        supervisor.conferir_ambiente(env, TP.GIT)


@pytest.mark.parametrize("tipo", list(TP))
@pytest.mark.parametrize("chave,valor", [
    ("HOME", "/tmp/h"), ("DYLD_INSERT_LIBRARIES", "/tmp/l.dylib"),
    ("LD_PRELOAD", "/tmp/l.so"), ("XDG_CONFIG_HOME", "/tmp/x"),
])
def test_s1_05_proibicao_universal_vale_para_TODO_tipo(tipo, chave, valor):
    """`HOME` e `DYLD_*` concedem autoridade a qualquer processo, não só ao Git.

    Se a tipagem tivesse transformado proibição em coisa "do tipo Git", o filtro
    passaria a herdar HOME — e HOME é `~/.ssh` pelo caminho mais curto.
    """
    env = dict(supervisor.EXIGIDAS_POR_TIPO[tipo])
    env[chave] = valor
    with pytest.raises(supervisor.ErroSeguranca):
        supervisor.conferir_ambiente(env, tipo)


def test_s1_06_filtro_passa_com_o_minimo_dele():
    pol = _politica_minima()
    supervisor.conferir_ambiente(pol.ambiente(), TP.FILTRO_GOVERNADO)


def test_s1_07_filtro_NAO_precisa_e_NAO_aceita_variavel_de_git():
    """As duas direções da fronteira de tipo, no mesmo teste.

    O filtro não é Git: não deve ser obrigado a carregar a neutralização de Git
    (senão o ambiente mínimo de A5.5 seria impossível), e não deve poder
    carregá-la (senão a fronteira de tipo seria decorativa).
    """
    minimo = {"LANG": "C", "LC_ALL": "C"}
    supervisor.conferir_ambiente(minimo, TP.FILTRO_GOVERNADO)   # não precisa

    com_git = dict(minimo, GIT_CONFIG_NOSYSTEM="1")
    with pytest.raises(supervisor.ErroSeguranca, match="OUTRO tipo"):
        supervisor.conferir_ambiente(com_git, TP.FILTRO_GOVERNADO)   # nem pode


def test_s1_08_default_falha_FECHADO_e_nao_aberto():
    """Esquecer de declarar o tipo tem de RECUSAR, nunca conceder.

    O default é GIT porque a exigência do Git é a mais ESTRITA: um filtro que
    esqueça o tipo cai numa regra que pede MAIS do que ele tem, e o erro sai
    como recusa. O contrário — default no tipo permissivo — daria a um processo
    Git um ambiente sem neutralização, em silêncio.
    """
    minimo_de_filtro = {"LANG": "C", "LC_ALL": "C"}
    with pytest.raises(supervisor.ErroSeguranca, match="obrigatória ausente"):
        supervisor.conferir_ambiente(minimo_de_filtro)       # sem tipo => GIT


def test_s1_09_tipo_precisa_ser_enum_e_nao_string():
    """String de tipo abriria a porta para tipo vindo de fora, como dado."""
    with pytest.raises(supervisor.ErroSeguranca, match="não é TipoDeProcesso"):
        supervisor.conferir_ambiente(mod_git.ambiente_minimo(), "git")


def test_s1_10_NENHUMA_heuristica_de_string_decide_o_tipo():
    """O tipo é declarado pelo chamador. Nada no supervisor adivinha.

    Uma heurística tipo `"git" in argv[0]` seria a regressão exata que esta fase
    existe para impedir: adivinhação erra do lado de conceder, e o nome do
    binário é escolhido por quem monta o comando.
    """
    fonte = Path(supervisor.__file__).read_text()
    corpo = fonte[fonte.index("def conferir_ambiente"):]
    corpo = corpo[:corpo.index("\ndef ", 10)]
    for suspeito in ('"git" in', "'git' in", ".startswith(\"git",
                     ".endswith(\"git", "basename"):
        assert suspeito not in corpo, (
            f"conferir_ambiente decide tipo por heurística de string "
            f"({suspeito!r}) — o tipo tem de ser declarado, não adivinhado")


def test_s1_11_executar_repassa_o_tipo_ao_guard(tmp_path):
    """O tipo não pode ficar só na assinatura: tem de CHEGAR na conferência."""
    with pytest.raises(supervisor.ErroSeguranca, match="obrigatória ausente"):
        supervisor.executar([GIT, "--version"], cwd=tmp_path,
                            env={"LANG": "C", "LC_ALL": "C"}, prazo=10,
                            confinamento=_conf(str(tmp_path)),
                            tipo=TP.GIT)


# ═══════════════════════════ S2 — stdin supervisionado ═══════════════════════
#
# O consumidor de stdin é `git hash-object --stdin`: ele lê stdin ATÉ O FIM e
# imprime o sha1 do blob. Isso dá uma verificação de entrega EXATA — o hash
# depende de cada byte —, e usa o caminho Git que já está congelado, sem
# precisar de binário novo só para o teste.

def _sha_blob(dados: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(dados) + dados).hexdigest()


@pytest.fixture
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    subprocess.run([GIT, "-C", str(d), "init", "-q", "-b", "main"],
                   check=True, capture_output=True)
    return d


def _hash_object(repo: Path, dados: bytes | None, prazo: float = 30):
    return supervisor.executar(
        [GIT, "-C", str(repo), "hash-object", "--stdin"],
        cwd=repo, env=mod_git.ambiente_minimo(), prazo=prazo,
        confinamento=_conf(str(repo)), tipo=TP.GIT, entrada=dados)


def test_s2_01_sem_entrada_o_stdin_continua_DEVNULL(repo):
    """O comportamento histórico, byte a byte: EOF imediato, blob vazio.

    Nenhum caller do Git passa `entrada`, e nenhum deles pode mudar de
    semântica por causa desta fase.
    """
    p = _hash_object(repo, None)
    assert p.returncode == 0, p.stderr
    assert p.stdout.decode().strip() == _sha_blob(b"")


def test_s2_02_entrada_chega_EXATA(repo):
    dados = b"SENHA=hunter2\noutra linha\n"
    p = _hash_object(repo, dados)
    assert p.returncode == 0, p.stderr
    assert p.stdout.decode().strip() == _sha_blob(dados)


def test_s2_03_entrada_VAZIA_e_suportada_e_NAO_e_o_mesmo_que_None(repo):
    """`b""` vai por PIPE e fecha; `None` nem abre pipe.

    O resultado observável coincide (EOF imediato), e a distinção importa: um
    clean filter recebe um pipe real, e um dia alguém vai querer distinguir
    "não havia entrada" de "a entrada era vazia".
    """
    assert _hash_object(repo, b"").stdout.decode().strip() == _sha_blob(b"")
    assert _hash_object(repo, None).stdout.decode().strip() == _sha_blob(b"")


@pytest.mark.parametrize("dados,rotulo", [
    (b"\x00\x01\x02\x00\xff\xfe", "NUL e alto-bit"),
    (b"linha\r\nCRLF\r\n", "CRLF nao reescrito"),
    (b"\xc3\xa1\xc3\xa9 utf8 cru", "utf8 sem decode"),
    (b"\xff\xfe\x00\x00sem BOM implicito", "BOM nao interpretado"),
    (bytes(range(256)), "todos os 256 bytes"),
])
def test_s2_04_BINARY_SAFE_sem_reencode_e_sem_reescrita_de_newline(
        repo, dados, rotulo):
    p = _hash_object(repo, dados)
    assert p.returncode == 0, p.stderr
    assert p.stdout.decode().strip() == _sha_blob(dados), rotulo


def test_s2_05_entrada_GRANDE_passa_do_buffer_do_pipe(repo):
    """4 MiB > 64 KiB do buffer: sem a thread de alimentação isto travaria.

    Escrita inline bloquearia ANTES do `proc.wait(timeout=prazo)`, e o prazo
    deixaria de existir exatamente no caso em que ele é mais necessário.
    """
    dados = os.urandom(4 * 1024 * 1024)
    p = _hash_object(repo, dados)
    assert p.returncode == 0, p.stderr
    assert p.stdout.decode().strip() == _sha_blob(dados)


def test_s2_06_str_e_RECUSADO_sem_escolher_encoding(repo):
    with pytest.raises(supervisor.ErroSeguranca, match="não bytes"):
        _hash_object(repo, "texto")                     # type: ignore[arg-type]


def test_s2_07_processo_que_NAO_le_stdin_nao_trava_o_supervisor(repo):
    """`git --version` ignora stdin. Com 4 MiB pendurados, ainda assim termina.

    Sem a alimentação em thread, o supervisor ficaria preso escrevendo num pipe
    que ninguém drena — e o teste passaria a medir o timeout, não a entrega.
    """
    inicio = time.monotonic()
    p = supervisor.executar([GIT, "--version"], cwd=repo,
                            env=mod_git.ambiente_minimo(), prazo=30,
                            confinamento=_conf(str(repo)), tipo=TP.GIT,
                            entrada=os.urandom(4 * 1024 * 1024))
    assert p.returncode == 0, p.stderr
    assert not p.morto_por_timeout
    assert time.monotonic() - inicio < 25, "ficou preso na escrita de stdin"


def test_s2_08_stdout_e_stderr_NUNCA_se_misturam(repo):
    """Para um clean filter, stdout É o conteúdo transformado.

    Um byte de diagnóstico que vaze para stdout corrompe o arquivo indexado —
    e corromper em silêncio é pior que falhar.
    """
    p = supervisor.executar([GIT, "-C", str(repo), "hash-object", "--stdin",
                             "--", "--path=x"],
                            cwd=repo, env=mod_git.ambiente_minimo(), prazo=30,
                            confinamento=_conf(str(repo)), tipo=TP.GIT,
                            entrada=b"conteudo\n")
    assert b"fatal" not in p.stdout and b"error" not in p.stdout
    assert p.stdout == b"" or p.stdout.decode().strip().isalnum()


def test_s2_09_prazo_esgotado_MATA_mesmo_com_stdin_pendurado(politica_nativa,
                                                             tmp_path):
    """O prazo continua sendo quem manda, e a árvore morre.

    A sonda é NATIVA (`--sonda-dorme`), e não um shell script, pelo mesmo motivo
    que o filtro é nativo: `/bin/sh` exigiria o interpretador na allowlist, que
    é o que A5.5 fechou. A primeira versão deste teste usava script e morria com
    "Failed to exec /bin/bash as variant for /bin/sh" — desfecho que passaria
    por "não deu timeout" se ninguém olhasse o stderr.

    Ele lê stdin INTEIRO antes de dormir, então quando o prazo estoura a
    alimentação já terminou: o que se mede é o prazo, não a escrita.
    """
    pol = politica_nativa("--sonda-dorme", "30")
    inicio = time.monotonic()
    p = supervisor.executar(pol.comando(),
                            cwd=tmp_path, env=pol.ambiente(), prazo=2.0,
                            confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO, entrada=b"x" * 4096)
    decorrido = time.monotonic() - inicio
    assert p.morto_por_timeout, f"o prazo não matou o processo: {p.stderr[:300]}"
    assert p.classificacao == "KILLED_BY_TIMEOUT"
    assert b"LI_TUDO" in p.stdout, "a sonda nem chegou a ler o stdin"
    assert b"ACORDEI" not in p.stdout, "o processo sobreviveu ao prazo"
    assert decorrido < 20, f"demorou {decorrido:.1f}s para matar"
    assert not p.grupo_resistiu
    assert p.residuais_mortos == 0


# ═════════════════ S2 aplicado ao filtro governado (ponte para A5.7) ═════════

def _politica_minima() -> fg.PoliticaDeFiltro:
    return fg.PoliticaDeFiltro(filter_id="redator", canonical_executable=GIT,
                               managed_artifact=None)


@pytest.fixture
def politica_nativa(tmp_path):
    """Fábrica de políticas sobre o MESMO artefato nativo, com argv governado.

    Devolve uma fábrica, e não uma política pronta, porque o argv é parte da
    POLÍTICA (A5.4): quem quer uma sonda diferente declara outra política, não
    acrescenta argumento na hora da chamada. Um teste que fizesse
    `[*pol.comando(), "--sonda"]` estaria ensinando exatamente o padrão que A5.4
    proíbe — o chamador contribuindo com elemento do argv.
    """
    binario = tmp_path / "redator"
    r = subprocess.run(["cc", "-O2", "-o", str(binario), str(FONTE_NATIVA)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"sem toolchain C neste host: {r.stderr[:200]}")
    art = fg.ArmazemDeExecutaveis(tmp_path / "store").importar(binario)
    escopo = tmp_path / "escopo"
    escopo.mkdir()

    def fabrica(*argv: str) -> fg.PoliticaDeFiltro:
        return fg.PoliticaDeFiltro(filter_id="redator",
                                   canonical_executable=str(binario),
                                   managed_artifact=art,
                                   argv_policy=tuple(argv),
                                   read_roots=(str(escopo),),
                                   write_roots=(str(escopo),))
    return fabrica


@pytest.fixture
def filtro_nativo(politica_nativa):
    """A política do redator em modo normal: sem argumento, só stdin->stdout."""
    return politica_nativa()


def test_s2_10_o_filtro_governado_REDIGE_pelo_supervisor(filtro_nativo, tmp_path):
    """O achado que bloqueava A5.6, agora medido como resolvido.

    Este é o caminho inteiro e legítimo: política do NOMOS -> artefato
    gerenciado -> argv fixo -> confinamento de A5.5 -> ambiente mínimo do TIPO
    do filtro -> stdin supervisionado -> stdout transformado. Nenhum
    `subprocess` paralelo; nenhuma variável de Git no ambiente do filtro.
    """
    pol = filtro_nativo
    p = supervisor.executar(pol.comando(), cwd=tmp_path, env=pol.ambiente(),
                            prazo=pol.timeout, confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO,
                            entrada=b"SENHA=hunter2\nresto intacto\n")
    assert p.returncode == 0, p.stderr
    assert p.stdout == b"SENHA=REDIGIDO\nresto intacto\n"
    assert b"hunter2" not in p.stdout, "o segredo sobreviveu ao redator"


def test_s2_11_o_filtro_pelo_supervisor_SEM_stdin_nao_produz_nada(
        filtro_nativo, tmp_path):
    """O controle negativo do teste anterior — e o achado original, em teste.

    Com `entrada=None` o redator recebe EOF na hora e devolve vazio. É
    EXATAMENTE por isso que um clean filter era impossível antes desta fase:
    verde aqui sem `entrada` significaria que o teste anterior não mede nada.
    """
    pol = filtro_nativo
    p = supervisor.executar(pol.comando(), cwd=tmp_path, env=pol.ambiente(),
                            prazo=pol.timeout, confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO, entrada=None)
    assert p.returncode == 0, p.stderr
    assert p.stdout == b""


def test_s2_12_ambiente_do_filtro_nao_carrega_nada_de_git(filtro_nativo):
    amb = filtro_nativo.ambiente()
    assert set(amb) == {"LANG", "LC_ALL"}
    assert not [k for k in amb if k.startswith("GIT_")]


def test_s2_13_resto_do_conteudo_passa_INTACTO_byte_a_byte(filtro_nativo,
                                                           tmp_path):
    """Um filtro que corrompe o que não devia tocar é pior que filtro ausente."""
    pol = filtro_nativo
    entrada = b"alpha\nbeta\xc3\xa1\nSENHA=x\ngamma\n"
    p = supervisor.executar(pol.comando(), cwd=tmp_path, env=pol.ambiente(),
                            prazo=pol.timeout, confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO, entrada=entrada)
    assert p.returncode == 0, p.stderr
    assert p.stdout == b"alpha\nbeta\xc3\xa1\nSENHA=REDIGIDO\ngamma\n"


def test_s2_14_o_filtro_roda_SOB_sandbox_e_nao_solto(filtro_nativo, tmp_path):
    pol = filtro_nativo
    p = supervisor.executar(pol.comando(), cwd=tmp_path, env=pol.ambiente(),
                            prazo=pol.timeout, confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO, entrada=b"x\n")
    assert p.sandbox_aplicado
    assert p.argv_efetivo[0] == supervisor.SANDBOX
    assert p.argv_efetivo[-1] == pol.managed_artifact.managed_path


def test_s2_15_sem_residuo_apos_o_filtro(filtro_nativo, tmp_path):
    pol = filtro_nativo
    p = supervisor.executar(pol.comando(), cwd=tmp_path, env=pol.ambiente(),
                            prazo=pol.timeout, confinamento=pol.confinamento(),
                            tipo=TP.FILTRO_GOVERNADO, entrada=b"SENHA=a\n")
    assert not p.grupo_resistiu
    assert p.residuais_mortos == 0, "o filtro deixou descendente vivo"


def test_s2_16_estrutural_o_supervisor_e_o_unico_com_PIPE_de_stdin():
    """Alimentar stdin por fora do supervisor perderia timeout, kill de árvore,
    perfil de sandbox, auditoria e pós-condição de resíduo — de uma vez."""
    raiz = Path(supervisor.__file__).parent
    ofensores = [p.name for p in raiz.glob("*.py")
                 if p.name not in ("supervisor.py", "script.py")
                 and "stdin=subprocess.PIPE" in p.read_text()]
    assert ofensores == [], (
        f"estes adapters abrem stdin por conta própria: {ofensores}")


def test_s2_17_alimentar_fecha_o_pipe_sempre():
    """Sem `close()` não há EOF, e um clean filter espera para sempre.

    O prazo estouraria e o desfecho seria KILLED_BY_TIMEOUT — falha que parece
    lentidão do filtro e não esquecimento do supervisor.
    """
    fonte = Path(supervisor.__file__).read_text()
    corpo = fonte[fonte.index("def _alimentar"):]
    corpo = corpo[:corpo.index("\ndef ", 10)]
    assert "finally:" in corpo and ".close()" in corpo
