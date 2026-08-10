"""ABSORPTION-06 / C6+C7 — a fronteira de caminho e o censo de bypass.

Duas perguntas diferentes, e nenhuma delas é "a função funciona":

- **C6**: um plano consegue mutar algo FORA das raízes autorizadas? A resposta
  precisa ser não por todos os caminhos conhecidos de escape, incluindo os que
  já foram tentados em censos anteriores.
- **C7**: toda mutação alcançável passa por `PDP → PEP → adapter`? Um segundo
  caminho até o efeito é um segundo modelo de segurança, e o segundo é sempre
  o mais fraco.

Sobre hardlink: o censo original relatou "exfiltração confinada comprovada" e a
verificação independente **rebaixou** o achado — o mecanismo existe (realpath
não vê hardlink, porque um hardlink É o arquivo), mas nenhuma capacidade
governada cria hardlink, e o pré-requisito do ataque é um ator fora da cadeia,
com o mesmo UID e escrita dentro da raiz, que já teria a leitura de qualquer
jeito. O teste abaixo CONGELA esse comportamento conhecido em vez de fingir que
é uma defesa: a próxima auditoria encontra a resposta escrita, não a surpresa.

A regra genérica `st_nlink > 1 ⇒ DENY` foi considerada e recusada: quebraria
árvores legítimas (store do pnpm, `git clone --local`, `rsync --link-dest`) e
seria incompleta por construção — não há como enumerar todos os caminhos de um
inode sem varrer o filesystem. Heurística incompleta vendida como garantia é a
mesma "confiança falsa" que esta série de missões vem removendo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path as pathlib_Path

import pytest

from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.pdp.pep import PontoDeAplicacao
from nomos.runtime.governado import RuntimeGovernado

MUTANTES = frozenset({
    Category.WRITE_LOCAL, Category.NET_EGRESS, Category.CRED_USE,
    Category.CONNECTOR_USE, Category.DEVICE_MIC, Category.DEVICE_CAM,
    Category.DEVICE_SCREEN, Category.CODE_EXEC, Category.SKILL_INSTALL,
    Category.DESTRUCTIVE,
})


def _sim(_d):
    return True


@pytest.fixture()
def amb(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "isca.txt").write_text("ISCA-QUE-NAO-PODE-SER-TOCADA")
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True)
    return rt, ws, fora, ctx


def _plano(rt, ferramenta, **params):
    return rt.rodar("fronteira", passos=[{"id": "p", "ferramenta": ferramenta,
                                          "params": params}])


# ============================================ C6 — nenhuma mutação fora da raiz

def test_c6_traversal_com_ponto_ponto_nao_muta_fora(amb):
    rt, ws, fora, _ = amb
    alvo = str(ws / ".." / "fora" / "isca.txt")
    res = _plano(rt, "fs-escrever", alvo=alvo, conteudo="INVADIDO")
    assert not res.ok
    assert (fora / "isca.txt").read_text() == "ISCA-QUE-NAO-PODE-SER-TOCADA"


def test_c6_caminho_absoluto_fora_da_raiz_nao_muta(amb):
    rt, _, fora, _ = amb
    res = _plano(rt, "fs-escrever", alvo=str(fora / "isca.txt"),
                 conteudo="INVADIDO")
    assert not res.ok
    assert (fora / "isca.txt").read_text() == "ISCA-QUE-NAO-PODE-SER-TOCADA"


def test_c6_symlink_de_dentro_para_fora_nao_permite_escrita(amb):
    rt, ws, fora, _ = amb
    ponte = ws / "ponte.txt"
    ponte.symlink_to(fora / "isca.txt")
    res = _plano(rt, "fs-escrever", alvo=str(ponte), conteudo="INVADIDO")
    assert not res.ok
    assert (fora / "isca.txt").read_text() == "ISCA-QUE-NAO-PODE-SER-TOCADA"


def test_c6_cadeia_de_symlinks_nao_permite_escrita(amb):
    rt, ws, fora, _ = amb
    (ws / "a").symlink_to(ws / "b")
    (ws / "b").symlink_to(fora / "isca.txt")
    res = _plano(rt, "fs-escrever", alvo=str(ws / "a"), conteudo="INVADIDO")
    assert not res.ok
    assert (fora / "isca.txt").read_text() == "ISCA-QUE-NAO-PODE-SER-TOCADA"


def test_c6_symlink_de_diretorio_nao_vira_porta(amb):
    rt, ws, fora, _ = amb
    (ws / "atalho").symlink_to(fora, target_is_directory=True)
    res = _plano(rt, "fs-escrever", alvo=str(ws / "atalho" / "novo.txt"),
                 conteudo="INVADIDO")
    assert not res.ok
    assert not (fora / "novo.txt").exists(), "OUTSIDE_ROOT_MUTATION=TRUE"


def test_c6_caminho_intermediario_inexistente_nao_cria_fora(amb):
    rt, ws, fora, _ = amb
    res = _plano(rt, "fs-escrever",
                 alvo=str(ws / ".." / "fora" / "novo" / "x.txt"),
                 conteudo="INVADIDO")
    assert not res.ok
    assert not (fora / "novo").exists()


def test_c6_mover_cruzando_a_raiz_e_negado_nos_dois_sentidos(amb):
    rt, ws, fora, _ = amb
    dentro = ws / "meu.txt"
    dentro.write_text("meu")
    saida = _plano(rt, "fs-mover", alvo=str(dentro), destino=str(fora / "roubado.txt"))
    assert not saida.ok
    assert dentro.exists() and not (fora / "roubado.txt").exists()
    entrada = _plano(rt, "fs-mover", alvo=str(fora / "isca.txt"),
                     destino=str(ws / "trazido.txt"))
    assert not entrada.ok
    assert (fora / "isca.txt").exists()


def test_c6_apagar_cruzando_a_raiz_e_negado(amb):
    rt, _, fora, _ = amb
    res = _plano(rt, "fs-apagar", alvo=str(fora / "isca.txt"))
    assert not res.ok
    assert (fora / "isca.txt").exists()


def test_c6_apagar_arvore_por_symlink_nao_sai_da_raiz(amb, tmp_path):
    """A capacidade destrutiva não pode usar symlink como saída."""
    _rt0, ws, fora, ctx = amb
    dados = tmp_path / "fora" / "arvore-real"
    (dados / "sub").mkdir(parents=True)
    (dados / "sub" / "vital.txt").write_text("NAO PODE SUMIR")
    (ws / "atalho").symlink_to(dados, target_is_directory=True)
    caminho_pol = ctx["policy"].path
    d = json.loads(caminho_pol.read_text())
    d["rules"]["A6_DESTRUCTIVE"] = "REQUIRE_APPROVAL"
    caminho_pol.write_text(json.dumps(d))
    ctx["policy"] = PolicyEngine(caminho_pol)
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                          destrutivas=True)
    res = _plano(rt, "fs-apagar-arvore", alvo=str(ws / "atalho"))
    assert not res.ok
    assert (dados / "sub" / "vital.txt").exists(), "OUTSIDE_ROOT_MUTATION=TRUE"


def test_c6_hardlink_comportamento_CONHECIDO_e_congelado(amb):
    """Teste de CARACTERIZAÇÃO, não de defesa.

    Canonicalizar caminho não vê hardlink: um hardlink É o arquivo, não há
    link a resolver. A leitura pelo hardlink dentro da raiz é PERMITIDA, e
    isso é conhecido e aceito — o pré-requisito é um ator fora da cadeia
    governada, com o mesmo UID e escrita na raiz, que já teria a leitura do
    inode de qualquer forma (hardlink não muda dono nem modo).

    Nenhuma capacidade governada cria hardlink; foi verificado. O teste existe
    para que a próxima auditoria encontre a resposta escrita.
    """
    rt, ws, fora, _ = amb
    origem = fora / "isca.txt"
    link = ws / "link-duro.txt"
    os.link(origem, link)
    res = _plano(rt, "fs-ler", alvo=str(link))
    assert res.ok, "comportamento mudou: revise a documentação de caminho.py"
    assert res.missao.nos["p"].resultado == "ISCA-QUE-NAO-PODE-SER-TOCADA"
    # o mesmo arquivo pelo caminho REAL continua negado
    assert not _plano(rt, "fs-ler", alvo=str(origem)).ok


def test_c6_nenhuma_capacidade_governada_cria_hardlink():
    """A premissa que sustenta o teste acima, verificada na fonte."""
    import ast
    import pathlib

    import nomos.adapters as pacote
    raiz = pathlib.Path(pacote.__file__).parent
    culpados = []
    for arq in raiz.glob("*.py"):
        for no in ast.walk(ast.parse(arq.read_text())):
            if (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                    and no.func.attr in ("link", "hardlink_to")):
                culpados.append(f"{arq.name}:{no.lineno}")
    assert not culpados, f"adapter cria hardlink: {culpados}"


# ============================================ C7 — censo de bypass

def test_c7_toda_mutante_alcancavel_passa_por_pep(amb):
    rt, _, _, _ = amb
    vazando = [n for n in rt.capacidades_adapter
               if rt.registro.categoria_de(n) in MUTANTES
               and not isinstance(rt.executores_protegidos.get(n),
                                  PontoDeAplicacao)]
    assert not vazando, f"DIRECT_MUTATING_BYPASS: {vazando}"


def test_c7_toda_mutante_do_registro_esta_no_mapa_do_runtime(amb):
    rt, _, _, _ = amb
    vazando = []
    for nome, info in rt.registro.listar().items():
        if info.get("nativa"):
            continue
        if rt.registro.categoria_de(nome) in MUTANTES and nome not in rt.executores:
            vazando.append(nome)
    assert not vazando, f"alcançáveis pela ponte crua: {vazando}"


@pytest.mark.parametrize("ferramenta,params", [
    ("fs-escrever", {"conteudo": "x"}),
    ("fs-editar", {"de": "a", "para": "b"}),
    ("fs-criar-dir", {}),
    ("fs-apagar", {}),
])
def test_c7_cada_mutacao_deixa_pdp_e_pep_antes_do_efeito(amb, ferramenta, params):
    """A ordem é asseverada por capacidade, não por amostra."""
    rt, ws, _, ctx = amb
    alvo = ws / "arquivo.txt"
    alvo.write_text("a")
    _plano(rt, ferramenta, alvo=str(alvo), **params)
    ev = [json.loads(x).get("event") for x in
          (ctx["home"] / "logs" / "audit.jsonl").read_text().splitlines()
          if x.strip()]
    assert "pdp.decisao" in ev and "pep.aplicacao" in ev
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao")


def test_c7_registro_tardio_de_mutante_nao_executa(amb):
    """O ataque da ABSORPTION-05, revalidado depois das mudanças do GATE C."""
    rt, ws, _, _ = amb
    alvo = ws / "cru.txt"

    def _cru(**params):
        alvo.write_text("EXECUTOU CRU")
        return "ok"

    rt.registro.registrar("mutante-tardia", Category.WRITE_LOCAL, _cru,
                          origem="ataque")
    res = _plano(rt, "mutante-tardia")
    assert not res.ok
    assert not alvo.exists(), "MUTATION_OCCURRED por capacidade sem PEP"


# ============================================ cada camada com prova PRÓPRIA

def test_resolver_confina_por_si_mesmo_sem_depender_do_pdp(tmp_path):
    """A checagem de escopo do ADAPTER, isolada.

    Mutação achou: desligar `commonpath` em `caminho.resolver` não muda nada
    observável pela cadeia, porque o PDP também confina por escopo e recusa
    antes. Isso é defesa em profundidade funcionando — e é exatamente por isso
    que cada camada precisa da própria prova. Uma defesa cuja remoção ninguém
    percebe é uma defesa que a próxima refatoração remove.
    """
    from nomos.adapters.caminho import ErroEscopo, resolver
    raiz = tmp_path / "ws"
    raiz.mkdir()
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "isca.txt").write_text("x")
    assert resolver(str(raiz / "ok.txt"), (str(raiz),))
    for alvo in (str(fora / "isca.txt"), str(raiz / ".." / "fora" / "isca.txt")):
        with pytest.raises(ErroEscopo):
            resolver(alvo, (str(raiz),))


def test_guarda_de_symlink_recusa_link_que_fica_DENTRO_da_raiz(tmp_path):
    """O caso ÚNICO do guard de symlink, que a checagem de escopo não cobre.

    Symlink que sai da raiz já é pego pelo escopo. O que só este guard pega é
    o symlink que aponta para dentro: escrever por ele alteraria o alvo sem
    que o caminho auditado fosse o alvo real.
    """
    from nomos.adapters.caminho import ErroEscopo, resolver
    raiz = tmp_path / "ws"
    raiz.mkdir()
    real = raiz / "real.txt"
    real.write_text("conteudo")
    link = raiz / "link.txt"
    link.symlink_to(real)
    assert resolver(str(link), (str(raiz),))          # leitura passa
    with pytest.raises(ErroEscopo):
        resolver(str(link), (str(raiz),), para_escrita=True)


def test_politica_DENY_bloqueia_mesmo_com_aprovador_que_diz_sim(tmp_path):
    """`DENY` não é "peça aprovação": é não. Nem o aprovador reverte.

    Sem este teste, trocar `DENY → False` por `DENY → True` no gate do kernel
    passava despercebido pela suíte inteira do GATE C.
    """
    from nomos.kernel.policy import Decision, Effect, gate
    negado = Decision(effect=Effect.DENY, category="A6_DESTRUCTIVE",
                      target="/x", reason="teste")
    assert gate(negado, lambda _d: True) is False
    permitido = Decision(effect=Effect.ALLOW, category="A0_READ_LOCAL",
                         target="/x", reason="teste")
    assert gate(permitido, None) is True


def test_sem_aprovador_acao_sensivel_falha_fechada(tmp_path):
    """Contexto não interativo não pode virar passe livre."""
    from nomos.kernel.policy import Decision, Effect, gate
    pede = Decision(effect=Effect.REQUIRE_APPROVAL, category="A1_WRITE_LOCAL",
                    target="/x", reason="teste")
    assert gate(pede, None) is False, "sem aprovador virou ALLOW — fail-open"
    assert gate(pede, lambda _d: False) is False
    assert gate(pede, lambda _d: True) is True


def test_sem_aprovador_o_runtime_nao_registra_mutante(tmp_path):
    """O mesmo, pela cadeia: sem aprovador não há capacidade mutante."""
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    # Tipo EXATO. `pytest.raises(Exception)` é o mesmo anti-padrão que o censo
    # achou no test_n10 — e que o ruff me acusou três vezes hoje: passa com
    # qualquer erro, inclusive um bug do próprio teste.
    from nomos.orquestracao.registro import ErroRegistro
    with pytest.raises(ErroRegistro, match="aprovador|gate"):
        RuntimeGovernado(ctx, None, caminhos=(str(ws),), adapters=True)


def test_c8_raiz_sob_symlink_do_sistema_permite_mutacao(tmp_path):
    """No macOS, `/tmp` e `/var` são symlinks. Uma raiz ali dentro tornava
    TODA mutação impossível — leitura funcionava, escrita não — porque a
    caminhada de ancestrais subia até `/`.

    Este teste usa `tempfile.mkdtemp()` DE PROPÓSITO, e não o `tmp_path` do
    pytest: `tmp_path` já vem canonicalizado (`/private/var/...`), então a
    suíte inteira passava sobre um caminho que o operador real nunca digita.
    Era um ponto cego do ambiente de teste, não do código.
    """
    import shutil
    import tempfile
    base = pathlib_Path(tempfile.mkdtemp())
    try:
        home = base / "h"
        home.mkdir()
        ws = base / "ws"
        ws.mkdir()
        assert str(base).startswith("/var/"), f"esperava /var, veio {base}"
        ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
               "audit": AuditLog(home / "logs" / "audit.jsonl")}
        rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True)
        res = _plano(rt, "fs-escrever", alvo=str(ws / "novo.txt"), conteudo="ok")
        assert res.ok, f"raiz sob symlink do sistema bloqueou escrita: {res.motivo}"
        assert (ws / "novo.txt").read_text() == "ok"
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_c8_guarda_de_symlink_interno_sobrevive_a_correcao(tmp_path):
    """A correção do C8 não pode ter aberto o caso que o guard existe para pegar."""
    from nomos.adapters.caminho import ErroEscopo, resolver
    raiz = tmp_path / "ws"
    raiz.mkdir()
    (raiz / "sub").mkdir()
    real = raiz / "sub" / "real.txt"
    real.write_text("r")
    (raiz / "atalho").symlink_to(raiz / "sub", target_is_directory=True)
    with pytest.raises(ErroEscopo):
        resolver(str(raiz / "atalho" / "real.txt"), (str(raiz),),
                 para_escrita=True)
