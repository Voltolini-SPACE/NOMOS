"""Fase 1 — menu amigável de skills: status correto, permissões, diagnóstico."""
import hashlib
import json

from nomos.ext import skill_registry as reg
from nomos.ext import skill_status as st
from nomos.kernel.policy import PolicyEngine
from nomos.simple import skills_menu as smenu


def _instala(tmp_path, nomos_home, name="exemplo", permissions=None):
    src = tmp_path / f"src-{name}"
    src.mkdir()
    corpo = 'print("oi")\n'
    (src / "main.py").write_text(corpo, encoding="utf-8", newline="\n")
    (src / "skill.json").write_text(json.dumps({
        "name": name, "version": "1.0.0",
        "permissions": permissions or ["A0_READ_LOCAL"], "entry": "main.py",
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}))
    engine = PolicyEngine(nomos_home / "policy.json")
    return reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                        confirmar_experimental=lambda m: True)


def test_menu_lista_status_correto(tmp_path, nomos_home):
    _instala(tmp_path, nomos_home)
    itens = st.status_todas(nomos_home, nomos_home / "skills")
    assert len(itens) == 1
    it = itens[0]
    assert it["name"] == "exemplo"
    assert it["estado"] == "ativa (não confiável)"   # sem assinatura
    assert it["risco"] == "baixo" and it["confiavel"] is False
    texto = smenu.render_lista(itens)
    assert "exemplo@1.0.0" in texto and "risco" in texto
    assert "apenas leitura local" in texto


def test_desativar_e_reativar(tmp_path, nomos_home):
    _instala(tmp_path, nomos_home)
    st.ativar(nomos_home, "exemplo", False)
    it = st.status_todas(nomos_home, nomos_home / "skills")[0]
    assert it["estado"] == "inativa" and "reative" in it["acao"]
    st.ativar(nomos_home, "exemplo", True)
    assert st.status_todas(nomos_home, nomos_home / "skills")[0]["estado"] \
        == "ativa (não confiável)"


def test_quebrada_detectada_e_acao_recomendada(tmp_path, nomos_home):
    _instala(tmp_path, nomos_home)
    (nomos_home / "skills" / "exemplo" / "main.py").write_text("print('adulterada')\n")
    it = st.status_todas(nomos_home, nomos_home / "skills")[0]
    assert it["estado"] == "quebrada" and "checksum" in (it["defeito"] or "")
    assert "reinstale" in it["acao"]


def test_ultimo_uso_registrado(tmp_path, nomos_home):
    _instala(tmp_path, nomos_home)
    assert st.ultimo_uso(nomos_home, "exemplo") is None
    st.marcar_uso(nomos_home, "exemplo")
    assert isinstance(st.ultimo_uso(nomos_home, "exemplo"), int)


def test_diagnostico_de_seguranca(tmp_path, nomos_home):
    _instala(tmp_path, nomos_home, name="leitora")
    _instala(tmp_path, nomos_home, name="ousada", permissions=["A2_NET_EGRESS"])
    texto = smenu.diagnostico_texto(nomos_home, nomos_home / "skills")
    assert "instaladas: 2" in texto
    assert "ousada" in texto and "risco alto" in texto
    assert "não assinad" in texto


def test_menu_interativo_navega_e_sai(tmp_path, nomos_home):
    _instala(tmp_path, nomos_home)
    ctx = {"home": nomos_home, "skills": nomos_home / "skills"}
    respostas = iter(["1", "4", "5", "6"])   # lista, permissões, diagnóstico, sai
    ditos = []
    rc = smenu.menu(ctx, ask=lambda p: next(respostas), say=ditos.append)
    assert rc == 0
    tudo = "\n".join(str(d) for d in ditos)
    assert "Suas skills" in tudo and "Diagnóstico" in tudo


def test_render_info_completo(tmp_path, nomos_home):
    _instala(tmp_path, nomos_home)
    info = smenu.render_info(st.status_skill(nomos_home,
                                             nomos_home / "skills" / "exemplo"))
    for trecho in ("Skill: exemplo@1.0.0", "risco", "publicador",
                   "ação recomendada"):
        assert trecho in info
