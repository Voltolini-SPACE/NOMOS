"""ABSORPTION-06 / P1 — a aprovação vincula o humano à operação EXATA.

O censo do G1 mostrou o prompt que o operador realmente via:

    A5 · executar código | alvo='orquestracao:h:script-rodar:'

Um plano benigno e um plano que exfiltrava chave privada produziam prompts
**byte-idênticos** — o único campo variável era o id do nó, escolhido por quem
escreve o plano. `No.alvo` não tinha nenhum escritor no código.

Estes testes atacam a aprovação da única forma que importa: obter um "APROVO"
legítimo para uma operação benigna e, DEPOIS, trocar cada campo separadamente.
Todas as trocas têm de ser recusadas — e recusadas pelo digest, não por acaso.

Um ponto que os testes prendem explicitamente: `descrever()` (o que o humano lê)
e `canonico()` (o que o digest assina) precisam cobrir os mesmos campos. Se
divergirem, a UI mostra A e o sistema assina B — que é a forma mais perigosa
deste defeito, porque parece resolvido.
"""
from __future__ import annotations

from pathlib import Path as pathlib_Path

from datetime import datetime, timedelta, timezone

import pytest

from nomos.pdp.aprovacao import (Aprovacao, ErroAprovacao, OperacaoAprovavel,
                                 RegistroAprovacoes, versao_da_politica)

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _op(**troca) -> OperacaoAprovavel:
    base = dict(
        sujeito="runtime-governado",
        capacidade="fs-escrever",
        recurso="/ws/relatorio.txt",
        classe_de_risco="A1_WRITE_LOCAL",
        argumentos={"alvo": "/ws/relatorio.txt", "conteudo": "olá"},
        escopo_dados=("/ws",),
        escopo_controle=(),
        versao_da_politica="pol-abc",
        digest_do_plano="passo-1",
    )
    base.update(troca)
    return OperacaoAprovavel(**base)


class Relogio:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


# ===================================== substituição, campo a campo

SUBSTITUICOES = [
    ("alvo", {"recurso": "/ws/OUTRO.txt"}),
    ("argumento", {"argumentos": {"alvo": "/ws/relatorio.txt",
                                  "conteudo": "conteúdo TROCADO"}}),
    ("argumento oculto", {"argumentos": {"alvo": "/ws/relatorio.txt",
                                         "conteudo": "olá", "recursivo": True}}),
    ("capacidade", {"capacidade": "fs-apagar"}),
    ("sujeito", {"sujeito": "jeferson (dono)"}),
    ("classe de risco", {"classe_de_risco": "A0_READ_LOCAL"}),
    ("escopo de dados", {"escopo_dados": ("/ws", "/etc")}),
    ("escopo de controle", {"escopo_controle": ("/h/scheduler",)}),
    ("política", {"versao_da_politica": "pol-DEPOIS-DE-MUDAR"}),
    ("plano", {"digest_do_plano": "passo-2"}),
]


@pytest.mark.parametrize("rotulo,troca", SUBSTITUICOES,
                         ids=[r for r, _ in SUBSTITUICOES])
def test_p1_substituicao_depois_do_aprovo_e_recusada(rotulo, troca):
    """APROVO para a operação benigna; troca de UM campo; recusa."""
    reg = RegistroAprovacoes(ttl_s=300, agora_fn=Relogio())
    reg.conceder(_op())                       # o humano aprovou ISTO
    with pytest.raises(ErroAprovacao, match="não é o que foi aprovado"):
        reg.consumir(_op(**troca))            # e isto é outra coisa


def test_p1_operacao_identica_e_aceita():
    """Contraparte positiva: sem ela, um registro que recusa TUDO passaria."""
    reg = RegistroAprovacoes(ttl_s=300, agora_fn=Relogio())
    ap = reg.conceder(_op())
    assert reg.consumir(_op()).id_aprovacao == ap.id_aprovacao


def test_p1_ordem_dos_argumentos_nao_muda_o_digest():
    """Canonização recursiva: reordenar não é substituir.

    Sem isto, o operador seria consultado de novo por nada — ou pior, uma
    reordenação passaria a valer como operação distinta.
    """
    a = _op(argumentos={"alvo": "/ws/x", "conteudo": "c", "n": 1})
    b = _op(argumentos={"n": 1, "conteudo": "c", "alvo": "/ws/x"})
    assert a.digest() == b.digest()


