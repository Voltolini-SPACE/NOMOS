"""F2 — histórico de conversas: store, modo privado, retenção, export cifrado."""
import io

import pytest

from nomos import cli
from nomos.conversations import retention as ret
from nomos.conversations.store import ConversationStore


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ---------------- store ----------------

def test_persiste_conversa_e_gera_titulo(nomos_home):
    st = ConversationStore(nomos_home / "c.db")
    cid = st.nova_conversa(motor="embutido")
    st.add_turno(cid, "user", "preciso organizar minhas finanças de janeiro")
    st.add_turno(cid, "assistant", "vamos lá")
    conv, turnos = st.abrir(cid)
    assert conv.titulo.startswith("preciso organizar")   # título local automático
    assert "financas" in conv.tags or "organizar" in conv.tags
    assert len(turnos) == 2 and conv.n_turnos == 2
    assert (nomos_home / "c.db").exists()


def test_busca_por_palavra_e_significado(nomos_home):
    st = ConversationStore(nomos_home / "c.db")
    cid = st.nova_conversa()
    st.add_turno(cid, "user", "onde guardei o contrato do apartamento")
    st.add_turno(cid, "assistant", "está na pasta Documentos")
    outra = st.nova_conversa()
    st.add_turno(outra, "user", "receita de bolo de cenoura")
    r = st.buscar("contrato")
    assert r and r[0][0].id == cid
    # semântica: "aluguel/imóvel" acha o contrato do apartamento, não o bolo
    r2 = st.buscar("imóvel apartamento")
    assert any(c.id == cid for c, _ in r2)


def test_esquecer_e_fixar(nomos_home):
    st = ConversationStore(nomos_home / "c.db")
    cid = st.nova_conversa()
    st.add_turno(cid, "user", "algo")
    st.fixar(cid, True)
    assert st.listar()[0].fixada is True
    assert st.esquecer(cid) is True
    assert st.count() == 0


def test_nao_usar_como_memoria(nomos_home):
    st = ConversationStore(nomos_home / "c.db")
    cid = st.nova_conversa()
    st.add_turno(cid, "user", "segredo de família")
    st.definir_usar_memoria(cid, False)
    conv, _ = st.abrir(cid)
    assert conv.usar_como_memoria is False


# ---------------- P1-8 (auditoria de 2026-07-17): sem N+1, com índice ----------------

def test_listar_nao_e_mais_n_mais_1(nomos_home):
    """Antes, cada linha de `listar()` disparava um SELECT COUNT(*) próprio
    (listar(50) chegava a 51 statements SQL). Agora é 1 statement, com a
    contagem agregada num único GROUP BY — independente de quantas
    conversas existam."""
    st = ConversationStore(nomos_home / "c.db")
    for i in range(12):
        cid = st.nova_conversa()
        st.add_turno(cid, "user", f"conversa numero {i}")
    log: list[str] = []
    st.conn.set_trace_callback(log.append)
    r = st.listar(50)
    st.conn.set_trace_callback(None)
    assert len(r) == 12
    assert all(c.n_turnos == 1 for c in r)
    assert len(log) == 1, f"listar() disparou {len(log)} statements (esperado 1): {log}"


def test_abrir_deriva_contagem_sem_query_extra(nomos_home):
    """`abrir()` já busca todos os turnos da conversa — n_turnos vem de
    `len(turnos)`, sem mais nenhum SELECT COUNT(*) redundante."""
    st = ConversationStore(nomos_home / "c.db")
    cid = st.nova_conversa()
    for i in range(5):
        st.add_turno(cid, "user", f"turno {i}")
    log: list[str] = []
    st.conn.set_trace_callback(log.append)
    conv, turnos = st.abrir(cid)
    st.conn.set_trace_callback(None)
    assert conv.n_turnos == 5 == len(turnos)
    assert len(log) == 2, f"abrir() disparou {len(log)} statements (esperado 2): {log}"


