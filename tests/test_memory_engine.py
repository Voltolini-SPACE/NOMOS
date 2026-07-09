"""MC28 — NOMOS Memory Engine: orquestrador (engine) + garantias de segurança.

Cobre: dry-run não grava, apply grava, apply bloqueado não grava, integridade
íntegra valida, adulteração falha, listagem, relatório, falha-fechada em campo
inválido, isolamento (leitura não cria arquivos, sem vínculo com repo externo)
e as invariantes "sem subprocesso" e "sem rede" no código final do módulo.
"""
import re
from pathlib import Path

import nomos.memory as _pkg
from nomos.memory.engine import MemoryEngine

PKG_DIR = Path(_pkg.__file__).parent


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in PKG_DIR.glob("*.py")}


# ---------------- dry-run / apply ----------------
def test_dry_run_nao_grava(tmp_path):
    base = tmp_path / "mem"
    r = MemoryEngine(base_dir=base).add("memoria valida e limpa")
    assert r.allowed and r.dry_run and not r.applied
    assert not base.exists()          # nada foi criado no disco


def test_apply_grava(tmp_path):
    base = tmp_path / "mem"
    eng = MemoryEngine(base_dir=base)
    r = eng.add("memoria valida e limpa", apply=True)
    assert r.applied and not r.dry_run
    assert eng.store.paths.raw.exists()
    assert len(eng.list_entries()) == 1


def test_apply_bloqueado_nao_grava(tmp_path):
    eng = MemoryEngine(base_dir=tmp_path / "mem")
    r = eng.add("chave sk-ABCDEFGHIJKLMNOP1234567890xyz", apply=True)
    assert r.applied is False and r.allowed is False
    assert r.reason == "MEMORY_REJECTED_FAIL_CLOSED"
    assert eng.list_entries() == []   # fail-closed: nada persistido


# ---------------- integridade ----------------
def test_hash_integro_valida(tmp_path):
    eng = MemoryEngine(base_dir=tmp_path / "mem")
    eng.add("conteudo limpo", apply=True)
    v = eng.validate()
    assert v.checked == 1 and v.ok == 1 and v.valid is True


def test_hash_adulterado_falha(tmp_path):
    eng = MemoryEngine(base_dir=tmp_path / "mem")
    eng.add("conteudo original limpo", apply=True)
    p = eng.store.paths.raw
    p.write_text(p.read_text().replace("conteudo original limpo", "ADULTERADO"))
    v = eng.validate()
    assert v.tampered and v.valid is False


# ---------------- listagem / relatório ----------------
def test_listagem_funciona(tmp_path):
    eng = MemoryEngine(base_dir=tmp_path / "mem")
    eng.add("um", apply=True)
    eng.add("dois", apply=True)
    assert len(eng.list_entries()) == 2


def test_relatorio_gerado(tmp_path):
    eng = MemoryEngine(base_dir=tmp_path / "mem")
    eng.add("conteudo", apply=True)
    rep, md, path = eng.report(apply=False)
    assert rep["total_raw"] == 1 and "Relatório" in md and path is None
    _, _, path2 = eng.report(apply=True)
    assert path2 and Path(path2).exists()


# ---------------- falha fechada ----------------
def test_falha_fechada_campo_invalido(tmp_path):
    eng = MemoryEngine(base_dir=tmp_path / "mem")
    assert eng.add("conteudo limpo", source="externo", apply=True).applied is False
    assert eng.add("conteudo limpo", scope="global", apply=True).applied is False
    assert eng.add("conteudo limpo", priority="urgent", apply=True).applied is False
    assert eng.list_entries() == []


def test_leitura_nao_cria_arquivos(tmp_path):
    base = tmp_path / "inexistente"
    eng = MemoryEngine(base_dir=base)
    eng.list_entries()
    eng.context()
    eng.validate()
    assert not base.exists()


# ---------------- invariantes de segurança do CÓDIGO ----------------
def test_modulo_sem_subprocesso():
    for nome, src in _sources().items():
        assert not re.search(r"(?m)^\s*(?:import|from)\s+subprocess\b", src), nome
        assert not re.search(r"\bsubprocess\.\w+\s*\(", src), nome
        assert not re.search(r"\bos\.system\s*\(", src), nome
        assert not re.search(r"\b(?:os\.popen|Popen)\s*\(", src), nome
        assert not re.search(r"\beval\s*\(", src), nome
        assert not re.search(r"\bexec\s*\(", src), nome


def test_modulo_sem_rede():
    for nome, src in _sources().items():
        assert not re.search(
            r"(?m)^\s*(?:import|from)\s+"
            r"(?:socket|requests|urllib|http|ftplib|smtplib|telnetlib)\b", src), nome
        assert not re.search(r"\bsocket\.\w+\s*\(", src), nome
        # nenhuma URL de cliente http embutida no runtime
        assert "http://" not in src and "https://" not in src, nome


def test_sem_vinculo_com_repo_externo():
    proibidos = ("claude_mem", "claude-mem", "chromadb", "bullmq", "chroma.sqlite")
    for nome, src in _sources().items():
        low = src.lower()
        for tok in proibidos:
            assert tok not in low, f"{nome} referencia {tok}"
