"""FASE 2 (ABSORPTION-01) — suíte ofensiva contra PDP/PEP.

Happy path não prova barreira. Aqui a pergunta é sempre a mesma: *existe algum
jeito de produzir efeito sem uma decisão ALLOW legítima?* Cada teste é uma
tentativa de furo; qualquer bypass reproduzível é FAIL da missão.

Convenção: quando o ataque "funciona" na vida real, o teste falha. Nada aqui é
enfraquecido para ficar verde — quando um destes quebrou durante o
desenvolvimento, a correção foi na arquitetura, não no teste.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from nomos.agents.manifest import FERRAMENTAS
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine
from nomos.orquestracao.grafo import ErroGrafo, GrafoTarefas, No
from nomos.orquestracao.registro import RegistroCapacidades
from nomos.pdp import (
    ArmazemNonce, Autorizacao, Chaveiro, Decisor, Efeito, Motivo, NegadoPeloPEP,
    Pedido, PontoDeAplicacao, atenuar, e_atenuacao, hash_contrato, proteger,
)
from nomos.pdp.autorizacao import agora_utc
from nomos.runtime.governado import AUDIENCIA_RUNTIME, RuntimeGovernado

CHAVE = b"0123456789abcdef0123456789abcdef"
SUJEITO = "runtime-governado"


# ------------------------------------------------------------------ fixtures

def _ctx(tmp_path):
    home = tmp_path / "h"
    home.mkdir(parents=True, exist_ok=True)
    return {"home": home,
            "policy": PolicyEngine(home / "policy.json"),
            "audit": AuditLog(home / "logs" / "audit.jsonl")}


def _chaveiro():
    return Chaveiro({"k1": CHAVE})


def _auth(chaveiro, **kw):
    agora = agora_utc()
    base = dict(capacidades=("arquivo_ler", "doutor"), sujeito=SUJEITO,
                audiencia=AUDIENCIA_RUNTIME, emitida_em=agora,
                expira_em=agora + timedelta(hours=1), risco_max="A0")
    base.update(kw)
    return chaveiro.assinar(Autorizacao(**base), "k1")


def _decisor(chaveiro, registro=None, **kw):
    kw.setdefault("armazem_nonce", ArmazemNonce())
    return Decisor(chaveiro, registro or RegistroCapacidades(),
                   audiencia=AUDIENCIA_RUNTIME, **kw)


def _pedido(cap="arquivo_ler", **kw):
    kw.setdefault("nonce", "n-" + cap)
    return Pedido(capacidade=cap, sujeito=SUJEITO, **kw)


def _decide(auth, pedido, decisor=None, chaveiro=None):
    chaveiro = chaveiro or _chaveiro()
    return (decisor or _decisor(chaveiro)).decidir(pedido, auth)


# ------------------------------------------------- autorização forjada/adulterada

def test_token_forjado_com_chave_errada_e_negado():
    falso = Chaveiro({"k1": b"chave-totalmente-diferente-0000000"})
    auth = _auth(falso)                      # assinado com a chave errada
    d = _decide(auth, _pedido())
    assert d.efeito is Efeito.DENY
    assert d.motivo is Motivo.ASSINATURA_INVALIDA


def test_chave_desconhecida_e_negada():
    auth = _auth(_chaveiro())
    auth = replace(auth, id_chave="k-inexistente")
    d = _decide(auth, _pedido())
    assert d.motivo is Motivo.CHAVE_DESCONHECIDA


def test_adulteracao_pos_assinatura_invalida_a_assinatura():
    """Serialization tampering: mexer em QUALQUER campo quebra o HMAC."""
    chaveiro = _chaveiro()
    auth = _auth(chaveiro)
    assert chaveiro.verificar(auth)
    for campo, valor in (("capacidades", ("arquivo_ler", "arquivo_escrever")),
                         ("risco_max", "A6"),
                         ("sujeito", "outro"),
                         ("audiencia", "outro-pep"),
                         ("expira_em", auth.expira_em + timedelta(days=365))):
        adulterada = replace(auth, **{campo: valor})
        assert not chaveiro.verificar(adulterada), campo
        assert _decide(adulterada, _pedido()).efeito is Efeito.DENY, campo


def test_assinatura_de_tamanho_errado_e_negada():
    auth = replace(_auth(_chaveiro()), assinatura="abc")
    assert _decide(auth, _pedido()).motivo is Motivo.ASSINATURA_INVALIDA


def test_hash_contrato_muda_com_o_conteudo():
    chaveiro = _chaveiro()
    a = _auth(chaveiro)
    b = replace(a, risco_max="A1")
    assert hash_contrato(a) != hash_contrato(b)


# ------------------------------------------------- tempo

def test_token_expirado_e_negado():
    chaveiro = _chaveiro()
    agora = agora_utc()
    auth = chaveiro.assinar(Autorizacao(
        capacidades=("arquivo_ler",), sujeito=SUJEITO, audiencia=AUDIENCIA_RUNTIME,
        emitida_em=agora - timedelta(hours=3),
        expira_em=agora - timedelta(hours=2), risco_max="A0"), "k1")
    assert _decide(auth, _pedido()).motivo is Motivo.EXPIRADA


def test_token_do_futuro_e_negado():
    chaveiro = _chaveiro()
    agora = agora_utc()
    auth = chaveiro.assinar(Autorizacao(
        capacidades=("arquivo_ler",), sujeito=SUJEITO, audiencia=AUDIENCIA_RUNTIME,
        emitida_em=agora + timedelta(hours=2),
        expira_em=agora + timedelta(hours=3), risco_max="A0"), "k1")
    assert _decide(auth, _pedido()).motivo is Motivo.AINDA_NAO_VALIDA


# ------------------------------------------------- replay

def test_nonce_repetido_e_negado():
    chaveiro = _chaveiro()
    decisor = _decisor(chaveiro)
    auth = _auth(chaveiro)
    p = _pedido(nonce="mesmo-nonce")
    assert decisor.decidir(p, auth).efeito is Efeito.ALLOW
    assert decisor.decidir(p, auth).motivo is Motivo.NONCE_REPETIDO


def test_nonce_ausente_e_negado_quando_exigido():
    chaveiro = _chaveiro()
    auth = _auth(chaveiro)
    p = Pedido(capacidade="arquivo_ler", sujeito=SUJEITO, nonce="")
    assert _decide(auth, p, _decisor(chaveiro)).motivo is Motivo.NONCE_AUSENTE


def test_replay_do_envelope_inteiro_e_negado():
    """Reapresentar o MESMO par (pedido, autorização) não repete o efeito."""
    chaveiro = _chaveiro()
    decisor = _decisor(chaveiro)
    auth = _auth(chaveiro, nonce="nonce-do-token")
    p = Pedido(capacidade="arquivo_ler", sujeito=SUJEITO)
    assert decisor.decidir(p, auth).efeito is Efeito.ALLOW
    assert decisor.decidir(p, auth).motivo is Motivo.NONCE_REPETIDO


# ------------------------------------------------- escopo / escalação

def test_capacidade_nao_concedida_e_negada():
    auth = _auth(_chaveiro())                       # só arquivo_ler e doutor
    d = _decide(auth, _pedido("arquivo_escrever"))
    assert d.motivo is Motivo.CAPACIDADE_NAO_CONCEDIDA


def test_capacidade_desconhecida_e_negada():
    auth = _auth(_chaveiro(), capacidades=("shell_exec",))
    d = _decide(auth, _pedido("shell_exec"))
    assert d.motivo is Motivo.CAPACIDADE_DESCONHECIDA


def test_sujeito_errado_e_negado():
    auth = _auth(_chaveiro(), sujeito="outro-agente")
    d = _decide(auth, _pedido())
    assert d.motivo is Motivo.SUJEITO_ERRADO


def test_audiencia_errada_e_negada():
    """Token emitido para outro PEP não vale aqui."""
    auth = _auth(_chaveiro(), audiencia="nomos:outro-pep")
    d = _decide(auth, _pedido())
    assert d.motivo is Motivo.AUDIENCIA_ERRADA


def test_risco_acima_do_teto_e_negado():
    chaveiro = _chaveiro()
    auth = _auth(chaveiro, capacidades=("arquivo_escrever",), risco_max="A0")
    d = _decide(auth, _pedido("arquivo_escrever"))
    assert d.motivo is Motivo.RISCO_ACIMA_DO_AUTORIZADO


def test_recurso_fora_do_escopo_e_negado():
    auth = _auth(_chaveiro(), caminhos=("/permitido",))
    d = _decide(auth, _pedido(recurso="/proibido/segredo"))
    assert d.motivo is Motivo.RECURSO_FORA_DO_ESCOPO


def test_recurso_dentro_do_escopo_passa():
    chaveiro = _chaveiro()
    auth = _auth(chaveiro, caminhos=("/permitido",))
    d = _decide(auth, _pedido(recurso="/permitido/arquivo.txt"))
    assert d.efeito is Efeito.ALLOW


def test_prefixo_parecido_nao_engana_o_escopo():
    """'/permitido-outro' NÃO está dentro de '/permitido'."""
    auth = _auth(_chaveiro(), caminhos=("/permitido",))
    d = _decide(auth, _pedido(recurso="/permitido-outro/x"))
    assert d.motivo is Motivo.RECURSO_FORA_DO_ESCOPO


def test_argumento_contrabandeia_recurso_e_negado():
    """Recurso no escopo, mas argumento apontando para fora ⇒ DENY."""
    auth = _auth(_chaveiro(), caminhos=("/permitido",))
    d = _decide(auth, _pedido(recurso="/permitido/ok.txt",
                              argumentos={"alvo": "/etc/passwd"}))
    assert d.motivo is Motivo.ARGUMENTO_FORA_DO_ESCOPO


# ------------------------------------------------- atenuação

def test_atenuacao_nao_consegue_alargar_capacidades():
    chaveiro = _chaveiro()
    pai = _auth(chaveiro)                            # arquivo_ler, doutor
    filho = atenuar(pai, chaveiro, "k1",
                    capacidades=["arquivo_ler", "arquivo_escrever"])
    assert "arquivo_escrever" not in filho.capacidades
    assert e_atenuacao(filho, pai)


def test_atenuacao_nao_consegue_subir_risco_nem_prazo():
    chaveiro = _chaveiro()
    pai = _auth(chaveiro, risco_max="A1")
    filho = atenuar(pai, chaveiro, "k1", risco_max="A6",
                    expira_em=pai.expira_em + timedelta(days=30))
    assert filho.risco_max == "A1"
    assert filho.expira_em <= pai.expira_em
    assert e_atenuacao(filho, pai)


def test_filho_forjado_mais_amplo_nao_e_atenuacao():
    chaveiro = _chaveiro()
    pai = _auth(chaveiro, risco_max="A0")
    forjado = replace(pai, capacidades=("arquivo_ler", "arquivo_escrever"),
                      risco_max="A5")
    assert not e_atenuacao(forjado, pai)
    assert not chaveiro.verificar(forjado)      # e nem assinado está


def test_atenuacao_restringe_caminhos():
    chaveiro = _chaveiro()
    pai = _auth(chaveiro, caminhos=("/a", "/b"))
    filho = atenuar(pai, chaveiro, "k1", caminhos=["/a/sub", "/fora"])
    assert "/fora" not in filho.caminhos
    assert e_atenuacao(filho, pai)


# ------------------------------------------------- indisponibilidade / corrupção

def test_sem_autorizacao_e_negado():
    assert _decide(None, _pedido()).motivo is Motivo.SEM_AUTORIZACAO


def test_autorizacao_de_tipo_errado_e_negada():
    for lixo in ({"capacidades": ["arquivo_ler"]}, "token", 42, []):
        assert _decide(lixo, _pedido()).motivo is Motivo.AUTORIZACAO_MALFORMADA


def test_armazem_de_nonce_indisponivel_nega():
    chaveiro = _chaveiro()
    decisor = _decisor(chaveiro, armazem_nonce=ArmazemNonce(indisponivel=True))
    assert decisor.decidir(_pedido(), _auth(chaveiro)).motivo is Motivo.ARMAZEM_INDISPONIVEL


def test_registro_indisponivel_nega():
    chaveiro = _chaveiro()
    decisor = Decisor(chaveiro, None, audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce())
    assert decisor.decidir(_pedido(), _auth(chaveiro)).motivo is Motivo.REGISTRO_INDISPONIVEL


def test_registro_que_explode_nega_sem_propagar():
    class RegistroQuebrado:
        def conhecida(self, nome):
            raise RuntimeError("banco fora")

        def categoria_de(self, nome):
            raise RuntimeError("banco fora")

        def risco_de(self, nome):
            raise RuntimeError("banco fora")

    chaveiro = _chaveiro()
    decisor = Decisor(chaveiro, RegistroQuebrado(), audiencia=AUDIENCIA_RUNTIME,
                      armazem_nonce=ArmazemNonce())
    d = decisor.decidir(_pedido(), _auth(chaveiro))
    assert d.efeito is Efeito.DENY
    assert d.motivo is Motivo.POLITICA_INDISPONIVEL


def test_relogio_quebrado_nega_sem_propagar():
    def _relogio_ruim():
        raise RuntimeError("sem relógio")

    chaveiro = _chaveiro()
    decisor = _decisor(chaveiro, agora_fn=_relogio_ruim)
    d = decisor.decidir(_pedido(), _auth(chaveiro))
    assert d.efeito is Efeito.DENY
    assert d.motivo is Motivo.ERRO_INTERNO


def test_pedido_malformado_e_negado():
    chaveiro = _chaveiro()
    auth = _auth(chaveiro)
    for lixo in ("nao-e-pedido", {"capacidade": "arquivo_ler"}, None, 7):
        assert _decide(auth, lixo, _decisor(chaveiro)).efeito is Efeito.DENY


def test_chaveiro_vazio_ou_chave_curta_e_recusado():
    from nomos.pdp.autorizacao import ErroChaveiro
    with pytest.raises(ErroChaveiro):
        Chaveiro({})
    with pytest.raises(ErroChaveiro):
        Chaveiro({"k": b"curta"})


# ------------------------------------------------- PEP: sem caminho alternativo

def _pep_de_teste(chaveiro, alvo):
    return proteger("arquivo_ler", alvo, _decisor(chaveiro))


def test_pep_nega_sem_autorizacao_valida():
    chaveiro = _chaveiro()
    chamou = {"n": 0}

    def _efeito(**kw):
        chamou["n"] += 1
        return "EFEITO"

    pep = _pep_de_teste(chaveiro, _efeito)
    with pytest.raises(NegadoPeloPEP):
        pep(_pedido(), None)
    assert chamou["n"] == 0                 # o executor não foi nem tocado


def test_pep_nao_expoe_o_executor_bruto():
    """Adapter direct call: não existe atributo público com o callable."""
    chaveiro = _chaveiro()
    sentinela = object()

    def _efeito(**kw):
        return sentinela

    pep = _pep_de_teste(chaveiro, _efeito)
    assert isinstance(pep, PontoDeAplicacao)
    assert not hasattr(pep, "__dict__")            # __slots__, sem enxerto
    with pytest.raises(TypeError):
        vars(pep)
    # nenhum atributo alcançável devolve o executor original
    for nome in dir(pep):
        if nome.startswith("__"):
            continue
        assert getattr(pep, nome, None) is not _efeito
    assert _efeito not in [getattr(pep, n, None) for n in dir(pep)]


def test_pep_nao_deixa_pedir_x_e_executar_y():
    chaveiro = _chaveiro()
    pep = proteger("doutor", lambda **kw: "EFEITO", _decisor(chaveiro))
    with pytest.raises(NegadoPeloPEP):
        pep(_pedido("arquivo_ler"), _auth(chaveiro))   # capacidade divergente


def test_pep_nao_pode_ganhar_atributo_novo():
    chaveiro = _chaveiro()
    pep = _pep_de_teste(chaveiro, lambda **kw: "x")
    with pytest.raises(AttributeError):
        pep.executor = lambda **kw: "backdoor"


def test_pep_permite_quando_tudo_confere():
    chaveiro = _chaveiro()
    pep = _pep_de_teste(chaveiro, lambda **kw: "EFEITO")
    assert pep(_pedido(), _auth(chaveiro)) == "EFEITO"


# ------------------------------------------------- runtime: bypass end-to-end

def test_runtime_executa_somente_via_pdp(tmp_path):
    """Todo executor do runtime é um PEP — nenhum callable cru."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, lambda d: True)
    assert rt.executores_protegidos
    for nome, pep in rt.executores_protegidos.items():
        assert isinstance(pep, PontoDeAplicacao), nome


