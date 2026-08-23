"""O botão de executar: reusa o approver da fila, não inventa consentimento.

Medido em home ISOLADA, com a política e o cadeado reais do dono:
  sistema-info (A0 puro)      -> rc=0, approver NUNCA chamado (política ALLOW)
  reach-rss    (A1+A2)        -> approver chamado DUAS vezes, uma por permissão
  reach-rss com cadeado ligado-> A2 vira DENY e o approver nem é consultado

Isso decide o desenho: a tela não classifica skill nenhuma. Passa o approver
da fila sempre, e quem decide é o PDP. A fronteira mora na política.
"""
from __future__ import annotations

from nomos.interface import painel_web as pw


def _sk(instaladas, token="T", base="/d/x"):
    return {"instaladas": instaladas, "prontas": [], "diagnostico": "",
            "token": token, "base": base}


def test_botao_so_aparece_com_token():
    """Sem token CSRF a página é leitura — não oferece ação que recusaria."""
    inst = [{"name": "x", "version": "1", "permissions": ["A0_READ_LOCAL"]}]
    com = pw._secao_skills({}, _sk(inst))
    sem = pw._secao_skills({}, _sk(inst, token=None))
    assert "skills/rodar" in com
    assert "skills/rodar" not in sem
    assert "<button" not in sem


def test_a0_puro_avisa_que_roda_direto():
    """Não é caso especial da tela: a política diz ALLOW e `preparar_execucao`
    nem chama o approver. A tela só conta o que vai acontecer."""
    inst = [{"name": "x", "version": "1", "permissions": ["A0_READ_LOCAL"]}]
    html = pw._secao_skills({}, _sk(inst))
    assert "roda direto" in html
    assert "aprovações" not in html.lower().split("roda direto")[0][-200:]


def test_avisa_quantas_aprovacoes_um_clique_gera():
    """O gate é POR PERMISSÃO. Sem o aviso, o dono clica uma vez e vê pedidos
    aparecendo em sequência sem saber que são do mesmo clique."""
    inst = [{"name": "r", "version": "1",
             "permissions": ["A1_WRITE_LOCAL", "A2_NET_EGRESS"]}]
    html = pw._secao_skills({}, _sk(inst))
    assert "2 aprovações" in html
    assert "deste mesmo clique" in html


def test_uma_permissao_fala_no_singular():
    inst = [{"name": "r", "version": "1", "permissions": ["A1_WRITE_LOCAL"]}]
    html = pw._secao_skills({}, _sk(inst))
    assert "1 aprovação" in html
    assert "1 aprovações" not in html


def test_a0_nao_conta_na_soma():
    """A0 não gera pedido — contá-lo prometeria uma aprovação que não vem."""
    inst = [{"name": "r", "version": "1",
             "permissions": ["A0_READ_LOCAL", "A2_NET_EGRESS"]}]
    html = pw._secao_skills({}, _sk(inst))
    assert "1 aprovação" in html


def test_resultado_mostra_rc_e_saida_reais():
    """Nunca inventar sucesso: o rc é o da própria skill."""
    d = _sk([])
    d["saida"] = {"nome": "sistema-info", "rc": 0, "texto": '{"ok": true}'}
    html = pw._secao_skills({}, d)
    assert "sistema-info" in html and "rc=0" in html and "ok" in html


def test_falha_nao_e_disfarcada_de_sucesso():
    d = _sk([])
    d["saida"] = {"nome": "r", "rc": 3, "texto": "permissão A2 negada"}
    html = pw._secao_skills({}, d)
    assert "rc=3" in html
    assert "negada" in html
    assert "ok-banner" not in html      # verde só quando rc=0


def test_a_pagina_nao_executa_sozinha():
    """Renderizar não pode disparar execução — a tela é leitura até o clique."""
    import inspect
    src = inspect.getsource(pw._secao_skills)
    for proibido in ("executar_json", "executar(", "subprocess"):
        assert proibido not in src, f"_secao_skills chama {proibido}"
