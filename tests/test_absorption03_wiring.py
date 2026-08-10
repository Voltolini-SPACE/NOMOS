"""ABSORPTION-03 — os adapters são OPERACIONAIS, não só existentes.

O critério de encerramento da missão é explícito: filesystem e scheduler só
deixam de ser gap "de forma comportamental, adversarial e governada, não apenas
porque os módulos ou classes existem".

Estes testes provam o elo que faltava: a capacidade está no registro, o
planejador a conhece, o grafo a aceita, o PDP a autoriza, o PEP a aplica e o
efeito acontece — tudo pela cadeia, sem atalho.
"""
from __future__ import annotations

import json

import pytest

from nomos.adapters.wiring import CATEGORIAS_FS, IDEMPOTENTES_FS
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.runtime.governado import RuntimeGovernado


def _ctx(tmp_path):
    home = tmp_path / "h"
    home.mkdir(parents=True, exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


def _sim(_d):
    return True


def _nao(_d):
    return False


def _eventos(ctx):
    p = ctx["home"] / "logs" / "audit.jsonl"
    return [json.loads(x).get("event") for x in p.read_text().splitlines() if x.strip()]


def test_sem_adapters_o_registro_nao_os_conhece(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim)
    assert rt.capacidades_adapter == []
    assert not rt.registro.conhecida("fs-ler")


def test_adapters_entram_como_capacidade_dinamica_governada(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(tmp_path),))
    assert set(rt.capacidades_adapter) == set(CATEGORIAS_FS)
    assert rt.registro.conhecida("fs-ler")
    # registrar é ato A5 auditado — não edição de constante
    assert "registro.capacidade.registrada" in _eventos(ctx)


def test_risco_e_idempotencia_vem_do_registro(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(tmp_path),))
    assert rt.registro.risco_de("fs-ler") == "A0"
    assert rt.registro.risco_de("fs-apagar") == "A1"
    for nome in CATEGORIAS_FS:
        assert rt.registro.idempotente_de(nome) is (nome in IDEMPOTENTES_FS)


def test_sem_aprovador_nada_e_registrado(tmp_path):
    """Registrar exige gate: sem aprovação, a capacidade não entra."""
    from nomos.orquestracao.registro import ErroRegistro
    ctx = _ctx(tmp_path)
    with pytest.raises(ErroRegistro):
        RuntimeGovernado(ctx, _nao, adapters=True, caminhos=(str(tmp_path),))


def test_efeito_real_pela_cadeia_completa(tmp_path):
    """fs_escrever chega ao disco atravessando registry→PDP→PEP→adapter."""
    ctx = _ctx(tmp_path)
    raiz = tmp_path / "ws"
    raiz.mkdir()
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(raiz),))
    alvo = raiz / "criado.txt"
    res = rt.rodar("escrever", passos=[
        {"id": "w", "ferramenta": "fs-escrever",
         "params": {"alvo": str(alvo), "conteudo": "efeito governado"}}])
    assert res.ok, res.resumo()
    assert alvo.read_text() == "efeito governado"
    ev = _eventos(ctx)
    assert "pdp.decisao" in ev and "pep.aplicacao" in ev and "fs.escrever" in ev


def test_leitura_devolve_conteudo_pela_cadeia(tmp_path):
    ctx = _ctx(tmp_path)
    raiz = tmp_path / "ws"
    raiz.mkdir()
    (raiz / "a.txt").write_text("conteudo real")
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(raiz),))
    res = rt.rodar("ler", passos=[
        {"id": "r", "ferramenta": "fs-ler", "params": {"alvo": str(raiz / "a.txt")}}])
    assert res.ok
    assert res.missao.nos["r"].resultado == "conteudo real"


def test_escopo_do_pdp_barra_alvo_fora_da_raiz(tmp_path):
    ctx = _ctx(tmp_path)
    raiz = tmp_path / "ws"
    raiz.mkdir()
    fora = tmp_path / "segredo.txt"
    fora.write_text("SEGREDO")
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(raiz),))
    res = rt.rodar("vazar", passos=[
        {"id": "r", "ferramenta": "fs-ler", "params": {"alvo": str(fora)}}])
    assert not res.ok
    assert "escopo" in res.missao.nos["r"].detalhe


def test_capacidade_mutante_negada_sem_aprovacao_de_uso(tmp_path):
    """Registrar com aprovação não dá passe livre para USAR: cada nó A1 volta
    ao gate na hora de executar."""
    ctx = _ctx(tmp_path)
    raiz = tmp_path / "ws"
    raiz.mkdir()
    aprovacoes = {"n": 0}

    def _so_a_primeira(_d):
        aprovacoes["n"] += 1
        return aprovacoes["n"] <= len(CATEGORIAS_FS)   # aprova só os registros

    rt = RuntimeGovernado(ctx, _so_a_primeira, adapters=True, caminhos=(str(raiz),))
    res = rt.rodar("escrever", passos=[
        {"id": "w", "ferramenta": "fs-escrever",
         "params": {"alvo": str(raiz / "x.txt"), "conteudo": "y"}}])
    assert not res.ok
    assert res.missao.nos["w"].status == "NEGADO"
    assert not (raiz / "x.txt").exists()


