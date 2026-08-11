"""A5.2 — o registry é a autoridade; o repositório só faz um pedido.

O gate desta fase é de TITULARIDADE, não de sandbox. A pergunta é uma só:

    quem decide qual binário roda?

Antes: o `.git/config` do repositório. Agora: o registry do NOMOS. O repositório
contribui com exatamente um dado — `requested_filter_id` — e nada mais.

    REPOSITORY_MAY_DECLARE_REQUIREMENT       = TRUE
    REPOSITORY_MAY_GRANT_EXECUTION_AUTHORITY = FALSE
    NOMOS_POLICY_IS_SOLE_EXECUTION_AUTHORITY = TRUE
"""
from __future__ import annotations

import dataclasses
import sys

import pytest

from nomos.adapters.contrato import ErroInvalido
from nomos.adapters.filtro_governado import (
    ErroFiltro,
    PoliticaDeFiltro,
    RegistroDeFiltros,
    conferir_id,
)

SED = "/usr/bin/sed"


def _politica(pid="synthetic-redactor", **kw):
    base = dict(filter_id=pid, canonical_executable=SED,
                argv_policy=("-e", "s/SENHA=.*/SENHA=REDIGIDO/"))
    base.update(kw)
    return PoliticaDeFiltro(**base)


# ═══════════════════ Os seis contratos mínimos do gate ══════════════════════

def test_id_aprovado_resolve():
    reg = RegistroDeFiltros({"synthetic-redactor": _politica()})
    pol = reg.resolver("synthetic-redactor")
    assert pol.canonical_executable == SED
    assert pol.argv_policy == ("-e", "s/SENHA=.*/SENHA=REDIGIDO/")


def test_id_desconhecido_e_NEGADO():
    reg = RegistroDeFiltros({"synthetic-redactor": _politica()})
    with pytest.raises(ErroFiltro, match="não está no registry"):
        reg.resolver("qualquer-outro")


def test_registry_vazio_nega_tudo():
    """Ausência de política é NEGAÇÃO, nunca fallback."""
    with pytest.raises(ErroFiltro):
        RegistroDeFiltros().resolver("synthetic-redactor")


def test_repo_NAO_pode_sobrepor_o_executavel():
    """O caso central: o repo pede o id aprovado e tenta trocar o binário.

    Não existe parâmetro por onde isso passe — `resolver` recebe SÓ o id. A
    política devolvida é a do registry, com o binário do registry.
    """
    reg = RegistroDeFiltros({"synthetic-redactor": _politica()})
    pol = reg.resolver("synthetic-redactor")
    assert pol.canonical_executable == SED, (
        "o executável veio de outro lugar que não o registry")
    # E a política é imutável: nem depois da resolução alguém a reescreve.
    with pytest.raises(dataclasses.FrozenInstanceError):
        pol.canonical_executable = "/bin/sh"        # type: ignore[misc]


def test_repo_NAO_pode_sobrepor_o_argv():
    reg = RegistroDeFiltros({"synthetic-redactor": _politica()})
    pol = reg.resolver("synthetic-redactor")
    assert pol.argv_policy == ("-e", "s/SENHA=.*/SENHA=REDIGIDO/")
    with pytest.raises(dataclasses.FrozenInstanceError):
        pol.argv_policy = ("-e", "s/.*/rm -rf/e")   # type: ignore[misc]


@pytest.mark.parametrize("ruim,motivo", [
    ({"canonical_executable": ""}, "sem executável"),
    ({"canonical_executable": "sed"}, "relativo (resolvido por PATH)"),
    ({"canonical_executable": "/nao/existe/binario"}, "inexistente"),
    ({"timeout": 0}, "timeout não positivo"),
    ({"timeout": -1}, "timeout negativo"),
    ({"descendant_policy": "deixar-viver"}, "descendente sobrevivente"),
])
def test_politica_malformada_e_NEGADA_na_construcao(ruim, motivo):
    """Recusa na CONSTRUÇÃO, não na execução: política inválida nunca existe."""
    with pytest.raises(ErroFiltro):
        _politica(**ruim)


