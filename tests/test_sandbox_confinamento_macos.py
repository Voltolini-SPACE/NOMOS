"""O ramo COM REDE do sandbox ganhou cerca de sistema de arquivos no macOS.

Defeito medido em 23/08: `sandbox.run(..., allow_network=True)` rodava com
acesso TOTAL ao disco como o usuário — listava o home e enxergava
`~/.nomos/vault.json`. Havia env limpo, cwd temporário e rlimits; não havia
cerca de arquivos. A inversão: o caso de MENOR risco (sem rede) era recusado
fail-closed, e o de MAIOR risco (com rede) corria com menos cerca.

O ramo sem rede segue só-Linux POR DESENHO — ver
`kernel.plataforma.execucao_isolada_disponivel`. Isto aqui não muda essa
postura; fecha o outro lado.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
import sys
from pathlib import Path

import pytest

from nomos.kernel import plataforma
from nomos.runtime import sandbox

so_mac = pytest.mark.skipif(not plataforma.EH_MAC, reason="seatbelt é do macOS")


def test_perfil_recusa_caminho_que_quebraria_a_politica():
    """Aspa no caminho fecharia a string e o resto viraria política do atacante.

    Não há escape confiável na linguagem do seatbelt: recusar é a resposta.
    """
    with pytest.raises(sandbox.IsolationUnavailable):
        sandbox._perfil_seatbelt('/tmp/a"b')


def test_perfil_resolve_symlink_do_tmp():
    """/tmp é symlink para /private/tmp; o perfil precisa do caminho real,
    senão a área gravável declarada não é a que o processo usa."""
    perfil = sandbox._perfil_seatbelt("/tmp")
    assert "/private/tmp" in perfil


def test_perfil_permite_rede_e_so_o_workdir_grava():
    perfil = sandbox._perfil_seatbelt("/tmp")
    assert "(deny default)" in perfil
    assert "(allow network-outbound)" in perfil
    assert 'file-write* (subpath "/private/tmp")' in perfil


def test_perfil_tem_a_raiz_legivel():
    """`(literal "/")` é obrigatório: sem ele o dyld aborta com rc=134 e sem
    mensagem — falha muda, o pior modo. Lição já paga por adapters/supervisor."""
    assert '(allow file-read* (literal "/"))' in sandbox._perfil_seatbelt("/tmp")


def test_fora_do_mac_nao_inventa_isolamento(monkeypatch):
    """Não fingir cerca onde não há: o argv sai intacto e o chamador sabe."""
    monkeypatch.setattr(plataforma, "EH_MAC", False)
    argv, confinado = sandbox._confinamento_macos(["/bin/echo", "x"], "/tmp")
    assert argv == ["/bin/echo", "x"] and confinado is False


def test_sem_o_binario_nao_inventa_isolamento(monkeypatch):
    monkeypatch.setattr(plataforma, "EH_MAC", True)
    monkeypatch.setattr(sandbox.shutil, "which", lambda n: None)
    monkeypatch.setattr(sandbox.os.path, "exists", lambda p: False)
    argv, confinado = sandbox._confinamento_macos(["/bin/echo", "x"], "/tmp")
    assert confinado is False


# ------------------------------------------------- comportamento real no Mac
@so_mac
def test_com_rede_nao_le_mais_o_home_do_dono():
    """O defeito original, preso: era `ls /Users/... ` devolvendo o conteúdo."""
    r = sandbox.run(["/bin/sh", "-c", f"ls {os.path.expanduser('~')} 2>&1 | head -1"],
                    allow_network=True, timeout=20)
    assert "not permitted" in (r.stdout or "").lower()


@so_mac
def test_com_rede_nao_enxerga_o_cofre():
    cofre = os.path.expanduser("~/.nomos/vault.json")
    r = sandbox.run(["/bin/sh", "-c", f"ls -l {cofre} 2>&1 | head -1"],
                    allow_network=True, timeout=20)
    assert "not permitted" in (r.stdout or "").lower()


@so_mac
def test_a_rede_pedida_continua_funcionando():
    """Confinar arquivo não pode tirar a rede: era o que o chamador pediu."""
    r = sandbox.run(["/bin/sh", "-c",
                     "curl -s -o /dev/null -w '%{http_code}' --max-time 5 "
                     "http://127.0.0.1:11434/api/tags || echo sem-servico"],
                    allow_network=True, timeout=20)
    assert (r.stdout or "").strip() in ("200", "sem-servico"), r.stdout


@so_mac
def test_escrita_no_proprio_workdir_funciona():
    r = sandbox.run(["/bin/sh", "-c", "echo ok > x && cat x"],
                    allow_network=True, timeout=20)
    assert (r.stdout or "").strip() == "ok"


@so_mac
def test_resultado_diz_a_verdade_nos_dois_eixos():
    """`network_isolated=False` é esperado para quem pediu rede — e sozinho
    escondia a ausência de cerca de arquivos. Agora são dois campos."""
    r = sandbox.run(["/bin/echo", "x"], allow_network=True, timeout=15)
    assert r.network_isolated is False and r.fs_confinado is True


@so_mac
def test_sem_rede_EXECUTA_no_mac_com_rede_negada_de_verdade():
    """A postura mudou em 23/08, de propósito — este teste substitui o pino
    "continua recusado no mac", que existia exatamente para forçar a mudança a
    ser explícita em vez de acidental.

    O que caiu: a INVERSÃO — a skill mais segura (sem rede) era a única que não
    executava, enquanto a com rede rodava sob o seatbelt. O que entrou: o ramo
    sem rede usa o perfil BASE do MESMO seatbelt, cujo (deny default) nega
    network-* — garantia igual à do unshare no Linux, com cerca de arquivos
    junto. A recusa fail-closed segue existindo para máquina sem unshare E sem
    sandbox-exec (coberto em test_sandbox_skills, pelo mesmo critério que o
    previsor consulta).
    """
    r = sandbox.run(["/bin/echo", "x"], allow_network=False, timeout=15)
    assert r.rc == 0
    assert r.network_isolated is True     # a garantia existe e é DECLARADA
    assert r.fs_confinado is True         # e a cerca de arquivos veio junto

    # rede negada DE FATO, não por declaração: sonda tenta e falha
    sonda = sandbox.run(
        ["/opt/homebrew/bin/python3", "-c",
         "import socket\ns=socket.socket()\ns.settimeout(3)\n"
         "s.connect(('1.1.1.1', 80))\nprint('REDE_ABERTA')"],
        allow_network=False, timeout=15)
    assert "REDE_ABERTA" not in sonda.stdout
    assert sonda.rc != 0


# ------------------------------------------------ o caminho legítimo de volta
# A cerca de 651dfc3 fechou o cofre e fechou JUNTO o interpretador: medido em
# 23/08, NENHUMA skill Python executava. `python3` nu caía no shim do xcrun;
# o python do Homebrew morria em "realpath: /opt/homebrew/bin/: Operation not
# permitted"; o do venv em `execvp()` negado. Uma skill instalava, aparecia
# instalada e quebrava no uso — a promessa falsa que se quer evitar.

def test_resolve_interpretador_relativo_para_absoluto():
    """`python3` nu dentro da cerca caía em /usr/bin/python3, que é SHIM DO
    XCRUN — mesma família da landmine que custou a CI em 21/08."""
    argv, regras = sandbox._regras_do_interpretador(["python3", "-c", "pass"])
    assert argv[0].startswith("/") and "python3" in argv[0]
    assert regras, "sem regras o interpretador não se resolve"


def test_path_de_busca_inclui_o_homebrew():
    """Num Mac Apple Silicon é onde mora tudo; ficava de fora."""
    assert "/opt/homebrew/bin" in sandbox._PATH_BUSCA


def test_libera_o_prefixo_do_interpretador_e_nao_um_diretorio_generico():
    _, regras = sandbox._regras_do_interpretador(["/bin/echo", "x"])
    texto = "\n".join(regras)
    assert "process-exec" in texto
    assert "/Users" not in texto, "não pode liberar o home do dono"


def test_libera_leitura_da_pasta_da_entrada(tmp_path):
    """A skill instalada mora fora do workdir; sem isto o Python arranca e
    morre em 'can't open file … Operation not permitted'."""
    script = tmp_path / "skill.py"
    script.write_text("pass")
    _, regras = sandbox._regras_do_interpretador(["/bin/echo", str(script)])
    assert any(f'subpath "{tmp_path.resolve()}"' in r for r in regras)
    assert not any("file-write" in r and str(tmp_path) in r for r in regras), \
        "a pasta da skill é de LEITURA — a skill não escreve onde foi instalada"


