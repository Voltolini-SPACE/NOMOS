"""FASE 1 (ABSORPTION-01) — o runtime governado é caminho REAL de execução.

Estes testes provam o que a validação anterior não podia provar: que o pacote
`orquestracao` deixou de ser biblioteca sem chamador e virou runtime, e que ao
virar runtime NÃO abriu nenhum caminho novo de autorização.

O eixo é sempre o mesmo: o que decide risco é o REGISTRO; o que decide execução
é o GATE do kernel; o plano é dado, nunca autoridade.
"""
from __future__ import annotations

import pytest

from nomos.agents.manifest import FERRAMENTAS
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, Effect, PolicyEngine
from nomos.orquestracao.grafo import ErroGrafo, GrafoTarefas, No, Orquestrador
from nomos.orquestracao.recuperacao import GerenciadorRecuperacao, PoliticaRecuperacao
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.runtime.governado import (
    ErroRuntime, ResultadoExecucao, RuntimeGovernado, executores_nativos,
)


# ---------------------------------------------------------------- utilidades

def _ctx(tmp_path):
    home = tmp_path / "nomos-home"
    home.mkdir(parents=True, exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


def _aprova_tudo(decision):
    """Aprovador que sempre aprova — para provar que o gate é consultado
    (e não para afrouxar nada: sem ele, sensível é negado)."""
    return True


def _nega_tudo(decision):
    return False


def _passo(pid, ferramenta, **kw):
    d = {"id": pid, "ferramenta": ferramenta}
    d.update(kw)
    return d


# ------------------------------------------------- 1. caller real / cadeia

def test_runtime_exige_politica_carregada(tmp_path):
    """Sem política no contexto ⇒ nem constrói (fail-closed)."""
    with pytest.raises(ErroRuntime):
        RuntimeGovernado({}, None)
    with pytest.raises(ErroRuntime):
        RuntimeGovernado(None, None)


def test_executores_nativos_sao_exatamente_a_allowlist(tmp_path):
    """O runtime não inventa capacidade: o conjunto de executores é
    EXATAMENTE a allowlist de 8 ferramentas do manifesto."""
    ctx = _ctx(tmp_path)
    ex = executores_nativos(ctx)
    assert set(ex) == set(FERRAMENTAS)
    assert len(ex) == 8


def test_dag_valido_executa_em_ordem_topologica(tmp_path):
    ctx = _ctx(tmp_path)
    alvo = tmp_path / "a.txt"
    alvo.write_text("conteudo")
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    res = rt.rodar("ler e diagnosticar", passos=[
        _passo("a", "arquivo_ler", params={"alvo": str(alvo)}),
        _passo("b", "doutor", depende_de=["a"]),
    ])
    assert res.ok, res.resumo()
    assert res.missao.ordem == ("a", "b")
    assert res.missao.nos["a"].status == "OK"
    assert res.missao.nos["b"].status == "OK"


def test_multiplos_niveis_de_dependencia(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    res = rt.rodar("tres niveis", passos=[
        _passo("a", "doutor"),
        _passo("b", "doutor", depende_de=["a"]),
        _passo("c", "doutor", depende_de=["b"]),
    ])
    assert res.ok
    assert res.missao.ordem == ("a", "b", "c")


# ------------------------------------------------- 2. falhas estruturais

def test_ciclo_falha_deterministicamente_e_nada_executa(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    res = rt.rodar("ciclo", passos=[
        _passo("a", "doutor", depende_de=["b"]),
        _passo("b", "doutor", depende_de=["a"]),
    ])
    assert not res.ok
    assert "ciclo" in res.motivo
    assert res.missao is None            # nada executou


def test_capability_inexistente_falha_fechada(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    res = rt.rodar("shell", passos=[
        _passo("s", "shell_exec", params={"alvo": "rm -rf /"}),
    ])
    assert not res.ok
    assert res.missao is None
    assert any("fora do registro" in r["motivo"] for r in res.plano.rejeitados)


def test_planner_malformado_falha_fechado(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    for passos in ([{"nao": "e um passo"}], ["texto solto"], [], [{"id": "A!", "ferramenta": "doutor"}]):
        res = rt.rodar("malformado", passos=passos)
        assert not res.ok, passos
        assert res.missao is None


def test_llm_ilegivel_falha_fechado(tmp_path):
    """Sugestão de modelo é DATA, nunca autoridade."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    plano = rt.planejar("x", llm=lambda _: "isto não é json")
    assert not plano.ok
    plano2 = rt.planejar("x", llm=lambda _: '{"nao": "lista"}')
    assert not plano2.ok


# ------------------------------------------------- 3. risco vem do registro

def test_categoria_vem_do_registro_nao_do_plano(tmp_path):
    """Passo que tenta declarar categoria baixa não rebaixa o risco real."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    plano = rt.planejar("mentir sobre risco", passos=[
        _passo("w", "arquivo_escrever", categoria="A0_READ_LOCAL",
               params={"alvo": "x.txt", "conteudo": "y"}),
    ])
    assert plano.ok
    (passo,) = plano.passos
    assert passo.categoria is FERRAMENTAS["arquivo_escrever"]
    assert passo.categoria is not Category.READ_LOCAL
    assert plano.risco != "A0"
    assert plano.exige_aprovacao


def test_no_nao_compra_idempotencia_no_grafo(tmp_path):
    """ABSORPTION-01: grafo montado à mão não pode declarar idempotência que
    a capacidade não tem — senão 1 aprovação vira N efeitos reais."""
    reg = RegistroCapacidades()
    assert reg.idempotente_de("arquivo_escrever") is False
    with pytest.raises(ErroGrafo, match="não define o próprio risco"):
        GrafoTarefas([No("w", "arquivo_escrever", idempotente=True)], reg)


def test_no_pode_ser_mais_conservador_que_o_registro(tmp_path):
    """Declarar MENOS idempotência é seguro e permitido."""
    reg = RegistroCapacidades()
    assert reg.idempotente_de("arquivo_ler") is True
    g = GrafoTarefas([No("r", "arquivo_ler", idempotente=False)], reg)
    assert "r" in g.nos


def test_recuperacao_ignora_idempotencia_do_no(tmp_path):
    """Defesa em profundidade: mesmo recebendo um nó mentiroso, a recuperação
    só concede retry com o valor autoritativo passado pelo orquestrador."""
    ger = GerenciadorRecuperacao(politica=PoliticaRecuperacao(max_tentativas=3),
                                 dormir=lambda _s: None)
    mentiroso = No("n", "arquivo_escrever", idempotente=True)
    chamadas = {"n": 0}

    def _falha(**kw):
        chamadas["n"] += 1
        raise RuntimeError("boom")

    ok, _motivo, tentativas = ger.executar(mentiroso, _falha, {})
    assert not ok
    assert tentativas == 1          # sem kwarg autoritativo ⇒ fail-closed
    assert chamadas["n"] == 1


# ------------------------------------------------- 4. gate preservado

def test_capacidade_mutante_negada_sem_aprovacao(tmp_path):
    ctx = _ctx(tmp_path)
    alvo = tmp_path / "novo.txt"
    rt = RuntimeGovernado(ctx, _nega_tudo)
    res = rt.rodar("escrever", passos=[
        _passo("w", "arquivo_escrever",
               params={"alvo": str(alvo), "conteudo": "x"}),
    ])
    assert not res.ok
    assert res.missao.nos["w"].status == "NEGADO"
    assert not alvo.exists()          # nenhum efeito colateral


def test_deny_bloqueia_dependentes_transitivos(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _nega_tudo)
    res = rt.rodar("negado propaga", passos=[
        _passo("w", "arquivo_escrever",
               params={"alvo": str(tmp_path / "n.txt"), "conteudo": "x"}),
        _passo("b", "doutor", depende_de=["w"]),
        _passo("c", "doutor", depende_de=["b"]),
    ])
    assert res.missao.nos["w"].status == "NEGADO"
    assert res.missao.nos["b"].status == "BLOQUEADO"
    assert res.missao.nos["c"].status == "BLOQUEADO"


def test_deny_nao_vira_retry_then_allow(tmp_path):
    """Recuperação NUNCA reexecuta nó negado: DENY não é falha transiente."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _nega_tudo)
    res = rt.rodar("deny", passos=[
        _passo("w", "arquivo_escrever",
               params={"alvo": str(tmp_path / "n.txt"), "conteudo": "x"}),
    ])
    no = res.missao.nos["w"]
    assert no.status == "NEGADO"
    assert no.tentativas == 0          # não houve NENHUMA tentativa de execução


def test_execucao_parcial_ramo_independente_segue(tmp_path):
    """Falha num ramo não abandona o que ainda é seguro fazer."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    res = rt.rodar("parcial", passos=[
        _passo("mau", "arquivo_ler", params={"alvo": str(tmp_path / "nao-existe")}),
        _passo("dep", "doutor", depende_de=["mau"]),
        _passo("bom", "doutor"),
    ])
    assert not res.ok
    assert res.missao.nos["mau"].status == "FALHOU"
    assert res.missao.nos["dep"].status == "BLOQUEADO"
    assert res.missao.nos["bom"].status == "OK"      # ramo independente seguiu


# ------------------------------------------------- 5. retry / circuito

def _reg_com(nome, categoria, idempotente, executor):
    reg = RegistroCapacidades(policy=_PolicyOK(), approver=_aprova_tudo)
    reg.registrar(nome, categoria, executor, origem="teste",
                  idempotente=idempotente)
    return reg


class _PolicyOK:
    """Política mínima que permite registrar e executar (o gate É consultado)."""

    def decide(self, categoria, target=""):
        from nomos.kernel.policy import Decision
        cat = categoria.value if hasattr(categoria, "value") else str(categoria)
        return Decision(Effect.ALLOW, cat, target, "teste")


def test_retry_permitido_para_capacidade_idempotente(tmp_path):
    tentativas = {"n": 0}

    def _instavel(**kw):
        tentativas["n"] += 1
        if tentativas["n"] < 3:
            raise RuntimeError("transiente")
        return "ok"

    reg = _reg_com("leitura-remota", Category.READ_LOCAL, True, _instavel)
    orq = Orquestrador(reg, _PolicyOK(), approver=_aprova_tudo,
                       recuperacao=GerenciadorRecuperacao(
                           politica=PoliticaRecuperacao(max_tentativas=3),
                           dormir=lambda _s: None))
    res = orq.executar(GrafoTarefas([No("n", "leitura-remota")], reg))
    assert res.ok
    assert res.nos["n"].tentativas == 3


def test_retry_proibido_para_capacidade_nao_idempotente(tmp_path):
    tentativas = {"n": 0}

    def _instavel(**kw):
        tentativas["n"] += 1
        raise RuntimeError("transiente")

    reg = _reg_com("escrita-remota", Category.WRITE_LOCAL, False, _instavel)
    orq = Orquestrador(reg, _PolicyOK(), approver=_aprova_tudo,
                       recuperacao=GerenciadorRecuperacao(
                           politica=PoliticaRecuperacao(max_tentativas=5),
                           dormir=lambda _s: None))
    res = orq.executar(GrafoTarefas([No("n", "escrita-remota")], reg))
    assert not res.ok
    assert tentativas["n"] == 1          # efeito colateral nunca repetido


def test_circuito_abre_e_nao_vira_bypass(tmp_path):
    """Circuito aberto FALHA a chamada — nunca a deixa passar sem gate."""
    def _sempre_falha(**kw):
        raise RuntimeError("down")

    reg = _reg_com("flaky", Category.READ_LOCAL, True, _sempre_falha)
    ger = GerenciadorRecuperacao(
        politica=PoliticaRecuperacao(max_tentativas=1, circuito_limite=2),
        dormir=lambda _s: None)
    orq = Orquestrador(reg, _PolicyOK(), approver=_aprova_tudo, recuperacao=ger)
    for _ in range(2):
        orq.executar(GrafoTarefas([No("n", "flaky")], reg))
    res = orq.executar(GrafoTarefas([No("n", "flaky")], reg))
    assert not res.ok
    assert "circuito aberto" in res.nos["n"].detalhe


# ------------------------------------------------- 6. auditoria / evidência

def test_execucao_gera_trilha_auditavel(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    res = rt.rodar("auditar", passos=[_passo("a", "doutor")])
    assert res.ok
    trilha = (ctx["home"] / "logs" / "audit.jsonl").read_text()
    for evento in ("runtime.execucao.inicio", "orquestracao.missao.inicio",
                   "orquestracao.no.ok", "runtime.execucao.fim"):
        assert evento in trilha, evento


def test_resumo_nao_vaza_conteudo_de_params(tmp_path):
    """Evidência carrega metadado, não payload."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _nega_tudo)
    segredo = "SENHA-SUPER-SECRETA-123"
    res = rt.rodar("segredo", passos=[
        _passo("w", "arquivo_escrever",
               params={"alvo": str(tmp_path / "s.txt"), "conteudo": segredo}),
    ])
    assert segredo not in repr(res.resumo())


# ------------------------------------------------- 7. sem execução fora do boundary

def test_nenhum_executor_generico_no_runtime(tmp_path):
    """Nenhuma capacidade nativa aceita comando/shell: os executores são as 8
    ferramentas, e params desconhecidos não viram argumento novo."""
    ctx = _ctx(tmp_path)
    ex = executores_nativos(ctx)
    for nome in ("shell", "bash", "exec", "subprocess", "git", "http", "pty"):
        assert nome not in ex


def test_params_invalidos_falham_fechado(tmp_path):
    ctx = _ctx(tmp_path)
    ex = executores_nativos(ctx)
    with pytest.raises(ErroRuntime):
        ex["arquivo_ler"](alvo=["nao", "e", "texto"])


def test_plano_reprovado_nao_executa(tmp_path):
    from nomos.orquestracao.planejador import PlanoTipado
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    res = rt.executar(PlanoTipado(ok=False, objetivo="x", motivo="reprovado"))
    assert isinstance(res, ResultadoExecucao)
    assert not res.ok
    assert res.missao is None


def test_executar_rejeita_tipo_inesperado(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _aprova_tudo)
    with pytest.raises(ErroRuntime):
        rt.executar({"ok": True})        # dict não é PlanoTipado
