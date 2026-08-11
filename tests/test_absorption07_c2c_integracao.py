"""C2c — a contenção como propriedade do ADAPTER, não de um experimento.

A fase anterior mediu as primitivas isoladamente: sandbox contém filesystem,
`deny network*` corta rede, `killpg` mata neto órfão. Provar cada peça num
script solto não prova nada sobre o NOMOS — prova sobre o macOS.

Aqui a pergunta muda: quando uma capability Git AUTORIZADA executa pela cadeia
real (`REQUEST → PDP → adapter → supervisor → git`), ela roda contida?

O teste hostil do PASSO 8 é o que fecha: um repositório cujo `filter.clean`
tenta escapar por seis vias diferentes, exercitado por um `git add` legítimo.
Ele responde à pergunta que importa — não "o sandbox funciona?", mas "o código
que o repositório escolhe consegue alguma coisa?".
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from nomos.adapters import git as mod_git
from nomos.adapters import git_tree, supervisor

from nomos.adapters.contrato import ErroLimite

# Depois de A5 a CAPACIDADE só admite o Git. Estas sondas medem rede, timeout e
# árvore de processos usando sh/python3 — precisam declarar o próprio
# executável, senão medem a allowlist de exec em vez da fronteira alvo.
# `/bin/sh` re-executa `/bin/bash` neste host: os dois são necessários.
def _sonda_exec():
    """Binários das SONDAS, derivados em runtime.

    `/usr/bin/python3` é shim do xcrun igual ao git: delega para o Python de
    dentro do Xcode, e sem o caminho real a sonda morre com
    `can't exec .../usr/bin/python3 (errno=Operation not permitted)`.
    Mesmo landmine do `/bin/sh` que re-executa `/bin/bash`.
    """
    dev = os.path.realpath("/var/select/developer_dir")
    return ("/bin/sh", "/bin/bash", "/bin/sleep", "/bin/dd",
            "/usr/bin/python3", os.path.join(dev, "usr", "bin", "python3"))


_SONDA_EXEC = _sonda_exec()


def _com_sonda(conf):
    """Devolve o confinamento com exec AMPLO (o perfil histórico).

    Estas sondas medem REDE, TIMEOUT e ÁRVORE DE PROCESSOS. Para isso precisam
    lançar sh/python3, e a cadeia de shims do host é profunda: `/usr/bin/sh`
    re-executa `/bin/bash`, `/usr/bin/python3` delega ao Python do Xcode, que
    por sua vez carrega de `Contents/Developer/Library/...`. Enumerar essa
    cadeia dentro da sonda faria o teste medir a allowlist de exec — que NÃO é
    o que ele se propõe a medir, e que tem bateria própria em A5.

    A fronteira sob teste aqui continua real e intacta: a rede segue negada e a
    árvore segue morrendo, agora provado sem depender da lista de executáveis.
    """
    import dataclasses
    return dataclasses.replace(conf, exec_permitido=())

GIT = "/usr/bin/git"
pytestmark = pytest.mark.skipif(
    not (Path(supervisor.SANDBOX).exists() and Path(GIT).exists()),
    reason="sandbox-exec ou git ausentes (fora do macOS)")

RAIZ = Path(__file__).resolve().parents[1] / "src" / "nomos"


# ══════════════════════════ PASSO 1 — a fronteira é única ═══════════════════

def test_p1_nenhum_adapter_git_chama_subprocess_diretamente():
    """Estrutural: o supervisor é o gargalo, não uma convenção.

    Sem esta trava, o próximo adapter que copiar o padrão de `subprocess.run`
    herda a forma e perde a política — e ninguém percebe, porque os testes de
    comportamento dele passariam.
    """
    # `script.py` fica de fora: é o executor genérico do `script-rodar` que o
    # runtime já recusa (`ErroRuntime("INDISPONÍVEL")`). Ele não é fronteira de
    # capability viva — está no censo do legado, logo abaixo, e some no C10.
    ofensores = [str(p.relative_to(RAIZ)) for p in (RAIZ / "adapters").rglob("*.py")
                 if p.name not in ("supervisor.py", "script.py")
                 and ("subprocess.Popen" in p.read_text()
                      or "subprocess.run" in p.read_text())]
    assert ofensores == [], (
        f"estes adapters executam processo fora do supervisor: {ofensores}. "
        "Toda execução de capability passa por supervisor.executar()")


# Módulos FORA de `adapters/` que ainda executam processo por conta própria.
# Não são regressão desta missão: são o legado que o C10 vai eliminar. Ficam
# ENUMERADOS em vez de ignorados — uma lista que precisa encolher é pressão;
# um teste que não olha para eles é esquecimento.
LEGADO_COM_SUBPROCESS = {
    "cli.py", "interface/mcp_client.py", "cognition/embutido.py",
    "cognition/arquivos.py", "cognition/criacao.py", "runtime/sandbox_s1.py",
    "runtime/sandbox.py", "adapters/script.py",
    "conectores/mcp/signal/servidor.py",
}


def test_p1_o_legado_com_subprocess_nao_cresceu():
    """Trava de crescimento. `adapters/script.py` continua no disco mesmo com
    `script-rodar` recusado pelo runtime — remoção física é o C10, não aqui."""
    atual = {str(p.relative_to(RAIZ)) for p in RAIZ.rglob("*.py")
             if p.name != "supervisor.py"
             and ("subprocess.Popen" in p.read_text()
                  or "subprocess.run" in p.read_text())}
    novos = atual - LEGADO_COM_SUBPROCESS
    assert novos == set(), f"execução de processo NOVA fora do supervisor: {novos}"


def test_p1_todo_adapter_git_usa_o_supervisor():
    for nome in ("git.py", "git_write.py", "git_push.py", "git_tree.py"):
        texto = (RAIZ / "adapters" / nome).read_text()
        assert "supervisor.executar(" in texto, nome


# ═══════════════════════ PASSO 2 — canonicalização ══════════════════════════

def test_p2_confinamento_canonicaliza_antes_de_gerar_a_politica(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    subprocess.run([GIT, "-C", str(d), "init", "-q", "-b", "main"], check=True,
                   capture_output=True)
    link = tmp_path / "atalho"
    link.symlink_to(d, target_is_directory=True)
    conf = mod_git.confinamento_de_repo(link)
    # A autoridade para no GIT DIR: a working tree ficou fora.
    assert conf.escrita == (str((d / ".git").resolve()),)
    perfil = supervisor.perfil(conf)
    assert f'(subpath "{link}")' not in perfil
    assert f'(subpath "{d.resolve()}")' not in perfil, (
        "o perfil concedeu a working tree inteira")


def test_p2_alvo_inexistente_e_recusado(tmp_path):
    """Canonicalizar caminho ausente resolveria para o pai e AMPLIARIA a
    fronteira sem que ninguém percebesse."""
    with pytest.raises(supervisor.ErroSeguranca, match="não existe"):
        mod_git.confinamento_de_repo(tmp_path / "nao-existe")


@pytest.mark.parametrize("ruim", ['a"b', "a\\b", "a\nb"])
def test_p2_caminho_que_quebraria_o_perfil_e_recusado(tmp_path, ruim):
    """Aspa ou barra invertida sairiam do literal e virariam diretiva do
    sandbox — injeção no próprio arquivo de política."""
    alvo = tmp_path / ruim
    try:
        alvo.mkdir()
    except OSError:
        pytest.skip("o filesystem recusou o nome antes de nós")
    with pytest.raises(supervisor.ErroSeguranca, match="quebraria o perfil"):
        supervisor.canonicalizar(alvo)


# ═══════════════════════════ PASSO 5 — ambiente ═════════════════════════════

@pytest.mark.parametrize("chave,valor", [
    ("GIT_SSH_COMMAND", "/tmp/x"), ("GIT_DIR", "/tmp/outro"),
    ("GIT_CONFIG_COUNT", "1"), ("GIT_CONFIG_KEY_0", "core.fsmonitor"),
    ("GIT_OBJECT_DIRECTORY", "/tmp/o"), ("GIT_EXEC_PATH", "/tmp/e"),
    ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "/tmp/a"), ("HOME", "/tmp/h"),
    ("DYLD_INSERT_LIBRARIES", "/tmp/l.dylib"), ("GIT_INDEX_FILE", "/tmp/i"),
])
def test_p5_ambiente_com_autoridade_extra_e_recusado(chave, valor):
    env = dict(mod_git.ambiente_minimo())
    env[chave] = valor
    with pytest.raises(supervisor.ErroSeguranca):
        supervisor.conferir_ambiente(env)


@pytest.mark.parametrize("chave", list(supervisor.EXIGIDAS_NO_AMBIENTE))
def test_p5_neutralizacao_obrigatoria_ausente_recusa(chave):
    env = dict(mod_git.ambiente_minimo())
    del env[chave]
    with pytest.raises(supervisor.ErroSeguranca, match="obrigatória ausente"):
        supervisor.conferir_ambiente(env)


def test_p5_o_ambiente_real_dos_adapters_passa():
    supervisor.conferir_ambiente(mod_git.ambiente_minimo())
    supervisor.conferir_ambiente(git_tree.GitTreeAdapter().ambiente())


# ═══════════════════════════ PASSO 9 — fail-closed ══════════════════════════

def _conf(p):
    return supervisor.Confinamento(escrita=(str(p),))


def test_p9_sandbox_ausente_recusa_em_vez_de_rodar_sem_ele(tmp_path):
    """A degradação silenciosa é o furo clássico: 'se o sandbox falhar, roda
    sem ele' protege exatamente enquanto não é preciso."""
    with pytest.raises(supervisor.ErroSeguranca, match="ausente"):
        supervisor.executar([GIT, "--version"], cwd=tmp_path,
                            env=mod_git.ambiente_minimo(), prazo=10,
                            confinamento=_conf(tmp_path),
                            binario_sandbox=str(tmp_path / "nao-existe"))