def test_argumento_que_nao_e_arquivo_nao_vira_regra():
    """`sh -c '<script inline>'` não pode virar liberação de caminho."""
    _, regras = sandbox._regras_do_interpretador(["/bin/sh", "-c", "echo oi"])
    assert not any("subpath" in r and "echo" in r for r in regras)


def test_argv_vazio_nao_estoura():
    assert sandbox._regras_do_interpretador([]) == ([], [])


@so_mac
def test_skill_python_executa_de_verdade(tmp_path):
    """O defeito, preso: rc=0 e a saída da skill."""
    script = tmp_path / "skill.py"
    script.write_text("print('SKILL RODOU')\n")
    r = sandbox.run([sys.executable, str(script)], allow_network=True, timeout=30)
    assert r.rc == 0 and "SKILL RODOU" in (r.stdout or "")


@so_mac
def test_a_cerca_continua_fechada_com_o_interpretador_liberado(tmp_path):
    """O ponto todo: destravar a execução NÃO pode reabrir o cofre."""
    script = tmp_path / "sonda.py"
    script.write_text(
        "import os\n"
        "for nome, alvo in (('home','~'), ('nomos','~/.nomos'), ('ssh','~/.ssh')):\n"
        "    try: os.listdir(os.path.expanduser(alvo)); print(nome, 'ABERTO')\n"
        "    except PermissionError: print(nome, 'bloqueado')\n")
    r = sandbox.run([sys.executable, str(script)], allow_network=True, timeout=30)
    assert r.rc == 0, r.stderr
    assert "ABERTO" not in (r.stdout or ""), r.stdout
    assert (r.stdout or "").count("bloqueado") == 3