def test_nao_idempotente_nao_ganha_retry(tmp_path):
    """fs_apagar é A1 e não-idempotente ⇒ uma tentativa só."""
    from nomos.orquestracao.recuperacao import PoliticaRecuperacao
    ctx = _ctx(tmp_path)
    raiz = tmp_path / "ws"
    raiz.mkdir()
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(raiz),),
                          politica_recuperacao=PoliticaRecuperacao(
                              max_tentativas=5, backoff_base=0.0))
    res = rt.rodar("apagar inexistente", passos=[
        {"id": "d", "ferramenta": "fs-apagar",
         "params": {"alvo": str(raiz / "nao-existe.txt")}}])
    assert not res.ok
    assert res.missao.nos["d"].tentativas == 1


def test_apenas_leitura_registra_so_as_tres(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim, adapters=True,
                          adapters_apenas_leitura=True, caminhos=(str(tmp_path),))
    assert set(rt.capacidades_adapter) == IDEMPOTENTES_FS
    assert not rt.registro.conhecida("fs-apagar")


def test_allowlist_nativa_de_8_permanece_intacta():
    """Adapters não engordam a superfície nativa — entram como dinâmicas."""
    from nomos.agents.manifest import FERRAMENTAS
    assert len(FERRAMENTAS) == 8
    assert not any(n.startswith("fs_") for n in FERRAMENTAS)


def test_capacidade_dinamica_nao_escapa_do_pep(tmp_path):
    """Regressão do bypass que o wiring abriu e a trilha denunciou.

    O `Orquestrador` procura executor primeiro em `executores` e só depois cai
    em `registro.executor_de()`. Sem embrulhar as dinâmicas, ele chamava a
    ponte CRUA — PDP e PEP fora do caminho. Este teste fixa a correção: TODA
    capacidade executável pelo runtime é um `PontoDeAplicacao`.
    """
    from nomos.pdp.pep import PontoDeAplicacao
    ctx = _ctx(tmp_path)
    raiz = tmp_path / "ws"
    raiz.mkdir()
    rt = RuntimeGovernado(ctx, _sim, adapters=True, caminhos=(str(raiz),))
    for nome in rt.capacidades_adapter:
        assert isinstance(rt.executores_protegidos[nome], PontoDeAplicacao), nome
        assert nome in rt.executores
    # e a execução real deixa a marca do PDP na trilha
    rt.rodar("ler", passos=[{"id": "r", "ferramenta": "fs-metadados",
                             "params": {"alvo": str(raiz)}}])
    ev = _eventos(ctx)
    assert "pdp.decisao" in ev and "pep.aplicacao" in ev


# ------------------------------------------------------------- scheduler wiring

def test_scheduler_registrado_como_capacidade_governada(tmp_path):
    from nomos.adapters.scheduler import ArmazemJobs, Scheduler
    from nomos.adapters.wiring import CATEGORIAS_SCHED, registrar_scheduler
    from nomos.orquestracao.registro import RegistroCapacidades
    ctx = _ctx(tmp_path)
    reg = RegistroCapacidades(policy=ctx["policy"], approver=_sim, audit=ctx["audit"])
    sched = Scheduler(ArmazemJobs(tmp_path / "j.db"), executor=lambda d, i: None)
    nomes = registrar_scheduler(reg, sched)
    assert set(nomes) == set(CATEGORIAS_SCHED)
    assert reg.risco_de("sched-listar") == "A0"
    assert reg.risco_de("sched-criar") == "A5"       # armar execução é sensível
    assert reg.risco_de("sched-cancelar") == "A1"    # desarmar é direção segura


def test_desarmar_e_menos_sensivel_que_armar(tmp_path):
    """A saída de emergência não pode ter fechadura mais dura que a entrada."""
    from nomos.adapters.wiring import CATEGORIAS_SCHED
    from nomos.kernel.policy import Category
    assert CATEGORIAS_SCHED["sched-criar"] is Category.CODE_EXEC
    assert CATEGORIAS_SCHED["sched-habilitar"] is Category.CODE_EXEC
    for desarmar in ("sched-desabilitar", "sched-cancelar", "sched-apagar"):
        assert CATEGORIAS_SCHED[desarmar] is Category.WRITE_LOCAL


def test_operacoes_de_scheduler_sao_capacidades_separadas(tmp_path):
    """Listar não carrega a autoridade de cancelar."""
    from nomos.adapters.wiring import CATEGORIAS_SCHED, IDEMPOTENTES_SCHED
    assert len(CATEGORIAS_SCHED) == 7
    assert IDEMPOTENTES_SCHED == {"sched-listar", "sched-status"}