def test_p9_confinamento_sem_raiz_de_escrita_recusa(tmp_path):
    with pytest.raises(supervisor.ErroSeguranca, match="raiz de escrita"):
        supervisor.executar([GIT, "--version"], cwd=tmp_path,
                            env=mod_git.ambiente_minimo(), prazo=10,
                            confinamento=supervisor.Confinamento())


def test_p9_prazo_esgotado_recusa(tmp_path):
    with pytest.raises(ErroLimite):
        supervisor.executar([GIT, "--version"], cwd=tmp_path,
                            env=mod_git.ambiente_minimo(), prazo=0,
                            confinamento=_conf(tmp_path))


def test_p9_perfil_sempre_nega_por_padrao():
    p = supervisor.perfil(supervisor.Confinamento(escrita=("/private/tmp",)))
    assert "(deny default)" in p
    assert "(deny network*)" in p


def test_p9_rede_so_aparece_quando_concedida_explicitamente():
    assert "(allow network*)" in supervisor.perfil(
        supervisor.Confinamento(escrita=("/private/tmp",), rede=True))


# ═══════════ PASSOS 3/6/7 — cadeia real: positivo, negativo, árvore ═════════

@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                 ("commit", "-qm", "p0", "--allow-empty")):
        subprocess.run([GIT, "-C", str(r), *args], check=True, env=env,
                       capture_output=True)
    return r


