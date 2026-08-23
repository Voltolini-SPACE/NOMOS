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
def test_sem_rede_continua_recusado_no_mac():
    """Não mudei a postura só-Linux do ramo sem rede — é desenho, não defeito."""
    with pytest.raises(sandbox.IsolationUnavailable):
        sandbox.run(["/bin/echo", "x"], allow_network=False, timeout=15)