def test_runtime_com_autorizacao_expirada_nao_produz_efeito(tmp_path):
    ctx = _ctx(tmp_path)
    alvo = tmp_path / "escrito.txt"
    chaveiro = _chaveiro()
    agora = agora_utc()
    vencida = chaveiro.assinar(Autorizacao(
        capacidades=tuple(FERRAMENTAS), sujeito="runtime-governado",
        audiencia=AUDIENCIA_RUNTIME,
        emitida_em=agora - timedelta(hours=5),
        expira_em=agora - timedelta(hours=4), risco_max="A5"), "k1")
    rt = RuntimeGovernado(ctx, lambda d: True, autorizacao=vencida,
                          decisor=_decisor(chaveiro))
    res = rt.rodar("escrever", passos=[
        {"id": "w", "ferramenta": "arquivo_escrever",
         "params": {"alvo": str(alvo), "conteudo": "x"}}])
    assert not res.ok
    # o MOTIVO importa: sem isto o teste passaria por causa do guard de
    # destino de arquivo_escrever, mascarando o PDP (verificado por mutação)
    assert Motivo.EXPIRADA.value in res.missao.nos["w"].detalhe
    assert not alvo.exists()


def test_runtime_com_token_de_outra_audiencia_nao_executa(tmp_path):
    ctx = _ctx(tmp_path)
    chaveiro = _chaveiro()
    agora = agora_utc()
    outro = chaveiro.assinar(Autorizacao(
        capacidades=tuple(FERRAMENTAS), sujeito="runtime-governado",
        audiencia="nomos:outro-pep", emitida_em=agora,
        expira_em=agora + timedelta(hours=1), risco_max="A5"), "k1")
    rt = RuntimeGovernado(ctx, lambda d: True, autorizacao=outro,
                          decisor=_decisor(chaveiro))
    res = rt.rodar("ler", passos=[{"id": "a", "ferramenta": "doutor"}])
    assert not res.ok