# ═══════════════════ A gramática do único dado do repo ══════════════════════

@pytest.mark.parametrize("ruim", [
    "../../etc/passwd", "/usr/bin/sh", "a b", "id;rm", "id$(x)", "id\nx",
    "", "x" * 65, None, 123, b"bytes",
])
def test_id_fora_da_gramatica_e_NEGADO(ruim):
    """O id vem do repositório: é entrada não confiável.

    A gramática exclui caminho e metacaractere de propósito — um id que possa
    PARECER caminho convida alguém, no futuro, a tentar resolvê-lo como um.
    """
    with pytest.raises(ErroFiltro):
        conferir_id(ruim)


def test_id_valido_passa():
    for bom in ("synthetic-redactor", "git_lfs", "norm2", "A-b_9"):
        assert conferir_id(bom) == bom


# ═══════════════════════ Invariantes do registry ════════════════════════════

def test_registrar_duas_vezes_o_mesmo_id_e_recusado():
    """Redefinição silenciosa trocaria a autoridade de um filtro em uso."""
    reg = RegistroDeFiltros({"synthetic-redactor": _politica()})
    with pytest.raises(ErroFiltro, match="já registrado"):
        reg.registrar("synthetic-redactor", _politica())


def test_dicionario_solto_nao_vira_politica():
    """Autoridade só entra tipada — dict passaria sem validação nenhuma."""
    reg = RegistroDeFiltros()
    with pytest.raises(ErroFiltro, match="não é PoliticaDeFiltro"):
        reg.registrar("x", {"canonical_executable": "/bin/sh"})  # type: ignore[arg-type]


def test_chave_divergente_do_filter_id_e_recusada():
    reg = RegistroDeFiltros()
    with pytest.raises(ErroFiltro, match="!="):
        reg.registrar("um-nome", _politica(pid="outro-nome"))


def test_executavel_e_canonicalizado(tmp_path):
    """Symlink resolve para o destino REAL já na construção.

    Isto NÃO é identidade forte — é canonicalização. A diferença está fixada
    no teste seguinte, para que ninguém leia isto como garantia de A5.3.
    """
    link = tmp_path / "atalho-sed"
    link.symlink_to(SED)
    assert _politica(canonical_executable=str(link)).canonical_executable == SED


def test_identidade_forte_AGORA_e_por_artefato_gerenciado(tmp_path):
    """SUBSTITUI `test_LIMITE_A52_identidade_forte_ainda_NAO_esta_provada`.

    Aquele teste passava AFIRMANDO a lacuna — `executable_identity == {}`. Sob
    a regra `TEST_ASSERTS_DESIRED_SECURITY_PROPERTY` ele não podia sobreviver a
    A5.3: um teste verde que documenta a ausência de uma defesa faz a defesa
    parecer regressão quando ela chega.

    O contrato positivo que o substitui: identidade forte existe, é endereçada
    por CONTEÚDO, e não depende do path externo.
    """
    from nomos.adapters.filtro_governado import ArmazemDeExecutaveis

    origem = tmp_path / "f.sh"
    origem.write_text("#!/bin/sh\necho ok\n")
    origem.chmod(0o755)
    art = ArmazemDeExecutaveis(tmp_path / "store").importar(origem)

    assert art.artifact_id == art.sha256, "identidade não é por conteúdo"
    assert len(art.sha256) == 64
    assert art.managed_path != str(origem), (
        "o artefato governado é o próprio path externo — o TOCTOU externo "
        "continuaria alcançando a execução")


def test_erro_de_filtro_preserva_o_contrato_de_erro():
    assert issubclass(ErroFiltro, ErroInvalido)


if __name__ == "__main__":       # pragma: no cover
    sys.exit(pytest.main([__file__, "-v"]))
