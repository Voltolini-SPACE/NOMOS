"""P2-3 (auditoria de 2026-07-17): elevar cobertura de approvals.py/audit.py/
missao.py ao piso de 90%.

Medição ANTES (pytest --cov=nomos.kernel.approvals --cov=nomos.kernel.audit
--cov=nomos.kernel.missao --cov-report=term-missing, suíte completa):
- kernel/approvals.py: 176 stmts, 23 miss, 87%
- kernel/audit.py:     161 stmts, 21 miss, 87%
- kernel/missao.py:    131 stmts, 20 miss, 85%

Os três já tinham testes de comportamento sólidos (test_approvals.py,
test_seguranca_auditoria.py, test_mc32_p1_missao.py) — o que faltava eram
justamente os ramos de FALHA/BORDA: corrupção de arquivo, condição de
corrida entre decisores concorrentes, claim órfão, cauda ilegível,
truncamento de nome inválido, colisão que só aparece na hora de executar.
Para um cofre de aprovações e uma trilha de auditoria com cadeia de hash,
esses são exatamente os ramos que mais importa testar — não é
"cobertura pela cobertura".

Nenhuma linha de produção de approvals.py/audit.py/missao.py foi alterada
neste item — é puramente lacuna de teste, não de comportamento. (A ÚNICA
exceção documentada: `Memory._last_hash()` de audit.py não tem NENHUM
chamador em produção hoje, nem mesmo `_tail_scan_cached()`/`append()` o
usam — está testado aqui por completude de cobertura, mas o achado em si
[método órfão] fica fora do escopo deste item, que é sobre medição de
cobertura, não sobre localizar código morto.)
"""
from __future__ import annotations

import json
import sys
import uuid

import pytest

from nomos.kernel.approvals import (
    DEFAULT_TTL_S, EXPIRADA, NEGADA, PENDENTE,
    ApprovalError, ApprovalQueue,
)
from nomos.kernel.audit import GENESIS, AuditLog
from nomos.kernel import missao as ms


# ======================================================================
# approvals.py
# ======================================================================

class _FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture()
def q(tmp_path):
    clock = _FakeClock()
    queue = ApprovalQueue(tmp_path / "appr", clock=clock)
    queue._clock_test = clock
    return queue


def test_get_rid_com_caractere_invalido_e_recusado(q):
    with pytest.raises(ApprovalError, match="inválido"):
        q.get("id com espaço!")


def test_get_id_totalmente_inexistente_levanta_erro_claro(q):
    """rid válido no formato (uuid), mas nunca solicitado — nem .json nem
    .deciding existem em disco. _load() esgota as 2 tentativas e recusa."""
    rid_fantasma = str(uuid.uuid4())
    with pytest.raises(ApprovalError, match="inexistente"):
        q.get(rid_fantasma)


def test_expire_if_due_arquivo_sumiu_sob_lock_devolve_dados_intactos(q):
    """Simula a corrida real que o comentário do código descreve: entre o
    caller ler `data` (pendente e já expirado) e _expire_if_due() confirmar
    sob o lock, o arquivo sumiu (outro decide() reivindicou). Não pode
    quebrar nem inventar um estado — devolve `data` como veio."""
    dados = {"id": str(uuid.uuid4()), "status": PENDENTE,
             "expires": q.clock() - 1, "category": "A1", "target": "x",
             "reason": "y", "created": q.clock() - 10}
    resultado = q._expire_if_due(dict(dados))
    assert resultado == dados
    assert resultado["status"] == PENDENTE   # não foi marcado expirada às cegas


def test_token_of_apos_decidida_recusa(q):
    rid, token = q.request("A1", "x", "y")
    q.decide(rid, token, approve=True)
    with pytest.raises(ApprovalError, match="não está pendente"):
        q.token_of(rid)


def test_decide_concorrente_encontra_reivindicacao_de_outro_decisor(q):
    """Duas abas do painel decidindo ao mesmo tempo: a 2ª chega depois que a
    1ª já renomeou p -> .deciding. os.replace(p, claim) da 2ª falha com
    FileNotFoundError; _load() acha o claim (ainda "pendente" no disco) e a
    2ª é recusada sem mexer no que a 1ª está decidindo."""
    rid, token = q.request("A1", "x", "y")
    p = q.dir / f"{rid}.json"
    claim = p.with_suffix(".deciding")
    p.replace(claim)                          # simula 1ª decisão já reivindicada
    with pytest.raises(ApprovalError, match="pendente"):
        q.decide(rid, token, approve=True)
    assert claim.exists() and not p.exists()  # não tocou na reivindicação alheia