def test_no_do_grafo_nao_escala_privilegio(tmp_path):
    """Graph node attempting privilege escalation: idempotência é do registro."""
    reg = RegistroCapacidades()
    with pytest.raises(ErroGrafo):
        GrafoTarefas([No("w", "arquivo_escrever", idempotente=True)], reg)


def test_planner_nao_alcanca_capacidade_privilegiada(tmp_path):
    """Planner attempting privileged capability: fora do registro ⇒ rejeitado."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, lambda d: True)
    plano = rt.planejar("escalar", passos=[
        {"id": "x", "ferramenta": "shell_exec", "params": {"alvo": "id"}},
        {"id": "y", "ferramenta": "git_push", "params": {}},
    ])
    assert not plano.ok
    assert len(plano.rejeitados) == 2


def test_recuperacao_nao_reexecuta_apos_deny(tmp_path):
    """Recovery attempting re-execution after DENY."""
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, lambda d: False)      # nega tudo que é sensível
    res = rt.rodar("negado", passos=[
        {"id": "w", "ferramenta": "arquivo_escrever",
         "params": {"alvo": str(tmp_path / "n.txt"), "conteudo": "x"}}])
    assert res.missao.nos["w"].status == "NEGADO"
    assert res.missao.nos["w"].tentativas == 0


def test_entrada_alternativa_no_runtime_nao_pula_o_pdp(tmp_path):
    """Alternate entry point: `executar()` direto com plano forjado.

    Verifica o MOTIVO, não só o desfecho. Asseverar apenas "não escreveu"
    deixava o teste passar por causa do guard de destino de
    `arquivo_escrever` — outra defesa, que mascarava a que este teste existe
    para provar. Exigindo `missao is None` + "grafo inválido", a mutação que
    remove a validação do grafo faz este teste falhar (verificado).
    """
    from nomos.orquestracao.planejador import PassoTipado, PlanoTipado
    ctx = _ctx(tmp_path)
    alvo = ctx["home"] / "forjado.txt"
    rt = RuntimeGovernado(ctx, lambda d: True)
    # plano montado à mão, sem passar por planejar()
    plano = PlanoTipado(ok=True, objetivo="forjado", passos=(
        PassoTipado(id="w", ferramenta="arquivo_escrever",
                    categoria=FERRAMENTAS["arquivo_escrever"],
                    params={"alvo": str(alvo), "conteudo": "x"},
                    idempotente=True),          # mentira embutida
    ), risco="A0")                              # risco rebaixado na marra
    res = rt.executar(plano)
    assert not res.ok
    assert res.missao is None, "o grafo deveria ter sido recusado ANTES de executar"
    assert "grafo inválido" in res.motivo
    assert not alvo.exists()


def test_executor_injetado_ainda_passa_pelo_pep(tmp_path):
    """Internal-call bypass: mesmo entregando executores próprios, o runtime
    os protege — não existe modo 'executor cru'."""
    ctx = _ctx(tmp_path)
    chamou = {"n": 0}

    def _meu(**kw):
        chamou["n"] += 1
        return "EFEITO"

    rt = RuntimeGovernado(ctx, lambda d: True, executores={"doutor": _meu})
    assert isinstance(rt.executores_protegidos["doutor"], PontoDeAplicacao)
    res = rt.rodar("ok", passos=[{"id": "d", "ferramenta": "doutor"}])
    assert res.ok
    assert chamou["n"] == 1                     # passou, mas via PEP


def test_decisao_do_pdp_fica_na_trilha(tmp_path):
    ctx = _ctx(tmp_path)
    rt = RuntimeGovernado(ctx, lambda d: True)
    rt.rodar("auditar", passos=[{"id": "d", "ferramenta": "doutor"}])
    eventos = [json.loads(linha).get("event")
               for linha in (ctx["home"] / "logs" / "audit.jsonl").read_text().splitlines()
               if linha.strip()]
    assert "pdp.decisao" in eventos
    assert "pep.aplicacao" in eventos
    # a ordem importa: decidir ANTES de aplicar
    assert eventos.index("pdp.decisao") < eventos.index("pep.aplicacao")


def test_rotas_ate_o_adapter_sao_exatamente_estas():
    """DIRECT ROUTE BYPASS — censo estrutural, não impressão.

    Enumera TODO módulo de `src/` que alcança `ferramentas_wired` (o dispatch
    dos 8 executores) e fixa a lista. Cada rota precisa referenciar um
    aplicador — `AgentToolBoundary` (gate A0–A6 + manifesto) e/ou o PEP de
    capacidade. Rota nova sem aplicador quebra este teste.

    Estado honesto hoje:
    - `runtime/governado.py`: boundary **e** PDP/PEP de capacidade;
    - `cli.py` (`nomos agentes usar`) e `simple/amigavel.py`: boundary apenas.
      Não são bypass do A0–A6 (o gate do kernel decide e nega), mas NÃO
      atravessam o PDP de token/escopo/TTL/replay. Fechar essas duas é item
      declarado da ABSORPTION-02 — aqui fica registrado, não escondido.
    """
    import pathlib
    raiz = pathlib.Path(__file__).resolve().parents[1] / "src" / "nomos"
    rotas = {}
    for arq in raiz.rglob("*.py"):
        if arq.name == "execucao.py":
            continue                       # é o próprio adapter
        txt = arq.read_text(encoding="utf-8")
        if "ferramentas_wired(" in txt and "import" in txt:
            if "from nomos.agents.execucao import" in txt:
                rotas[arq.relative_to(raiz).as_posix()] = txt

    assert set(rotas) == {"cli.py", "runtime/governado.py", "simple/amigavel.py"}, (
        f"conjunto de rotas até o adapter mudou: {sorted(rotas)}")

    for nome, txt in rotas.items():
        assert "AgentToolBoundary" in txt, f"{nome} alcança o adapter sem boundary"

    # a rota do runtime é a única que hoje soma o PDP de capacidade
    assert "proteger_executores" in rotas["runtime/governado.py"]


def test_default_deny_e_a_regra(tmp_path):
    """Qualquer coisa que não seja ALLOW explícito é DENY."""
    chaveiro = _chaveiro()
    decisor = _decisor(chaveiro)
    combinacoes = [
        (None, _pedido()),
        (_auth(chaveiro, capacidades=()), _pedido()),
        (_auth(chaveiro), Pedido(capacidade="", sujeito=SUJEITO)),
        (_auth(chaveiro), Pedido(capacidade="doutor", sujeito="")),
    ]
    for auth, pedido in combinacoes:
        d = decisor.decidir(pedido, auth)
        assert d.efeito is Efeito.DENY
        assert not d.permitido
