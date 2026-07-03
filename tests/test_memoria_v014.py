"""v0.14 — memória de verdade: semântica local, backup cifrado, consolidação."""
import io

import pytest

from nomos import cli
from nomos.cognition import backup as bkp
from nomos.cognition import semantica
from nomos.cognition.memory import Memory


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


# ---------------- semântica local ----------------

def test_vetor_deterministico_e_normalizado():
    v1, v2 = semantica.vetor("pagar aluguel"), semantica.vetor("pagar aluguel")
    assert v1 == v2
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-9


def test_similaridade_por_significado():
    frases = ["pagamento do aluguel do apartamento dia 5",
              "receita de bolo de cenoura",
              "consulta médica na quinta-feira"]
    ordem = semantica.ranquear("pagar a moradia", frases, k=1)
    assert ordem and ordem[0][0] == 0     # acha o aluguel, não o bolo


def test_recall_hibrido_preserva_keyword_e_completa(nomos_home, tmp_path):
    mem = Memory(tmp_path / "m.db")
    mem.remember("note", "pagar aluguel do apartamento dia 5")
    mem.remember("note", "bolo de cenoura da vovó")
    mem.remember("note", "levar o carro na revisão")
    # keyword exata continua vindo primeiro (compat com v0.10)
    r = mem.recall_hibrido("aluguel", k=2)
    assert r and "aluguel" in r[0].text
    # sem keyword em comum, ainda encontra por significado
    r2 = mem.recall_hibrido("pagamento da moradia", k=1)
    assert r2 and "aluguel" in r2[0].text


# ---------------- backup cifrado ----------------

def test_export_import_roundtrip(tmp_path):
    m1 = Memory(tmp_path / "a.db")
    m1.remember("note", "segredo pessoal do usuário")
    m1.remember("user", "mensagem antiga")
    destino = tmp_path / "backup.nomos"
    assert bkp.exportar(m1, destino, "senha-forte-123") == 2
    bruto = destino.read_bytes()
    assert b"segredo pessoal" not in bruto        # cifrado de verdade

    m2 = Memory(tmp_path / "b.db")
    novas, ignoradas = bkp.importar(m2, destino, "senha-forte-123")
    assert (novas, ignoradas) == (2, 0)
    assert any("segredo pessoal" in i.text for i in m2.recent(10))
    # reimportar não duplica
    novas2, ignoradas2 = bkp.importar(m2, destino, "senha-forte-123")
    assert (novas2, ignoradas2) == (0, 2)


def test_senha_errada_nao_importa_nada(tmp_path):
    m1 = Memory(tmp_path / "a.db")
    m1.remember("note", "coisa importante")
    destino = tmp_path / "b.nomos"
    bkp.exportar(m1, destino, "senha-forte-123")
    m2 = Memory(tmp_path / "b.db")
    with pytest.raises(bkp.BackupError, match="senha incorreta"):
        bkp.importar(m2, destino, "senha-errada-999")
    assert m2.count() == 0


def test_senha_curta_recusada(tmp_path):
    m = Memory(tmp_path / "a.db")
    with pytest.raises(bkp.BackupError, match="8 caracteres"):
        bkp.exportar(m, tmp_path / "x.nomos", "curta")


def test_arquivo_adulterado_recusado(tmp_path):
    m1 = Memory(tmp_path / "a.db")
    m1.remember("note", "x")
    destino = tmp_path / "b.nomos"
    bkp.exportar(m1, destino, "senha-forte-123")
    corpo = destino.read_bytes()
    destino.write_bytes(corpo[:-8] + b"AAAAAAAA")   # adultera o final
    with pytest.raises(bkp.BackupError):
        bkp.importar(Memory(tmp_path / "c.db"), destino, "senha-forte-123")


# ---------------- consolidação ----------------

def test_consolidar_extrai_fatos_e_tarefas(tmp_path):
    mem = Memory(tmp_path / "m.db")
    mem.remember("user", "eu prefiro respostas curtas, sem enrolação")
    mem.remember("user", "não posso esquecer de renovar o passaporte")
    mem.remember("assistant", "anotado!")
    mem.remember("user", "qual a capital da França?")   # não vira nota
    criadas = mem.consolidar()
    tudo = " | ".join(criadas)
    assert "preferência: respostas curtas" in tudo
    assert "tarefa:" in tudo and "passaporte" in tudo
    assert "capital da França" not in tudo
    # idempotente: rodar de novo não duplica
    assert mem.consolidar() == []


# ---------------- CLI ----------------

def test_cli_exportar_sem_tty_sem_env_nega(nomos_home, capsys, tmp_path):
    assert cli.main(["init"]) == 0
    assert cli.main(["memory", "exportar", str(tmp_path / "b.nomos")]) == 1
    assert "interativo" in capsys.readouterr().err


def test_cli_export_import_com_env(nomos_home, monkeypatch, capsys, tmp_path):
    assert cli.main(["init"]) == 0
    assert cli.main(["memory", "note", "lembrar", "de", "tudo"]) == 0
    monkeypatch.setenv("NOMOS_BACKUP_SENHA", "senha-forte-123")
    destino = tmp_path / "backup.nomos"
    assert cli.main(["memory", "exportar", str(destino)]) == 0
    assert destino.exists()
    assert cli.main(["memory", "importar", str(destino)]) == 0
    out = capsys.readouterr().out
    assert "0 memória(s) nova(s)" in out          # dedup: nada duplicado


def test_cli_consolidar(nomos_home, capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["memory", "note", "so uma nota"]) == 0
    assert cli.main(["memory", "consolidar"]) == 0
    assert "em dia" in capsys.readouterr().out