# --------------------- correções vindas do censo adversarial da FASE 6

def test_pdp_confina_por_componente_nao_por_prefixo(tmp_path):
    """`/ws/../etc/passwd` NÃO está sob `/ws` — o `..` derrotava o escopo.

    Grave porque as ferramentas NATIVAS (`arquivo_ler`, `arquivo_resumir`) não
    têm resolver próprio: ali o escopo do PDP é o ÚNICO confinamento.
    """
    from nomos.pdp.decisor import _no_escopo
    ws = tmp_path / "ws"
    ws.mkdir()
    assert _no_escopo(str(ws / "ok.txt"), (str(ws),))
    assert not _no_escopo(str(ws / ".." / "segredo.txt"), (str(ws),))
    assert not _no_escopo("/etc/passwd", (str(ws),))
    assert not _no_escopo(str(tmp_path / "ws-outro" / "x"), (str(ws),))


def test_traversal_barrado_no_pdp_para_ferramenta_nativa(tmp_path):
    """Ponta a ponta com capacidade NATIVA e escopo ligado."""
    ctx = _ctx(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "segredo.txt").write_text("SEGREDO")
    rt = RuntimeGovernado(ctx, _sim, caminhos=(str(ws),))
    res = rt.rodar("escapar", passos=[
        {"id": "r", "ferramenta": "arquivo_ler",
         "params": {"alvo": str(ws / ".." / "segredo.txt")}}])
    assert not res.ok
    assert "escopo" in res.missao.nos["r"].detalhe


def test_capacidade_mutante_exige_raiz_explicita(tmp_path):
    """Fail-closed: `adapters=True` sem `caminhos` daria delete de caminho
    arbitrário — MENOS confinado que o nativo que substitui."""
    ctx = _ctx(tmp_path)
    with pytest.raises(ValueError, match="exige `raizes`"):
        RuntimeGovernado(ctx, _sim, adapters=True)      # sem caminhos


def test_apenas_leitura_dispensa_raiz(tmp_path):
    """Leitura sem raiz é o comportamento herdado e consciente."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, _sim, adapters=True, adapters_apenas_leitura=True)
    assert set(rt.capacidades_adapter) == IDEMPOTENTES_FS


def test_fs_listar_com_padrao_absoluto_erro_tipado(tmp_path):
    """Contrato: adapter falha com subclasse de ErroCapacidade, nunca com
    NotImplementedError crua do pathlib."""
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest, ErroInvalido
    from nomos.adapters.filesystem import FilesystemAdapter
    from nomos.adapters.wiring import CATEGORIAS_FS

    class _Reg:
        conhecida = staticmethod(lambda n: n in CATEGORIAS_FS)
        categoria_de = staticmethod(lambda n: CATEGORIAS_FS[n])
        risco_de = staticmethod(lambda n: "A0")
        idempotente_de = staticmethod(lambda n: True)
        executor_de = staticmethod(lambda n: None)

    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = CapabilityContext.de_registro(_Reg(), "fs-listar", "s", raizes=(str(ws),))
    with pytest.raises(ErroInvalido, match="relativo"):
        FilesystemAdapter().executar(
            CapabilityRequest(capacidade="fs-listar", alvo=str(ws),
                              argumentos={"padrao": "/etc/*"}), ctx)


def test_fs_criar_dir_funciona_e_e_confinado(tmp_path):
    """`fs-criar-dir` não tinha teste nenhum — apontado pelo censo."""
    from nomos.adapters.contrato import CapabilityContext, CapabilityRequest, ErroEscopo
    from nomos.adapters.filesystem import FilesystemAdapter
    from nomos.adapters.wiring import CATEGORIAS_FS

    class _Reg:
        conhecida = staticmethod(lambda n: n in CATEGORIAS_FS)
        categoria_de = staticmethod(lambda n: CATEGORIAS_FS[n])
        risco_de = staticmethod(lambda n: "A1")
        idempotente_de = staticmethod(lambda n: False)
        executor_de = staticmethod(lambda n: None)

    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = CapabilityContext.de_registro(_Reg(), "fs-criar-dir", "s", raizes=(str(ws),))
    ad = FilesystemAdapter()
    r = ad.executar(CapabilityRequest(capacidade="fs-criar-dir",
                                      alvo=str(ws / "novo" / "sub")), ctx)
    assert r.ok and r.efeito_aplicado
    assert (ws / "novo" / "sub").is_dir()
    # idempotente na prática: recriar não marca efeito
    r2 = ad.executar(CapabilityRequest(capacidade="fs-criar-dir",
                                       alvo=str(ws / "novo" / "sub")), ctx)
    assert r2.ok and not r2.efeito_aplicado
    with pytest.raises(ErroEscopo):
        ad.executar(CapabilityRequest(capacidade="fs-criar-dir",
                                      alvo=str(tmp_path / "fora")), ctx)