def test_p1_aninhamento_profundo_entra_no_digest():
    """Argumento aninhado também é autoridade: `{"argumentos": {"alvo": ...}}`
    foi exatamente o contrabando que o censo achou no `sched-criar`."""
    a = _op(argumentos={"argumentos": {"alvo": "/ws/a"}})
    b = _op(argumentos={"argumentos": {"alvo": "/ws/OUTRO"}})
    assert a.digest() != b.digest()


# ===================================== replay e prazo

def test_p1_um_aprovo_autoriza_uma_execucao():
    """APPROVAL_REPLAY=FALSE."""
    reg = RegistroAprovacoes(ttl_s=300, agora_fn=Relogio())
    reg.conceder(_op())
    reg.consumir(_op())
    with pytest.raises(ErroAprovacao, match="já usada"):
        reg.consumir(_op())


def test_p1_aprovacao_expirada_nao_e_aceita():
    """APPROVAL_EXPIRED_ACCEPTED=FALSE."""
    relogio = Relogio()
    reg = RegistroAprovacoes(ttl_s=60, agora_fn=relogio)
    reg.conceder(_op())
    relogio.t = T0 + timedelta(seconds=61)
    with pytest.raises(ErroAprovacao, match="expirada"):
        reg.consumir(_op())


def test_p1_expirada_nao_ressuscita_com_o_relogio_para_tras():
    relogio = Relogio()
    reg = RegistroAprovacoes(ttl_s=60, agora_fn=relogio)
    reg.conceder(_op())
    relogio.t = T0 + timedelta(seconds=61)
    with pytest.raises(ErroAprovacao):
        reg.consumir(_op())
    relogio.t = T0 + timedelta(seconds=10)
    with pytest.raises(ErroAprovacao):
        reg.consumir(_op())


def test_p1_sem_aprovacao_nenhuma_o_consumo_falha():
    reg = RegistroAprovacoes(ttl_s=300, agora_fn=Relogio())
    with pytest.raises(ErroAprovacao, match="nenhuma aprovação"):
        reg.consumir(_op())


def test_p1_aprovacao_de_outra_operacao_nao_serve():
    reg = RegistroAprovacoes(ttl_s=300, agora_fn=Relogio())
    reg.conceder(_op(capacidade="fs-ler", classe_de_risco="A0_READ_LOCAL"))
    with pytest.raises(ErroAprovacao):
        reg.consumir(_op())


# ===================================== a UI não pode mostrar A e assinar B

def test_p1_descricao_cobre_os_campos_do_digest():
    """O invariante mais importante deste módulo.

    Se `descrever()` omitir um campo que `canonico()` assina, existe autoridade
    que o humano aprova sem ver. Se assinar um campo que a descrição não mostra,
    é a mesma coisa com outro nome.
    """
    op = _op()
    texto = op.descrever()
    canon = op.canonico()
    ausentes = []
    for chave, valor in canon.items():
        if chave in ("versao_da_politica", "digest_do_plano"):
            continue                       # aparecem truncados, conferidos abaixo
        agulha = (str(valor) if not isinstance(valor, (list, dict))
                  else None)
        if agulha and agulha not in texto:
            ausentes.append(chave)
    assert not ausentes, f"campos assinados e NÃO mostrados: {ausentes}"
    assert canon["versao_da_politica"][:16] in texto
    assert canon["digest_do_plano"][:16] in texto
    for arg in ("alvo", "conteudo"):
        assert arg in texto, f"argumento '{arg}' não é mostrado ao operador"


def test_p1_planos_diferentes_produzem_prompts_diferentes():
    """O defeito literal do censo: prompts byte-idênticos.

    Benigno e hostil diferiam só pelo id do nó. Agora a descrição carrega o
    recurso e os argumentos reais.
    """
    benigno = _op(recurso="/ws/nota.txt",
                  argumentos={"alvo": "/ws/nota.txt", "conteudo": "oi"})
    hostil = _op(recurso="/ws/roubado.txt",
                 argumentos={"alvo": "/ws/roubado.txt",
                             "conteudo": "-----BEGIN PRIVATE KEY-----"})
    assert benigno.descrever() != hostil.descrever()
    assert benigno.digest() != hostil.digest()
    assert "roubado" in hostil.descrever()


def test_p1_tipo_opaco_nao_vira_texto_livre_no_digest():
    """Objeto arbitrário no argumento não pode colidir com um texto."""
    class Coisa:
        def __repr__(self):
            return "/ws/relatorio.txt"

    a = _op(argumentos={"alvo": Coisa()})
    b = _op(argumentos={"alvo": "/ws/relatorio.txt"})
    assert a.digest() != b.digest()


