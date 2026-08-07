"""H4.5-B (missão de selagem arquitetural, 2026-08-04): o reparo de
`agent.json` corrompido não pode apagar silenciosamente a única evidência
da corrupção — reforça `doutor.consertar()` (que já preservava o original
como `.corrompido` desde H4/HIGH-01, mas sem hash, sem modo explícito na
quarentena, sem o caminho na resposta, e sem proteção against falha
parcial de I/O) com garantias forenses adicionais, reaproveitando o
mecanismo genérico já existente (não um subsistema paralelo específico de
agent.json — a mesma correção vale para localidade.json/policy.json/
skills_estado.json/rotinas.json, todos passam pelo mesmo branch
`elif tipo == "arquivo":`).

Cobre, na ordem pedida pela missão:
1. diagnóstico simples não altera o arquivo;
2. reparo preserva o conteúdo corrompido (byte a byte, mais o hash);
3. novo arquivo contém configuração mínima válida;
4. modo do novo arquivo é 0600;
5. backup não é sobrescrito (segunda corrupção diferente vira .corrompido.1);
6. segunda execução é idempotente;
7. falha durante backup não destrói o original.
"""
from __future__ import annotations

import hashlib
import json
import stat
import sys
from pathlib import Path

import pytest

from nomos.kernel import config
from nomos.simple import doutor

# H4.10: `os.chmod(..., 0o600)` no Windows não força modo POSIX (o arquivo
# fica 0o666=438 em vez de 0o600=384). Marcamos este teste como Linux/macOS
# apenas — a garantia semântica de modo 0o600 vale em POSIX; em Windows
# vale o ACL, que é testado em outro lugar.
_POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mode 0o600 é semântica POSIX; Windows usa ACLs",
)

CORROMPIDO = "{corrompido: sem aspas, json invalido"


def _corromper_agent_json(home: Path, conteudo: str = CORROMPIDO) -> None:
    config.ensure_home()
    (home / "agent.json").write_text(conteudo, encoding="utf-8")


def _modo(caminho: Path) -> int:
    return stat.S_IMODE(caminho.stat().st_mode)


# --------------------------------------------------------------------------
# 1) Diagnóstico simples (sem confirmar) não altera nada
# --------------------------------------------------------------------------

def test_diagnostico_simples_nao_altera_o_arquivo(nomos_home):
    _corromper_agent_json(nomos_home)
    conteudo_antes = (nomos_home / "agent.json").read_text(encoding="utf-8")

    achados = doutor.diagnosticar_consertos(nomos_home)

    assert any(a["id"] == "arquivo:agent.json" for a in achados)
    assert (nomos_home / "agent.json").read_text(encoding="utf-8") == conteudo_antes
    assert not (nomos_home / "agent.json.corrompido").exists()


def test_consertar_sem_confirmacao_nao_altera_nada(nomos_home):
    _corromper_agent_json(nomos_home)
    conteudo_antes = (nomos_home / "agent.json").read_text(encoding="utf-8")

    rc, feitos = doutor.consertar(nomos_home, confirmar=lambda: False, say=lambda *a: None)

    assert rc == 3
    assert feitos == []
    assert (nomos_home / "agent.json").read_text(encoding="utf-8") == conteudo_antes
    assert not (nomos_home / "agent.json.corrompido").exists()


# --------------------------------------------------------------------------
# 2) Reparo preserva o conteúdo corrompido (byte a byte + hash)
# --------------------------------------------------------------------------

def test_reparo_preserva_conteudo_corrompido_byte_a_byte(nomos_home):
    _corromper_agent_json(nomos_home)
    hash_esperado = hashlib.sha256(CORROMPIDO.encode("utf-8")).hexdigest()

    rc, feitos = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None)

    assert rc == 0
    quarentena = nomos_home / "agent.json.corrompido"
    assert quarentena.exists()
    assert quarentena.read_text(encoding="utf-8") == CORROMPIDO
    # o hash do conteúdo original aparece na resposta (evidência forense
    # verificável sem precisar reabrir o arquivo de quarentena)
    assert any(hash_esperado[:16] in f for f in feitos), feitos
    assert any(str(quarentena) in f for f in feitos), feitos


def test_reparo_registra_hash_e_caminho_de_quarentena_na_auditoria(nomos_home):
    from nomos.kernel.audit import AuditLog
    audit = AuditLog(nomos_home / "logs" / "audit.jsonl")
    _corromper_agent_json(nomos_home)
    hash_esperado = hashlib.sha256(CORROMPIDO.encode("utf-8")).hexdigest()

    rc, _ = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None,
                             audit=audit)

    assert rc == 0
    linhas = [json.loads(linha) for linha in
              (nomos_home / "logs" / "audit.jsonl").read_text().splitlines() if linha.strip()]
    eventos = [r for r in linhas if r.get("event") == "doutor.consertado"
              and r.get("item") == "arquivo:agent.json"]
    assert len(eventos) == 1, linhas
    assert eventos[0]["sha256"] == hash_esperado
    assert eventos[0]["quarentena"].endswith("agent.json.corrompido")
    # o CONTEÚDO corrompido nunca aparece no log de auditoria, só hash/caminho
    log_bruto = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert "corrompido: sem aspas" not in log_bruto


