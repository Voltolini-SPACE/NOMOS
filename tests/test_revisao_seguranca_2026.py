"""Revisão 2026-07 — endurecimentos de segurança/concorrência.

Contratos cobertos aqui:
- approvals.decide é single-use DE VERDADE sob concorrência (reivindicação
  atômica): N decisores simultâneos ⇒ exatamente UM vence;
- claim órfão (crash a meio-decidir) jamais vira aprovação: expira (fail-closed);
- fila de aprovações não cai por um arquivo corrompido;
- auditoria: appends concorrentes não bifurcam a cadeia de hash;
- auditoria: cauda parcial (crash/disco cheio) é reparada no próximo append —
  verify() volta a passar em vez de acusar violação para sempre;
- redação cobre nomes de campo pt-BR ("chave", "credencial");
- localidade: alvo vazio/não-parseável NÃO é loopback (cadeado fecha);
- doutor NÃO executa scripts do diretório atual sem --repo (exec é opt-in).
"""
import json
import threading

import pytest

from nomos.kernel import localidade
from nomos.kernel.approvals import (
    APROVADA, EXPIRADA, NEGADA, PENDENTE, ApprovalError, ApprovalQueue,
)
from nomos.kernel.audit import AuditLog


class FakeClock:
    def __init__(self):
        self.t = 1_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