def test_indice_em_turnos_conversa_id_existe_e_e_usado(nomos_home):
    st = ConversationStore(nomos_home / "c.db")
    nomes_indice = {r[0] for r in st.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_turnos_conversa_id" in nomes_indice
    plano = st.conn.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM turnos WHERE conversa_id=1").fetchall()
    assert any("idx_turnos_conversa_id" in str(linha) for linha in plano), plano


def test_buscar_nao_chama_abrir_por_achado(nomos_home):
    """Antes, `buscar(k)` chamava `abrir(cid)` (2 queries) para cada um dos
    até k achados — um segundo N+1. Agora é 1 SELECT batched no final,
    então o total de statements NOSSOS não cresce linearmente com k.

    Statements que começam com ``--`` são gerados internamente pelo módulo
    FTS5 do próprio SQLite (leitura de segmentos/docsize para o bm25()) —
    não são nada que este código dispare, então ficam de fora da contagem;
    seria ruído medir implementação interna do SQLite, não o N+1 do NOMOS."""
    st = ConversationStore(nomos_home / "c.db")
    for i in range(15):
        cid = st.nova_conversa()
        st.add_turno(cid, "user", f"contrato numero {i} sobre imposto")
    log: list[str] = []
    st.conn.set_trace_callback(log.append)
    r = st.buscar("contrato", k=10)
    st.conn.set_trace_callback(None)
    assert r
    nossos = [sql for sql in log if not sql.strip().startswith("--")]
    # antes: 1 (FTS) + k*2 (abrir por achado) = até 21 statements NOSSOS só
    # nessa cauda; agora é 1 (FTS) [+ eventual fallback semântico] + 1 (batch).
    assert len(nossos) <= 3, f"buscar() disparou {len(nossos)} statements: {nossos}"


# ---------------- modo privado NÃO toca o disco ----------------

def test_modo_privado_nao_grava_em_disco(nomos_home, tmp_path):
    caminho = tmp_path / "priv.db"
    st = ConversationStore(caminho, privado=True)
    cid = st.nova_conversa()
    st.add_turno(cid, "user", "isto é confidencial e efêmero")
    assert st.count() == 1                       # existe em memória
    assert not caminho.exists()                  # mas NADA no disco
    st.close()
    # reabrir persistente: não há nada
    st2 = ConversationStore(caminho)
    assert st2.count() == 0


def test_chat_modo_privado_nao_persiste(nomos_home):
    from nomos.kernel.policy import PolicyEngine
    from nomos.simple import amigavel

    class _RouterEco:
        def chat_stream(self, messages, on_token):
            from nomos.cognition.router import ChatOutcome
            on_token("oi")
            return ChatOutcome(True, "local", "oi", "embutido", "m")

    feed = iter(["/privado", "guarda esse segredo", "/sair"])
    tela = []
    ctx = {"home": nomos_home, "policy": PolicyEngine(nomos_home / "p.json")}
    amigavel.iniciar_chat(ctx, {"agent_name": "L"}, router=_RouterEco(),
                          ask=lambda _: next(feed), say=tela.append,
                          colorido=False, aprovador=lambda d: True,
                          say_token=lambda t: None)
    # conversas.db não deve conter o segredo (modo privado ligado antes de falar)
    dbp = nomos_home / "conversas.db"
    if dbp.exists():
        assert b"segredo" not in dbp.read_bytes()
    assert "modo privado LIGADO" in "\n".join(tela)


# ---------------- retenção ----------------

def test_retencao_expira_nao_fixadas(nomos_home):
    import time
    st = ConversationStore(nomos_home / "c.db")
    velha = st.nova_conversa()
    st.add_turno(velha, "user", "conversa velha")
    st.conn.execute("UPDATE conversas SET ultima_ts=? WHERE id=?",
                    (time.time() - 40 * 86400, velha))
    st.conn.commit()
    fixa = st.nova_conversa()
    st.add_turno(fixa, "user", "conversa velha mas fixada")
    st.conn.execute("UPDATE conversas SET ultima_ts=? WHERE id=?",
                    (time.time() - 40 * 86400, fixa))
    st.fixar(fixa, True)
    apagadas = ret.aplicar_retencao(st, dias=30)
    assert apagadas == 1                          # só a não fixada
    ids = {c.id for c in st.listar()}
    assert fixa in ids and velha not in ids


# ---------------- export/import cifrado ----------------

def test_export_import_cifrado(nomos_home, tmp_path):
    st = ConversationStore(nomos_home / "c.db")
    cid = st.nova_conversa()
    st.add_turno(cid, "user", "informação pessoal delicada")
    destino = tmp_path / "conversas.export"
    assert ret.exportar(st, destino, "senha-forte-123") == 1
    assert b"informacao pessoal" not in destino.read_bytes()   # cifrado
    assert b"informa\xc3\xa7\xc3\xa3o pessoal" not in destino.read_bytes()

    st2 = ConversationStore(tmp_path / "novo.db")
    assert ret.importar(st2, destino, "senha-forte-123") == 1
    _, turnos = st2.abrir(st2.listar()[0].id)
    assert any("delicada" in t.text for t in turnos)


def test_export_senha_errada_nada_importa(nomos_home, tmp_path):
    st = ConversationStore(nomos_home / "c.db")
    st.add_turno(st.nova_conversa(), "user", "x")
    destino = tmp_path / "e.export"
    ret.exportar(st, destino, "senha-forte-123")
    st2 = ConversationStore(tmp_path / "n.db")
    with pytest.raises(ret.ConversaBackupError, match="senha incorreta"):
        ret.importar(st2, destino, "senha-errada-000")
    assert st2.count() == 0


# ---------------- CLI ----------------

def test_cli_conversas_listar_vazio(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["conversas"]) == 0
    assert "nenhuma conversa" in capsys.readouterr().out


def test_cli_conversas_ciclo(nomos_home, monkeypatch, capsys, tmp_path):
    assert cli.main(["init"]) == 0
    st = ConversationStore(nomos_home / "conversas.db")
    cid = st.nova_conversa()
    st.add_turno(cid, "user", "conversa sobre imposto de renda")
    st.close()
    assert cli.main(["conversas", "listar"]) == 0
    assert "imposto" in capsys.readouterr().out
    assert cli.main(["conversas", "buscar", "imposto"]) == 0
    assert f"#{cid}" in capsys.readouterr().out
    monkeypatch.setenv("NOMOS_BACKUP_SENHA", "senha-forte-123")
    dest = tmp_path / "c.export"
    assert cli.main(["conversas", "exportar", str(dest)]) == 0
    assert dest.exists()
    assert cli.main(["conversas", "esquecer", str(cid)]) == 0


def test_cli_retencao(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["conversas", "retencao", "30"]) == 0
    assert "30 dia" in capsys.readouterr().out
    assert cli.main(["conversas", "retencao"]) == 0
    assert "30 dia" in capsys.readouterr().out
