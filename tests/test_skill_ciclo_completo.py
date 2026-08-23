"""O ciclo criar → catálogo → instalar → listar, provado de ponta a ponta.

Existiam testes das PARTES, e todos passavam — mas o ciclo estava quebrado no
meio: `adicionar_ao_catalogo` não tinha nenhum chamador de produção (só dois
testes), então o catálogo tinha leitor e nenhum escritor e a lista de "skills
disponíveis para instalar" nascia sempre vazia. Teste de parte não pega isso;
só o ciclo pega. Daí este arquivo.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from nomos.ext import skill_catalogo as scat
from nomos.ext import skill_registry as reg
from nomos.kernel.policy import PolicyEngine


def _skill_em(pasta, nome, permissions=None):
    d = pasta / nome
    d.mkdir(parents=True)
    corpo = f'print("sou {nome}")\n'
    (d / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    (d / "skill.json").write_text(json.dumps({
        "name": nome, "version": "1.0.0",
        "description": f"skill {nome}",
        "permissions": permissions or ["A0_READ_LOCAL"],
        "entry": "main.py",
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()},
    }))
    return d


# --------------------------------------------------------------- semeadura
def test_catalogo_nasce_vazio_sem_semear(nomos_home):
    """O estado que o dono via: nada para instalar, sem caminho para encher."""
    assert reg.catalogo(nomos_home) == []
    assert scat.capacidades(nomos_home, nomos_home / "skills") == []


def test_semear_da_ao_catalogo_o_escritor_que_faltava(tmp_path, nomos_home):
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    _skill_em(origem, "beta")

    res = reg.semear_catalogo(nomos_home, origem)

    assert sorted(res["adicionadas"]) == ["alfa", "beta"]
    assert res["erros"] == []
    assert sorted(s["name"] for s in reg.catalogo(nomos_home)) == ["alfa", "beta"]


def test_semear_e_idempotente(tmp_path, nomos_home):
    """Semear duas vezes não duplica — upsert por nome."""
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    reg.semear_catalogo(nomos_home, origem)
    reg.semear_catalogo(nomos_home, origem)
    assert len(reg.catalogo(nomos_home)) == 1


def test_manifesto_quebrado_nao_derruba_os_bons(tmp_path, nomos_home):
    origem = tmp_path / "loja"
    _skill_em(origem, "boa")
    ruim = origem / "ruim"
    ruim.mkdir()
    (ruim / "skill.json").write_text("{ isto não é json")

    res = reg.semear_catalogo(nomos_home, origem)

    assert res["adicionadas"] == ["boa"]
    assert [p for p, _ in res["erros"]] == ["ruim"]


def test_semear_pasta_inexistente_falha_limpo(tmp_path, nomos_home):
    with pytest.raises(reg.RegistroError):
        reg.semear_catalogo(nomos_home, tmp_path / "nao-existe")


# ------------------------------------------------------------- ciclo todo
def test_ciclo_completo_disponivel_vira_instalada(tmp_path, nomos_home):
    """semear → aparece DISPONÍVEL → instalar → aparece INSTALADA.

    É o percurso que o dono faz na página de skills, inteiro.
    """
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    _skill_em(origem, "beta")
    skills_dir = nomos_home / "skills"

    # 1) semear: as duas ficam visíveis, nenhuma instalada
    reg.semear_catalogo(nomos_home, origem)
    caps = {c["nome"]: c["status"] for c in scat.capacidades(nomos_home, skills_dir)}
    assert caps == {"alfa": "disponível no catálogo", "beta": "disponível no catálogo"}

    # 2) instalar UMA, pelo mesmo caminho do CLI (gate + confirmação)
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(origem / "alfa", skills_dir, engine, lambda d: True,
                 confirmar_experimental=lambda mf: True)

    # 3) o status VIRA, e a outra continua disponível
    caps = {c["nome"]: c["status"] for c in scat.capacidades(nomos_home, skills_dir)}
    assert caps["alfa"] == "instalada"
    assert caps["beta"] == "disponível no catálogo"

    # 4) `disponiveis` para de oferecer o que já está instalado
    assert [d["name"] for d in reg.disponiveis(nomos_home, skills_dir)] == ["beta"]


def test_semear_nao_afrouxa_o_gate(tmp_path, nomos_home):
    """Constar no catálogo é ficar VISÍVEL, não ficar autorizado.

    Se semear virasse permissão implícita, a semeadura seria um bypass do A5.
    """
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    reg.semear_catalogo(nomos_home, origem)

    engine = PolicyEngine(nomos_home / "policy.json")
    # ATENÇÃO ao tipo: as duas recusas levantam exceções IRMÃS e não
    # relacionadas — `RegistroError` (registry) e `SkillError` (skills). Quem
    # consome tem de pegar as duas; a produção faz isso em
    # `simple/skills_menu.py:156`, com a tupla. Não "simplifique" para uma só.
    from nomos.ext.skills import SkillError

    # sem confirmador de experimental: recusa mesmo estando no catálogo
    with pytest.raises(reg.RegistroError):
        reg.instalar(origem / "alfa", nomos_home / "skills", engine, lambda d: True)
    # sem aprovação no gate A5: recusa também
    with pytest.raises(SkillError):
        reg.instalar(origem / "alfa", nomos_home / "skills", engine, lambda d: False,
                     confirmar_experimental=lambda mf: True)
    # e nada foi instalado por nenhum dos dois caminhos
    assert not (nomos_home / "skills" / "alfa").exists()


def test_semeado_entra_NAO_assinado(tmp_path, nomos_home):
    """A semeadura local não pode fingir procedência: nada de assinatura."""
    origem = tmp_path / "loja"
    _skill_em(origem, "alfa")
    reg.semear_catalogo(nomos_home, origem)

    _, assinado, _ = reg.catalogo_info(nomos_home)
    assert assinado is False
    assert all("signature" not in s for s in reg.catalogo(nomos_home))
