"""v0.13 — arquivos e voz: pipeline local, honesto e governado."""
import io

import pytest

from nomos import cli
from nomos.cognition import arquivos as arq
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import PolicyEngine


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _ctx(nomos_home):
    nomos_home.mkdir(parents=True, exist_ok=True)
    return {"home": nomos_home,
            "policy": PolicyEngine(nomos_home / "policy.json"),
            "audit": AuditLog(nomos_home / "logs" / "audit.jsonl")}


class _RouterFake:
    class _Out:
        ok, text = True, "Resumo local do documento em três frases."
    def chat(self, messages):
        return self._Out()


# ---------------- extração ----------------

def test_extrair_txt_e_md(tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo simples")
    (tmp_path / "b.md").write_text("# Título\ncorpo")
    assert arq.extrair_texto(tmp_path / "a.txt") == ("conteúdo simples", "txt")
    assert arq.extrair_texto(tmp_path / "b.md")[1] == "md"


def test_formato_nao_suportado_erro_honesto(tmp_path):
    (tmp_path / "x.exe").write_bytes(b"MZ")
    with pytest.raises(arq.ArquivoError, match="não suportado"):
        arq.extrair_texto(tmp_path / "x.exe")


def test_arquivo_inexistente_e_grande(tmp_path):
    with pytest.raises(arq.ArquivoError, match="não encontrado"):
        arq.extrair_texto(tmp_path / "nao-existe.txt")
    grande = tmp_path / "g.txt"
    grande.write_bytes(b"x" * (arq.LIMITE_BYTES + 1))
    with pytest.raises(arq.ArquivoError, match="grande demais"):
        arq.extrair_texto(grande)


def test_pdf_sem_dependencia_orienta(tmp_path, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "pypdf", None)
    (tmp_path / "d.pdf").write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(arq.ArquivoError, match="nomos\\[arquivos\\]"):
        arq.extrair_texto(tmp_path / "d.pdf")


def test_extrair_pontos_titulos_e_listas():
    texto = ("# Plano\n- comprar servidor\n- migrar banco\n"
             "Observações finais:\ntexto corrido aqui.")
    pontos = arq.extrair_pontos(texto)
    assert "Plano" in pontos and "comprar servidor" in pontos
    assert "Observações finais" in pontos


def test_extrair_pontos_texto_corrido():
    texto = ("A reunião definiu que o lançamento será em março do ano que vem. "
             "O orçamento aprovado foi de cem mil reais para a primeira fase. "
             "Ficou pendente a contratação de duas pessoas para o time.")
    pontos = arq.extrair_pontos(texto)
    assert len(pontos) >= 2 and any("lançamento" in p for p in pontos)


# ---------------- pipeline ----------------

def test_processar_com_motor_local(tmp_path, nomos_home):
    doc = tmp_path / "doc.md"
    doc.write_text("# Projeto X\n- meta um\n- meta dois\n")
    resultado, estado = arq.processar(doc, _ctx(nomos_home), approver=None,
                                      router=_RouterFake())
    assert resultado.ok
    assert estado["resumo"].startswith("Resumo local")
    assert "meta um" in estado["pontos"]
    assert "Nada saiu da sua máquina" in resultado.explicacao


def test_processar_sem_motor_e_honesto(tmp_path, nomos_home):
    doc = tmp_path / "doc.txt"
    doc.write_text("- item alfa\n- item beta\n")
    resultado, estado = arq.processar(doc, _ctx(nomos_home), approver=None,
                                      router=None)
    assert resultado.ok and estado["resumo"] is None
    corpo = arq.render_resultado(doc, estado)
    assert "cerebro baixar" in corpo and "item alfa" in corpo


def test_salvar_exige_aprovacao_a1(tmp_path, nomos_home):
    doc = tmp_path / "doc.txt"
    doc.write_text("- ponto\n")
    ctx = _ctx(nomos_home)
    # sem aprovador: etapa salvar (A1) nega e NADA é escrito
    resultado, estado = arq.processar(doc, ctx, approver=None,
                                      router=None, salvar=True)
    assert resultado.ok is False and resultado.etapa_falhou == "salvar-resumo"
    assert not doc.with_suffix(".txt.resumo.md").exists()
    # com humano aprovando: salva
    resultado2, estado2 = arq.processar(doc, ctx, approver=lambda d: True,
                                        router=None, salvar=True)
    assert resultado2.ok and doc.with_suffix(".txt.resumo.md").exists()


# ---------------- voz ----------------

def test_transcrever_sem_whisper_orienta(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda *a: None)
    audio = tmp_path / "fala.wav"
    audio.write_bytes(b"RIFF")
    with pytest.raises(arq.ArquivoError, match="whisper"):
        arq.transcrever(audio)


def test_transcrever_com_transcritor_injetado(tmp_path):
    audio = tmp_path / "fala.wav"
    audio.write_bytes(b"RIFF")
    texto = arq.transcrever(audio, transcritor=lambda p: "olá do áudio")
    assert texto == "olá do áudio"


# ---------------- CLI ----------------

def test_cli_arquivo_sem_motor(tmp_path, capsys):
    assert cli.main(["init"]) == 0
    doc = tmp_path / "notas.md"
    doc.write_text("# Notas\n- primeira\n- segunda\n")
    assert cli.main(["arquivo", str(doc), "--sem-motor"]) == 0
    out = capsys.readouterr().out
    assert "primeira" in out and "Nada saiu da sua máquina" in out


def test_cli_arquivo_inexistente(capsys):
    assert cli.main(["init"]) == 0
    assert cli.main(["arquivo", "/nao/existe.txt"]) == 1
    assert "não deu" in capsys.readouterr().err


def test_cli_arquivo_salvar_nega_sem_tty(tmp_path, capsys):
    assert cli.main(["init"]) == 0
    doc = tmp_path / "n.txt"
    doc.write_text("- a\n")
    rc = cli.main(["arquivo", str(doc), "--sem-motor", "--salvar"])
    assert rc == 3                                # A1 negado fail-closed
    assert not doc.with_suffix(".txt.resumo.md").exists()