def _rodar(repo, *argv, prazo=30.0, conf=None):
    """Harness das sondas. Concede ao PROBE o executável que ele precisa.

    Depois de A5 a capacidade real só admite o Git. Estas sondas medem rede,
    timeout e árvore de processos — para isso precisam de sh/python3. Conceder
    aqui é correto: o que está sob medição é a fronteira de REDE ou de
    PROCESSO, não a allowlist de exec (essa tem bateria própria em A5).
    """
    return supervisor.executar(
        list(argv), cwd=repo, env=mod_git.ambiente_minimo(), prazo=prazo,
        confinamento=_com_sonda(conf or mod_git.confinamento_de_repo(repo)))


def _ctx_e_registro(raiz, tmp_path):
    """Contexto pela ÚNICA via sancionada: risco e idempotência vêm do
    registro, não do chamador."""
    from nomos.adapters.wiring import registrar_git_tree
    from nomos.kernel.policy import PolicyEngine
    from nomos.orquestracao.registro import RegistroCapacidades
    registro = RegistroCapacidades(policy=PolicyEngine(tmp_path / "pol.json"),
                                   approver=lambda *a, **k: True)
    registrar_git_tree(registro, raizes=(str(raiz),))
    return registro


class TrilhaFake:
    """Coletor com a MESMA forma da trilha real (`append(evento, **campos)`).
    Uma lista crua passaria no `is not None` do adapter e estouraria só na
    chamada — o teste mediria a fixture, não a auditoria."""

    def __init__(self):
        self.eventos = []

    def append(self, evento, **campos):
        self.eventos.append((evento, campos))

    def __str__(self):
        return str(self.eventos)


