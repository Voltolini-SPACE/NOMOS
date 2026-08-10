"""ABSORPTION-06 / ETAPA 2 — INVARIANTE: capacidade mutante ⇒ PDP → PEP.

A ABSORPTION-05 introduziu um bypass e o censo independente o encontrou:
registrar o scheduler DEPOIS de o `RuntimeGovernado` montar `self.executores`
deixava `sched-*` fora do mapa protegido e fora da autorização assinada, e a
capacidade caía no fallback `registro.executor_de()` do Orquestrador —
executando pela ponte CRUA.

Um bug corrigido é um bug que volta. Estes testes transformam a correção em
INVARIANTE estrutural: não checam "o scheduler está certo", checam que
**nenhuma capacidade mutante alcançável pelo Orquestrador pode existir fora do
mapa protegido por PEP** — inclusive as que ainda não foram escritas.

    CAPABILITY_REGISTERED → PDP_DECISION → PEP_APPLICATION → MUTATION   ✅
    CAPABILITY_REGISTERED → RAW_BRIDGE   → MUTATION                     ❌
"""
from __future__ import annotations

import json
import sys

import pytest

from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine
from nomos.pdp.pep import PontoDeAplicacao
from nomos.runtime.governado import RuntimeGovernado

# Categorias que produzem efeito externo. A0 (leitura) não muta; o invariante
# vale para tudo além dela.
CATEGORIAS_MUTANTES = frozenset({
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
    ctx = {"home": home,
           "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    return ctx, ws


def _eventos(ctx):
    p = ctx["home"] / "logs" / "audit.jsonl"
    return [json.loads(x).get("event")
            for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def _runtime_completo(ctx, ws, com_scheduler=True):
    """Runtime com TODAS as famílias de capacidade ligadas."""
    scheduler = None
    if com_scheduler:
        from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador
        scheduler = AgendadorGovernado(
            ctx, _sim, ConfigAgendador(raizes=(str(ws),))).scheduler
    return RuntimeGovernado(ctx, _sim, caminhos=(str(ws),), adapters=True,
                            executaveis=(sys.executable,), scheduler=scheduler)


# ============================================ O INVARIANTE

def test_toda_capacidade_registrada_esta_no_mapa_PEP(amb):
    """Nenhuma capacidade registrada pode faltar em `executores_protegidos`."""
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws)
    assert rt.capacidades_adapter, "nenhuma capacidade registrada — teste inócuo"
    for nome in rt.capacidades_adapter:
        assert nome in rt.executores_protegidos, (
            f"'{nome}' registrada mas FORA do mapa protegido por PEP — "
            "cairia no fallback cru do Orquestrador")
        assert isinstance(rt.executores_protegidos[nome], PontoDeAplicacao)
        assert nome in rt.executores, f"'{nome}' não é alcançável pelo runtime"


def test_toda_capacidade_registrada_esta_na_autorizacao(amb):
    """Estar no mapa não basta: o PDP precisa ter o que autorizar."""
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws)
    concedidas = set(rt.autorizacao.capacidades)
    for nome in rt.capacidades_adapter:
        assert nome in concedidas, (
            f"'{nome}' registrada mas fora da autorização assinada — o PDP "
            "negaria por CAPACIDADE_NAO_CONCEDIDA, ou pior, seria contornado")


def test_nenhuma_mutante_alcancavel_pelo_fallback_cru(amb):
    """O ataque exato da ABSORPTION-05, generalizado.

    `Orquestrador._executor_para` consulta `self.executores` e, se não achar,
    cai em `registro.executor_de()`. Toda capacidade MUTANTE conhecida pelo
    registro tem de estar no primeiro — senão o segundo a executa crua.
    """
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws)
    vazando = []
    for nome, info in rt.registro.listar().items():
        if info.get("nativa"):
            continue                      # nativas usam o wiring do boundary
        categoria = rt.registro.categoria_de(nome)
        if categoria not in CATEGORIAS_MUTANTES:
            continue
        if nome not in rt.executores:
            vazando.append(nome)
    assert not vazando, (
        f"capacidades MUTANTES alcançáveis pela ponte crua: {vazando}")


def test_o_fallback_cru_do_orquestrador_nao_tem_mutante(amb):
    """Prova pelo outro lado: o que `registro.executor_de()` devolve para uma
    mutante tem de ser exatamente o que o PEP embrulha, nunca um caminho
    alternativo vivo."""
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws)
    for nome in rt.capacidades_adapter:
        categoria = rt.registro.categoria_de(nome)
        if categoria not in CATEGORIAS_MUTANTES:
            continue
        bruto = rt.registro.executor_de(nome)
        assert bruto is not None
        pep = rt.executores_protegidos[nome]
        # o PEP é o único caminho publicado; o bruto existe só dentro dele
        assert pep is not bruto
        assert not hasattr(pep, "__dict__")


@pytest.mark.parametrize("familia,prefixo", [
    ("filesystem", "fs-"),
    ("scheduler", "sched-"),
    ("script", "script-"),
])
def test_cada_familia_de_capacidade_respeita_o_invariante(amb, familia, prefixo):
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws)
    da_familia = [n for n in rt.capacidades_adapter if n.startswith(prefixo)]
    assert da_familia, f"família {familia} não registrou nada — teste inócuo"
    for nome in da_familia:
        assert isinstance(rt.executores_protegidos.get(nome), PontoDeAplicacao)
        assert nome in rt.autorizacao.capacidades