# --------------------------------------------------------------------------
# 3) Novo arquivo contém configuração mínima válida
# --------------------------------------------------------------------------

def test_novo_agent_json_e_minimo_e_valido(nomos_home):
    _corromper_agent_json(nomos_home)

    rc, _ = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None)

    assert rc == 0
    novo = (nomos_home / "agent.json").read_text(encoding="utf-8")
    assert json.loads(novo) == {}          # mínimo válido, mesmo formato de sempre
    assert config.load_agent() == {}       # e o consumidor real volta a funcionar


# --------------------------------------------------------------------------
# 4) Modo do novo arquivo (e da quarentena) é 0600
# --------------------------------------------------------------------------

@_POSIX_ONLY
def test_novo_agent_json_e_quarentena_tem_modo_0600(nomos_home):
    _corromper_agent_json(nomos_home)

    rc, _ = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None)

    assert rc == 0
    assert _modo(nomos_home / "agent.json") == 0o600
    assert _modo(nomos_home / "agent.json.corrompido") == 0o600


# --------------------------------------------------------------------------
# 5) Backup não é sobrescrito — segunda corrupção vira .corrompido.1
# --------------------------------------------------------------------------

def test_segunda_corrupcao_nao_sobrescreve_quarentena_anterior(nomos_home):
    _corromper_agent_json(nomos_home, "primeira corrupcao: {")
    rc1, _ = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None)
    assert rc1 == 0
    primeira_quarentena = (nomos_home / "agent.json.corrompido").read_text(encoding="utf-8")
    assert primeira_quarentena == "primeira corrupcao: {"

    _corromper_agent_json(nomos_home, "segunda corrupcao, diferente: [")
    rc2, feitos2 = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None)
    assert rc2 == 0

    # a quarentena original continua intacta...
    assert (nomos_home / "agent.json.corrompido").read_text(encoding="utf-8") == \
        "primeira corrupcao: {"
    # ...e a segunda corrupção foi preservada num arquivo NOVO, não por cima
    segunda_quarentena = nomos_home / "agent.json.corrompido.1"
    assert segunda_quarentena.exists()
    assert segunda_quarentena.read_text(encoding="utf-8") == "segunda corrupcao, diferente: ["
    assert any(str(segunda_quarentena) in f for f in feitos2), feitos2


# --------------------------------------------------------------------------
# 6) Segunda execução (sem nova corrupção) é idempotente
# --------------------------------------------------------------------------

def test_segunda_execucao_sem_nova_corrupcao_e_idempotente(nomos_home, capsys):
    _corromper_agent_json(nomos_home)
    rc1, feitos1 = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None)
    assert rc1 == 0
    assert len(feitos1) >= 1

    mensagens: list[str] = []
    rc2, feitos2 = doutor.consertar(nomos_home, confirmar=lambda: True,
                                    say=mensagens.append)

    assert rc2 == 0
    assert feitos2 == []                    # nada mais para consertar
    assert any("íntegro" in m for m in mensagens)
    # o agent.json continua exatamente "{}" — não foi tocado de novo
    assert (nomos_home / "agent.json").read_text(encoding="utf-8") == "{}"
    # nem uma segunda quarentena foi criada
    assert not (nomos_home / "agent.json.corrompido.1").exists()


# --------------------------------------------------------------------------
# 7) Falha durante o backup (rename atômico) não destrói o original
# --------------------------------------------------------------------------

def test_falha_ao_mover_para_quarentena_preserva_original_sem_crash(
        nomos_home, monkeypatch):
    _corromper_agent_json(nomos_home)
    conteudo_antes = (nomos_home / "agent.json").read_text(encoding="utf-8")

    def _os_replace_quebrado(*a, **k):
        raise OSError("disco cheio (simulado)")

    monkeypatch.setattr("nomos.simple.doutor.os.replace", _os_replace_quebrado)

    rc, feitos = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None)

    assert rc == 1                          # falhou, mas não crashou
    assert any("FALHA" in f for f in feitos), feitos
    # o original continua exatamente como estava — nada foi destruído
    assert (nomos_home / "agent.json").exists()
    assert (nomos_home / "agent.json").read_text(encoding="utf-8") == conteudo_antes
    assert not (nomos_home / "agent.json.corrompido").exists()


def test_falha_ao_mover_registra_evento_de_auditoria_verificavel(nomos_home, monkeypatch):
    from nomos.kernel.audit import AuditLog
    audit = AuditLog(nomos_home / "logs" / "audit.jsonl")
    _corromper_agent_json(nomos_home)

    def _os_replace_quebrado(*a, **k):
        raise PermissionError("permissão negada (simulado)")

    monkeypatch.setattr("nomos.simple.doutor.os.replace", _os_replace_quebrado)

    rc, _ = doutor.consertar(nomos_home, confirmar=lambda: True, say=lambda *a: None,
                             audit=audit)

    assert rc == 1
    linhas = [json.loads(linha) for linha in
              (nomos_home / "logs" / "audit.jsonl").read_text().splitlines() if linha.strip()]
    falhas = [r for r in linhas if r.get("event") == "doutor.conserto_falhou"]
    assert len(falhas) == 1, linhas
    assert falhas[0]["item"] == "arquivo:agent.json"
    assert falhas[0]["erro"] == "PermissionError"   # diagnóstico verificável,
                                                     # não um catch genérico mudo