def _ctx(registro, cap, raiz, audit=None):
    from nomos.adapters.contrato import CapabilityContext
    return CapabilityContext.de_registro(registro, cap, "runtime-governado",
                                         raizes=(str(raiz),), audit=audit)


def test_p6_git_add_e_commit_autorizados_pelo_adapter_real(repo, tmp_path):
    """PDP_ALLOW → adapter → supervisor → git, com efeito verificado no disco.

    Não aceito `subprocess` direto como substituto: o que precisa ser provado é
    que o caminho GOVERNADO funciona, não que o git funciona.
    """
    from nomos.adapters.contrato import CapabilityRequest

    (repo / "novo.txt").write_text("conteudo\n")
    ad = git_tree.GitTreeAdapter()
    registro = _ctx_e_registro(tmp_path, tmp_path)
    trilha = TrilhaFake()

    r1 = ad.executar(CapabilityRequest(
        capacidade="git-add", alvo=str(repo),
        argumentos={"caminhos": ["novo.txt"]}),
        _ctx(registro, "git-add", tmp_path, audit=trilha))
    assert r1.efeito_aplicado is True

    r2 = ad.executar(CapabilityRequest(
        capacidade="git-commit", alvo=str(repo),
        argumentos={"mensagem": "pelo adapter governado"}),
        _ctx(registro, "git-commit", tmp_path, audit=trilha))
    assert r2.efeito_aplicado is True

    log = subprocess.run([GIT, "-C", str(repo), "log", "--oneline", "-1"],
                         capture_output=True, text=True).stdout
    assert "pelo adapter governado" in log

    # PASSO 10 — a auditoria registra a decisão, sem segredo.
    assert trilha.eventos, "nada foi auditado"
    texto = str(trilha)
    assert "git.add" in texto and "git.commit" in texto
    assert "sandbox" in texto and "EXIT_OK" in texto
    assert "morto_por_timeout" in texto
    assert os.path.realpath(repo) in texto        # repo CANONICALIZADO


def test_p6_o_adapter_realmente_passa_pelo_sandbox(repo):
    r = _rodar(repo, GIT, "--version")
    assert r.sandbox_aplicado is True
    assert r.argv_efetivo[0] == supervisor.SANDBOX
    assert r.classificacao == "EXIT_OK"


def test_p7_escrita_fora_do_repo_negada_pela_fronteira_real(repo, tmp_path):
    fora = tmp_path / "FORA.txt"
    fora.write_text("protegido")
    # Controle positivo: SEM sandbox a ação funcionaria — senão o teste
    # provaria apenas que o comando estava quebrado.
    subprocess.run(["/bin/sh", "-c", f"echo INVADIDO > {fora}"], check=True)
    assert fora.read_text().strip() == "INVADIDO"
    fora.write_text("protegido")

    _rodar(repo, "/bin/sh", "-c", f"echo INVADIDO > {fora}")
    assert fora.read_text() == "protegido"


def test_p7_escrita_no_diretorio_pai_negada(repo, tmp_path):
    alvo = tmp_path / "no-pai.txt"
    _rodar(repo, "/bin/sh", "-c", f"echo X > {alvo}")
    assert not alvo.exists()


_SONDA_REDE = ("import socket;s=socket.socket();s.settimeout(2)\n"
               "try:\n s.connect(('127.0.0.1',9)); print('CONECTOU')\n"
               "except PermissionError: print('NEGADA')\n"
               "except Exception as e: print(type(e).__name__)")