# ---------------------------------------------------------------------------
# approvals: single-use atômico
# ---------------------------------------------------------------------------
def test_decide_concorrente_um_so_vence(tmp_path):
    q = ApprovalQueue(tmp_path / "ap")
    rid, token = q.request("A2_NET_EGRESS", "alvo", "motivo")
    resultados, erros = [], []
    barreira = threading.Barrier(8)

    def tenta(aprovar: bool):
        barreira.wait()
        try:
            resultados.append(q.decide(rid, token, approve=aprovar))
        except ApprovalError as exc:
            erros.append(str(exc))

    ths = [threading.Thread(target=tenta, args=(i % 2 == 0,))
           for i in range(8)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    # exatamente UM decisor vence; todos os demais são recusados
    assert len(resultados) == 1
    assert resultados[0] in (APROVADA, NEGADA)
    assert len(erros) == 7
    # o estado final no disco é o do vencedor (ninguém sobrescreve depois)
    assert q.get(rid).status == resultados[0]


def test_claim_orfao_nao_vira_aprovacao(tmp_path):
    clock = FakeClock()
    q = ApprovalQueue(tmp_path / "ap", clock=clock)
    rid, token = q.request("A5_CODE_EXEC", "x", "m")
    p = q._path(rid)
    # simula crash NO MEIO de decide(): arquivo ficou reivindicado
    p.rename(p.with_suffix(".deciding"))
    # antes do TTL: pedido segue visível como pendente (snapshot do claim)
    assert q.get(rid).status == PENDENTE
    # bem depois do TTL(+folga): órfão volta à fila e expira — fail-closed
    clock.advance(q.ttl + 60)
    assert q.get(rid).status == EXPIRADA
    with pytest.raises(ApprovalError):
        q.decide(rid, token, approve=True)


def test_pending_ignora_arquivo_corrompido(tmp_path):
    q = ApprovalQueue(tmp_path / "ap")
    rid, _ = q.request("A1", "alvo", "motivo")
    (q.dir / "lixo.json").write_text("{nem-json")
    pend = q.pending()          # não pode estourar
    assert [a.id for a in pend] == [rid]


# ---------------------------------------------------------------------------
# auditoria: concorrência e reparo de cauda
# ---------------------------------------------------------------------------
def test_appends_concorrentes_nao_bifurcam_cadeia(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    barreira = threading.Barrier(6)

    def grava(i):
        barreira.wait()
        for j in range(5):
            log.append("evento.concorrente", n=i * 10 + j)

    ths = [threading.Thread(target=grava, args=(i,)) for i in range(6)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    ok, viol = log.verify()
    assert ok, f"cadeia bifurcou na linha {viol}"
    assert log.estado()[0] == 30


def test_cauda_parcial_e_reparada_no_proximo_append(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("um")
    log.append("dois")
    # crash/disco cheio: meia-linha SEM \n na cauda
    with log.path.open("a", encoding="utf-8") as fh:
        fh.write('{"ts":123,"event":"tru')
    log.append("tres")
    ok, _ = log.verify()
    assert ok, "a cauda parcial deveria ter sido reparada antes do append"
    assert log.estado()[0] == 3
    eventos = [json.loads(li)["event"]
               for li in log.path.read_text().splitlines()]
    assert eventos == ["um", "dois", "tres"]


def test_append_usa_cache_e_nao_rele_o_arquivo_a_cada_chamada(tmp_path, monkeypatch):
    """P1-9 da auditoria de 2026-07-17: append() chamava _tail_scan() (relê
    o arquivo inteiro) em TODA gravação — O(n) por chamada, O(n²) agregado
    (medido: 0.21ms/chamada com 100 linhas -> 15.46ms/chamada com 10.000).
    Agora só relê na 1ª chamada (cache frio); as seguintes reaproveitam o
    cache em memória, validado por um stat() O(1) a cada append()."""
    log = AuditLog(tmp_path / "audit.jsonl")
    chamadas = {"n": 0}
    original = log._tail_scan

    def _contando():
        chamadas["n"] += 1
        return original()

    monkeypatch.setattr(log, "_tail_scan", _contando)
    for i in range(20):
        log.append("ev", n=i)
    assert chamadas["n"] == 1, f"_tail_scan() foi chamado {chamadas['n']}x (esperado 1)"
    assert log.estado()[0] == 20


def test_cache_de_append_detecta_escrita_externa_ao_arquivo(tmp_path):
    """Se OUTRA instância (outro processo, na prática — painel + CLI ao
    mesmo tempo) gravar no MESMO arquivo, o cache desta instância fica
    desatualizado; o próximo append() tem de perceber isso (tamanho real
    do disco ≠ tamanho em cache, via stat()) e encadear a partir do estado
    VERDADEIRO — nunca de um cache obsoleto, o que bifurcaria a cadeia."""
    p = tmp_path / "audit.jsonl"
    log_a = AuditLog(p)
    log_a.append("de-a", n=1)
    log_b = AuditLog(p)             # outra instância, mesmo arquivo
    log_b.append("de-b", n=2)
    log_a.append("de-a-de-novo", n=3)   # cache de log_a estava desatualizado
    ok, viol = log_a.verify()
    assert ok, f"cadeia quebrada na linha {viol} — cache ficou desatualizado"
    assert log_a.estado()[0] == 3
    eventos = [json.loads(li)["event"] for li in p.read_text().splitlines()]
    assert eventos == ["de-a", "de-b", "de-a-de-novo"]


def test_redacao_cobre_chave_e_credencial(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    log.append("teste.redacao", chave="valor-em-claro",
               credencial="outro-em-claro")
    bruto = log.path.read_text()
    assert "valor-em-claro" not in bruto
    assert "outro-em-claro" not in bruto


# ---------------------------------------------------------------------------
# localidade: vazio não é loopback
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("alvo", ["", "   ", "http://", "://"])
def test_alvo_vazio_ou_neblina_nao_e_loopback(alvo):
    assert localidade.eh_loopback(alvo) is False


# ---------------------------------------------------------------------------
# doutor: exec do CWD é opt-in (--repo)
# ---------------------------------------------------------------------------
_AGENTE_FALSO = """\
import json, sys
from pathlib import Path
Path(__file__).with_name("EXECUTOU-{n}").touch()
print(json.dumps({{"consistent": True, "checks_passed": 1, "checks_total": 1,
                   "clean": True, "ruido": [], "branch": "main"}}))
"""


def _repo_falso(tmp_path):
    raiz = tmp_path / "repo-malicioso"
    (raiz / "tools").mkdir(parents=True)
    for n, nome in enumerate(("nomos_update_agent.py", "nomos_git_agent.py")):
        (raiz / "tools" / nome).write_text(_AGENTE_FALSO.format(n=n))
    (raiz / "pyproject.toml").write_text("[project]\nname='x'\n")
    return raiz


def test_doutor_sem_repo_nao_executa_cwd(nomos_home, tmp_path, monkeypatch, capsys):
    from nomos.cli import main
    raiz = _repo_falso(tmp_path)
    monkeypatch.chdir(raiz)
    assert main(["doutor"]) == 0
    capsys.readouterr()
    executou = list((raiz / "tools").glob("EXECUTOU-*"))
    assert executou == [], "doutor executou script do CWD sem --repo (fail-open!)"


def test_doutor_com_repo_executa_por_opt_in(nomos_home, tmp_path, monkeypatch, capsys):
    from nomos.cli import main
    raiz = _repo_falso(tmp_path)
    monkeypatch.chdir(raiz)
    assert main(["doutor", "--repo"]) == 0
    saida = capsys.readouterr().out
    assert "Guardião do repositório" in saida
    assert len(list((raiz / "tools").glob("EXECUTOU-*"))) == 2