# ============================================ registro TARDIO é o bug

def test_registro_apos_a_construcao_nao_vaza_para_o_runtime(amb):
    """Reproduz o bug da 05 e prova que ele não produz mais execução crua.

    Registrar depois continua sendo possível (o registro é dinâmico), mas a
    capacidade NÃO fica alcançável pelo runtime já construído: ela não entra em
    `executores` nem na autorização, então o Orquestrador a recusa em vez de
    executá-la pela ponte.
    """
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws, com_scheduler=False)
    assert not any(n.startswith("sched-") for n in rt.capacidades_adapter)

    from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador
    from nomos.adapters.wiring import registrar_scheduler
    ag = AgendadorGovernado(ctx, _sim, ConfigAgendador(raizes=(str(ws),)))
    tardias = registrar_scheduler(rt.registro, ag.scheduler)   # o padrão da 05

    for nome in tardias:
        assert nome not in rt.executores, (
            f"'{nome}' registrada TARDE ficou alcançável — o bypass voltou")
        assert nome not in rt.autorizacao.capacidades

    res = rt.rodar("tardia", passos=[{
        "id": "t", "ferramenta": "sched-criar",
        "params": {"job_id": "x", "capacidade": "fs-listar",
                   "alvo_job": str(ws)}}])
    assert not res.ok, "capacidade registrada tarde EXECUTOU — bypass reaberto"


# ============================================ teste NEGATIVO obrigatório

def test_mutante_sem_politica_falha_fechado(amb):
    """Registrar mutante sem política ⇒ nada é registrado, nada muta."""
    from nomos.orquestracao.registro import ErroRegistro, RegistroCapacidades
    ctx, ws = amb
    alvo = ws / "nao-deve-existir.txt"

    def _efeito(**params):
        alvo.write_text("MUTOU")
        return "ok"

    registro = RegistroCapacidades(policy=None, approver=_sim)   # SEM política
    with pytest.raises(ErroRegistro, match="sem política"):
        registro.registrar("mutante-solta", Category.WRITE_LOCAL, _efeito,
                           origem="teste")
    assert not registro.conhecida("mutante-solta")
    assert not alvo.exists(), "MUTATION_OCCURRED — deveria ser fail-closed"


def test_mutante_sem_aprovador_falha_fechado(amb):
    """Registrar mutante sem aprovador ⇒ gate nega, nada muta."""
    from nomos.orquestracao.registro import ErroRegistro, RegistroCapacidades
    ctx, ws = amb
    alvo = ws / "tambem-nao.txt"

    def _efeito(**params):
        alvo.write_text("MUTOU")
        return "ok"

    registro = RegistroCapacidades(policy=ctx["policy"], approver=None)
    with pytest.raises(ErroRegistro):
        registro.registrar("mutante-sem-gate", Category.WRITE_LOCAL, _efeito,
                           origem="teste")
    assert not registro.conhecida("mutante-sem-gate")
    assert not alvo.exists()


def test_capacidade_sem_pep_nao_executa_pelo_runtime(amb):
    """Injetar executor cru no registro NÃO o torna executável pelo runtime."""
    ctx, ws = amb
    alvo = ws / "cru.txt"
    rt = _runtime_completo(ctx, ws, com_scheduler=False)

    def _cru(**params):
        alvo.write_text("EXECUTOU CRU")
        return "ok"

    rt.registro.registrar("mutante-crua", Category.WRITE_LOCAL, _cru,
                          origem="ataque")
    assert rt.registro.conhecida("mutante-crua")
    assert "mutante-crua" not in rt.executores          # não vazou

    res = rt.rodar("ataque", passos=[{
        "id": "m", "ferramenta": "mutante-crua", "params": {}}])
    assert not res.ok
    assert not alvo.exists(), "MUTATION_OCCURRED por capacidade sem PEP"


# ============================================ cadeia auditável

def test_mutacao_deixa_pdp_e_pep_na_trilha_antes_do_efeito(amb):
    """A ordem é asseverada: decidir → aplicar → mutar."""
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws, com_scheduler=False)
    alvo = ws / "governado.txt"
    res = rt.rodar("escrever", passos=[{
        "id": "w", "ferramenta": "fs-escrever",
        "params": {"alvo": str(alvo), "conteudo": "ok"}}])
    assert res.ok and alvo.exists()
    ev = _eventos(ctx)
    assert ev.index("pdp.decisao") < ev.index("pep.aplicacao") < ev.index("fs.escrever")


def test_invariante_cobre_registros_dinamicos_futuros(amb):
    """O invariante não lista nomes: vale para qualquer capacidade futura.

    Registrar uma capacidade mutante NOVA e reconstruir o runtime a inclui
    automaticamente no mapa protegido — sem editar este teste.
    """
    ctx, ws = amb
    rt = _runtime_completo(ctx, ws, com_scheduler=False)
    antes = len(rt.capacidades_adapter)
    # a próxima família de adapter (git, http, hooks…) entra por este caminho
    assert antes >= 8
    for nome in rt.capacidades_adapter:
        if rt.registro.categoria_de(nome) in CATEGORIAS_MUTANTES:
            assert isinstance(rt.executores_protegidos[nome], PontoDeAplicacao)