def test_p7_rede_direta_negada(repo):
    r = _rodar(repo, "/usr/bin/python3", "-c", _SONDA_REDE)
    assert b"NEGADA" in r.stdout, r.stdout + r.stderr


def test_p7_rede_de_descendente_negada(repo):
    """Um filho não recupera rede que o pai não tem — o sandbox é herdado."""
    sonda = repo / "sonda.py"
    sonda.write_text(_SONDA_REDE)
    r = _rodar(repo, "/bin/sh", "-c", f"/usr/bin/python3 {sonda}")
    assert b"NEGADA" in r.stdout, r.stdout + r.stderr


def test_p3_timeout_mata_a_arvore_inteira_filho_e_neto(repo, tmp_path):
    """DESCENDANT_SURVIVED=0.

    Matar só o PID principal daria um PASS falso: o `git` morre e o neto que o
    filtro deixou para trás continua. O neto aqui é ÓRFÃO de propósito — o pai
    sai imediatamente, então ele é reparentado antes do timeout.
    """
    import time
    # A marca fica DENTRO do repo, onde a escrita é PERMITIDA. Se ficasse fora,
    # o sandbox a negaria de qualquer jeito e o teste passaria mesmo com o neto
    # vivo — provaria contenção de filesystem, não morte da árvore.
    marca = repo / "neto-vivo.txt"
    script = repo / "arvore.sh"
    script.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        ( sleep 0.3; while true; do echo vivo > {marca}; sleep 0.2; done ) &
        sleep 300
    """))
    script.chmod(0o755)
    r = _rodar(repo, "/bin/sh", str(script), prazo=2.0)
    assert r.morto_por_timeout is True
    assert r.classificacao == "KILLED_BY_TIMEOUT"

    # A marca pode existir do período ANTES do timeout; o que importa é que
    # nada volte a escrevê-la depois que a árvore morreu.
    marca.unlink(missing_ok=True)
    time.sleep(1.2)
    assert not marca.exists(), "o neto sobreviveu ao timeout e continua escrevendo"


def test_p3_timeout_simples_classifica_e_nao_deixa_processo(repo):
    r = _rodar(repo, "/bin/sh", "-c", "sleep 300", prazo=1.5)
    assert r.morto_por_timeout is True
    assert r.classificacao == "KILLED_BY_TIMEOUT"


def test_p3_limite_de_recurso_e_aplicado(repo):
    """RLIMIT_FSIZE ativo: o processo morre em SIGXFSZ em vez de encher o
    disco dentro do repositório que ele legitimamente pode escrever."""
    conf = supervisor.Confinamento(
        escrita=(supervisor.existente(repo),), arquivo_bytes=4096)
    r = _rodar(repo, "/bin/sh", "-c",
               f"dd if=/dev/zero of={repo}/grande bs=1024 count=1000 2>/dev/null",
               conf=conf)
    assert (repo / "grande").stat().st_size <= 8192, "RLIMIT_FSIZE não aplicado"
    assert r.classificacao in ("RESOURCE_LIMIT", "EXIT_ERRO",
                               "KILLED_BY_SIGNAL_25")


# ═════════════════ PASSO 8 — repositório hostil via filter.clean ════════════

@pytest.fixture()
def repo_hostil(tmp_path):
    """`git add` legítimo, filtro do repositório tentando escapar por 6 vias.

    O filtro PRECISA repassar stdin para stdout: ele é o mecanismo de conversão
    working-tree → objeto. Um filtro que não repassa quebraria o `add` por
    outro motivo e mascararia o resultado.
    """
    r = tmp_path / "hostil"
    r.mkdir()
    fora = tmp_path / "ALVO_FORA.txt"
    fora.write_text("intacto")
    marca_neto = r / "neto.txt"      # DENTRO do repo: escrita permitida

    filtro = r / "filtro.sh"
    filtro.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        echo RODOU > {r}/.git/CANARIO                # 0. controle positivo
        echo INVADIDO > {fora}                       # 1. escrever fora
        echo INVADIDO > {tmp_path}/no-pai.txt        # 2. escrever no pai
        /usr/bin/python3 -c 'import socket;s=socket.socket();s.settimeout(1);s.connect(("127.0.0.1",9))' 2>/dev/null && echo REDE_OK > {fora}
        ( while true; do echo neto > {marca_neto}; sleep 0.2; done ) >/dev/null 2>&1 &  # 4/5. neto DESTACADO
        /usr/bin/env > {tmp_path}/ambiente.txt       # 7. vazar ambiente
        /usr/bin/git config --list > {tmp_path}/config.txt
        cat
    """))
    filtro.chmod(0o755)
    (r / ".gitattributes").write_text("*.dat filter=hostil\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run([GIT, "-C", str(r), "init", "-q", "-b", "main"],
                   check=True, env=env, capture_output=True)
    subprocess.run([GIT, "-C", str(r), "config", "filter.hostil.clean",
                    str(filtro)], check=True, env=env, capture_output=True)
    (r / "dados.dat").write_text("carga\n")
    return r, fora, marca_neto


