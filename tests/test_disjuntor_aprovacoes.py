"""NH-017c — disjuntor de negações: corta a PERGUNTA, nunca inventa o SIM."""
from __future__ import annotations

from dataclasses import dataclass

from nomos.kernel.disjuntor import DisjuntorAprovacoes


@dataclass(frozen=True)
class _Decisao:
    category: str
    target: str


class _AuditFake:
    def __init__(self):
        self.eventos = []

    def append(self, evento, **campos):
        self.eventos.append((evento, campos))


class _Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _setup(respostas, limite=3, janela=300.0):
    chamadas = []
    relogio = _Relogio()
    audit = _AuditFake()

    def humano(decision):
        chamadas.append(decision)
        return respostas.pop(0) if respostas else False

    d = DisjuntorAprovacoes(limite=limite, janela_s=janela,
                            audit=audit, relogio=relogio)
    return d.envolver(humano), chamadas, relogio, audit, d


def test_disjuntor_abre_apos_n_negacoes_na_janela():
    aprovador, chamadas, _rel, audit, _d = _setup([False, False, False])
    dec = _Decisao("A2_NET_EGRESS", "api.x")
    for _ in range(3):
        assert aprovador(dec) is False
    assert len(chamadas) == 3
    assert aprovador(dec) is False, "aberto nega direto"
    assert len(chamadas) == 3, "a 4ª solicitação NEM chama o humano"
    abertos = [e for e, _c in audit.eventos
               if e == "approvals.disjuntor.aberto"]
    assert len(abertos) == 1


def test_disjuntor_nunca_aprova_sozinho():
    aprovador, chamadas, _rel, _a, _d = _setup([False, False, False])
    dec = _Decisao("A2_NET_EGRESS", "api.x")
    for _ in range(10):
        assert aprovador(dec) is False, \
            "aberto ⇒ False; True SÓ pode vir do humano"


def test_disjuntor_chave_por_categoria_e_alvo():
    aprovador, chamadas, _rel, _a, _d = _setup(
        [False, False, False, True])
    for _ in range(3):
        aprovador(_Decisao("A2_NET_EGRESS", "api.x"))
    # outra chave NÃO está suprimida: o humano é consultado e diz sim
    assert aprovador(_Decisao("A1_WRITE_LOCAL", "arquivo.y")) is True
    assert len(chamadas) == 4


def test_disjuntor_rearma_fora_da_janela_e_zera_na_aprovacao():
    aprovador, chamadas, relogio, audit, _d = _setup(
        [False, False, False, True, False])
    dec = _Decisao("A2_NET_EGRESS", "api.x")
    for _ in range(3):
        aprovador(dec)
    assert aprovador(dec) is False and len(chamadas) == 3   # aberto
    relogio.t += 301                                        # janela venceu
    assert aprovador(dec) is True, "meia-abertura: volta a perguntar"
    assert len(chamadas) == 4
    rearmados = [c for e, c in audit.eventos
                 if e == "approvals.disjuntor.rearmado"]
    assert len(rearmados) == 1 and rearmados[0]["suprimidas"] == 1
    # aprovação zerou: a próxima negação é a PRIMEIRA da nova contagem
    assert aprovador(dec) is False
    assert len(chamadas) == 5


def test_disjuntor_um_evento_por_abertura_e_total_no_rearme():
    aprovador, _ch, relogio, audit, _d = _setup([False] * 3)
    dec = _Decisao("A2_NET_EGRESS", "api.x")
    for _ in range(3):
        aprovador(dec)
    for _ in range(10):
        aprovador(dec)                    # 10 supressões silenciosas
    abertos = [e for e, _c in audit.eventos
               if e == "approvals.disjuntor.aberto"]
    assert len(abertos) == 1, "10 supressões = 1 evento (DoS de trilha)"
    relogio.t += 301
    aprovador(dec)                        # rearme reporta o total
    (rearme,) = [c for e, c in audit.eventos
                 if e == "approvals.disjuntor.rearmado"]
    assert rearme["suprimidas"] == 10


def test_disjuntor_no_agendador_atravessa_ocorrencias(tmp_path):
    """O wrap do AgendadorGovernado acumula entre ocorrências do processo."""
    from nomos.kernel.audit import AuditLog
    from nomos.kernel.policy import PolicyEngine
    from nomos.runtime.agendador import AgendadorGovernado, ConfigAgendador
    home = tmp_path / "h"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    ctx = {"home": home, "policy": PolicyEngine(home / "policy.json"),
           "audit": AuditLog(home / "logs" / "audit.jsonl")}
    consultas = []

    def humano(decision):
        consultas.append(str(decision.target))
        return False

    ag = AgendadorGovernado(ctx, humano, ConfigAgendador(raizes=(str(ws),)))
    dec = _Decisao("A5_SKILL_INSTALL", "registro:fs-apagar")
    for _ in range(6):
        ag.aprovador(dec)
    assert len(consultas) == 3, \
        "após o limite, o disjuntor do agendador para de consultar o humano"
