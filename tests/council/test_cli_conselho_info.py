"""MC23-UX — `nomos conselho status` e `nomos conselho modos` finalizados.

Estes dois subcomandos são PURAMENTE INFORMATIVOS: imprimem fatos estáticos (o
estado das travas e a tabela dos 4 modos) e nada mais. Prova de comportamento e
de segurança:

- não executam motor real, harness, orquestrador, policy/vault/audit;
- não leem, processam, ecoam, logam nem persistem nada digitado pelo usuário;
- não criam arquivos; recusam flags proibidas fail-closed (sem ecoar);
- a trava `REAL_LOCAL_ENGINE_EXECUTION_ENABLED` do harness segue `False`.

Prova de pureza (AST): o módulo `nomos.council.cli_info` não importa rede/
subprocess/threading/asyncio/SDK de nuvem/motor/kernel/orquestrador/harness,
não toca FS/env, não usa tempo/random.
"""
import ast
import io

import pytest

from nomos import cli
from nomos.council import cli_info

_SENSIVEL = "PROMPT-SENSIVEL-xyz789-nao-pode-vazar"


@pytest.fixture(autouse=True)
def _nao_interativo(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    yield


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    out = capsys.readouterr().out
    return rc, out


# --------------------------------------------------------------------------
# Comportamento — status
# --------------------------------------------------------------------------

def test_status_imprime_fatos_e_travas(capsys):
    rc, out = _run(capsys, "conselho", "status")
    assert cli_info.STATUS_CODE in out
    assert rc == cli_info.INFO_EXIT_CODE
    for marca in ("REAL_ENGINE_EXECUTION=false", "REAL_POLICY=false",
                  "REAL_AUDIT=false", "REAL_VAULT=false", "PERSISTENCE=false",
                  "CLOUD=false", "NETWORK=false"):
        assert marca in out, marca
    # aponta o único comando que roda de verdade (dry-run) e a doc
    assert "conselho simular" in out
    assert "MOTOR_COUNCIL_INDEX_v1.md" in out


def test_status_nao_esta_desabilitado(capsys):
    rc, out = _run(capsys, "conselho", "status")
    assert "[NOMOS-MC-CLI-DISABLED]" not in out


# --------------------------------------------------------------------------
# Comportamento — modos
# --------------------------------------------------------------------------

def test_modos_lista_os_quatro(capsys):
    rc, out = _run(capsys, "conselho", "modos")
    assert cli_info.MODOS_CODE in out
    assert rc == cli_info.INFO_EXIT_CODE
    for modo in ("rapido", "balanceado", "critico", "paranoico"):
        assert modo in out, modo
    # linguagem simples por padrão: sem termos internos
    assert "CouncilMode" not in out
    assert "fast" not in out


def test_modos_avancado_revela_mapeamento(capsys):
    rc, out = _run(capsys, "conselho", "modos", "--avancado")
    assert "CouncilMode" in out
    assert "balanceado=balanced" in out
    assert "paranoico=paranoid" in out


# --------------------------------------------------------------------------
# MC25-UX — saída --json estável (para scripts)
# --------------------------------------------------------------------------

def test_status_json_estavel(capsys):
    import json
    rc, out = _run(capsys, "conselho", "status", "--json")
    d = json.loads(out)
    assert d["schema"] == "nomos.council.status.v1"
    assert d["real_engine_execution"] is False
    assert d["persistence"] is False and d["cloud"] is False
    assert "simular" in d["commands_available"]
    assert rc == cli_info.INFO_EXIT_CODE


def test_modos_json_estavel(capsys):
    import json
    rc, out = _run(capsys, "conselho", "modos", "--json")
    d = json.loads(out)
    assert d["schema"] == "nomos.council.modos.v1"
    nomes = [m["nome"] for m in d["modes"]]
    assert nomes == ["rapido", "balanceado", "critico", "paranoico"]
    assert d["modes"][3]["council_mode"] == "paranoid"


def test_json_nao_vaza_nada_do_usuario(capsys):
    # posicional após --json é ignorado, nunca ecoado
    rc, out = _run(capsys, "conselho", "status", "--json", _SENSIVEL)
    assert _SENSIVEL not in out


# --------------------------------------------------------------------------
# MC27-UX — `ajuda` (mapa amigável dos comandos)
# --------------------------------------------------------------------------

def test_ajuda_lista_os_comandos(capsys):
    rc, out = _run(capsys, "conselho", "ajuda")
    assert cli_info.AJUDA_CODE in out
    for cmd in ("status", "modos", "diagnostico", "simular"):
        assert cmd in out, cmd
    assert "REAL_LOCAL_ENGINE_EXECUTION_ENABLED = False" in out
    assert rc == cli_info.INFO_EXIT_CODE


def test_ajuda_recusa_flag_proibida(capsys):
    rc, out = _run(capsys, "conselho", "ajuda", "--enable")
    assert cli_info.INFO_DENIED_CODE in out
    assert "--enable" not in out


# --------------------------------------------------------------------------
# Segurança — flags proibidas, sem eco, sem execução real, sem persistência
# --------------------------------------------------------------------------

def test_info_recusa_flags_proibidas_sem_ecoar(capsys):
    for flag in ("--real", "--enable", "--ativar", "--force", "--unsafe",
                 "--cloud", "--engine-real", "--vault-real"):
        rc, out = _run(capsys, "conselho", "status", flag)
        assert cli_info.INFO_DENIED_CODE in out, flag
        assert flag not in out, flag
        assert rc == cli_info.INFO_DENIED_EXIT_CODE, flag


def test_info_ignora_posicional_e_nao_ecoa(capsys):
    # um "prompt" solto após status/modos é ignorado, nunca ecoado
    rc, out = _run(capsys, "conselho", "status", _SENSIVEL)
    assert _SENSIVEL not in out
    rc2, out2 = _run(capsys, "conselho", "modos", _SENSIVEL)
    assert _SENSIVEL not in out2


def test_info_nao_chama_harness_nem_orquestrador(capsys, monkeypatch):
    import nomos.council.local_harness as harness
    import nomos.council.orchestrator as orch

    def boom(*a, **k):
        raise AssertionError("info não pode tocar execução/orquestração")

    monkeypatch.setattr(harness.LocalExecutionHarness, "execute", boom)
    monkeypatch.setattr(orch.CouncilOrchestratorDryRun, "run", boom)
    _run(capsys, "conselho", "status")
    _run(capsys, "conselho", "modos")
    # a trava real segue desligada
    assert harness.real_execution_enabled() is False


def test_info_nao_constroi_paths(capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("_paths (vault/policy/audit) não pode ser construído")

    monkeypatch.setattr(cli, "_paths", boom)
    rc, out = _run(capsys, "conselho", "status")
    assert cli_info.STATUS_CODE in out


def test_info_nao_persiste_em_disco(capsys, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("NOMOS_HOME", str(home))
    antes = list(home.rglob("*"))
    _run(capsys, "conselho", "status")
    _run(capsys, "conselho", "modos", "--avancado")
    assert list(home.rglob("*")) == antes == []


# --------------------------------------------------------------------------
# Pureza / segurança por AST do módulo cli_info
# --------------------------------------------------------------------------

def _imports():
    src = open(cli_info.__file__, encoding="utf-8").read()
    nomes = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            nomes.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            nomes.add(node.module)
    return nomes


def _fonte():
    return open(cli_info.__file__, encoding="utf-8").read()


def test_info_module_nao_importa_rede():
    proibidos = {"socket", "ssl", "http", "http.client", "urllib",
                 "urllib.request", "requests", "httpx", "aiohttp", "ftplib",
                 "smtplib"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_info_module_nao_importa_subprocess_threading_asyncio():
    proibidos = {"subprocess", "threading", "multiprocessing", "asyncio",
                 "concurrent.futures", "signal"}
    assert not (_imports() & proibidos), _imports() & proibidos


def test_info_module_nao_importa_cloud_nem_runtime():
    usados = _imports()
    prefixos = ("openai", "anthropic", "google", "gemini", "cohere", "boto3",
                "azure", "vertexai", "ollama", "llama_cpp", "transformers",
                "torch", "nomos.council.orchestrator", "nomos.council.local_harness",
                "nomos.council.policy_gate", "nomos.council.audit_envelope",
                "nomos.kernel", "nomos.cognition", "nomos.runtime", "nomos.agents",
                "nomos.ext")
    ruins = [m for m in usados if any(m == p or m.startswith(p + ".") for p in prefixos)]
    assert not ruins, ruins


def test_info_module_nao_toca_fs_ou_env():
    src = _fonte()
    for proibido in ("environ", "getenv", "open(", "write_text", "write_bytes"):
        assert proibido not in src, proibido


def test_info_module_nao_usa_tempo_nem_random():
    usados = _imports()
    for mod in ("time", "random", "secrets"):
        assert mod not in usados, mod
    src = _fonte()
    for chamada in (".now(", "random.", "time."):
        assert chamada not in src, chamada


def test_info_module_nao_tem_api_de_habilitacao():
    callables = [n for n in dir(cli_info)
                 if not n.startswith("_") and callable(getattr(cli_info, n))]
    proibidos = [n for n in callables
                 if any(p in n.lower() for p in ("enable", "activate", "unlock",
                                                 "ativar", "habilit"))]
    assert not proibidos, proibidos