# ===================================== versão da política entra no digest

def test_p1_mudar_a_politica_invalida_a_aprovacao(tmp_path):
    """Um APROVO dado sob `A6=DENY` não vale depois que virou `ALLOW`.

    Sem este campo, a aprovação sobreviveria à mudança da premissa que a
    justificou — o humano consentiu com um mundo, e o efeito aconteceria noutro.
    """
    import json

    from nomos.kernel.policy import PolicyEngine
    caminho = tmp_path / "policy.json"
    pol = PolicyEngine(caminho)
    v1 = versao_da_politica(pol)
    reg = RegistroAprovacoes(ttl_s=300, agora_fn=Relogio())
    reg.conceder(_op(versao_da_politica=v1))

    dados = json.loads(caminho.read_text())
    dados["rules"]["A6_DESTRUCTIVE"] = "ALLOW"
    caminho.write_text(json.dumps(dados))
    v2 = versao_da_politica(PolicyEngine(caminho))
    assert v1 != v2, "mudar a regra não mudou a versão — o campo seria inócuo"
    with pytest.raises(ErroAprovacao):
        reg.consumir(_op(versao_da_politica=v2))


def test_p1_versao_da_politica_e_estavel_para_a_mesma_politica(tmp_path):
    from nomos.kernel.policy import PolicyEngine
    pol = PolicyEngine(tmp_path / "policy.json")
    assert versao_da_politica(pol) == versao_da_politica(pol)


def test_p1_aprovacao_valida_no_instante_da_concessao():
    """Fronteira: `concedida_em <= agora < expira_em`."""
    ap = Aprovacao(id_aprovacao="x", digest="d", concedida_em=T0,
                   expira_em=T0 + timedelta(seconds=60))
    assert ap.valida_em(T0)
    assert ap.valida_em(T0 + timedelta(seconds=59))
    assert not ap.valida_em(T0 + timedelta(seconds=60))
    assert not ap.valida_em(T0 - timedelta(seconds=1))


# ===================================== TOCTOU pela cadeia REAL

def _amb(tmp_path):
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    return ({"home": home, "policy": PolicyEngine(home / "policy.json"),
             "audit": AuditLog(home / "logs" / "audit.jsonl")}, ws)


def test_p1_toctou_params_alterados_depois_do_aprovo_nao_executam(tmp_path):
    """O ataque clássico: o aprovador vê A, e B é executado.

    O aprovador aqui MUTA o plano no instante em que aprova — que é o pior
    caso possível, porque a janela entre a decisão e o efeito é a menor que
    existe. O runtime remonta a operação a partir dos dados que vão executar e
    compara com o que foi aprovado.
    """
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws = _amb(tmp_path)
    benigno = ws / "benigno.txt"
    vitima = ws / "vitima.txt"
    vitima.write_text("CONTEUDO ORIGINAL")
    passos = [{"id": "p", "ferramenta": "fs-escrever",
               "params": {"alvo": str(benigno), "conteudo": "ok"}}]

    # A mutação só pode acontecer na aprovação DO NÓ. O aprovador também é
    # chamado ~8 vezes durante o registro das capacidades, dentro do
    # construtor — mutar ali faria o plano nascer hostil e não haveria TOCTOU
    # nenhum para barrar. A primeira versão deste teste tinha esse defeito e
    # "provava" um furo que não existia.
    fase = {"registrando": True}

    def aprovador_que_troca(d):
        if not fase["registrando"] and "fs-escrever" in str(d.target):
            # o humano acabou de ver e aprovar o BENIGNO; o plano troca agora
            passos[0]["params"]["alvo"] = str(vitima)
            passos[0]["params"]["conteudo"] = "INVADIDO"
        return True

    rt = RuntimeGovernado(ctx, aprovador_que_troca, caminhos=(str(ws),),
                          adapters=True)
    fase["registrando"] = False
    res = rt.rodar("toctou", passos=passos)
    # DUAS defesas, e vale distinguir qual está agindo aqui: o planejador
    # MATERIALIZA o plano antes da aprovação, copiando os params para os nós.
    # Mutar a lista de entrada depois não alcança o que executa. O recálculo
    # do digest é a segunda defesa, exercitada no teste seguinte, que muta o
    # NÓ — o dado que de fato vai executar.
    assert vitima.read_text() == "CONTEUDO ORIGINAL", (
        "APPROVAL_TOCTOU: o efeito caiu sobre o alvo TROCADO depois do APROVO")
    assert res.ok, "o plano BENIGNO, que foi o aprovado, deveria executar"
    assert benigno.read_text() == "ok"