def test_decide_arquivo_corrompido_e_devolvido_a_fila(q):
    rid, token = q.request("A1", "x", "y")
    (q.dir / f"{rid}.json").write_text("{isto não é json válido")
    with pytest.raises(ApprovalError, match="ilegível"):
        q.decide(rid, token, approve=True)
    assert (q.dir / f"{rid}.json").exists()             # devolvido à fila
    assert not (q.dir / f"{rid}.deciding").exists()


def test_decide_direto_apos_expirar_sem_get_previo_marca_expirada(q):
    """decide() tem sua PRÓPRIA checagem de expiração (independente de
    _expire_if_due) — precisa recusar mesmo se ninguém chamou .get() antes
    (o disco ainda diz "pendente")."""
    rid, token = q.request("A1", "x", "y")
    q._clock_test.advance(DEFAULT_TTL_S + 1)
    with pytest.raises(ApprovalError, match="expirada"):
        q.decide(rid, token, approve=True)
    assert q.get(rid).status == EXPIRADA


def test_deny_all_pula_arquivo_corrompido_sem_quebrar(q):
    (q.dir / "corrompido.json").write_text("{não é json")
    rid, _ = q.request("A1", "x", "y")
    negadas = q.deny_all()
    assert negadas == 1                        # só o pedido válido foi negado
    assert q.get(rid).status == NEGADA


# ======================================================================
# audit.py
# ======================================================================

def test_flock_degrada_sem_fcntl_como_no_windows(tmp_path, monkeypatch):
    """Sem fcntl (ex.: Windows), _flock() degrada para 'yield' sem travar
    arquivo entre processos — não pode quebrar append()."""
    log = AuditLog(tmp_path / "a.jsonl")
    monkeypatch.setitem(sys.modules, "fcntl", None)   # força ImportError real
    rec = log.append("ev", x=1)
    assert rec["event"] == "ev"
    ok, _ = log.verify()
    assert ok


def test_tail_scan_tolera_linha_em_branco_com_newline_na_cauda(tmp_path):
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    log.append("ev1", n=1)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    tip, valid_end, tamanho = log._tail_scan()
    assert valid_end == tamanho, "linha em branco com \\n não é cauda inválida"


def test_tail_scan_pula_linha_corrompida_no_meio_sem_abortar(tmp_path):
    """Linha corrompida NO MEIO (uma linha boa depois dela) é pulada — o
    scan segue e volta a confiar na próxima linha boa. Construído com
    escrita crua (não via append(): o próprio reparo de cauda do append()
    apagaria a linha corrompida antes de eu conseguir observar o
    comportamento de _tail_scan() sobre uma corrupção real no meio —
    corrigido nesta versão do teste depois que a 1ª tentativa, com só
    1 linha boa + 1 corrompida NO FIM, na prática testava cauda inválida
    (valid_end<tamanho), não corrupção no meio; achado do próprio teste,
    corrigido antes do commit)."""
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    p.write_text(
        json.dumps({"hash": "aaa"}) + "\n" +
        "{corrompida, mas com newline}\n" +
        json.dumps({"hash": "bbb"}) + "\n",
        encoding="utf-8")
    tip, valid_end, tamanho = log._tail_scan()
    assert tamanho == p.stat().st_size
    assert valid_end == tamanho          # a ÚLTIMA linha (boa) fecha a cauda válida
    assert tip == "bbb"                  # tip é da última linha BOA, corrompida não conta


def test_last_hash_devolve_o_tip_da_cadeia(tmp_path):
    """_last_hash() não tem nenhum chamador em produção hoje — nem
    append()/_tail_scan_cached() o usam (ambos chamam _tail_scan() direto).
    Chamado aqui só para fechar a lacuna de cobertura; não é um achado de
    comportamento novo."""
    log = AuditLog(tmp_path / "a.jsonl")
    rec = log.append("ev1", n=1)
    assert log._last_hash() == rec["hash"]


