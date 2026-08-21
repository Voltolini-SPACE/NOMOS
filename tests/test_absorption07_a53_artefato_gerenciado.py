"""A5.3 — o source externo NUNCA é executado depois da aprovação.

A medição de A5.3.1 provou que o modelo por identidade de path é impossível
neste host:

    os.execve in os.supports_fd                   -> False   (sem fexecve)
    subprocess.run(["/dev/fd/N"], pass_fds=(N,))  -> EACCES  (script E Mach-O)

Não há primitive que vincule validação e uso ao MESMO objeto aberto. E o TOCTOU
é real, medido: trocar o arquivo no path entre validar e executar roda o binário
TROCADO.

A saída não é vencer a corrida — é tirar a corrida do caminho de execução. O
gate deixa de afirmar a propriedade IMPOSSÍVEL:

    objeto validado no path externo == objeto executado no path externo

e passa a afirmar a DEMONSTRÁVEL:

    o source externo nunca é executado depois da aprovação
    bytes importados verificados == bytes aprovados para execução
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from nomos.kernel import plataforma
from nomos.adapters.filtro_governado import (
    ArmazemDeExecutaveis,
    ErroFiltro,
    _digerir,
)

BOM = "#!/bin/sh\necho SAIDA_BOA\n"
HOSTIL = "#!/bin/sh\necho SAIDA_HOSTIL > \"$CANARIO\"\necho SAIDA_HOSTIL\n"


@pytest.fixture
def armazem(tmp_path):
    return ArmazemDeExecutaveis(tmp_path / "exec-store")


def _script(caminho: Path, corpo: str) -> Path:
    caminho.write_text(corpo)
    caminho.chmod(0o755)
    return caminho


def _rodar(caminho, canario=None):
    env = dict(os.environ, CANARIO=str(canario or "/dev/null"))
    return subprocess.run([str(caminho)], capture_output=True, text=True,
                          timeout=20, env=env)


# ════════ O CONTRATO CENTRAL — troca do source depois do import ═════════════

def test_source_trocado_apos_import_NAO_muda_o_codigo_executado(armazem,
                                                                tmp_path):
    """O teste que fecha o TOCTOU externo.

    Antes da asserção de contenção vem o CONTROLE POSITIVO: o hostil precisa
    ser funcional, senão "sem side effect" não prova nada — provaria só que o
    script hostil estava quebrado.
    """
    origem = _script(tmp_path / "filtro.sh", BOM)
    art = armazem.importar(origem)
    assert _rodar(art.managed_path).stdout.strip() == "SAIDA_BOA"

    canario = tmp_path / "CANARIO_HOSTIL"
    hostil = _script(tmp_path / "hostil.sh", HOSTIL)
    # CONTROLE POSITIVO: o hostil REALMENTE produz side effect se executado.
    assert _rodar(hostil, canario).stdout.strip() == "SAIDA_HOSTIL"
    assert canario.exists()
    canario.unlink()

    os.replace(hostil, origem)          # troca o source no MESMO path
    assert _rodar(origem, canario).stdout.strip() == "SAIDA_HOSTIL", (
        "o source não ficou hostil — o cenário não se armou")
    canario.unlink()

    # E o artefato governado continua sendo o aprovado.
    r = _rodar(art.managed_path, canario)
    assert r.stdout.strip() == "SAIDA_BOA", "código NÃO aprovado executou"
    assert not canario.exists(), "UNAPPROVED_CODE_EXECUTED"
    art.conferir()


def test_source_apagado_apos_import_e_inofensivo(armazem, tmp_path):
    origem = _script(tmp_path / "filtro.sh", BOM)
    art = armazem.importar(origem)
    origem.unlink()
    assert not origem.exists()
    assert _rodar(art.managed_path).stdout.strip() == "SAIDA_BOA"
    art.conferir()


def test_source_virando_symlink_para_hostil_e_inofensivo(armazem, tmp_path):
    origem = _script(tmp_path / "filtro.sh", BOM)
    art = armazem.importar(origem)
    hostil = _script(tmp_path / "hostil.sh", HOSTIL)
    origem.unlink()
    origem.symlink_to(hostil)
    canario = tmp_path / "C"
    assert _rodar(art.managed_path, canario).stdout.strip() == "SAIDA_BOA"
    assert not canario.exists()


def test_symlink_como_origem_congela_o_DESTINO(armazem, tmp_path):
    """Symlink é entrada administrativa aceitável; o que congela é o destino."""
    alvo = _script(tmp_path / "real.sh", BOM)
    link = tmp_path / "link.sh"
    link.symlink_to(alvo)
    art = armazem.importar(link)
    assert art.sha256 == _digerir(str(alvo))[0]
    # Retargetar o symlink depois não alcança o artefato.
    hostil = _script(tmp_path / "hostil.sh", HOSTIL)
    link.unlink()
    link.symlink_to(hostil)
    assert _rodar(art.managed_path).stdout.strip() == "SAIDA_BOA"


# ═════════════════ Identidade endereçada por conteúdo ═══════════════════════

def test_artifact_id_e_o_sha256_do_conteudo(armazem, tmp_path):
    origem = _script(tmp_path / "f.sh", BOM)
    art = armazem.importar(origem)
    assert art.artifact_id == art.sha256 == _digerir(str(origem))[0]
    assert art.artifact_id in art.managed_path


def test_mesmos_bytes_de_origens_diferentes_deduplicam(armazem, tmp_path):
    a = armazem.importar(_script(tmp_path / "a.sh", BOM))
    b = armazem.importar(_script(tmp_path / "b.sh", BOM))
    assert a.artifact_id == b.artifact_id
    assert a.managed_path == b.managed_path
    assert _rodar(b.managed_path).stdout.strip() == "SAIDA_BOA"


def test_bytes_diferentes_dao_artefatos_diferentes(armazem, tmp_path):
    a = armazem.importar(_script(tmp_path / "a.sh", BOM))
    b = armazem.importar(_script(tmp_path / "b.sh", BOM + "# outro\n"))
    assert a.artifact_id != b.artifact_id


# ═══════════════ Imutabilidade: divergência é DENY, não refresh ═════════════

def test_artefato_adulterado_e_RECUSADO_e_nao_atualizado(armazem, tmp_path):
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    os.chmod(art.managed_path, 0o700)
    Path(art.managed_path).write_text(HOSTIL)          # adultera o armazém
    with pytest.raises(ErroFiltro, match="DIVERGE"):
        art.conferir()
    assert art.sha256 == _digerir(str(tmp_path / "f.sh"))[0], (
        "a identidade registrada foi ATUALIZADA — trocar binário exige nova "
        "aprovação, nunca auto-trust")


def test_artefato_removido_do_armazem_e_recusado(armazem, tmp_path):
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    os.chmod(Path(art.managed_path).parent, 0o700)
    os.unlink(art.managed_path)
    with pytest.raises(ErroFiltro, match="ilegível"):
        art.conferir()


def test_artefato_nasce_nao_gravavel(armazem, tmp_path):
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    modo = os.stat(art.managed_path).st_mode
    assert not modo & 0o222, "artefato gravável — o filtro poderia se reescrever"
    assert modo & 0o100, "artefato não executável"


def test_armazem_e_privado(armazem):
    modo = os.stat(armazem.raiz).st_mode
    assert not modo & 0o077, "armazém acessível a outros — deve ser 0700"


# ═══════════════════════ Import fail-closed ═════════════════════════════════

def test_origem_inexistente_e_recusada(armazem, tmp_path):
    with pytest.raises(ErroFiltro, match="ilegível"):
        armazem.importar(tmp_path / "nao-existe")


def test_diretorio_como_origem_e_recusado(armazem, tmp_path):
    d = tmp_path / "dir"
    d.mkdir()
    with pytest.raises(ErroFiltro, match="não é arquivo regular"):
        armazem.importar(d)


def test_nada_e_publicado_quando_o_import_falha(armazem, tmp_path):
    antes = sum(1 for _ in Path(armazem.raiz).rglob("*") if _.is_file())
    with pytest.raises(ErroFiltro):
        armazem.importar(tmp_path / "ausente")
    depois = [p for p in Path(armazem.raiz).rglob("*") if p.is_file()]
    assert len(depois) == antes
    assert not [p for p in depois if p.name.startswith(".importando-")], (
        "sobrou temporário — publicação parcial visível")


def test_source_metadata_e_so_auditoria(armazem, tmp_path):
    """O caminho externo fica registrado para auditoria e NÃO para execução."""
    origem = _script(tmp_path / "f.sh", BOM)
    art = armazem.importar(origem)
    assert art.source_metadata["source_path"] == os.path.realpath(origem)
    assert art.managed_path != str(origem)
    assert not art.managed_path.startswith(str(tmp_path / "f.sh"))


@pytest.mark.skipif(
    not plataforma.EH_MAC,
    reason="medição de macOS: no Linux `fexecve` EXISTE, e A5.3 foi decidido "
           "para a plataforma onde o supervisor roda — ver CHANGELOG")
def test_MEDICAO_A531_o_primitive_forte_nao_existe_neste_host():
    """Fixa a medição que motivou o modelo de artefato gerenciado.

    Se um dia `fexecve` ou exec via `/dev/fd` passar a existir, este teste
    falha — e aí vale reavaliar se o modelo por identidade de objeto aberto
    fica disponível, em vez de manter a decisão por inércia.

    ATENÇÃO — o gatilho acima vale para o macOS, que é onde a capacidade Git
    governada roda. No **Linux** `os.execve` JÁ está em `os.supports_fd`: o
    primitive forte existe lá. Isso não é defeito nem alarme falso; é uma
    pergunta de projeto em aberto (se um dia o supervisor ganhar porte para
    Linux, A5.3 deve ser reavaliado ali). Fica pulado em vez de vermelho para
    não travar o CI com uma decisão de arquitetura disfarçada de falha.
    """
    assert os.execve not in os.supports_fd, (
        "fexecve passou a existir — reavaliar A5.3")


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))


# ═══════ A5.3 POLICY BINDING — a autoridade de execução é o artefato ════════

def _pol(**kw):
    from nomos.adapters.filtro_governado import PoliticaDeFiltro
    base = dict(filter_id="synthetic-redactor",
                canonical_executable="/usr/bin/sed",
                argv_policy=("-e", "s/x/y/"))
    base.update(kw)
    return PoliticaDeFiltro(**base)


def test_politica_SEM_artefato_recusa_executar():
    """Sem import não há execução. Apontar o exec para o path externo
    reabriria exatamente o TOCTOU que A5.3 fechou."""
    with pytest.raises(ErroFiltro, match="proveniência, não autoridade"):
        _pol().executavel()


def test_executavel_vem_do_ARTEFATO_e_nao_do_path_externo(armazem, tmp_path):
    origem = _script(tmp_path / "f.sh", BOM)
    art = armazem.importar(origem)
    pol = _pol(canonical_executable=str(origem), managed_artifact=art)

    assert pol.executavel() == art.managed_path
    assert pol.executavel() != str(origem), (
        "a execução aponta para o path externo — TOCTOU reaberto")
    assert pol.proveniencia() == os.path.realpath(origem)


@pytest.mark.parametrize("ataque", ["remover", "substituir", "retargetar"])
def test_resolucao_IDENTICA_com_o_source_atacado(armazem, tmp_path, ataque):
    """A propriedade que o gate exige: mexer no source não muda a resolução."""
    origem = _script(tmp_path / "f.sh", BOM)
    art = armazem.importar(origem)
    pol = _pol(canonical_executable=str(origem), managed_artifact=art)
    antes = pol.executavel()

    hostil = _script(tmp_path / "hostil.sh", HOSTIL)
    if ataque == "remover":
        origem.unlink()
    elif ataque == "substituir":
        os.replace(hostil, origem)
    else:
        origem.unlink()
        origem.symlink_to(hostil)

    assert pol.executavel() == antes, f"{ataque} mudou a resolução"
    canario = tmp_path / "C"
    assert _rodar(pol.executavel(), canario).stdout.strip() == "SAIDA_BOA"
    assert not canario.exists(), "UNAPPROVED_CODE_EXECUTED"


def test_executavel_CONFERE_o_artefato_antes_de_devolver(armazem, tmp_path):
    """`conferir()` está COLADO na porta de execução, não num passo anterior."""
    art = armazem.importar(_script(tmp_path / "f.sh", BOM))
    pol = _pol(managed_artifact=art)
    assert pol.executavel() == art.managed_path

    os.chmod(art.managed_path, 0o700)
    Path(art.managed_path).write_text(HOSTIL)
    with pytest.raises(ErroFiltro, match="DIVERGE"):
        pol.executavel()


def test_estrutural_conferir_está_dentro_de_executavel():
    """Se alguém separar verificação de uso, a distância volta a existir."""
    import inspect
    from nomos.adapters.filtro_governado import PoliticaDeFiltro
    fonte = inspect.getsource(PoliticaDeFiltro.executavel)
    assert "conferir()" in fonte, (
        "executavel() deixou de conferir — verificação longe do uso é a "
        "superfície que A5.3 existe para fechar")
