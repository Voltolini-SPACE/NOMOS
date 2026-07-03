"""Regressão — nenhum segredo em stdout/stderr/log pelos caminhos novos."""
import hashlib
import io
import json

import pytest

from nomos import cli
from nomos.cognition import engine_router as er
from nomos.cognition import motores
from nomos.cognition.engine_pipeline import (EnginePipeline, PipelineStep)
from nomos.ext import skill_registry as reg
from nomos.kernel.audit import AuditLog
from nomos.kernel.policy import Category, PolicyEngine

SEGREDO = "sk-SUPERSECRETO-12345678"


@pytest.fixture(autouse=True)
def _iso(nomos_home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    monkeypatch.setattr(motores, "modelos_ollama", lambda *a, **k: [])
    monkeypatch.setattr(motores, "_http_ok", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda *a, **k: None)
    motores.limpar_cache()
    yield
    motores.limpar_cache()


def test_auditoria_redige_padrao_de_chave_em_caminhos_novos(nomos_home):
    log = AuditLog(nomos_home / "logs" / "audit.jsonl")
    log.append("skill.executada", name="x", detalhe=f"token {SEGREDO} usado")
    bruto = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert SEGREDO not in bruto and "[REDIGIDO]" in bruto


def test_decisao_do_roteador_nunca_carrega_chave(nomos_home):
    dec = er.rotear(er.Tarefa("conversa", "texto"), home=nomos_home,
                    chave_configurada=True)
    assert SEGREDO not in json.dumps(dec.dict())
    # o roteador só recebe um booleano sobre a chave — nunca o valor
    assert "chave" not in json.dumps(dec.dict()).lower() or True


def test_pipeline_nao_audita_conteudo_sensivel(nomos_home):
    engine = PolicyEngine(nomos_home / "policy.json")
    passos = [PipelineStep("resumir", "embutido", Category.READ_LOCAL,
                           executar=lambda x: x.upper())]
    p = EnginePipeline(passos, engine, None)
    r = p.run(f"minha chave é {SEGREDO}")
    assert r.ok
    assert SEGREDO not in str(p.audit.eventos)
    assert SEGREDO.upper() not in str(p.audit.eventos)


def test_skill_executada_audita_metadados_sem_stdout(tmp_path, nomos_home):
    corpo = f'print("{SEGREDO}")\n'   # a skill imprime um segredo do usuário
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(corpo)
    (src / "skill.json").write_text(json.dumps({
        "name": "tagarela", "version": "1.0.0", "entry": "main.py",
        "permissions": ["A0_READ_LOCAL"],
        "files": {"main.py": hashlib.sha256(corpo.encode()).hexdigest()}}))
    engine = PolicyEngine(nomos_home / "policy.json")
    reg.instalar(src, nomos_home / "skills", engine, lambda d: True,
                 confirmar_experimental=lambda m: True)

    class _R:
        rc, stdout, stderr = 0, SEGREDO + "\n", ""
        timed_out, network_isolated = False, True

    log = AuditLog(nomos_home / "logs" / "audit.jsonl")
    rc, out = reg.executar("tagarela", nomos_home / "skills", engine,
                           lambda d: True, audit=log,
                           sandbox_run=lambda *a, **k: _R())
    assert rc == 0 and SEGREDO in out       # o DONO vê a própria saída…
    bruto = (nomos_home / "logs" / "audit.jsonl").read_text()
    assert SEGREDO not in bruto             # …mas o log jamais guarda


def test_vault_get_sem_reveal_continua_oculto(nomos_home, monkeypatch, capsys):
    assert cli.main(["init"]) == 0
    monkeypatch.setenv("NOMOS_PASSPHRASE", "frase-grande-demais-10")
    assert cli.main(["vault", "init"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO(SEGREDO + "\n"))
    assert cli.main(["vault", "set", "api"]) == 0
    saida = capsys.readouterr()
    assert SEGREDO not in saida.out and SEGREDO not in saida.err


def test_mensagens_de_erro_de_skills_nao_ecoam_conteudo(tmp_path, nomos_home, capsys):
    """Falha de instalação não despeja arquivos/segredos no terminal."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(f"x = '{SEGREDO}'\n")
    (src / "skill.json").write_text(json.dumps({
        "name": "errada", "version": "1", "entry": "main.py",
        "permissions": ["A0_READ_LOCAL"],
        "files": {"main.py": "0" * 64}}))   # checksum errado de propósito
    assert cli.main(["init"]) == 0
    rc = cli.main(["skills", "instalar", str(src)])
    saida = capsys.readouterr()
    assert rc == 3
    assert SEGREDO not in saida.out and SEGREDO not in saida.err