def test_estado_para_no_primeiro_registro_corrompido(tmp_path):
    """estado() é mais rígido que _tail_scan(): não pula corrupção, para
    ali. Comportamento real verificado por execução (não assumido): `count`
    já foi incrementado PARA a linha corrompida antes do parse falhar (é
    'quantas linhas não-em-branco existem até aqui', não 'quantas são
    válidas') — só `tip` fica conservador, preso no hash da última linha
    BOA. A 1ª versão deste teste assumia count==2 (não contaria a linha
    ruim); falhou (veio 3), achado do próprio teste, corrigido aqui."""
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    log.append("ev1", n=1)
    rec2 = log.append("ev2", n=2)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{corrompido}\n")
    count, tip = log.estado()
    assert count == 3                # conta a linha corrompida como presente...
    assert tip == rec2["hash"]       # ...mas o tip não avança para ela


def test_tip_em_zero_negativo_e_arquivo_inexistente(tmp_path):
    log = AuditLog(tmp_path / "nunca-escrito.jsonl")
    assert log.tip_em(0) == GENESIS
    assert log.tip_em(-1) == GENESIS
    assert log.tip_em(1) is None             # arquivo nem existe


def test_tip_em_pula_branco_e_devolve_none_alem_do_fim_ou_corrompido(tmp_path):
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    rec1 = log.append("ev1", n=1)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n")                        # não conta como entrada
    rec2 = log.append("ev2", n=2)
    assert log.tip_em(1) == rec1["hash"]
    assert log.tip_em(2) == rec2["hash"]       # branco no meio não deslocou a contagem
    assert log.tip_em(99) is None              # além do fim
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{corrompido}\n")
    assert log.tip_em(3) is None               # 3ª entrada de verdade é ilegível


def test_verify_pula_linha_em_branco(tmp_path):
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    log.append("ev1", n=1)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    log.append("ev2", n=2)
    ok, idx = log.verify()
    assert ok, f"linha em branco não deveria contar como violação (idx={idx})"


def test_verify_detecta_linha_corrompida_como_violacao(tmp_path):
    """Ao contrário de _tail_scan() (tolerante), verify() é a checagem de
    integridade de verdade — corrupção no meio TEM que aparecer como
    violação, senão adulteração passaria despercebida."""
    p = tmp_path / "a.jsonl"
    log = AuditLog(p)
    log.append("ev1", n=1)
    log.append("ev2", n=2)
    with p.open("a", encoding="utf-8") as fh:
        fh.write("{corrompido}\n")
    ok, idx = log.verify()
    assert ok is False and idx == 2      # 3ª linha (0-based idx=2) é a corrompida


# ======================================================================
# missao.py
# ======================================================================

def test_resumo_organizar_lista_contagem_por_categoria(tmp_path):
    """Chamado DIRETO (não via `nomos missao planejar` em subprocesso, como
    test_cli_planejar_dry_run já faz) — o mesmo problema de invisibilidade
    de cobertura via subprocesso do P2-2 se aplica aqui: cli.py chama
    plano.resumo() só dentro de um processo filho nos testes existentes."""
    d = tmp_path / "pasta"
    d.mkdir()
    for nome in ("a.pdf", "b.pdf", "c.png"):
        (d / nome).write_text("x", encoding="utf-8")
    plano = ms.planejar_organizacao(d)
    texto = plano.resumo()
    assert "documentos/: 2 arquivo(s)" in texto
    assert "imagens/: 1 arquivo(s)" in texto


def test_resumo_renomear_trunca_apos_20_passos(tmp_path):
    d = tmp_path / "pasta"
    d.mkdir()
    for i in range(25):
        (d / f"arquivo{i:02d}_x.txt").write_text("x", encoding="utf-8")
    plano = ms.planejar_renomeacao(d, "_x", "_y")
    assert len(plano.passos) == 25
    texto = plano.resumo()
    assert "… e mais 5" in texto


def test_resumo_mostra_conflitos_quando_plano_nao_executavel(tmp_path):
    d = tmp_path / "pasta"
    d.mkdir()
    (d / "a.pdf").write_text("x", encoding="utf-8")
    (d / "documentos").mkdir()
    (d / "documentos" / "a.pdf").write_text("já existo", encoding="utf-8")
    plano = ms.planejar_organizacao(d)
    assert not plano.executavel
    assert "CONFLITOS" in plano.resumo()


def test_planejar_organizacao_pasta_inexistente_levanta_erro(tmp_path):
    with pytest.raises(ms.MissaoErro, match="não encontrada"):
        ms.planejar_organizacao(tmp_path / "fantasma")


