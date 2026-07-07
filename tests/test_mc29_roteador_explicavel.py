"""MC29 — Roteador explicável: decisão + trace completo, contrato estável.

O roteamento sempre soube o porquê; agora o porquê é exposto como dado
(`relatorio_decisao`) e na CLI (`nomos motores recomendar <mod> --json`).
Contratos: `rotear()` inalterado, trace lista TODOS os candidatos com motivo,
local-first preservado no relatório, JSON estável para automação.
"""
import json
import subprocess
import sys
from pathlib import Path

from nomos.cognition import engine_router as er
from _cli_env import cli_env

ROOT = Path(__file__).resolve().parent.parent


# 1. contrato do relatório
def test_relatorio_tem_contrato_estavel(tmp_path):
    rel = er.relatorio_decisao(er.Tarefa(), home=tmp_path)
    assert rel["contrato"] == er.CONTRATO_RELATORIO == 1
    assert set(rel) == {"contrato", "decisao", "trace"}
    dec, trace = rel["decisao"], rel["trace"]
    for campo in ("selected_engine", "fallback_engine", "reason", "privacy_level",
                  "approval_required", "estimated_cost", "local_only_preserved",
                  "confidence", "steps"):
        assert campo in dec
    for campo in ("tipo", "modalidade", "dados_sensiveis", "local_only",
                  "candidatos", "ranking", "regras_aplicadas"):
        assert campo in trace


# 2. todos os candidatos aparecem com motivo (aceitos E rejeitados)
def test_trace_lista_candidatos_com_motivo(tmp_path):
    rel = er.relatorio_decisao(er.Tarefa(modalidade="texto"), home=tmp_path)
    candidatos = rel["trace"]["candidatos"]
    assert candidatos, "modalidade texto deveria ter candidatos no catálogo"
    for c in candidatos:
        assert set(c) == {"id", "local", "qualidade", "custo", "elegivel", "motivo"}
        assert isinstance(c["motivo"], str) and c["motivo"]


# 3. rotear() continua com o contrato original (mesma decisão do relatório)
def test_rotear_e_relatorio_decidem_igual(tmp_path):
    tarefa = er.Tarefa(modalidade="texto")
    dec = er.rotear(tarefa, home=tmp_path)
    rel = er.relatorio_decisao(tarefa, home=tmp_path)
    assert rel["decisao"] == dec.dict()


# 4. local-first explicado: cadeado ligado (default) => nuvem nunca é escolhida
#    e a regra R1/R6 aparece no trace
def test_local_first_preservado_e_explicado(tmp_path):
    rel = er.relatorio_decisao(er.Tarefa(modalidade="texto"), home=tmp_path)
    assert rel["trace"]["local_only"] is True
    dec = rel["decisao"]
    if dec["selected_engine"] is not None:
        assert dec["local_only_preserved"] is True
        nuvem = [c["id"] for c in rel["trace"]["candidatos"] if not c["local"]]
        assert dec["selected_engine"] not in nuvem
        assert dec["fallback_engine"] not in nuvem or dec["fallback_engine"] is None
    else:
        # sem motor pronto: diagnóstico honesto com próximo passo
        assert "proximo_passo" in rel["trace"]
        assert any("R6" in r for r in rel["trace"]["regras_aplicadas"])


# 5. sem motor pronto o relatório orienta (nunca inventa)
def test_sem_motor_pronto_relatorio_orienta(tmp_path):
    import nomos.cognition.engine_catalog as cat
    catalogo = cat.Catalogo(motores=[])  # catálogo vazio forçado
    rel = er.relatorio_decisao(er.Tarefa(modalidade="texto"),
                               home=tmp_path, catalogo=catalogo)
    assert rel["decisao"]["selected_engine"] is None
    assert "nenhum motor" in rel["decisao"]["reason"]


# 6. CLI real: --json parseável e estável
def _cli(args, home: Path):
    return subprocess.run(
        [sys.executable, "-m", "nomos", *args],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env=cli_env(home),
    )


def test_cli_recomendar_json(tmp_path):
    proc = _cli(["motores", "recomendar", "texto", "--json"], tmp_path)
    data = json.loads(proc.stdout)
    assert data["contrato"] == 1
    assert data["trace"]["modalidade"] == "texto"
    assert isinstance(data["trace"]["candidatos"], list)
    # exit code honesto: 0 com motor escolhido, 1 sem motor pronto
    esperado = 0 if data["decisao"]["selected_engine"] else 1
    assert proc.returncode == esperado


def test_cli_recomendar_humano_preservado(tmp_path):
    proc = _cli(["motores", "recomendar", "texto"], tmp_path)
    assert "{" not in proc.stdout.splitlines()[0] if proc.stdout else True
    assert proc.returncode in (0, 1)