def test_p1_operacao_benigna_aprovada_executa_normalmente(tmp_path):
    """Contraparte positiva: o vínculo não pode ter quebrado o caminho feliz."""
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws = _amb(tmp_path)
    alvo = ws / "ok.txt"
    rt = RuntimeGovernado(ctx, lambda _d: True, caminhos=(str(ws),),
                          adapters=True)
    res = rt.rodar("feliz", passos=[{"id": "p", "ferramenta": "fs-escrever",
                                     "params": {"alvo": str(alvo),
                                                "conteudo": "conteudo"}}])
    assert res.ok, res.motivo
    assert alvo.read_text() == "conteudo"


def test_p1_o_operador_ve_o_alvo_real_no_prompt(tmp_path):
    """O defeito literal: `alvo='orquestracao:h:script-rodar:'`, sempre vazio."""
    from nomos.runtime.governado import RuntimeGovernado
    ctx, ws = _amb(tmp_path)
    alvo = ws / "arquivo-que-o-operador-precisa-ver.txt"
    vistos = []

    def aprovador(d):
        vistos.append(d.target)
        return True

    rt = RuntimeGovernado(ctx, aprovador, caminhos=(str(ws),), adapters=True)
    rt.rodar("prompt", passos=[{"id": "p", "ferramenta": "fs-escrever",
                                "params": {"alvo": str(alvo),
                                           "conteudo": "x"}}])
    do_no = [t for t in vistos if "fs-escrever" in t and "registro" not in t]
    assert do_no, f"nenhum prompt do nó; vistos={vistos[:3]}"
    texto = do_no[-1]
    assert "arquivo-que-o-operador-precisa-ver" in texto, texto
    assert "conteudo" in texto or "conteúdo" in texto, texto


def test_p1_mutacao_do_NO_entre_aprovacao_e_efeito_e_recusada(tmp_path):
    """O recálculo do digest, exercitado no dado que REALMENTE executa.

    O teste anterior mostra que o planejador copia os params — defesa em
    profundidade que impede o vetor mais óbvio. Este ataca a camada de baixo:
    muta `grafo.nos[...]`.params DEPOIS do "APROVO", que é a última janela
    existente antes do efeito. Sem o recálculo, o efeito cairia no alvo
    trocado com uma aprovação legítima para outro alvo.
    """
    from nomos.orquestracao.grafo import GrafoTarefas, No, Orquestrador
    from nomos.pdp.aprovacao import RegistroAprovacoes
    ctx, ws = _amb(tmp_path)
    benigno = ws / "benigno.txt"
    vitima = ws / "vitima.txt"
    vitima.write_text("CONTEUDO ORIGINAL")
    efeitos = []

    def executor(**params):
        alvo = pathlib_Path(params["alvo"])
        alvo.write_text(params.get("conteudo", ""))
        efeitos.append(str(alvo))
        return "ok"

    from nomos.kernel.policy import Category
    from nomos.orquestracao.registro import RegistroCapacidades
    registro = RegistroCapacidades(policy=ctx["policy"], approver=lambda _d: True,
                                   audit=ctx["audit"])
    registro.registrar("fs-escrever", Category.WRITE_LOCAL, executor,
                       origem="teste")
    grafo = GrafoTarefas([No(id="p", ferramenta="fs-escrever",
                             params={"alvo": str(benigno), "conteudo": "ok"})],
                         registro)
    reg_ap = RegistroAprovacoes(ttl_s=300)

    def aprovador_que_troca(d):
        if "fs-escrever" in str(d.target):
            grafo.nos["p"].params["alvo"] = str(vitima)
            grafo.nos["p"].params["conteudo"] = "INVADIDO"
        return True

    orq = Orquestrador(registro, ctx["policy"], approver=aprovador_que_troca,
                       audit=ctx["audit"],
                       executores={"fs-escrever": executor},
                       contexto_aprovacao=lambda: ("runtime-governado",
                                                   (str(ws),), (), reg_ap))
    resultado = orq.executar(grafo)
    assert vitima.read_text() == "CONTEUDO ORIGINAL", (
        f"APPROVAL_TOCTOU: efeito no alvo trocado; efeitos={efeitos}")
    assert not resultado.ok
    assert resultado.nos["p"].status == "NEGADO"
    assert "aprovad" in resultado.nos["p"].detalhe.lower(), resultado.nos["p"].detalhe
