"""Horizonte 3, item 2 (auditoria de 2026-07-17): correlação dos eventos de
evidência (evidencia.criada/evidencia.verificada) e backup
(backup.total.criado/backup.total.restaurado) no audit log.

Contexto: o P2-5 (Horizonte 2) corrigiu a mesma lacuna para
missao.executada/desfeita (kernel/missao.py) e documentou explicitamente,
no corpo do commit, que a MESMA causa-raiz existia aqui — um identificador
que já atravessa a operação como argumento de CLI (args.pacote / args.arquivo)
simplesmente não era propagado para o evento de auditoria da segunda ponta.
Este arquivo cobre o fechamento desse gap, sem duplicar a cobertura já
existente em test_evidencia_pacote.py (roundtrip/redação/adulteração) ou
test_v101.py (backup total: cifragem, exclusões, senha errada).
"""
import json
import sys
from pathlib import Path

from nomos import cli
from nomos.kernel.audit import AuditLog


def _eventos(caminho: Path) -> list[dict]:
    if not caminho.exists():
        return []
    return [json.loads(li) for li in caminho.read_text(encoding="utf-8").splitlines()
            if li.strip()]


# ---------------- evidencia.criada <-> evidencia.verificada ----------------

def test_evidencia_criada_e_verificada_correlacionam_pelo_pacote_no_audit(nomos_home):
    assert cli.main(["init"]) == 0
    assert cli.main(["evidencia", "criar", "missão de teste H3-item2"]) == 0
    pacotes = list((nomos_home / "evidencias").glob("EVIDENCIA_*"))
    assert len(pacotes) == 1
    pacote = pacotes[0]

    assert cli.main(["evidencia", "verificar", str(pacote)]) == 0

    eventos = _eventos(nomos_home / "logs" / "audit.jsonl")
    ev_criada = next(e for e in eventos if e["event"] == "evidencia.criada")
    ev_verificada = next(e for e in eventos if e["event"] == "evidencia.verificada")
    assert ev_criada["pacote"] == ev_verificada["pacote"] == pacote.name

    # a cadeia de hash segue íntegra com o campo novo (retrocompatível, mesma
    # prova aplicada ao P2-5: _canonical()/verify() não têm lista fixa de
    # campos esperados)
    ok, viol = AuditLog(nomos_home / "logs" / "audit.jsonl").verify()
    assert ok, f"cadeia quebrou na linha {viol}"


def test_evidencia_verificada_isolada_ainda_registra_pacote_sem_evento_criada(nomos_home):
    """O pacote pode ser verificado numa sessão sem ter sido criado nesta
    mesma execução (ex.: `nomos evidencia verificar` num pacote antigo) — o
    campo `pacote` deve aparecer de qualquer forma, sem exigir o evento
    'evidencia.criada' no mesmo log."""
    assert cli.main(["init"]) == 0
    assert cli.main(["evidencia", "criar", "missão isolada"]) == 0
    pacote = next((nomos_home / "evidencias").glob("EVIDENCIA_*"))
    # limpa o log para simular "verificar sem ter criado nesta sessão"
    (nomos_home / "logs" / "audit.jsonl").write_text("", encoding="utf-8")

    assert cli.main(["evidencia", "verificar", str(pacote)]) == 0
    eventos = _eventos(nomos_home / "logs" / "audit.jsonl")
    ev_verificada = next(e for e in eventos if e["event"] == "evidencia.verificada")
    assert ev_verificada["pacote"] == pacote.name


# ---------------- backup.total.criado <-> backup.total.restaurado ----------------

def test_backup_criado_e_restaurado_correlacionam_pelo_arquivo_no_audit(
        nomos_home, monkeypatch, tmp_path):
    assert cli.main(["init"]) == 0
    monkeypatch.setenv("NOMOS_BACKUP_SENHA", "senha-forte-123")
    destino = tmp_path / "meu-nomos.backup"
    assert cli.main(["backup", "criar", str(destino)]) == 0

    # Descoberta feita ao rodar este teste pela 1a vez: NÃO existe home
    # "vazio" alcançável via cli.main() — _paths()/config.ensure_home()
    # sempre povoa arquivos base (policy.json etc.) ANTES do próprio
    # comando `backup restaurar` checar `tem_conteudo`, então mesmo um home
    # novo em folha aciona o gate interativo de sobrescrita (E002 sem TTY,
    # já coberto em test_v101.py). Aqui simulamos um terminal real
    # respondendo "RESTAURAR", como no fluxo de produção — não existe (nem
    # deveria existir) um bypass não-interativo para essa confirmação.
    novo_home = tmp_path / "novo-home"
    monkeypatch.setenv("NOMOS_HOME", str(novo_home))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *_: "RESTAURAR")
    assert cli.main(["backup", "restaurar", str(destino)]) == 0

    # nota estrutural (não é bug): restaurar() sobrescreve home/logs/audit.jsonl
    # com o audit.jsonl QUE ESTAVA DENTRO DO PACOTE — necessariamente anterior
    # ao próprio evento 'backup.total.criado' (ele só é anexado ao log ao
    # VIVO depois que bt.criar() já seria o pacote). Por isso os dois
    # eventos nunca vão estar na MESMA cadeia física — a correlação é
    # entre logs (origem vs. destino), pelo nome do arquivo de backup, não
    # dentro de um único audit.jsonl (diferente do caso evidencia.*/missao.*,
    # que operam sobre uma cadeia ao vivo contínua).
    ev_criado = next(e for e in _eventos(nomos_home / "logs" / "audit.jsonl")
                     if e["event"] == "backup.total.criado")
    ev_restaurado = next(e for e in _eventos(novo_home / "logs" / "audit.jsonl")
                         if e["event"] == "backup.total.restaurado")
    assert ev_criado["arquivo_backup"] == ev_restaurado["arquivo_backup"] == destino.name
    # a contagem de arquivos (`arquivos`) continua existindo e distinta do
    # novo campo — não foi removida nem colidiu com ele
    assert isinstance(ev_criado["arquivos"], int)
    assert isinstance(ev_restaurado["arquivos"], int)

    ok1, viol1 = AuditLog(nomos_home / "logs" / "audit.jsonl").verify()
    assert ok1, f"cadeia (home origem) quebrou na linha {viol1}"
    ok2, viol2 = AuditLog(novo_home / "logs" / "audit.jsonl").verify()
    assert ok2, f"cadeia (home destino) quebrou na linha {viol2}"