def test_p8_filtro_do_repo_NAO_EXECUTA(repo_hostil, tmp_path):
    """CONTRATO NOVO (A5). Substitui `test_p8_filtro_hostil_executa_...`.

    O contrato antigo era "o filtro executa e não alcança nada" — contenção
    depois da execução. Depois de A5 o contrato é mais forte e mais simples:
    o filtro escolhido pelo REPOSITÓRIO não executa. Fazer o teste antigo
    passar de novo exigiria readmitir a execução, que é o que a decisão de
    produto proibiu.
    """
    from nomos.adapters.contrato import CapabilityRequest

    repo, _fora, _marca_neto = repo_hostil
    registro = _ctx_e_registro(tmp_path, tmp_path)
    with pytest.raises(supervisor.ErroSeguranca) as exc:
        git_tree.GitTreeAdapter().executar(
            CapabilityRequest(capacidade="git-add", alvo=str(repo),
                              argumentos={"caminhos": ["dados.dat"]}),
            _ctx(registro, "git-add", tmp_path))
    assert "cannot exec" in str(exc.value), str(exc.value)[:300]
    assert not (repo / ".git" / "CANARIO").exists(), (
        "o filtro do repositório executou — NO_REPO_CONTROLLED_EXEC caiu")


def test_p8_neto_do_filtro_hostil_nao_sobrevive(repo_hostil, tmp_path):
    """DESCENDANT_SURVIVED=0 no caminho de SUCESSO, que é o difícil.

    Três armadilhas tiveram de sair da frente para este teste significar algo:

    1. a marca precisa ficar DENTRO do repo — fora, o sandbox a negaria e o
       teste passaria com o neto vivo;
    2. o neto precisa DESTACAR o stdio (`>/dev/null 2>&1`) — senão ele segura
       a ponta do pipe, o `git` espera por ele, e o neto termina dentro da
       própria operação em vez de sobreviver a ela;
    3. o kill não pode acontecer só no timeout — este `git add` tem SUCESSO;
    4. e a verificação precisa ser "a marca REAPARECE depois do retorno?", não
       "a marca existe?" — a primeira versão dormia 1s esperando um neto que
       só escrevia aos 30s, e passava com ele vivo.

    Sem (1) e (2) o teste passava por acidente. Com elas, ele reprovou o
    supervisor e obrigou a encerrar o grupo em todo caminho de saída.
    """
    import time
    from nomos.adapters.contrato import CapabilityRequest

    repo, _fora, marca_neto = repo_hostil
    ad = git_tree.GitTreeAdapter()
    registro = _ctx_e_registro(tmp_path, tmp_path)
    with contextlib.suppress(Exception):
        ad.executar(CapabilityRequest(capacidade="git-add", alvo=str(repo),
                                      argumentos={"caminhos": ["dados.dat"]}),
                    _ctx(registro, "git-add", tmp_path))
    # Apagar e ver se REAPARECE. Checar a simples ausência não serve: o neto
    # escreve em laço, então a marca pode existir legitimamente do período em
    # que a operação ainda corria. O que denuncia sobrevivência é a escrita
    # DEPOIS que o adapter retornou.
    marca_neto.unlink(missing_ok=True)
    time.sleep(1.0)
    assert not marca_neto.exists(), "DESCENDANT_SURVIVED"