def test_planejar_renomeacao_pasta_inexistente_levanta_erro(tmp_path):
    with pytest.raises(ms.MissaoErro, match="não encontrada"):
        ms.planejar_renomeacao(tmp_path / "fantasma", "a", "b")


def test_planejar_renomeacao_de_vazio_levanta_erro(tmp_path):
    d = tmp_path / "pasta"
    d.mkdir()
    with pytest.raises(ms.MissaoErro, match="--de"):
        ms.planejar_renomeacao(d, "", "x")


def test_planejar_renomeacao_ignora_ocultos_e_subpastas(tmp_path):
    d = tmp_path / "pasta"
    d.mkdir()
    (d / ".oculto_x.txt").write_text("x", encoding="utf-8")
    (d / "sub_x").mkdir()
    (d / "normal_x.txt").write_text("x", encoding="utf-8")
    plano = ms.planejar_renomeacao(d, "_x", "_y")
    assert {p.origem for p in plano.passos} == {"normal_x.txt"}


def test_planejar_renomeacao_recusa_nome_resultante_invalido(tmp_path):
    d = tmp_path / "pasta"
    d.mkdir()
    (d / "aaa.txt").write_text("x", encoding="utf-8")
    plano = ms.planejar_renomeacao(d, "aaa.txt", "")   # substituição total -> nome vazio
    assert not plano.executavel
    assert any("nome inválido" in c for c in plano.conflitos)


def test_executar_plano_vazio_ou_com_conflitos_levanta_erro(tmp_path):
    d = tmp_path / "pasta"
    d.mkdir()
    plano_vazio = ms.planejar_organizacao(d)
    with pytest.raises(ms.MissaoErro, match="não executável"):
        ms.executar(plano_vazio, aprovado=True, evidencias_dir=tmp_path / "e")


def test_executar_para_no_primeiro_erro_e_gera_evidencia_parcial(tmp_path):
    """Colisão que só aparece NA HORA de mover — o disco mudou entre
    planejar() e executar() (condição de corrida real: outro processo
    criou o destino nesse meio-tempo). executar() tem que parar no
    primeiro erro, não sobrescrever, e registrar PARCIAL na evidência."""
    d = tmp_path / "pasta"
    d.mkdir()
    (d / "a.pdf").write_text("a", encoding="utf-8")
    (d / "b.pdf").write_text("b", encoding="utf-8")
    plano = ms.planejar_organizacao(d)
    assert [p.origem for p in plano.passos] == ["a.pdf", "b.pdf"]
    (d / "documentos").mkdir()
    (d / "documentos" / "b.pdf").write_text("já tava lá", encoding="utf-8")
    with pytest.raises(ms.MissaoErro, match="interrompida"):
        ms.executar(plano, aprovado=True, evidencias_dir=tmp_path / "e")
    assert (d / "documentos" / "a.pdf").exists()                       # o que deu certo, moveu
    assert (d / "documentos" / "b.pdf").read_text() == "já tava lá"    # não sobrescreveu
    pacotes = list((tmp_path / "e").glob("EVIDENCIA_*"))
    assert len(pacotes) == 1
    manifesto = json.loads((pacotes[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifesto["status"] == "PARCIAL_INTERROMPIDA"


def test_desfazer_pacote_sem_manifesto_de_desfazer_levanta_erro(tmp_path):
    pacote_falso = tmp_path / "pacote-vazio"
    pacote_falso.mkdir()
    with pytest.raises(ms.MissaoErro, match=ms.DESFAZER_ARQ):
        ms.desfazer(pacote_falso, tmp_path, aprovado=True)


def test_desfazer_recusa_sobrescrever_destino_existente(tmp_path):
    d = tmp_path / "pasta"
    d.mkdir()
    (d / "a.pdf").write_text("x", encoding="utf-8")
    plano = ms.planejar_organizacao(d)
    pacote = ms.executar(plano, aprovado=True, evidencias_dir=tmp_path / "e")
    # algo reocupou o lugar de origem ANTES do desfazer rodar
    (d / "a.pdf").write_text("nova versão, não pode ser sobrescrita", encoding="utf-8")
    with pytest.raises(ms.MissaoErro, match="não sobrescrevo"):
        ms.desfazer(pacote, d, aprovado=True)
    assert (d / "a.pdf").read_text() == "nova versão, não pode ser sobrescrita"