# ------------------------------------------------- symlink no caminho (23/08)
def test_metadata_nos_ancestrais_da_pasta_do_script(tmp_path):
    """Abrir arquivo percorre o caminho componente a componente.

    No macOS `/tmp` e `/var` são SYMLINK. Sem `file-read-metadata` em cada
    ancestral, `/tmp/x/s.py` era negado com `[Errno 1] Operation not
    permitted` MESMO com `/private/tmp/x` liberado — medido. Era a mesma lição
    que `/var` e `/etc` já tinham imposto ao perfil base; `/tmp` era o terceiro.
    """
    script = tmp_path / "sub" / "s.py"
    script.parent.mkdir()
    script.write_text("pass")
    _, regras = sandbox._regras_do_interpretador(["/bin/echo", str(script)])
    texto = "\n".join(regras)
    assert f'subpath "{script.parent}"' in texto
    assert "file-read-metadata" in texto
    assert f'literal "{script.parent.parent}"' in texto


def test_emite_as_duas_formas_do_caminho(monkeypatch, tmp_path):
    """Caminho pode chegar resolvido ou não; as duas formas são o MESMO
    diretório, então emitir ambas não alarga a cerca."""
    script = tmp_path / "s.py"
    script.write_text("pass")
    _, regras = sandbox._regras_do_interpretador(["/bin/echo", str(script)])
    pastas = [r for r in regras if "subpath" in r]
    assert pastas, "sem regra de pasta a skill não abre o próprio arquivo"


@so_mac
def test_script_sob_tmp_executa(tmp_path):
    """O defeito reportado, preso: mesmo arquivo, `/tmp` falhava e
    `/private/tmp` rodava."""
    import os
    script = Path("/tmp") / f"nomos_t_{os.getpid()}" / "s.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('OK')\n")
    try:
        r = sandbox.run([sys.executable, str(script)],
                        allow_network=True, timeout=30)
        assert r.rc == 0 and "OK" in (r.stdout or ""), r.stderr
    finally:
        script.unlink(missing_ok=True)
        script.parent.rmdir()


@so_mac
def test_o_cofre_continua_fechado_por_caminho_absoluto(tmp_path):
    """Sonda honesta: dentro da cerca `HOME=/tmp`, então `~/.nomos` não é o
    cofre real — a prova precisa do caminho absoluto."""
    import os
    real = os.path.expanduser("~")
    script = tmp_path / "sonda.py"
    script.write_text(
        "import os\n"
        f"for a in ({real!r}, {real + '/.nomos'!r}, {real + '/.ssh'!r}):\n"
        "    try: os.stat(a); print('ABERTO', a)\n"
        "    except PermissionError: print('bloqueado')\n")
    r = sandbox.run([sys.executable, str(script)], allow_network=True, timeout=30)
    assert "ABERTO" not in (r.stdout or ""), r.stdout
    assert (r.stdout or "").count("bloqueado") == 3
