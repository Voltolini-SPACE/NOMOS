"""C2c — pós-condição: a capability não deixa processo vivo para trás.

O gate anterior provou `ORIGINAL_PROCESS_GROUP_DEAD`. Não é a mesma coisa que
`ZERO descendentes vivos`, e a diferença foi medida: um `filter.clean` que faz
`setsid()` — ou só `setpgid(0, 0)` — sai do grupo e sobrevive a um `git add`
BEM-SUCEDIDO. O supervisor não percebia, porque `killpg` num grupo vazio
devolve `ProcessLookupError`, que era lido como "nada sobreviveu". Grupo vazio
é a assinatura do escape.

Quatro armadilhas tiveram de ser resolvidas para estes testes valerem alguma
coisa; todas produziram PASS falso antes:

1. **marcador fora do repo** — o sandbox nega a escrita de qualquer jeito, e a
   ausência do marcador prova negação de filesystem, não morte do processo;
2. **descendente que segura o stdio** — o `git` espera EOF do filtro, o
   descendente termina DENTRO da operação e nunca chega a sobreviver a ela;
3. **`git add` de arquivo já indexado e inalterado NÃO chama o `filter.clean`** —
   mede-se um no-op e conclui-se que nada sobreviveu;
4. **descendente em Python morto durante o startup do interpretador**, antes de
   chegar ao `setsid()` — o filtro precisa esperar o regime permanente.

Por isso o controle positivo do PASSO 3 não é opcional: sem provar que a
fixture CONSEGUE sobreviver quando a defesa está desligada, nenhum PASS aqui
significa alguma coisa.
"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from nomos.adapters import git_tree, processos, supervisor
from nomos.adapters.contrato import CapabilityRequest, ErroInvalido

GIT = "/usr/bin/git"
pytestmark = pytest.mark.skipif(
    not (Path(supervisor.SANDBOX).exists() and Path(GIT).exists()
         and processos.DISPONIVEL),
    reason="sandbox-exec / git / libproc ausentes (fora do macOS)")

# Cada modo é uma forma diferente de escapar (ou não) do process group.
# `setpgid` está aqui por causa do censo adversarial: uma defesa validada só
# contra `setsid` passaria e continuaria furada — `setpgid(0,0)` troca de grupo
# mantendo a sessão, e `killpg` também não o alcança.
MODOS = ["filho", "neto", "setsid", "setpgid", "setsid_neto",
         "doublefork", "ignora_term", "setsid_ignora_term"]
# Os que REALMENTE escapam do grupo original — medido, não suposto.
ESCAPAM = {"setsid", "setpgid", "setsid_neto", "setsid_ignora_term"}

_HELPER = '''\
import os, signal, sys, time
modo, marca = sys.argv[1], sys.argv[2]
if modo in ("setsid", "setsid_neto", "setsid_ignora_term"):
    if os.fork(): os._exit(0)
    os.setsid()
elif modo == "setpgid":
    if os.fork(): os._exit(0)
    os.setpgid(0, 0)
elif modo == "doublefork":
    if os.fork(): os._exit(0)
    if os.fork(): os._exit(0)
elif modo == "neto":
    if os.fork(): os._exit(0)
if modo in ("ignora_term", "setsid_ignora_term"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
if modo == "setsid_neto":
    if os.fork(): os._exit(0)
# stdio destacado: sem isso o git espera EOF do filtro e o descendente morre
# dentro da propria operacao, em vez de sobreviver a ela.
d = os.open(os.devnull, os.O_RDWR)
os.dup2(d, 0); os.dup2(d, 1); os.dup2(d, 2)
while True:
    with open(marca, "w") as fh:
        fh.write(str(os.getpid()))
    time.sleep(0.05)
'''


@pytest.fixture()
def repo_hostil(tmp_path):
    """Repositório cujo `filter.clean` gera as 8 categorias de descendente.

    Os marcadores ficam DENTRO do repo, onde a escrita é permitida pelo
    sandbox: assim a ausência do marcador prova morte do processo, e não
    negação de filesystem.
    """
    r = tmp_path / "hostil"
    (r / "marks").mkdir(parents=True)
    (r / "hostil.py").write_text(_HELPER)

    linhas = "\n".join(
        f'/usr/bin/python3 {r}/hostil.py {m} {r}/marks/{m}.mark >/dev/null 2>&1 &'
        for m in MODOS)
    espera = " ".join(f'"{r}/marks/{m}.mark"' for m in MODOS)
    (r / "filtro.sh").write_text(textwrap.dedent(f"""\
        #!/bin/sh
        echo RODOU > {r}/CANARIO
        {linhas}
        # Esperar o REGIME PERMANENTE. Sem isto os descendentes em Python
        # morrem durante o startup do interpretador, antes de chegarem ao
        # setsid(), e a medicao diz que nada escapa.
        i=0
        while [ $i -lt 60 ]; do
            faltam=0
            for f in {espera}; do [ -f "$f" ] || faltam=1; done
            [ $faltam -eq 0 ] && break
            sleep 0.1
            i=$((i+1))
        done
        cat
    """))
    (r / "filtro.sh").chmod(0o755)

    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run([GIT, "-C", str(r), "init", "-q", "-b", "main"], check=True,
                   env=env, capture_output=True)
    subprocess.run([GIT, "-C", str(r), "config", "filter.hostil.clean",
                    str(r / "filtro.sh")], check=True, env=env,
                   capture_output=True)
    (r / ".gitattributes").write_text("*.dat filter=hostil\n")
    yield r
    _faxina(r)


def _faxina(repo: Path) -> None:
    """Mata o que sobrou, pelo PID EXATO que cada helper gravou no marcador.

    Nunca por nome nem `pkill`: matar processo alheio do host seria pior que o
    defeito sob teste.
    """
    for marca in (repo / "marks").glob("*.mark"):
        with contextlib.suppress(OSError, ValueError):
            os.kill(int(marca.read_text().strip()), signal.SIGKILL)


def _registro(tmp_path):
    from nomos.adapters.wiring import registrar_git_tree
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades
    reg = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                              approver=lambda *a, **k: True)
    registrar_git_tree(reg, raizes=(str(tmp_path),))
    return reg


def _ctx(reg, cap, raiz):
    from nomos.adapters.contrato import CapabilityContext
    return CapabilityContext.de_registro(reg, cap, "runtime-governado",
                                         raizes=(str(raiz),))


def _add(repo, tmp_path, conteudo):
    """`git add` pelo adapter REAL. O conteúdo MUDA a cada chamada: arquivo já
    indexado e inalterado não invoca o `filter.clean`, e a medição viraria um
    no-op silencioso."""
    (repo / "dados.dat").write_text(conteudo)
    reg = _registro(tmp_path)
    ad = git_tree.GitTreeAdapter()
    with contextlib.suppress(Exception):
        ad.executar(CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                      argumentos={"caminhos": ["dados.dat"]}),
                    _ctx(reg, "git-add", tmp_path))


def _reaparecem(repo: Path, espera: float = 1.2) -> set[str]:
    """Apaga os marcadores e devolve os que VOLTAM a ser escritos.

    "O marcador existe?" não serve: ele pode ser legítimo do período em que a
    operação ainda corria. O que denuncia sobrevivência é escrita DEPOIS do
    retorno.
    """
    for m in (repo / "marks").glob("*.mark"):
        m.unlink(missing_ok=True)
    time.sleep(espera)
    return {m.stem for m in (repo / "marks").glob("*.mark")}


# ════════════════ PASSO 3 — CONTROLE POSITIVO (sem ele nada vale) ═══════════

def test_controle_positivo_sem_defesa_os_destacados_sobrevivem(
        repo_hostil, tmp_path, monkeypatch):
    """Prova que a fixture CONSEGUE sobreviver quando a defesa está desligada.

    Sem este teste, todos os outros seriam vácuo: provariam que processos que
    nunca existiram não sobrevivem.
    """
    monkeypatch.setattr(processos, "exterminar", lambda *a, **k: ([], []))
    _add(repo_hostil, tmp_path, "controle-positivo\n")
    assert (repo_hostil / "CANARIO").exists(), "o filter.clean não executou"

    vivos = _reaparecem(repo_hostil)
    assert vivos, ("nenhum descendente sobreviveu nem com a defesa desligada — "
                   "a fixture não prova nada")
    # O escape é por troca de process group, e `setpgid` conta tanto quanto
    # `setsid`. Uma defesa validada só contra `setsid` passaria furada.
    assert vivos & ESCAPAM, f"os sobreviventes não são os que escapam: {vivos}"
    assert "setpgid" in vivos, (
        "setpgid(0,0) deixou de escapar — se o kernel mudou, o censo precisa "
        "ser refeito antes de confiar na defesa")


def test_controle_positivo_killpg_sozinho_nao_ve_o_escape(repo_hostil, tmp_path,
                                                          monkeypatch):
    """`_matar_arvore` devolve `False` (= nada sobreviveu) justo quando o
    escape funcionou: grupo vazio é a ASSINATURA do escape."""
    vistos = []
    real = supervisor._matar_arvore
    monkeypatch.setattr(supervisor, "_matar_arvore",
                        lambda pgid: vistos.append(real(pgid)) or vistos[-1])
    monkeypatch.setattr(processos, "exterminar", lambda *a, **k: ([], []))
    _add(repo_hostil, tmp_path, "killpg-cego\n")
    assert vistos and vistos[0] is False, (
        "o caminho rápido reportou resistência; o cenário esperado é ele "
        "reportar sucesso enquanto processos escaparam")
    assert _reaparecem(repo_hostil), "sem escape, este teste não diz nada"


# ═══════════════════ PASSO 4 — A PÓS-CONDIÇÃO, COM A DEFESA ════════════════

def test_pos_condicao_zero_residuais_apos_sucesso(repo_hostil, tmp_path):
    """`CAPABILITY_RETURNED → ZERO descendentes vivos`, no caminho de SUCESSO.

    Observado mais de uma vez: uma janela só não distingue "morreu" de "ainda
    não voltou a escrever".
    """
    _add(repo_hostil, tmp_path, "com-defesa\n")
    assert (repo_hostil / "CANARIO").exists(), "o filter.clean não executou"
    for rodada in range(3):
        vivos = _reaparecem(repo_hostil)
        assert vivos == set(), f"resíduo vivo na observação {rodada}: {vivos}"


def test_pos_condicao_zero_residuais_apos_timeout(repo_hostil, tmp_path,
                                                  monkeypatch):
    """O mesmo no caminho de TIMEOUT, onde o filtro pendura o processo."""
    monkeypatch.setattr(git_tree, "TIMEOUT_S", 3.0)
    (repo_hostil / "filtro.sh").write_text(
        (repo_hostil / "filtro.sh").read_text().replace("cat\n", "cat\nsleep 300\n"))
    _add(repo_hostil, tmp_path, "timeout\n")
    for _ in range(2):
        assert _reaparecem(repo_hostil) == set()


def test_pos_condicao_apos_excecao_do_adapter(repo_hostil, tmp_path):
    """E no caminho de EXCEÇÃO: o `add` recusa por caminho inválido DEPOIS de
    o filtro já ter rodado numa chamada anterior."""
    _add(repo_hostil, tmp_path, "antes-da-excecao\n")
    reg = _registro(tmp_path)
    with pytest.raises(ErroInvalido):
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-add", alvo=str(repo_hostil),
                              argumentos={"caminhos": ["--upload-pack=x"]}),
            _ctx(reg, "git-add", tmp_path))
    assert _reaparecem(repo_hostil) == set()


# ═════════════════════════ PASSO 5 — FAIL-CLOSED ═══════════════════════════

def test_residual_que_nao_morre_recusa_a_operacao(repo_hostil, tmp_path,
                                                  monkeypatch):
    """Processo sobrevivente NUNCA vira PASS por a resposta ter sido negada.

    Aqui a extermínio "falha" (simulado) e a operação precisa terminar em
    recusa explícita, não em sucesso silencioso.
    """
    monkeypatch.setattr(processos, "exterminar",
                        lambda *a, **k: ([], [(999999, 1, 1)]))
    reg = _registro(tmp_path)
    (repo_hostil / "dados.dat").write_text("fail-closed\n")
    with pytest.raises(supervisor.ErroSeguranca, match="PROCESS_CONFINEMENT=FAIL"):
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-add", alvo=str(repo_hostil),
                              argumentos={"caminhos": ["dados.dat"]}),
            _ctx(reg, "git-add", tmp_path))


def test_sem_discriminante_nao_ha_execucao(tmp_path, monkeypatch):
    """Se `sandbox_check` não estiver funcionando, não há como PROVAR ausência
    de resíduo — logo não há execução."""
    import shutil
    monkeypatch.setattr(processos, "DISPONIVEL", False)
    m = supervisor.criar_marca()
    try:
        with pytest.raises(processos.ErroProcessos, match="indisponíveis"):
            m.conferir()
    finally:
        shutil.rmtree(m.execdir, ignore_errors=True)


def test_marca_com_caminho_ausente_e_recusada(tmp_path):
    """O modo de falha SILENCIOSO: com caminho inexistente o `sandbox_check`
    devolve resposta errada com `errno=0`, e todo processo do host passaria a
    casar a marca."""
    m = supervisor.criar_marca()
    try:
        os.unlink(m.permitido)
        with pytest.raises(processos.ErroProcessos, match="não existe"):
            m.conferir()
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)


# ═════════════ PASSO 6 — herança: autoridade × ciclo de vida ═══════════════

def test_marca_nao_casa_processo_alheio_do_host(tmp_path):
    """A varredura não pode alcançar processo não relacionado.

    O discriminante anterior (só "pode escrever no meu nonce") casava 6 pids do
    host, 5 alheios: daemons do sistema também são sandboxados e também
    escrevem em /private/tmp. O par CONTRADITÓRIO — permitido no diretório E
    negado no subdiretório — não é reproduzível por acidente.
    """
    m = supervisor.criar_marca()
    try:
        m.conferir()
        alheio = subprocess.Popen(["/bin/sleep", "30"])
        try:
            time.sleep(0.2)
            assert not m.pertence(alheio.pid)
            assert not m.pertence(os.getpid())
            assert m.pertence(alheio.pid) is False
            achados = processos.residuais(m)
            assert achados == [], f"varredura casou processo alheio: {achados}"
        finally:
            alheio.kill()
            alheio.wait()
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)


def test_confinamento_de_autoridade_sobrevive_ao_destacamento(repo_hostil,
                                                              tmp_path,
                                                              monkeypatch):
    """AUTHORITY_CONFINEMENT vale mesmo para quem escapou do ciclo de vida.

    Distingue as duas propriedades: o descendente destacado escapa do
    LIFETIME, não da AUTORIDADE. Enquanto vive, segue sem escrever fora e sem
    rede.
    """
    fora = tmp_path / "FORA.txt"
    fora.write_text("intacto")
    (repo_hostil / "filtro.sh").write_text(
        (repo_hostil / "filtro.sh").read_text().replace(
            "cat\n",
            f'/usr/bin/python3 -c "\n'
            f'import os,socket\n'
            f'if os.fork(): os._exit(0)\n'
            f'os.setsid()\n'
            f'open(\'{fora}\',\'w\').write(\'INVADIU\')\n'
            f'" >/dev/null 2>&1\ncat\n'))
    monkeypatch.setattr(processos, "exterminar", lambda *a, **k: ([], []))
    _add(repo_hostil, tmp_path, "autoridade\n")
    time.sleep(0.8)
    assert fora.read_text() == "intacto", (
        "descendente destacado escreveu FORA do repo — o escape seria de "
        "autoridade, não só de ciclo de vida")


# ═══════════════════════ identidade e reuso de PID ═════════════════════════

def test_digital_distingue_pid_reciclado():
    """PID é endereço, não identidade — reuso foi reproduzido neste host."""
    p = subprocess.Popen(["/bin/sleep", "30"])
    try:
        d = processos.digital(p.pid)
        assert d is not None and d[0] == p.pid
        assert processos._vivo(d) is True
        assert processos._vivo((p.pid, d[1] + 1, d[2])) is False
    finally:
        p.kill()
        p.wait()


def test_zumbi_nao_conta_como_vivo():
    """`os.kill(pid, 0)` passa para sempre num filho zumbi até o `waitpid` —
    verificação por sinal daria 'vivo' eternamente."""
    p = subprocess.Popen(["/bin/sleep", "0.05"])
    d = processos.digital(p.pid)
    time.sleep(0.4)                       # morreu, mas ainda não foi colhido
    os.kill(p.pid, 0)                     # não levanta: o zumbi ainda responde
    assert processos._vivo(d) is False, "zumbi contado como processo vivo"
    p.wait()


# ════════════ propriedades exigidas que a fixture hostil não provoca ════════

def test_extermínio_exige_duas_varreduras_limpas(monkeypatch):
    """"Não usar teste instantâneo" vale para o supervisor, não só para o teste.

    Uma única varredura limpa não distingue "acabou" de "ainda não apareceu":
    entre matar um resíduo e o filho que ele acabou de gerar ser listado pelo
    kernel há uma janela real, de microssegundos. Ela é curta demais para uma
    fixture provocar de forma determinística, então a propriedade é verificada
    onde ela é decidível — na contagem de observações.
    """
    varreduras = []
    monkeypatch.setattr(processos, "residuais",
                        lambda *a, **k: varreduras.append(1) or [])
    m = supervisor.criar_marca()
    try:
        mortos, sobrando = processos.exterminar(m)
        assert (mortos, sobrando) == ([], [])
        assert len(varreduras) >= 2, (
            f"declarou limpeza com {len(varreduras)} varredura(s) — uma só não "
            "distingue ausência de atraso")
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)


def test_discriminante_quebrado_recusa_antes_de_matar(monkeypatch):
    """Se o `sandbox_check` passar a responder errado, o NOMOS para.

    Os dois modos de falha silenciosa medidos (caminho inexistente, `argtypes`
    errado) fazem processo ALHEIO do host casar a marca. A auto-validação é o
    que separa "não sei" de "vou matar" — sem ela, um bug de plataforma vira
    kill em processo de terceiro.
    """
    m = supervisor.criar_marca()
    try:
        m.conferir()                                   # sadio: não levanta
        monkeypatch.setattr(processos, "_sandbox_check",
                            lambda pid, caminho: processos.NEGADO)
        with pytest.raises(processos.ErroProcessos, match="auto-validação"):
            m.conferir()
    finally:
        import shutil
        shutil.rmtree(m.execdir, ignore_errors=True)
